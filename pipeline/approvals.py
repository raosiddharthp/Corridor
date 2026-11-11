"""Pending Tier 2 approvals. Single use, expiring, and never shown with the checkout."""
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

TTL_SECONDS = 900
MAX_PENDING = 200


class ApprovalError(RuntimeError):
    pass


@dataclass(frozen=True)
class Pending:
    run_id: str
    order_ref: str
    checkout_jwt: str
    total_minor: int
    transaction_id: str
    reasons: tuple
    expires_at: float

    def public(self) -> dict:
        return {
            "run_id": self.run_id,
            "order_ref": self.order_ref,
            "total_minor": self.total_minor,
            "reasons": list(self.reasons),
            "expires_at": self.expires_at,
        }


class MemoryApprovalStore:
    def __init__(self, *, ttl: float = TTL_SECONDS, max_pending: int = MAX_PENDING, clock=time.time):
        self._ttl = ttl
        self._max = max_pending
        self._clock = clock
        self._items: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def add(self, run_id, order_ref, checkout_jwt, total_minor, transaction_id, reasons) -> Pending:
        pending = Pending(
            run_id=run_id,
            order_ref=order_ref,
            checkout_jwt=checkout_jwt,
            total_minor=total_minor,
            transaction_id=transaction_id,
            reasons=tuple(reasons),
            expires_at=self._clock() + self._ttl,
        )
        with self._lock:
            self._items[run_id] = pending
            self._items.move_to_end(run_id)
            while len(self._items) > self._max:
                self._items.popitem(last=False)
        return pending

    def _live(self, pending):
        return pending is not None and pending.expires_at > self._clock()

    def take(self, run_id):
        with self._lock:
            pending = self._items.pop(run_id, None)
        return pending if self._live(pending) else None

    def peek(self, run_id):
        with self._lock:
            pending = self._items.get(run_id)
        return pending if self._live(pending) else None
