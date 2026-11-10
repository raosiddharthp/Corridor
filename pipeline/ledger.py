"""Spend ledger: what each mandate has actually paid out.

Money is integer minor units. One currency per mandate.
"""
import threading
from typing import Protocol

from ap2.sdk.constraints import MandateContext


class SpendLedger(Protocol):
    def usage(self, mandate_ref: str) -> MandateContext: ...
    def record(self, mandate_ref: str, payment_id: str, amount_minor: int) -> bool: ...


class MemorySpendLedger:
    def __init__(self):
        self._payments: dict[str, dict[str, int]] = {}
        self._lock = threading.Lock()

    def usage(self, mandate_ref: str) -> MandateContext:
        with self._lock:
            book = dict(self._payments.get(mandate_ref, {}))
        return MandateContext(total_uses=len(book), total_amount=sum(book.values()))

    def record(self, mandate_ref: str, payment_id: str, amount_minor: int) -> bool:
        """Idempotent per payment_id. Returns True only when newly recorded."""
        if not isinstance(amount_minor, int) or isinstance(amount_minor, bool) or amount_minor <= 0:
            raise ValueError("amount must be a positive integer in minor units")
        with self._lock:
            book = self._payments.setdefault(mandate_ref, {})
            if payment_id in book:
                if book[payment_id] != amount_minor:
                    raise ValueError("payment id was already used with a different amount")
                return False
            book[payment_id] = amount_minor
            return True
