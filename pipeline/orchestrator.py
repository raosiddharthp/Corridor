"""Orchestrator: runs one order through the components in order.

It negotiates, verifies the supplier's signed checkout, screens, prices, builds and
gates the payment, routes, picks a rail and, when an executor is configured, settles
Tier 1 payments. Tier 2 orders wait for a human decision, which is a fresh mandate
capped at the approved total. The price that counts is the total in the verified
signed checkout, never the supplier's stated total.
"""
import asyncio
import logging
from dataclasses import dataclass

from pipeline import checkout as co
from pipeline import interpreter as itp
from pipeline import negotiation, rails, seed
from pipeline.approvals import ApprovalError
from pipeline.events import EventLogError
from pipeline.payment_gate import gate_payment
from pipeline.payments import PaymentError
from pipeline.screening import screen
from pipeline.tiering import BLOCKED, TIER1, TIER2, check_price, route

log = logging.getLogger(__name__)

READY = "ready_to_pay"
PAID = "paid"
AWAITING = "awaiting_approval"
REJECTED = "rejected"
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
    reference: str | None = None

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
            "reference": self.reference,
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
        executor=None,
        approvals=None,
    ):
        self._keys = keys
        self._url = supplier_url
        self._http = http
        self._events = events
        self._challenges = challenges
        self._ledger = ledger
        self._interpreter = interpreter
        self._quote = quote
        self._executor = executor
        self._approvals = approvals

    def _emit(self, run_id, kind, data=None):
        self._events.append(run_id, kind, data)

    def _crashed(self, run_id, order_ref):
        log.exception("run failed")
        try:
            self._emit(run_id, "run.failed", {"reason": "internal error"})
        except EventLogError:
            pass
        return RunResult(
            run_id, order_ref, BLOCKED, FAILED, ("internal error, failing closed",)
        )

    def _failed(self, run_id, order_ref, reason):
        self._emit(run_id, "run.failed", {"reason": reason})
        return RunResult(run_id, order_ref, BLOCKED, FAILED, (reason,))

    def _finish(self, run_id, order_ref, tier, status, reasons, **fields):
        self._emit(run_id, "run.completed", {"status": status, "tier": tier})
        return RunResult(run_id, order_ref, tier, status, tuple(reasons), **fields)

    def _blocked(self, run_id, order_ref, reasons, total=None):
        self._emit(run_id, "tier.decision", {"tier": BLOCKED, "reasons": list(reasons)})
        return self._finish(
            run_id, order_ref, BLOCKED, BLOCKED_STATUS, reasons, total_minor=total
        )

    def _settle(self, run_id, order_ref, tier, reasons, total, transaction_id):
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
                run_id, order_ref, BLOCKED, BLOCKED_STATUS, choice.reasons, total_minor=total
            )
        if self._executor is None:
            return self._finish(
                run_id,
                order_ref,
                tier,
                READY,
                reasons,
                total_minor=total,
                rail=choice.rail.id,
                transaction_id=transaction_id,
            )
        try:
            receipt = self._executor.execute(
                transaction_id=transaction_id,
                amount_minor=total,
                rail_id=choice.rail.id,
            )
        except PaymentError as exc:
            return self._failed(run_id, order_ref, str(exc))
        self._emit(
            run_id,
            "payment.executed",
            {
                "payment_id": receipt.payment_id,
                "amount_minor": receipt.amount_minor,
                "rail": receipt.rail,
                "reference": receipt.reference,
                "duplicate": receipt.duplicate,
            },
        )
        return self._finish(
            run_id,
            order_ref,
            tier,
            PAID,
            reasons,
            total_minor=total,
            rail=choice.rail.id,
            transaction_id=transaction_id,
            reference=receipt.reference,
        )

    async def run(self, run_id: str, order: seed.Scenario) -> RunResult:
        self._emit(run_id, "run.started", {"order_ref": order.ref})
        try:
            return await self._run(run_id, order)
        except Exception:
            return self._crashed(run_id, order.ref)

    def decide(self, run_id: str, approve: bool) -> RunResult:
        """Apply a human decision to a pending Tier 2 order. Single use."""
        if self._approvals is None:
            raise ApprovalError("approvals are not enabled")
        pending = self._approvals.take(run_id)
        if pending is None:
            raise ApprovalError("no pending approval for this run")
        try:
            return self._decide(run_id, pending, approve)
        except Exception:
            return self._crashed(run_id, pending.order_ref)

    def _decide(self, run_id, pending, approve):
        if not approve:
            self._emit(run_id, "run.completed", {"status": REJECTED, "tier": TIER2})
            return RunResult(
                run_id,
                pending.order_ref,
                TIER2,
                REJECTED,
                ("rejected by the approver",),
                total_minor=pending.total_minor,
            )
        self._emit(run_id, "approval.granted", {"total_minor": pending.total_minor})
        mandate = gate_payment(
            keys=self._keys,
            challenges=self._challenges,
            ledger=self._ledger,
            checkout_jwt=pending.checkout_jwt,
            total_minor=pending.total_minor,
            transaction_id=pending.transaction_id,
            cap_minor=pending.total_minor,
        )
        self._emit(
            run_id,
            "gate.mandate",
            {"passed": mandate.passed, "reasons": list(mandate.reasons), "fresh_mandate": True},
        )
        if not mandate.passed:
            reasons = ("mandate gate rejected the payment", *mandate.reasons)
            return self._blocked(run_id, pending.order_ref, reasons, pending.total_minor)
        return self._settle(
            run_id, pending.order_ref, TIER2, (), pending.total_minor, pending.transaction_id
        )

    async def _run(self, run_id, order):
        try:
            offer = await self._quote(
                self._url, order.ref, http=self._http, expected_currency=seed.CURRENCY
            )
        except negotiation.NegotiationError as exc:
            return self._failed(run_id, order.ref, str(exc))
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
                run_id, order.ref, ("supplier checkout could not be verified",)
            )
        if total != offer.claimed_total_minor:
            return self._blocked(
                run_id,
                order.ref,
                ("supplier's stated total differs from its signed checkout",),
            )
        if transaction_id != offer.checkout_hash:
            return self._blocked(
                run_id, order.ref, ("supplier's checkout hash does not match its checkout",)
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
            mandate = gate_payment(
                keys=self._keys,
                challenges=self._challenges,
                ledger=self._ledger,
                checkout_jwt=offer.checkout_jwt,
                total_minor=total,
                transaction_id=transaction_id,
                cap_minor=seed.MANDATE_CAP_MINOR,
            )
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
            return self._settle(run_id, order.ref, TIER1, reasons, total, transaction_id)
        if tier == TIER2:
            if self._approvals is not None:
                pending = self._approvals.add(
                    run_id, order.ref, offer.checkout_jwt, total, transaction_id, reasons
                )
                self._emit(
                    run_id,
                    "approval.requested",
                    {
                        "total_minor": total,
                        "expires_at": pending.expires_at,
                        "reasons": reasons,
                    },
                )
            return self._finish(run_id, order.ref, TIER2, AWAITING, reasons, total_minor=total)
        return self._finish(
            run_id, order.ref, BLOCKED, BLOCKED_STATUS, reasons, total_minor=total
        )
