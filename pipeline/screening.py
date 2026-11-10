"""Compliance Screening Gate: party names against a sanctions list. Fails closed.

Statuses: "clear", "review" (near match, human decides) and "blocked" (hard stop).
"""
import difflib
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

GATE = "compliance_screening"
REVIEW_THRESHOLD = 0.88
_SUFFIXES = {
    "gmbh", "ltd", "limited", "llc", "ag", "inc", "co", "corp",
    "sa", "bv", "fze", "plc", "ug",
}


@dataclass(frozen=True)
class ScreeningResult:
    gate: str
    status: str
    reasons: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.status == "clear"


def _blocked(*reasons: str) -> ScreeningResult:
    return ScreeningResult(GATE, "blocked", tuple(reasons))


def normalise(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    tokens = re.sub(r"[\W_]+", " ", text).split()
    return " ".join(t for t in tokens if t not in _SUFFIXES)


def screen(names: Iterable[str], sanctions: Sequence[str]) -> ScreeningResult:
    try:
        parties = list(names)
        listed = {normalise(s): s for s in sanctions if normalise(s)}
        if not listed:
            return _blocked("sanctions list is unavailable or empty")
        if not parties:
            return _blocked("no parties to screen")

        blocked: list[str] = []
        review: list[str] = []
        for raw in parties:
            if not isinstance(raw, str) or not normalise(raw):
                return _blocked("a party name could not be screened")
            name = normalise(raw)
            if name in listed:
                blocked.append(f"{raw} matches a listed entity")
                continue
            for key, original in listed.items():
                if difflib.SequenceMatcher(None, name, key).ratio() >= REVIEW_THRESHOLD:
                    review.append(f"{raw} is close to a listed entity ({original})")
                    break
    except Exception:
        return _blocked("internal error, failing closed")

    if blocked:
        return ScreeningResult(GATE, "blocked", tuple(blocked + review))
    if review:
        return ScreeningResult(GATE, "review", tuple(review))
    return ScreeningResult(GATE, "clear", ())
