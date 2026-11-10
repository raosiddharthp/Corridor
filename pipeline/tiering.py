"""Tier router: Tier 1 (automatic), Tier 2 (human approval) or blocked.

Blocked outranks Tier 2, which outranks Tier 1. Fails closed.
"""
from dataclasses import dataclass

TIER1, TIER2, BLOCKED = "tier1", "tier2", "blocked"


@dataclass(frozen=True)
class PriceCheck:
    valid: bool
    within_tolerance: bool
    drift_bps: int
    tolerance_bps: int


@dataclass(frozen=True)
class Decision:
    outcome: str
    reasons: tuple[str, ...]


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_price(agreed_minor, quoted_minor, tolerance_bps) -> PriceCheck:
    """Upward drift beyond the tolerance needs a human. Exact integer maths."""
    if (
        not all(_is_int(v) for v in (agreed_minor, quoted_minor, tolerance_bps))
        or agreed_minor <= 0
        or quoted_minor <= 0
        or tolerance_bps < 0
    ):
        return PriceCheck(False, False, 0, 0)
    drift = (quoted_minor - agreed_minor) * 10_000 // agreed_minor
    within = quoted_minor * 10_000 <= agreed_minor * (10_000 + tolerance_bps)
    return PriceCheck(True, within, drift, tolerance_bps)


def route(price: PriceCheck, screening, mandate=None) -> Decision:
    try:
        blockers: list[str] = []
        if not price.valid:
            blockers.append("price could not be checked")
        if screening.status not in ("clear", "review"):
            blockers.extend(screening.reasons or ("screening blocked the payment",))
        if mandate is not None and not mandate.passed:
            blockers.append("mandate gate rejected the payment")
            blockers.extend(mandate.reasons)
        if blockers:
            return Decision(BLOCKED, tuple(blockers))

        humans: list[str] = []
        if not price.within_tolerance:
            humans.append(
                f"quoted price is {price.drift_bps} bps above the agreed price "
                f"(tolerance {price.tolerance_bps} bps)"
            )
        if screening.status == "review":
            humans.extend(screening.reasons)
        if humans:
            return Decision(TIER2, tuple(humans))

        if mandate is None:
            return Decision(BLOCKED, ("mandate has not been verified",))
        return Decision(TIER1, ())
    except Exception:
        return Decision(BLOCKED, ("internal error, failing closed",))
