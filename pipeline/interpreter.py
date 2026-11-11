"""Interpreter: reads the supplier's note and proposes accept or escalate.

A proposal is advice. It carries no amount, payee or approval, and it can only
tighten routing. The gates and the tier router alone decide whether money moves.
"""
import re
from dataclasses import dataclass
from typing import Protocol

from pipeline import tiering
from pipeline.untrusted import sanitise

ACCEPT = "accept"
ESCALATE = "escalate"
ACTIONS = (ACCEPT, ESCALATE)
MAX_REASON = 300
_FIELDS = {"action", "reason"}


class InterpreterError(ValueError):
    pass


@dataclass(frozen=True)
class Proposal:
    action: str
    reason: str


class Interpreter(Protocol):
    def interpret(self, note: str): ...


def validate_proposal(raw) -> Proposal:
    if not isinstance(raw, dict) or set(raw) != _FIELDS:
        raise InterpreterError("proposal must be exactly {action, reason}")
    action, reason = raw["action"], raw["reason"]
    if not isinstance(action, str) or action not in ACTIONS:
        raise InterpreterError("unknown action")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON:
        raise InterpreterError("invalid reason")
    cleaned = sanitise(reason).strip()
    if not cleaned:
        raise InterpreterError("invalid reason")
    return Proposal(action=action, reason=cleaned)


def propose(interpreter: Interpreter, note) -> Proposal:
    """Never raises. Anything unusable becomes an escalation."""
    try:
        return validate_proposal(interpreter.interpret(sanitise(note)))
    except Exception:
        return Proposal(ESCALATE, "interpreter output could not be used")


def apply(proposal: Proposal, tier: str) -> str:
    """A proposal can move Tier 1 to Tier 2. It never relaxes anything."""
    if tier == tiering.BLOCKED:
        return tier
    if proposal.action == ESCALATE and tier == tiering.TIER1:
        return tiering.TIER2
    return tier


_INSTRUCTIONS = re.compile(
    r"\b(ignore|disregard|override|previous instructions|system prompt|you are now)\b"
    r"|approve (this|the) payment",
    re.IGNORECASE,
)
_PRICE_CHANGE = re.compile(
    r"\b(revised|increased?|surcharge|new price|adjusted|raw[- ]material)\b",
    re.IGNORECASE,
)


class RuleInterpreter:
    """Deterministic stand-in. Keyword based, so it is a filter, not a defence."""

    def interpret(self, note: str) -> dict:
        if _INSTRUCTIONS.search(note):
            return {"action": ESCALATE, "reason": "note contains instructions addressed to the reader"}
        if _PRICE_CHANGE.search(note):
            return {"action": ESCALATE, "reason": "note mentions a price change"}
        return {"action": ACCEPT, "reason": "note is a routine confirmation"}
