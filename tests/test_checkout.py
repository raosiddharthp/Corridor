import json
from datetime import datetime, timedelta, timezone

import pytest
from ap2.sdk.generated.types.checkout import Status
from ap2.sdk.generated.types.merchant import Merchant
from ap2.sdk.generated.types.total import Total
from ap2.sdk.utils import compute_sha256_b64url
from jwcrypto.common import base64url_decode, base64url_encode

from pipeline import checkout as co
from pipeline import mandates as m

SUPPLIER = Merchant(id="brunnerteknik", name="BrunnerTeknik GmbH")
LINES = [("sensor-array", "Sensor array", 17_000_000, 2)]  # EUR 340,000


@pytest.fixture
def key():
    return m.new_key()


def _checkout(lines=LINES, **kwargs):
    return co.build_checkout(
        checkout_id="co-1", merchant=SUPPLIER, currency="EUR", lines=lines, **kwargs
    )


def test_signed_checkout_round_trips(key):
    signed = co.sign_checkout(_checkout(), key)
    checkout = co.verify_checkout(signed.jwt, m.public_only(key))
    assert checkout.id == "co-1"
    assert co.grand_total_minor(checkout) == 34_000_000
    assert signed.hash == compute_sha256_b64url(signed.jwt)


def test_hash_changes_with_the_order(key):
    a = co.sign_checkout(_checkout(), key)
    b = co.sign_checkout(_checkout(lines=[("sensor-array", "Sensor array", 17_000_000, 3)]), key)
    assert a.hash != b.hash


def test_tampered_payload_is_rejected(key):
    signed = co.sign_checkout(_checkout(), key)
    head, body, sig = signed.jwt.split(".")
    payload = json.loads(base64url_decode(body))
    for t in payload["totals"]:
        if t["type"] == co.TOTAL:
            t["amount"] = 1
    forged = ".".join([head, base64url_encode(json.dumps(payload)), sig])
    with pytest.raises(co.CheckoutError):
        co.verify_checkout(forged, m.public_only(key))


def test_wrong_supplier_key_is_rejected(key):
    signed = co.sign_checkout(_checkout(), key)
    with pytest.raises(co.CheckoutError):
        co.verify_checkout(signed.jwt, m.public_only(m.new_key()))


def test_unsigned_token_is_rejected(key):
    signed = co.sign_checkout(_checkout(), key)
    body = signed.jwt.split(".")[1]
    unsigned = f"{base64url_encode(json.dumps({'alg': 'none'}))}.{body}."
    with pytest.raises(co.CheckoutError):
        co.verify_checkout(unsigned, m.public_only(key))


def test_non_compact_token_is_rejected(key):
    with pytest.raises(co.CheckoutError):
        co.verify_checkout('{"payload": "x", "signatures": []}', m.public_only(key))


def test_expired_checkout_is_rejected(key):
    signed = co.sign_checkout(_checkout(), key)
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    with pytest.raises(co.CheckoutError, match="expired"):
        co.verify_checkout(signed.jwt, m.public_only(key), now=later)


def test_inconsistent_totals_are_rejected_even_when_validly_signed(key):
    bad = _checkout().model_copy(update={"totals": [Total(type=co.TOTAL, amount=1)]})
    signed = co.sign_checkout(bad, key)
    with pytest.raises(co.CheckoutError, match="does not match"):
        co.verify_checkout(signed.jwt, m.public_only(key))


def test_checkout_not_ready_is_rejected(key):
    bad = _checkout().model_copy(update={"status": Status.incomplete})
    signed = co.sign_checkout(bad, key)
    with pytest.raises(co.CheckoutError, match="not ready"):
        co.verify_checkout(signed.jwt, m.public_only(key))


def test_builder_rejects_a_zero_quantity():
    with pytest.raises(co.CheckoutError):
        _checkout(lines=[("sensor-array", "Sensor array", 17_000_000, 0)])
