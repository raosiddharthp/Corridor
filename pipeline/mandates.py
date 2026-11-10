"""Corridor's thin layer over the AP2 SDK: build, sign, delegate and verify payment mandates.

Money is always an integer in minor units (EUR cents).
"""
import json
import time
from dataclasses import dataclass, field
from typing import Any

from ap2.sdk.constraints import MandateContext
from ap2.sdk.generated.open_payment_mandate import (
    AgentRecurrence,
    AllowedPayees,
    AmountRange,
    Budget,
    OpenPaymentMandate,
)
from ap2.sdk.generated.payment_mandate import PaymentMandate
from ap2.sdk.generated.types.amount import Amount
from ap2.sdk.generated.types.merchant import Merchant
from ap2.sdk.generated.types.payment_instrument import PaymentInstrument
from ap2.sdk.mandate import MandateClient
from ap2.sdk.payment_mandate_chain import PaymentMandateChain
from jwcrypto.jwk import JWK
from pydantic import ConfigDict

CURRENCY = "EUR"
# The verifier insists on these, whatever the agent chooses to disclose.
REQUIRED_CONSTRAINTS = ("payment.allowed_payees", "payment.amount_range")
_client = MandateClient()


class _SerialisableRecurrence(AgentRecurrence):
    """Workaround: the pinned SDK cannot sign an enum-valued constraint, so keep the enum's value."""

    model_config = ConfigDict(use_enum_values=True)


def new_key() -> JWK:
    return JWK.generate(kty="EC", crv="P-256")


def public_only(key: JWK) -> JWK:
    return JWK.from_json(key.export_public())


def open_payment_mandate(
    *,
    payee: Merchant,
    max_minor: int,
    agent_key: JWK,
    max_occurrences: int | None = None,
    budget_minor: int | None = None,
    frequency: str = "QUARTERLY",
    now: int | None = None,
    ttl: int = 3600,
) -> OpenPaymentMandate:
    now = int(time.time()) if now is None else now
    constraints: list[Any] = [
        AllowedPayees(allowed=[payee]),
        AmountRange(currency=CURRENCY, max=max_minor),
    ]
    if max_occurrences is not None:
        if budget_minor is None:
            raise ValueError("a recurring mandate needs budget_minor (the SDK requires a budget)")
        constraints.append(Budget(max=budget_minor / 100, currency=CURRENCY))
        constraints.append(_SerialisableRecurrence(frequency=frequency, max_occurrences=max_occurrences))
    return OpenPaymentMandate(
        constraints=constraints,
        cnf={"jwk": json.loads(agent_key.export_public())},
        iat=now,
        exp=now + ttl,
    )


def closed_payment_mandate(
    *,
    transaction_id: str,
    payee: Merchant,
    amount_minor: int,
    instrument: PaymentInstrument,
    now: int | None = None,
    ttl: int = 600,
) -> PaymentMandate:
    now = int(time.time()) if now is None else now
    return PaymentMandate(
        transaction_id=transaction_id,
        payee=payee,
        payment_amount=Amount(amount=amount_minor, currency=CURRENCY),
        payment_instrument=instrument,
        iat=now,
        exp=now + ttl,
    )


def sign_open(mandate: OpenPaymentMandate, user_key: JWK) -> str:
    return _client.create(payloads=[mandate], issuer_key=user_key)


def delegate(
    open_token: str,
    closed: PaymentMandate,
    agent_key: JWK,
    *,
    aud: str,
    nonce: str,
    claims_to_disclose: dict[str, Any] | None = None,
) -> str:
    return _client.present(
        holder_key=agent_key,
        mandate_token=open_token,
        payloads=[closed],
        aud=aud,
        nonce=nonce,
        claims_to_disclose=claims_to_disclose,
    )


def verified_chain(token: str, *, user_public: JWK, aud: str, nonce: str) -> PaymentMandateChain:
    hops = _client.verify(token, lambda _tok: user_public, expected_aud=aud, expected_nonce=nonce)
    return PaymentMandateChain.parse(hops)


@dataclass
class ChainResult:
    ok: bool
    violations: list[str] = field(default_factory=list)


def verify_chain(
    token: str,
    *,
    user_public: JWK,
    aud: str,
    nonce: str,
    expected_transaction_id: str,
    usage: MandateContext | None = None,
    required_constraints: tuple[str, ...] = REQUIRED_CONSTRAINTS,
) -> ChainResult:
    """Verify signatures, SDK constraints and required constraints. Any failure rejects (fail closed)."""
    try:
        chain = verified_chain(token, user_public=user_public, aud=aud, nonce=nonce)
        violations = chain.verify(
            expected_transaction_id=expected_transaction_id,
            mandate_context=usage or MandateContext(),
        )
        present = {c.type for c in chain.open_mandate.constraints}
        for needed in required_constraints:
            if needed not in present:
                violations.append(f"required constraint missing from open mandate: {needed}")
    except Exception as exc:  # bad signature, audience, nonce, or malformed chain
        return ChainResult(False, [f"chain rejected: {type(exc).__name__}: {exc}"])
    return ChainResult(not violations, violations)
