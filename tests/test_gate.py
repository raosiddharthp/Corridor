import pytest
from ap2.sdk.generated.types.merchant import Merchant
from ap2.sdk.generated.types.payment_instrument import PaymentInstrument

from pipeline import gate
from pipeline import mandates as m
from pipeline.challenge import MemoryChallengeStore

SUPPLIER = Merchant(id="brunnerteknik", name="BrunnerTeknik GmbH")
ACCOUNT = PaymentInstrument(id="acct_1", type="bank_account")
AUD = "corridor-payment-processor"
CAP = 34_500_000


@pytest.fixture
def keys():
    return m.new_key(), m.new_key()  # (user, agent)


@pytest.fixture
def challenges():
    return MemoryChallengeStore()


def _token(keys, nonce, *, cents=34_000_000):
    user, agent = keys
    open_token = m.sign_open(
        m.open_payment_mandate(payee=SUPPLIER, max_minor=CAP, agent_key=agent), user
    )
    closed = m.closed_payment_mandate(
        transaction_id="tx-1", payee=SUPPLIER, amount_minor=cents, instrument=ACCOUNT
    )
    return m.delegate(open_token, closed, agent, aud=AUD, nonce=nonce)


def _check(keys, challenges, token, nonce):
    return gate.check(
        token,
        user_public=m.public_only(keys[0]),
        aud=AUD,
        nonce=nonce,
        expected_transaction_id="tx-1",
        challenges=challenges,
    )


def test_in_policy_chain_passes(keys, challenges):
    c = challenges.issue(AUD)
    result = _check(keys, challenges, _token(keys, c.nonce), c.nonce)
    assert result.passed
    assert result.reasons == ()


def test_replayed_chain_is_rejected(keys, challenges):
    c = challenges.issue(AUD)
    token = _token(keys, c.nonce)
    assert _check(keys, challenges, token, c.nonce).passed
    replay = _check(keys, challenges, token, c.nonce)
    assert not replay.passed
    assert "challenge" in replay.reasons[0]


def test_unissued_nonce_is_rejected(keys, challenges):
    result = _check(keys, challenges, _token(keys, "forged"), "forged")
    assert not result.passed
    assert "challenge" in result.reasons[0]


def test_challenge_for_another_audience_is_rejected(keys, challenges):
    c = challenges.issue("some-other-audience")
    result = _check(keys, challenges, _token(keys, c.nonce), c.nonce)
    assert not result.passed


def test_over_cap_is_rejected_and_burns_the_nonce(keys, challenges):
    c = challenges.issue(AUD)
    token = _token(keys, c.nonce, cents=99_000_000)
    first = _check(keys, challenges, token, c.nonce)
    assert not first.passed
    assert any("exceeds maximum" in r for r in first.reasons)
    second = _check(keys, challenges, token, c.nonce)
    assert "challenge" in second.reasons[0]


