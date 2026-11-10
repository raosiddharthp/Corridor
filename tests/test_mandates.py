import pytest
from ap2.sdk.generated.types.merchant import Merchant
from ap2.sdk.generated.types.payment_instrument import PaymentInstrument

from pipeline import mandates as m

SUPPLIER = Merchant(id="brunnerteknik", name="BrunnerTeknik GmbH")
OTHER = Merchant(id="someone-else", name="Someone Else Ltd")
ACCOUNT = PaymentInstrument(id="acct_1", type="bank_account")
AUD, NONCE = "corridor-payment-processor", "nonce-0001"
CAP = 34_500_000
BUDGET = 140_000_000


@pytest.fixture
def keys():
    return m.new_key(), m.new_key()  # (user, agent)


def run(keys, *, payee=SUPPLIER, cents=34_000_000, nonce=NONCE, expected_tx="tx-1", verify_key=None):
    user, agent = keys
    open_token = m.sign_open(m.open_payment_mandate(payee=SUPPLIER, max_minor=CAP, agent_key=agent), user)
    closed = m.closed_payment_mandate(transaction_id="tx-1", payee=payee, amount_minor=cents, instrument=ACCOUNT)
    token = m.delegate(open_token, closed, agent, aud=AUD, nonce=NONCE)
    return m.verify_chain(
        token,
        user_public=verify_key or m.public_only(user),
        aud=AUD,
        nonce=nonce,
        expected_transaction_id=expected_tx,
    )


def test_in_bounds_is_accepted(keys):
    result = run(keys)
    assert result.ok and result.violations == []


def test_over_the_cap_is_rejected(keys):
    result = run(keys, cents=99_000_000)
    assert not result.ok
    assert any("exceeds maximum" in v for v in result.violations)


def test_wrong_payee_is_rejected(keys):
    result = run(keys, payee=OTHER)
    assert not result.ok
    assert any("not in allowed list" in v for v in result.violations)


def test_wrong_nonce_is_rejected(keys):
    assert not run(keys, nonce="some-other-nonce").ok


def test_wrong_root_key_is_rejected(keys):
    assert not run(keys, verify_key=m.public_only(m.new_key())).ok


def test_transaction_id_mismatch_is_rejected(keys):
    result = run(keys, expected_tx="tx-999")
    assert not result.ok
    assert any("transaction_id mismatch" in v for v in result.violations)


def _signed(keys, **open_kwargs):
    user, agent = keys
    return m.sign_open(
        m.open_payment_mandate(payee=SUPPLIER, max_minor=CAP, agent_key=agent, **open_kwargs), user
    )


def _delegated(keys, open_token, cents=34_000_000, **delegate_kwargs):
    _, agent = keys
    closed = m.closed_payment_mandate(
        transaction_id="tx-1", payee=SUPPLIER, amount_minor=cents, instrument=ACCOUNT
    )
    return m.delegate(open_token, closed, agent, aud=AUD, nonce=NONCE, **delegate_kwargs)


def _check(keys, token, **kwargs):
    return m.verify_chain(
        token,
        user_public=m.public_only(keys[0]),
        aud=AUD,
        nonce=NONCE,
        expected_transaction_id="tx-1",
        **kwargs,
    )


def test_recurrence_survives_signing(keys):
    token = _delegated(keys, _signed(keys, max_occurrences=4, budget_minor=BUDGET))
    chain = m.verified_chain(token, user_public=m.public_only(keys[0]), aud=AUD, nonce=NONCE)
    by_type = {c.type: c for c in chain.open_mandate.constraints}
    recurrence = by_type["payment.agent_recurrence"]
    assert recurrence.max_occurrences == 4
    assert getattr(recurrence.frequency, "value", recurrence.frequency) == "QUARTERLY"


def test_first_use_under_recurrence_is_accepted(keys):
    token = _delegated(keys, _signed(keys, max_occurrences=4, budget_minor=BUDGET))
    result = _check(keys, token)
    assert result.ok, result.violations


def test_fifth_use_under_recurrence_is_rejected(keys):
    from ap2.sdk.constraints import MandateContext

    token = _delegated(keys, _signed(keys, max_occurrences=4, budget_minor=BUDGET))
    result = _check(keys, token, usage=MandateContext(total_uses=4, total_amount=136_000_000))
    print("fifth-use violations:", result.violations)
    assert not result.ok, "the SDK did not enforce max_occurrences"


def test_agent_cannot_hide_constraints(keys):
    token = _delegated(keys, _signed(keys), cents=99_000_000, claims_to_disclose={})
    result = _check(keys, token)
    print("hidden-constraint violations:", result.violations)
    assert not result.ok, "an over-limit mandate slipped through with its constraints hidden"


def test_budget_allows_spend_within_limit(keys):
    from ap2.sdk.constraints import MandateContext

    token = _delegated(keys, _signed(keys, max_occurrences=4, budget_minor=BUDGET))
    result = _check(keys, token, usage=MandateContext(total_uses=2, total_amount=100_000_000))
    print("within-budget violations:", result.violations)
    assert result.ok, result.violations


def test_budget_blocks_overspend_across_uses(keys):
    from ap2.sdk.constraints import MandateContext

    token = _delegated(keys, _signed(keys, max_occurrences=4, budget_minor=BUDGET))
    result = _check(keys, token, usage=MandateContext(total_uses=3, total_amount=108_000_000))
    print("overspend violations:", result.violations)
    assert not result.ok, "108M already spent plus 34M should exceed the 140M budget"


def test_budget_boundary_is_exact(keys):
    from ap2.sdk.constraints import MandateContext

    token = _delegated(keys, _signed(keys, max_occurrences=4, budget_minor=BUDGET))
    at_limit = _check(keys, token, usage=MandateContext(total_uses=3, total_amount=BUDGET - CAP))
    assert at_limit.ok, at_limit.violations

    one_cent_over = _check(keys, token, usage=MandateContext(total_uses=3, total_amount=BUDGET - CAP + 1))
    assert not one_cent_over.ok
    assert any("exceeds" in v for v in one_cent_over.violations), one_cent_over.violations
