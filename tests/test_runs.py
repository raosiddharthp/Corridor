import asyncio
import contextlib
import functools
import json

import httpx
from fastapi import FastAPI

import app.runs as runs
import pipeline.events as ev
import pipeline.interpreter as itp
import pipeline.keys as pkeys
import pipeline.mandates as m
import pipeline.negotiation as neg
import pipeline.orchestrator as orch
from pipeline.challenge import MemoryChallengeStore
from pipeline.ledger import MemorySpendLedger
from pipeline.tiering import TIER2
from supplier import app as supplier_app

BASE = "http://supplier.test"
FP_88213 = {"order_ref": "FP-88213"}


@contextlib.asynccontextmanager
async def _client(**router_kwargs):
    supplier = m.new_key()
    supplier_asgi = supplier_app.create_app(supplier, BASE)
    keys = pkeys.KeySet(
        user=m.new_key(), agent=m.new_key(), supplier_public=m.public_only(supplier)
    )
    events = ev.MemoryEventLog()
    challenges = MemoryChallengeStore()
    ledger = MemorySpendLedger()
    transport = httpx.ASGITransport(app=supplier_asgi)
    async with httpx.AsyncClient(transport=transport, base_url=BASE, timeout=10) as http:

        def make(hostile):
            quote = (
                functools.partial(neg.request_quote, demo_hostile=True)
                if hostile
                else neg.request_quote
            )
            return orch.Orchestrator(
                keys=keys,
                supplier_url=BASE,
                http=http,
                events=events,
                challenges=challenges,
                ledger=ledger,
                interpreter=itp.RuleInterpreter(),
                quote=quote,
            )

        api = FastAPI()
        api.include_router(
            runs.make_router(make_orchestrator=make, events=events, **router_kwargs)
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api), base_url="http://corridor.test", timeout=10
        ) as client:
            yield client


def _parse(text):
    parsed = []
    for block in text.strip().split("\n\n"):
        head, body = block.split("\n")
        parsed.append((head.removeprefix("event: "), json.loads(body.removeprefix("data: "))))
    return parsed


def _once(body, **kwargs):
    async def go():
        async with _client(**kwargs) as client:
            return await client.post("/runs", json=body)

    return asyncio.run(go())


def _twice(body, **kwargs):
    async def go():
        async with _client(**kwargs) as client:
            first = await client.post("/runs", json=body)
            second = await client.post("/runs", json=body)
            return first, second

    return asyncio.run(go())


def test_a_run_streams_its_events_then_a_result():
    response = _once(FP_88213)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    kinds = [kind for kind, _ in _parse(response.text)]
    assert kinds == [
        "run.started",
        "negotiation.offer",
        "interpreter.proposal",
        "gate.screening",
        "gate.mandate",
        "tier.decision",
        "rail.selected",
        "run.completed",
        "result",
    ]
    assert dict(_parse(response.text))["result"]["status"] == orch.READY


def test_fp_88214_streams_a_human_approval_result():
    result = dict(_parse(_once({"order_ref": "FP-88214"}).text))["result"]
    assert result["status"] == orch.AWAITING


def test_the_hostile_demo_switch_sends_the_order_to_a_human():
    body = {"order_ref": "FP-88213", "demo_hostile": True}
    result = dict(_parse(_once(body).text))["result"]
    assert result["tier"] == TIER2


def test_the_stream_never_carries_the_signed_checkout():
    assert "eyJ" not in _once(FP_88213).text


def test_an_unknown_order_is_not_found():
    assert _once({"order_ref": "FP-00000"}).status_code == 404


def test_unknown_fields_are_rejected():
    assert _once({"order_ref": "FP-88213", "amount": 1}).status_code == 422


def test_a_non_text_order_ref_is_rejected():
    assert _once({"order_ref": 123}).status_code == 422


def test_the_per_minute_limit_answers_429():
    first, second = _twice(FP_88213, max_per_minute=1)
    assert (first.status_code, second.status_code) == (200, 429)


def test_the_concurrency_cap_answers_429():
    assert _once(FP_88213, max_concurrent=0).status_code == 429


def test_a_finished_run_frees_its_slot():
    first, second = _twice(FP_88213, max_concurrent=1)
    assert (first.status_code, second.status_code) == (200, 200)


def test_events_can_be_read_back_after_a_run():
    async def go():
        async with _client() as client:
            run = await client.post("/runs", json=FP_88213)
            run_id = _parse(run.text)[0][1]["run_id"]
            full = await client.get(f"/runs/{run_id}/events")
            later = await client.get(f"/runs/{run_id}/events", params={"after": 3})
            return full, later

    full, later = asyncio.run(go())
    assert full.status_code == 200
    assert len(full.json()["events"]) == 8
    assert [e["seq"] for e in later.json()["events"]] == [4, 5, 6, 7, 8]


def test_reading_an_unknown_run_is_not_found():
    async def go():
        async with _client() as client:
            return await client.get("/runs/nope/events"), await client.get("/runs/bad.id/events")

    unknown, invalid = asyncio.run(go())
    assert unknown.status_code == 404
    assert invalid.status_code == 422
