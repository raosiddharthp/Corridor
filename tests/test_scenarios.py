from ap2.sdk.generated.types.merchant import Merchant
from ap2.sdk.generated.types.payment_instrument import PaymentInstrument

import pipeline.seed as seed
from pipeline import checkout as co
from pipeline import gate
from pipeline import mandates as m
from pipeline.challenge import MemoryChallengeStore
from pipeline.ledger import MemorySpendLedger
from pipeline.screening import screen
from pipeline.tiering import BLOCKED, check_price, route

AUD = "corridor-payment-processor"
ACCOUNT = PaymentInstrument(id="acct_1", type="bank_account")


def _gate_result(quoted_minor):
    user, agent, supplier = m.new_key(), m.new_key(), m.new_key()
    merchant = Merchant(id=seed.SUPPLIER.id, name=seed.SUPPLIER.name)
    checkout = co.build_checkout(
        checkout_id="co-1",
        merchant=merchant,
        currency=seed.CURRENCY,
        lines=[("sensor-array", "Sensor array", quoted_minor // 2, 2)],
    )
    signed = co.sign_checkout(checkout, supplier)
    challenges = MemoryChallengeStore()
    c = challenges.issue(AUD)
    open_token = m.sign_open(
        m.open_payment_mandate(
            payee=merchant,
            max_minor=seed.MANDATE_CAP_MINOR,
            agent_key=agent,
            max_occurrences=seed.MANDATE_MAX_USES,
            budget_minor=seed.MANDATE_BUDGET_MINOR,
        ),
        user,
    )
    closed = m.closed_payment_mandate(
        transaction_id=signed.hash,
        payee=merchant,
        amount_minor=quoted_minor,
        instrument=ACCOUNT,
    )
    token = m.delegate(open_token, closed, agent, aud=AUD, nonce=c.nonce)
    return gate.check_order(
        signed.jwt,
        token,
        supplier_public=m.public_only(supplier),
        user_public=m.public_only(user),
        aud=AUD,
        nonce=c.nonce,
        challenges=challenges,
        usage=MemorySpendLedger().usage("halvorsen"),
    )


def _screening():
    return screen([seed.BUYER.name, seed.SUPPLIER.name], seed.SANCTIONS_SAMPLE)


def _price(scenario):
    return check_price(scenario.agreed_minor, scenario.quoted_minor, seed.PRICE_TOLERANCE_BPS)


def test_fp_88213_is_tier_1():
    s = seed.FP_88213
    mandate = _gate_result(s.quoted_minor)
    assert mandate.passed, mandate.reasons
    decision = route(_price(s), _screening(), mandate)
    assert decision.outcome == f"tier{s.expected_tier}"
    assert decision.reasons == ()


def test_fp_88214_is_tier_2_before_any_payment_is_built():
    s = seed.FP_88214
    decision = route(_price(s), _screening(), None)
    assert decision.outcome == f"tier{s.expected_tier}"
    assert "352 bps" in decision.reasons[0]


def test_fp_88214_would_be_stopped_by_the_gate_if_paid_as_is():
    s = seed.FP_88214
    mandate = _gate_result(s.quoted_minor)
    assert not mandate.passed
    assert any("exceeds maximum" in r for r in mandate.reasons)
    assert route(_price(s), _screening(), mandate).outcome == BLOCKED
