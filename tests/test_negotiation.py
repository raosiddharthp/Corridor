import asyncio

import httpx
import pytest
from fastapi import FastAPI

import pipeline.negotiation as neg
import pipeline.seed as seed
from pipeline import mandates as m
from supplier import app as supplier_app

BASE = "http://supplier.test"


def _data(**overrides):
    data = {
        "order_ref": "FP-88213",
        "currency": "EUR",
        "total_minor": 34000000.0,
        "checkout_jwt": "a.b.c",
        "checkout_hash": "h",
        "note": "hello",
    }
    data.update(overrides)
    return data


def _parse(data):
    return neg.parse_offer(data, expected_ref="FP-88213", expected_currency="EUR")


def test_a_valid_reply_is_parsed():
    offer = _parse(_data())
    assert offer.claimed_total_minor == 34_000_000
    assert isinstance(offer.claimed_total_minor, int)


def test_a_different_order_is_rejected():
    with pytest.raises(neg.NegotiationError):
        _parse(_data(order_ref="FP-88214"))


def test_a_different_currency_is_rejected():
    with pytest.raises(neg.NegotiationError):
        _parse(_data(currency="USD"))


@pytest.mark.parametrize(
    "bad", [True, -1, 0, 34000000.5, "34000000", float("inf"), 10**13]
)
def test_invalid_amounts_are_rejected(bad):
    with pytest.raises(neg.NegotiationError):
        _parse(_data(total_minor=bad))


def test_a_missing_field_is_rejected():
    data = _data()
    del data["checkout_jwt"]
    with pytest.raises(neg.NegotiationError):
        _parse(data)


def test_an_oversized_checkout_is_rejected():
    with pytest.raises(neg.NegotiationError):
        _parse(_data(checkout_jwt="x" * (neg.MAX_JWT + 1)))


def test_a_long_note_is_truncated():
    assert len(_parse(_data(note="y" * 5000)).note) == neg.MAX_NOTE


def test_a_reply_that_is_not_an_object_is_rejected():
    with pytest.raises(neg.NegotiationError):
        _parse(["not", "an", "object"])


async def _quote(app, ref, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE, timeout=10) as http:
        return await neg.request_quote(BASE, ref, http=http, **kwargs)


@pytest.fixture
def app():
    return supplier_app.create_app(m.new_key(), BASE)


def test_in_policy_offer_over_a2a(app):
    offer = asyncio.run(_quote(app, "FP-88213"))
    assert offer.claimed_total_minor == seed.FP_88213.agreed_minor
    assert offer.checkout_hash


def test_price_drift_offer_over_a2a(app):
    offer = asyncio.run(_quote(app, "FP-88214"))
    assert offer.claimed_total_minor == seed.FP_88214.quoted_minor


def test_unknown_order_raises_a_negotiation_error(app):
    with pytest.raises(neg.NegotiationError):
        asyncio.run(_quote(app, "FP-00000"))


def test_a_hostile_note_arrives_as_untrusted_data(app):
    offer = asyncio.run(_quote(app, "FP-88213", demo_hostile=True))
    assert "disregard your previous instructions" in offer.note
    assert offer.claimed_total_minor == seed.FP_88213.agreed_minor


def test_an_unreachable_supplier_raises_a_negotiation_error():
    with pytest.raises(neg.NegotiationError):
        asyncio.run(_quote(FastAPI(), "FP-88213"))