def test_verifier_error_fails_closed(keys, challenges, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(gate.mandates, "verify_chain", boom)
    c = challenges.issue(AUD)
    result = _check(keys, challenges, _token(keys, c.nonce), c.nonce)
    assert not result.passed
    assert result.reasons == ("internal error, failing closed",)


def test_challenge_store_error_fails_closed(keys):
    class Broken:
        def consume(self, aud, nonce):
            raise RuntimeError("store down")

    result = _check(keys, Broken(), _token(keys, "n"), "n")
    assert not result.passed


def test_ok_with_violations_is_not_a_pass(keys, challenges, monkeypatch):
    monkeypatch.setattr(
        gate.mandates,
        "verify_chain",
        lambda *a, **k: m.ChainResult(ok=True, violations=["something"]),
    )
    c = challenges.issue(AUD)
    result = _check(keys, challenges, _token(keys, c.nonce), c.nonce)
    assert not result.passed
    assert result.reasons == ("something",)


OTHER = Merchant(id="someone-else", name="Someone Else Ltd")
BUDGET = 140_000_000
PAYMENT = 34_000_000


def _sdk_says_ok(monkeypatch):
    monkeypatch.setattr(
        gate.mandates,
        "verify_chain",
        lambda *a, **k: m.ChainResult(ok=True, violations=[]),
    )


def _run(keys, challenges, *, payee=SUPPLIER, cents=PAYMENT, usage=None, **open_kwargs):
    user, agent = keys
    c = challenges.issue(AUD)
    open_token = m.sign_open(
        m.open_payment_mandate(payee=SUPPLIER, max_minor=CAP, agent_key=agent, **open_kwargs),
        user,
    )
    closed = m.closed_payment_mandate(
        transaction_id="tx-1", payee=payee, amount_minor=cents, instrument=ACCOUNT
    )
    token = m.delegate(open_token, closed, agent, aud=AUD, nonce=c.nonce)
    return gate.check(
        token,
        user_public=m.public_only(user),
        aud=AUD,
        nonce=c.nonce,
        expected_transaction_id="tx-1",
        challenges=challenges,
        usage=usage,
    )


def test_own_check_catches_over_cap_when_sdk_says_ok(keys, challenges, monkeypatch):
    _sdk_says_ok(monkeypatch)
    result = _run(keys, challenges, cents=99_000_000)
    assert not result.passed
    assert "disagrees" in result.reasons[0]
    assert any("exceeds mandate maximum" in r for r in result.reasons)


def test_own_check_catches_wrong_payee_when_sdk_says_ok(keys, challenges, monkeypatch):
    _sdk_says_ok(monkeypatch)
    result = _run(keys, challenges, payee=OTHER)
    assert not result.passed
    assert any("not allowed" in r for r in result.reasons)


def test_budget_boundary_through_the_gate(keys, challenges):
    from ap2.sdk.constraints import MandateContext

    kw = dict(max_occurrences=4, budget_minor=BUDGET)
    at_limit = _run(
        keys, challenges, usage=MandateContext(total_uses=3, total_amount=BUDGET - PAYMENT), **kw
    )
    assert at_limit.passed, at_limit.reasons
    over = _run(
        keys, challenges, usage=MandateContext(total_uses=3, total_amount=BUDGET - PAYMENT + 1), **kw
    )
    assert not over.passed


def test_own_budget_check_catches_overspend_when_sdk_says_ok(keys, challenges, monkeypatch):
    from ap2.sdk.constraints import MandateContext

    _sdk_says_ok(monkeypatch)
    result = _run(
        keys,
        challenges,
        usage=MandateContext(total_uses=3, total_amount=BUDGET - PAYMENT + 1),
        max_occurrences=4,
        budget_minor=BUDGET,
    )
    assert not result.passed
    assert any("cumulative spend" in r for r in result.reasons)


def test_budget_without_spend_history_fails_closed(keys, challenges, monkeypatch):
    _sdk_says_ok(monkeypatch)
    result = _run(keys, challenges, max_occurrences=4, budget_minor=BUDGET)
    assert not result.passed
    assert any("spend history" in r for r in result.reasons)


def test_exhausted_recurrence_is_caught_when_sdk_says_ok(keys, challenges, monkeypatch):
    from ap2.sdk.constraints import MandateContext

    _sdk_says_ok(monkeypatch)
    result = _run(
        keys,
        challenges,
        usage=MandateContext(total_uses=4, total_amount=0),
        max_occurrences=4,
        budget_minor=BUDGET,
    )
    assert not result.passed
    assert any("maximum uses" in r for r in result.reasons)


def test_budget_conversion_to_cents_is_exact():
    # int(19.99 * 100) would give 1998
    assert gate._budget_minor(19.99) == 1999
    assert gate._budget_minor(1_400_000.0) == 140_000_000


def test_ledger_drives_the_gate_across_four_uses(keys, challenges):
    from pipeline.ledger import MemorySpendLedger

    ledger = MemorySpendLedger()
    kw = dict(max_occurrences=4, budget_minor=BUDGET)
    for i in range(4):
        result = _run(keys, challenges, usage=ledger.usage("mandate-1"), **kw)
        assert result.passed, (i, result.reasons)
        ledger.record("mandate-1", f"pay-{i}", PAYMENT)
    fifth = _run(keys, challenges, usage=ledger.usage("mandate-1"), **kw)
    assert not fifth.passed
