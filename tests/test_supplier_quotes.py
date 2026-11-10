import pytest

import pipeline.seed as seed
from pipeline import checkout as co
from pipeline import mandates as m
from supplier import quotes as q


@pytest.fixture
def key():
    return m.new_key()


def _verified(quote, key):
    return co.verify_checkout(quote.checkout_jwt, m.public_only(key))


def test_fp_88213_is_quoted_at_the_agreed_price(key):
    quote = q.make_quote("FP-88213", key)
    checkout = _verified(quote, key)
    assert co.grand_total_minor(checkout) == seed.FP_88213.agreed_minor
    assert quote.total_minor == seed.FP_88213.agreed_minor
    assert quote.note == q.NOTE_IN_POLICY
    assert quote.checkout_hash == co.compute_hash(quote.checkout_jwt)


def test_fp_88214_is_quoted_with_a_price_drift(key):
    quote = q.make_quote("FP-88214", key)
    assert co.grand_total_minor(_verified(quote, key)) == seed.FP_88214.quoted_minor
    assert quote.total_minor > seed.FP_88214.agreed_minor
    assert quote.note == q.NOTE_DRIFT


def test_hostile_mode_keeps_the_price_and_adds_an_injection(key):
    quote = q.make_quote("FP-88213", key, hostile=True)
    assert co.grand_total_minor(_verified(quote, key)) == seed.FP_88213.agreed_minor
    assert "disregard your previous instructions" in quote.note


def test_unknown_order_is_refused(key):
    with pytest.raises(q.UnknownOrder):
        q.make_quote("FP-00000", key)


def test_the_quote_on_the_wire_does_not_announce_a_behaviour(key):
    wire = q.make_quote("FP-88213", key, hostile=True).to_dict()
    assert set(wire) == {
        "order_ref", "currency", "total_minor", "checkout_jwt", "checkout_hash", "note",
    }


def test_the_checkout_names_the_supplier_as_merchant(key):
    checkout = _verified(q.make_quote("FP-88213", key), key)
    assert checkout.merchant.id == seed.SUPPLIER.id


def test_another_key_cannot_verify_the_quote(key):
    quote = q.make_quote("FP-88213", key)
    with pytest.raises(co.CheckoutError):
        co.verify_checkout(quote.checkout_jwt, m.public_only(m.new_key()))
