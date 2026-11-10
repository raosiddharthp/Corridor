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
