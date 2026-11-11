"""Builds a user-signed payment and runs it through the Mandate Integrity Gate."""
import logging

from ap2.sdk.generated.types.merchant import Merchant
from ap2.sdk.generated.types.payment_instrument import PaymentInstrument

from pipeline import gate
from pipeline import mandates as m
from pipeline import seed

log = logging.getLogger(__name__)

AUD = "corridor-payment-processor"
ACCOUNT = PaymentInstrument(id="acct_1", type="bank_account")


def gate_payment(
    *, keys, challenges, ledger, checkout_jwt, total_minor, transaction_id, cap_minor
) -> gate.GateResult:
    try:
        challenge = challenges.issue(AUD)
        merchant = Merchant(id=seed.SUPPLIER.id, name=seed.SUPPLIER.name)
        open_token = m.sign_open(
            m.open_payment_mandate(
                payee=merchant,
                max_minor=cap_minor,
                agent_key=keys.agent,
                max_occurrences=seed.MANDATE_MAX_USES,
                budget_minor=seed.MANDATE_BUDGET_MINOR,
            ),
            keys.user,
        )
        closed = m.closed_payment_mandate(
            transaction_id=transaction_id,
            payee=merchant,
            amount_minor=total_minor,
            instrument=ACCOUNT,
        )
        token = m.delegate(open_token, closed, keys.agent, aud=AUD, nonce=challenge.nonce)
        return gate.check_order(
            checkout_jwt,
            token,
            supplier_public=keys.supplier_public,
            user_public=m.public_only(keys.user),
            aud=AUD,
            nonce=challenge.nonce,
            challenges=challenges,
            usage=ledger.usage(seed.BUYER.id),
        )
    except Exception:
        log.exception("could not build the payment")
        return gate.GateResult(gate.GATE, False, ("payment could not be built",))
