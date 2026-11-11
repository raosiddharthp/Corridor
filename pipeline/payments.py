"""Payment Execution Agent (simulated): records the spend and returns a reference.

No money moves. Execution is idempotent on the transaction id.
"""
import threading
from collections import OrderedDict
from dataclasses import dataclass, replace

from pipeline import seed

MAX_ID = 200
MAX_RECEIPTS = 1000


class PaymentError(RuntimeError):
    pass


@dataclass(frozen=True)
class Receipt:
    payment_id: str
    amount_minor: int
    rail: str
    reference: str
    duplicate: bool = False


class PaymentExecutor:
    def __init__(self, ledger, *, mandate_ref: str = seed.BUYER.id):
        self._ledger = ledger
        self._mandate_ref = mandate_ref
        self._receipts: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def execute(self, *, transaction_id, amount_minor, rail_id) -> Receipt:
        if not isinstance(transaction_id, str) or not transaction_id or len(transaction_id) > MAX_ID:
            raise PaymentError("invalid transaction id")
        if isinstance(amount_minor, bool) or not isinstance(amount_minor, int) or amount_minor <= 0:
            raise PaymentError("invalid amount")
        if not isinstance(rail_id, str) or not rail_id:
            raise PaymentError("invalid rail")
        with self._lock:
            existing = self._receipts.get(transaction_id)
            if existing is not None:
                if existing.amount_minor != amount_minor or existing.rail != rail_id:
                    raise PaymentError("transaction was already executed with different details")
                return replace(existing, duplicate=True)
            try:
                self._ledger.record(self._mandate_ref, transaction_id, amount_minor)
            except Exception:
                raise PaymentError("could not record the payment") from None
            receipt = Receipt(
                payment_id=transaction_id,
                amount_minor=amount_minor,
                rail=rail_id,
                reference=f"SIM-{rail_id}-{transaction_id[:8]}",
            )
            self._receipts[transaction_id] = receipt
            while len(self._receipts) > MAX_RECEIPTS:
                self._receipts.popitem(last=False)
            return receipt
