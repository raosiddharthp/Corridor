"""Rail Selection Engine: a deterministic, explained choice among eligible rails."""
from dataclasses import dataclass

from pipeline import seed

COST, SPEED = "cost", "speed"


@dataclass(frozen=True)
class RailChoice:
    rail: "seed.Rail | None"
    reasons: tuple[str, ...]
    excluded: tuple[tuple[str, str], ...]


def _none(reason: str, excluded=()) -> RailChoice:
    return RailChoice(None, (reason,), tuple(excluded))


def select_rail(
    amount_minor,
    *,
    rails=seed.RAILS,
    objective=COST,
    deadline_hours=None,
    allowed_pisps=frozenset(),
) -> RailChoice:
    try:
        if not isinstance(amount_minor, int) or isinstance(amount_minor, bool) or amount_minor <= 0:
            return _none("amount is not a positive integer in minor units")
        if objective not in (COST, SPEED):
            return _none(f"unknown objective: {objective}")
        if deadline_hours is not None and (
            not isinstance(deadline_hours, int)
            or isinstance(deadline_hours, bool)
            or deadline_hours < 0
        ):
            return _none("deadline is not a valid number of hours")

        eligible = []
        excluded = []
        for rail in rails:
            if rail.max_minor is not None and amount_minor > rail.max_minor:
                excluded.append((rail.id, f"amount exceeds the rail limit of {rail.max_minor}"))
            elif rail.via_pisp and rail.id not in allowed_pisps:
                excluded.append((rail.id, "payment initiation provider is not allowed by the mandate"))
            elif deadline_hours is not None and rail.settlement_hours > deadline_hours:
                excluded.append(
                    (rail.id, f"settles in {rail.settlement_hours}h, after the {deadline_hours}h deadline")
                )
            else:
                eligible.append(rail)

        if not eligible:
            return _none("no eligible rail", excluded)

        if objective == COST:
            best = min(eligible, key=lambda r: (r.fee_minor, r.settlement_hours, r.id))
            why = "lowest fee"
        else:
            best = min(eligible, key=lambda r: (r.settlement_hours, r.fee_minor, r.id))
            why = "fastest settlement"
        return RailChoice(
            best,
            (f"{best.id}: {why} among {len(eligible)} eligible rail(s)",),
            tuple(excluded),
        )
    except Exception:
        return _none("internal error, failing closed")
