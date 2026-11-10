"""Negotiation Agent: the A2A client that asks the supplier for a quote.

Everything the supplier sends is untrusted data. The amount is only a claim;
the price that counts is the total in the supplier-signed checkout, verified
by the gate.
"""
import inspect
from dataclasses import dataclass

import httpx
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client import ClientConfig
from a2a.client.client_factory import create_client
from a2a.helpers.proto_helpers import get_data_parts, new_text_message
from a2a.types import Role, SendMessageRequest, TaskState

MAX_NOTE = 1000
MAX_JWT = 20_000
MAX_HASH = 200
MAX_MINOR = 10**12
HOSTILE_MARKER = "[demo:hostile]"


class NegotiationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Offer:
    order_ref: str
    currency: str
    claimed_total_minor: int
    checkout_jwt: str
    checkout_hash: str
    note: str


async def _maybe(result):
    return await result if inspect.isawaitable(result) else result


def _minor(value) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not float(value).is_integer()
        or not 0 < value <= MAX_MINOR
    ):
        raise NegotiationError("supplier sent an invalid amount")
    return int(value)


def _text(data: dict, key: str, limit: int) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value or len(value) > limit:
        raise NegotiationError(f"supplier sent an invalid {key}")
    return value


def parse_offer(data, *, expected_ref: str, expected_currency: str) -> Offer:
    if not isinstance(data, dict):
        raise NegotiationError("supplier reply is not an object")
    for key in ("order_ref", "currency", "total_minor", "checkout_jwt", "checkout_hash", "note"):
        if key not in data:
            raise NegotiationError(f"supplier reply is missing {key}")
    if data["order_ref"] != expected_ref:
        raise NegotiationError("supplier answered a different order")
    if data["currency"] != expected_currency:
        raise NegotiationError("supplier quoted in a different currency")
    note = data["note"]
    if not isinstance(note, str):
        raise NegotiationError("supplier sent an invalid note")
    return Offer(
        order_ref=expected_ref,
        currency=expected_currency,
        claimed_total_minor=_minor(data["total_minor"]),
        checkout_jwt=_text(data, "checkout_jwt", MAX_JWT),
        checkout_hash=_text(data, "checkout_hash", MAX_HASH),
        note=note[:MAX_NOTE],
    )


async def request_quote(
    base_url: str,
    order_ref: str,
    *,
    http: httpx.AsyncClient,
    expected_currency: str = "EUR",
    demo_hostile: bool = False,
) -> Offer:
    text = f"quote {order_ref}" + (f" {HOSTILE_MARKER}" if demo_hostile else "")
    try:
        card = await A2ACardResolver(http, base_url).get_agent_card()
        config = ClientConfig(streaming=False, httpx_client=http)
        client = await _maybe(create_client(card, client_config=config))
        request = SendMessageRequest(message=new_text_message(text, role=Role.ROLE_USER))
        responses = [r async for r in client.send_message(request)]
    except Exception as exc:
        raise NegotiationError("supplier could not be reached or rejected the request") from exc

    tasks = [r.task for r in responses if r.HasField("task")]
    if not tasks:
        raise NegotiationError("supplier sent no task")
    task = tasks[-1]
    if task.status.state != TaskState.TASK_STATE_COMPLETED:
        raise NegotiationError("supplier did not complete the quote")
    if not task.artifacts:
        raise NegotiationError("supplier sent no quote")
    parts = get_data_parts(task.artifacts[0].parts)
    if not parts:
        raise NegotiationError("supplier sent no quote data")
    return parse_offer(parts[0], expected_ref=order_ref, expected_currency=expected_currency)
