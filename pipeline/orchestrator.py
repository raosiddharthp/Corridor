"""Orchestrator: runs one order through the components in order.

It negotiates, verifies the supplier's signed checkout, screens, prices, builds and
gates the payment, routes, and picks a rail. It never moves money: a Tier 1 run ends
as ready_to_pay for the Payment Execution Agent. The price that counts is the total
in the verified signed checkout, never the supplier's stated total.
"""
import asyncio
import logging
from dataclasses import dataclass

from ap2.sdk.generated.types.merchant import Merchant
from ap2.sdk.generated.types.payment_instrument import PaymentInstrument

from pipeline import checkout as co
from pipeline import gate
from pipeline import interpreter as itp
from pipeline import mandates as m
from pipeline import negotiation, rails, seed
from pipeline.events import EventLogError
from pipeline.screening import screen
from pipeline.tiering import BLOCKED, TIER1, TIER2, check_price, route

log = logging.getLogger(__name__)

AUD = "corridor-payment-processor"
ACCOUNT = PaymentInstrument(id="acct_1", type="bank_account")

READY = "ready_to_pay"
AWAITING = "awaiting_approval"
BLOCKED_STATUS = "blocked"
FAILED = "failed"


@dataclass(frozen=True)
class RunResult:
    run_id: str
    order_ref: str
    tier: str
    status: str
    reasons: tuple
    total_minor: int | None = None
    rail: str | None = None
    transaction_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "order_ref": self.order_ref,
            "tier": self.tier,
            "status": self.status,
            "reasons": list(self.reasons),
            "total_minor": self.total_minor,
            "rail": self.rail,
            "transaction_id": self.transaction_id,
        }


