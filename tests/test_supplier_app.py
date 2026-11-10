import asyncio
import inspect

import httpx
import pytest
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client import ClientConfig
from a2a.client.client_factory import create_client
from a2a.helpers.proto_helpers import get_data_parts, new_text_message
from a2a.types import Role, SendMessageRequest, TaskState

import pipeline.seed as seed
from pipeline import checkout as co
from pipeline import mandates as m
from supplier import app as supplier_app
from supplier.quotes import NOTE_DRIFT, NOTE_IN_POLICY, UnknownOrder

BASE = "http://supplier.test"


@pytest.fixture
def key():
    return m.new_key()


@pytest.fixture
def app(key):
    return supplier_app.create_app(key, BASE)


async def _maybe(result):
    return await result if inspect.isawaitable(result) else result


async def _talk(app, text):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as http:
        card = await A2ACardResolver(http, BASE).get_agent_card()
        config = ClientConfig(streaming=False, httpx_client=http)
        client = await _maybe(create_client(card, client_config=config))
        request = SendMessageRequest(message=new_text_message(text, role=Role.ROLE_USER))
        responses = [r async for r in client.send_message(request)]
    return card, responses


def _task(responses):
    tasks = [r.task for r in responses if r.HasField("task")]
    assert tasks, f"no task in the responses: {responses}"
    return tasks[-1]


def _quote(task):
    return get_data_parts(task.artifacts[0].parts)[0]


def test_agent_card_is_discoverable(app):
    card, _ = asyncio.run(_talk(app, "quote FP-88213"))
    assert card.name == "BrunnerTeknik sales agent"
    assert [s.id for s in card.skills] == ["quote"]
    assert card.supported_interfaces[0].url == BASE + "/a2a"


def test_in_policy_quote_over_a2a(app, key):
    _, responses = asyncio.run(_talk(app, "quote FP-88213"))
    task = _task(responses)
    assert task.status.state == TaskState.TASK_STATE_COMPLETED
    quote = _quote(task)
    assert int(quote["total_minor"]) == seed.FP_88213.agreed_minor
    assert quote["note"] == NOTE_IN_POLICY
    checkout = co.verify_checkout(quote["checkout_jwt"], m.public_only(key))
    assert co.grand_total_minor(checkout) == seed.FP_88213.agreed_minor


def test_price_drift_quote_over_a2a(app):
    _, responses = asyncio.run(_talk(app, "quote FP-88214"))
    quote = _quote(_task(responses))
    assert int(quote["total_minor"]) == seed.FP_88214.quoted_minor
    assert quote["note"] == NOTE_DRIFT


def test_hostile_marker_adds_the_injection(app):
    _, responses = asyncio.run(_talk(app, "quote FP-88213 [demo:hostile]"))
    quote = _quote(_task(responses))
    assert "disregard your previous instructions" in quote["note"]
    assert int(quote["total_minor"]) == seed.FP_88213.agreed_minor


def test_unknown_order_fails_the_task(app):
    _, responses = asyncio.run(_talk(app, "quote FP-00000"))
    assert _task(responses).status.state == TaskState.TASK_STATE_FAILED


def test_health_endpoint(app):
    async def call():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as http:
            return (await http.get("/health")).json()

    assert asyncio.run(call())["status"] == "ok"


def test_parse_request_reads_the_order_ref():
    assert supplier_app.parse_request("quote FP-88213") == ("FP-88213", False)


def test_parse_request_reads_the_hostile_marker():
    assert supplier_app.parse_request("quote FP-88213 [demo:hostile]") == ("FP-88213", True)


def test_parse_request_rejects_anything_else():
    with pytest.raises(UnknownOrder):
        supplier_app.parse_request("hello there")
