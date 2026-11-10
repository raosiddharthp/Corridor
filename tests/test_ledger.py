import pytest

from pipeline.ledger import MemorySpendLedger


def test_unused_mandate_has_no_spend():
    usage = MemorySpendLedger().usage("m1")
    assert usage.total_uses == 0
    assert usage.total_amount == 0


def test_payments_accumulate():
    ledger = MemorySpendLedger()
    ledger.record("m1", "p1", 34_000_000)
    ledger.record("m1", "p2", 1_000)
    usage = ledger.usage("m1")
    assert usage.total_uses == 2
    assert usage.total_amount == 34_001_000


def test_recording_is_idempotent_per_payment():
    ledger = MemorySpendLedger()
    assert ledger.record("m1", "p1", 500) is True
    assert ledger.record("m1", "p1", 500) is False
    assert ledger.usage("m1").total_uses == 1
    assert ledger.usage("m1").total_amount == 500


def test_reusing_a_payment_id_with_another_amount_is_an_error():
    ledger = MemorySpendLedger()
    ledger.record("m1", "p1", 500)
    with pytest.raises(ValueError):
        ledger.record("m1", "p1", 600)


def test_mandates_are_isolated():
    ledger = MemorySpendLedger()
    ledger.record("m1", "p1", 500)
    assert ledger.usage("m2").total_amount == 0


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "100"])
def test_bad_amounts_are_rejected(bad):
    with pytest.raises(ValueError):
        MemorySpendLedger().record("m1", "p1", bad)
