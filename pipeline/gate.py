"""Mandate Integrity Gate. Fails closed: any doubt is a rejection."""
import logging
from dataclasses import dataclass
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
    except Exception:
        log.exception("mandate gate error")
        return _fail("internal error, failing closed")

    if result.ok and not result.violations:
        return GateResult(GATE, True, ())
    return _fail(*(result.violations or ["mandate chain rejected"]))
