"""Mandate Integrity Gate. Fails closed: any doubt is a rejection."""
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from pipeline import mandates

log = logging.getLogger("corridor.gate")

GATE = "mandate_integrity"


class Challenges(Protocol):
    def consume(self, aud: str, nonce: str) -> bool: ...


@dataclass(frozen=True)
class GateResult:
    gate: str
    passed: bool
    reasons: tuple[str, ...]


def _fail(*reasons: str) -> GateResult:
    return GateResult(GATE, False, tuple(reasons))


def _budget_minor(max_major: float) -> int:
    """Budget.max is in major units (euros); return exact minor units (cents)."""
    return int((Decimal(str(max_major)) * 100).to_integral_value())


def recompute(chain, usage) -> list[str]:
    """Re-derive the signed bounds in exact integers, independent of the SDK."""
    closed = chain.closed_mandate
    paid = closed.payment_amount
    by_type = {c.type: c for c in chain.open_mandate.constraints}
    out: list[str] = []

    payees = by_type.get("payment.allowed_payees")
    if payees is None:
        out.append("required constraint missing: payment.allowed_payees")
    elif closed.payee.id not in {p.id for p in payees.allowed}:
        out.append(f"payee {closed.payee.id} is not allowed by the mandate")

    rng = by_type.get("payment.amount_range")
    if rng is None:
        out.append("required constraint missing: payment.amount_range")
    else:
        if paid.currency != rng.currency:
            out.append("payment currency differs from the mandate")
        if rng.max is not None and paid.amount > rng.max:
            out.append(f"amount {paid.amount} exceeds mandate maximum {rng.max}")
        if rng.min is not None and paid.amount < rng.min:
            out.append(f"amount {paid.amount} is below mandate minimum {rng.min}")

    budget = by_type.get("payment.budget")
    recurrence = by_type.get("payment.agent_recurrence")
    if budget is not None or recurrence is not None:
        if usage is None:
            out.append("spend history is required to check budget and recurrence")
        else:
            if budget is not None:
                if paid.currency != budget.currency:
                    out.append("payment currency differs from the budget")
                limit = _budget_minor(budget.max)
                total = usage.total_amount + paid.amount
                if total > limit:
                    out.append(f"cumulative spend {total} exceeds budget {limit}")
            if recurrence is not None and usage.total_uses >= recurrence.max_occurrences:
                out.append(
                    f"maximum uses reached: {usage.total_uses} of {recurrence.max_occurrences}"
                )
    return out


def check(
    token,
    *,
    user_public,
    aud: str,
    nonce: str,
    expected_transaction_id: str,
    challenges: Challenges,
    usage=None,
) -> GateResult:
    try:
        if not challenges.consume(aud, nonce):
            return _fail("challenge is missing, expired, already used or for another audience")

        result = mandates.verify_chain(
            token,
            user_public=user_public,
            aud=aud,
            nonce=nonce,
            expected_transaction_id=expected_transaction_id,
            usage=usage,
        )
        if not (result.ok and not result.violations):
            return _fail(*(result.violations or ["mandate chain rejected"]))

        chain = mandates.verified_chain(token, user_public=user_public, aud=aud, nonce=nonce)
        own = recompute(chain, usage)
    except Exception:
        log.exception("mandate gate error")
        return _fail("internal error, failing closed")

    if own:
        log.error("verifier disagreement: %s", own)
        return _fail("independent check disagrees with the SDK verdict", *own)
    return GateResult(GATE, True, ())
