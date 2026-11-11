import pytest

import pipeline.seed as seed
from pipeline.ledger import MemorySpendLedger
from pipeline.payments import PaymentError, PaymentExecutor


def _executor():
    ledger = MemorySpendLedger()
    return PaymentExecutor(ledger), ledger


def test_execute_records_the_spend_and_returns_a_receipt():
    executor, ledger = _executor()
    receipt = executor.execute(transaction_id="txn-12345678", amount_minor=500, rail_id="sepa_sct")
    assert receipt.reference == "SIM-sepa_sct-txn-1234"
    assert not receipt.duplicate
    usage = ledger.usage(seed.BUYER.id)
    assert (usage.total_amount, usage.total_uses) == (500, 1)


def test_repeating_a_payment_returns_the_same_receipt_without_spending_again():
    executor, ledger = _executor()
    first = executor.execute(transaction_id="txn-1", amount_minor=500, rail_id="sepa_sct")
    again = executor.execute(transaction_id="txn-1", amount_minor=500, rail_id="sepa_sct")
    assert again.duplicate
    assert again.reference == first.reference
    assert ledger.usage(seed.BUYER.id).total_uses == 1


def test_the_same_transaction_with_different_details_is_rejected():
    executor, _ = _executor()
    executor.execute(transaction_id="txn-1", amount_minor=500, rail_id="sepa_sct")
    with pytest.raises(PaymentError):
        executor.execute(transaction_id="txn-1", amount_minor=501, rail_id="sepa_sct")


@pytest.mark.parametrize(
    "txn, amount, rail",
    [
        ("", 100, "r"),
        ("t", 0, "r"),
        ("t", -5, "r"),
        ("t", True, "r"),
        ("t", 1.5, "r"),
        ("t", "5", "r"),
        ("t", 100, ""),
    ],
)
def test_invalid_payments_are_rejected(txn, amount, rail):
    executor, _ = _executor()
    with pytest.raises(PaymentError):
        executor.execute(transaction_id=txn, amount_minor=amount, rail_id=rail)


class _BrokenLedger:
    def record(self, *args):
        raise RuntimeError("storage down")


def test_a_ledger_failure_means_no_receipt():
    with pytest.raises(PaymentError):
        PaymentExecutor(_BrokenLedger()).execute(
            transaction_id="t", amount_minor=100, rail_id="r"
        )
