"""Supplier-signed checkout: the order a payment mandate is bound to.

Money is integer minor units. The checkout hash is base64url(SHA-256) over the
signed JWT string; the payment mandate's transaction_id carries it.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ap2.sdk.generated.types.checkout import Checkout, Status
from ap2.sdk.generated.types.item import Item
from ap2.sdk.generated.types.line_item import LineItem
from ap2.sdk.generated.types.merchant import Merchant
from ap2.sdk.generated.types.total import Total
from ap2.sdk.utils import compute_sha256_b64url
from jwcrypto.jwk import JWK
from jwcrypto.jws import JWS

ALG = "ES256"
TOTAL = "total"
SUBTOTAL = "subtotal"


class CheckoutError(ValueError):
    pass


@dataclass(frozen=True)
class SignedCheckout:
    jwt: str
    hash: str


def build_checkout(
    *,
    checkout_id: str,
    merchant: Merchant,
    currency: str,
    lines,
    now: datetime | None = None,
    ttl: int = 600,
) -> Checkout:
    """lines: iterable of (item_id, title, unit_price_minor, quantity)."""
    now = now or datetime.now(timezone.utc)
    items = []
    grand = 0
    for item_id, title, unit, qty in lines:
        if not isinstance(unit, int) or unit < 0 or not isinstance(qty, int) or qty < 1:
            raise CheckoutError("line items need a non-negative integer price and a quantity of at least 1")
        line_total = unit * qty
        grand += line_total
        items.append(
            LineItem(
                id=f"li-{item_id}",
                item=Item(id=item_id, title=title, price=unit),
                quantity=qty,
                totals=[Total(type=SUBTOTAL, amount=line_total)],
            )
        )
    if not items:
        raise CheckoutError("a checkout needs at least one line item")
    return Checkout(
        id=checkout_id,
        merchant=merchant,
        line_items=items,
        status=Status.ready_for_complete,
        currency=currency,
        totals=[Total(type=SUBTOTAL, amount=grand), Total(type=TOTAL, amount=grand)],
        links=[],
        expires_at=now + timedelta(seconds=ttl),
    )


def compute_hash(checkout_jwt: str) -> str:
    """The checkout hash a payment mandate carries as its transaction_id."""
    return compute_sha256_b64url(checkout_jwt)


def sign_checkout(checkout: Checkout, supplier_key: JWK) -> SignedCheckout:
    payload = json.dumps(
        checkout.model_dump(mode="json", exclude_none=True),
        separators=(",", ":"),
        sort_keys=True,
    )
    jws = JWS(payload)
    jws.add_signature(supplier_key, alg=ALG, protected=json.dumps({"alg": ALG, "typ": "JWT"}))
    token = jws.serialize(compact=True)
    return SignedCheckout(jwt=token, hash=compute_hash(token))


def grand_total_minor(checkout: Checkout) -> int:
    totals = [t for t in checkout.totals if t.type == TOTAL]
    if len(totals) != 1:
        raise CheckoutError("checkout must carry exactly one total")
    return totals[0].amount


def verify_checkout(token: str, supplier_public: JWK, *, now: datetime | None = None) -> Checkout:
    """Verify the supplier's signature and the checkout's own consistency."""
    if not isinstance(token, str) or token.count(".") != 2:
        raise CheckoutError("checkout must be a compact JWT")
    try:
        jws = JWS()
        jws.deserialize(token)
        if jws.jose_header.get("alg") != ALG:
            raise CheckoutError("checkout must be signed with ES256")
        jws.verify(supplier_public, alg=ALG)
        checkout = Checkout.model_validate(json.loads(jws.payload))
    except Exception as exc:
        raise CheckoutError("checkout signature or content is invalid") from exc

    now = now or datetime.now(timezone.utc)
    if checkout.expires_at is None:
        raise CheckoutError("checkout has no expiry")
    if checkout.expires_at <= now:
        raise CheckoutError("checkout has expired")
    if checkout.status != Status.ready_for_complete:
        raise CheckoutError("checkout is not ready for completion")

    expected = 0
    for li in checkout.line_items:
        if li.item.price < 0 or li.quantity < 1:
            raise CheckoutError("checkout has an invalid line item")
        expected += li.item.price * li.quantity
    total = grand_total_minor(checkout)
    if total != expected:
        raise CheckoutError(f"checkout total {total} does not match its line items {expected}")
    return checkout