class Orchestrator:
    def __init__(
        self,
        *,
        keys,
        supplier_url,
        http,
        events,
        challenges,
        ledger,
        interpreter,
        quote=negotiation.request_quote,
    ):
        self._keys = keys
        self._url = supplier_url
        self._http = http
        self._events = events
        self._challenges = challenges
        self._ledger = ledger
        self._interpreter = interpreter
        self._quote = quote

    def _emit(self, run_id, kind, data=None):
        self._events.append(run_id, kind, data)

    async def run(self, run_id: str, order: seed.Scenario) -> RunResult:
        self._emit(run_id, "run.started", {"order_ref": order.ref})
        try:
            return await self._run(run_id, order)
        except Exception:
            log.exception("run failed")
            try:
                self._emit(run_id, "run.failed", {"reason": "internal error"})
            except EventLogError:
                pass
            return RunResult(
                run_id, order.ref, BLOCKED, FAILED, ("internal error, failing closed",)
            )

    def _failed(self, run_id, order, reason):
        self._emit(run_id, "run.failed", {"reason": reason})
        return RunResult(run_id, order.ref, BLOCKED, FAILED, (reason,))

    def _finish(self, run_id, order, tier, status, reasons, **fields):
        self._emit(run_id, "run.completed", {"status": status, "tier": tier})
        return RunResult(run_id, order.ref, tier, status, tuple(reasons), **fields)

    def _blocked(self, run_id, order, reasons, total=None):
        self._emit(run_id, "tier.decision", {"tier": BLOCKED, "reasons": list(reasons)})
        return self._finish(
            run_id, order, BLOCKED, BLOCKED_STATUS, reasons, total_minor=total
        )

    def _gate(self, offer, total, transaction_id):
        try:
            challenge = self._challenges.issue(AUD)
            merchant = Merchant(id=seed.SUPPLIER.id, name=seed.SUPPLIER.name)
            open_token = m.sign_open(
                m.open_payment_mandate(
                    payee=merchant,
                    max_minor=seed.MANDATE_CAP_MINOR,
                    agent_key=self._keys.agent,
                    max_occurrences=seed.MANDATE_MAX_USES,
                    budget_minor=seed.MANDATE_BUDGET_MINOR,
                ),
                self._keys.user,
            )
            closed = m.closed_payment_mandate(
                transaction_id=transaction_id,
                payee=merchant,
                amount_minor=total,
                instrument=ACCOUNT,
            )
            token = m.delegate(
                open_token, closed, self._keys.agent, aud=AUD, nonce=challenge.nonce
            )
            return gate.check_order(
                offer.checkout_jwt,
                token,
                supplier_public=self._keys.supplier_public,
                user_public=m.public_only(self._keys.user),
                aud=AUD,
                nonce=challenge.nonce,
                challenges=self._challenges,
                usage=self._ledger.usage(seed.BUYER.id),
            )
        except Exception:
            log.exception("could not build the payment")
            return gate.GateResult(gate.GATE, False, ("payment could not be built",))

    async def _run(self, run_id, order):
        try:
            offer = await self._quote(
                self._url, order.ref, http=self._http, expected_currency=seed.CURRENCY
            )
        except negotiation.NegotiationError as exc:
            return self._failed(run_id, order, str(exc))
        self._emit(
            run_id,
            "negotiation.offer",
            {
                "order_ref": offer.order_ref,
                "claimed_total_minor": offer.claimed_total_minor,
                "checkout_hash": offer.checkout_hash,
                "note": offer.note,
            },
        )

        try:
            checkout = co.verify_checkout(offer.checkout_jwt, self._keys.supplier_public)
            total = co.grand_total_minor(checkout)
            transaction_id = co.compute_hash(offer.checkout_jwt)
        except Exception:
            log.warning("supplier checkout could not be verified", exc_info=True)
            return self._blocked(
                run_id, order, ("supplier checkout could not be verified",)
            )
        if total != offer.claimed_total_minor:
            return self._blocked(
                run_id,
                order,
                ("supplier's stated total differs from its signed checkout",),
            )
        if transaction_id != offer.checkout_hash:
            return self._blocked(
                run_id, order, ("supplier's checkout hash does not match its checkout",)
            )

        proposal = await asyncio.to_thread(itp.propose, self._interpreter, offer.note)
        self._emit(
            run_id,
            "interpreter.proposal",
            {"action": proposal.action, "reason": proposal.reason},
        )

        screening = screen([seed.BUYER.name, seed.SUPPLIER.name], seed.SANCTIONS_SAMPLE)
        self._emit(
            run_id,
            "gate.screening",
            {"status": screening.status, "reasons": list(screening.reasons)},
        )

        price = check_price(order.agreed_minor, total, seed.PRICE_TOLERANCE_BPS)

        mandate = None
        if price.valid and price.within_tolerance and screening.status == "clear":
            mandate = self._gate(offer, total, transaction_id)
            self._emit(
                run_id,
                "gate.mandate",
                {"passed": mandate.passed, "reasons": list(mandate.reasons)},
            )

        decision = route(price, screening, mandate)
        tier = itp.apply(proposal, decision.outcome)
        reasons = list(decision.reasons)
        if tier != decision.outcome:
            reasons.append(f"supplier note flagged for review: {proposal.reason}")
        self._emit(
            run_id,
            "tier.decision",
            {
                "tier": tier,
                "reasons": reasons,
                "drift_bps": price.drift_bps,
                "total_minor": total,
                "agreed_minor": order.agreed_minor,
            },
        )

        if tier == TIER1:
            choice = rails.select_rail(total)
            self._emit(
                run_id,
                "rail.selected",
                {
                    "rail": choice.rail.id if choice.rail else None,
                    "reasons": list(choice.reasons),
                },
            )
            if choice.rail is None:
                return self._finish(
                    run_id, order, BLOCKED, BLOCKED_STATUS, choice.reasons, total_minor=total
                )
            return self._finish(
                run_id,
                order,
                TIER1,
                READY,
                reasons,
                total_minor=total,
                rail=choice.rail.id,
                transaction_id=transaction_id,
            )
        if tier == TIER2:
            return self._finish(run_id, order, TIER2, AWAITING, reasons, total_minor=total)
        return self._finish(run_id, order, BLOCKED, BLOCKED_STATUS, reasons, total_minor=total)
