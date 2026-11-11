"""Run event log: what the orchestrator did, in order, safe to show in a UI.

Event data is scrubbed on the way in. Secrets are redacted by key name, text is
cleaned and bounded, and only plain JSON values are accepted.
"""
import math
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Protocol

from pipeline.untrusted import sanitise

KINDS = frozenset(
    {
        "run.started",
        "negotiation.offer",
        "interpreter.proposal",
        "gate.mandate",
        "gate.order",
        "gate.screening",
        "tier.decision",
        "rail.selected",
        "approval.requested",
        "approval.granted",
        "payment.executed",
        "run.completed",
        "run.failed",
    }
)
MAX_STR = 500
MAX_ITEMS = 50
MAX_DEPTH = 4
REDACTED = "[redacted]"

_RUN_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_SENSITIVE = ("key", "token", "jwt", "secret", "password", "private", "nonce")


class EventLogError(ValueError):
    pass


@dataclass(frozen=True)
class Event:
    seq: int
    ts: float
    run_id: str
    kind: str
    data: dict


def to_dict(event: Event) -> dict:
    return {
        "seq": event.seq,
        "ts": event.ts,
        "run_id": event.run_id,
        "kind": event.kind,
        "data": event.data,
    }


def _scrub(value, depth: int = 0):
    if depth > MAX_DEPTH:
        raise EventLogError("event data is nested too deeply")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EventLogError("event data has a non-finite number")
        return value
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        return sanitise(value)[:MAX_STR]
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_ITEMS:
            raise EventLogError("event data has too many items")
        return [_scrub(v, depth + 1) for v in value]
    if isinstance(value, dict):
        if len(value) > MAX_ITEMS:
            raise EventLogError("event data has too many items")
        clean = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise EventLogError("event data keys must be text")
            if any(part in key.lower() for part in _SENSITIVE):
                clean[key] = REDACTED
            else:
                clean[key] = _scrub(item, depth + 1)
        return clean
    raise EventLogError("event data must be plain JSON values")


class EventLog(Protocol):
    def append(self, run_id: str, kind: str, data: dict | None = None) -> Event: ...

    def read(self, run_id: str, after: int = 0) -> list[Event]: ...


class MemoryEventLog:
    def __init__(self, *, clock=time.time, max_runs: int = 200, max_events_per_run: int = 200):
        self._clock = clock
        self._max_runs = max_runs
        self._max_events = max_events_per_run
        self._runs: OrderedDict[str, list[Event]] = OrderedDict()
        self._lock = threading.Lock()

    def append(self, run_id, kind, data=None) -> Event:
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise EventLogError("invalid run id")
        if not isinstance(kind, str) or kind not in KINDS:
            raise EventLogError("unknown event kind")
        clean = _scrub({} if data is None else data)
        if not isinstance(clean, dict):
            raise EventLogError("event data must be an object")
        with self._lock:
            events = self._runs.get(run_id)
            if events is None:
                events = self._runs[run_id] = []
                while len(self._runs) > self._max_runs:
                    self._runs.popitem(last=False)
            if len(events) >= self._max_events:
                raise EventLogError("run has too many events")
            event = Event(len(events) + 1, self._clock(), run_id, kind, clean)
            events.append(event)
            return event

    def read(self, run_id: str, after: int = 0) -> list[Event]:
        with self._lock:
            return [e for e in self._runs.get(run_id, []) if e.seq > after]
