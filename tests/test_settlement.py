import asyncio
import contextlib
import functools
import json
import time
import types

import httpx
import pytest
from fastapi import FastAPI

import app.runs as runs
import pipeline.events as ev
import pipeline.interpreter as itp
import pipeline.keys as pkeys
import pipeline.mandates as m
import pipeline.negotiation as neg
import pipeline.orchestrator as orch
import pipeline.seed as seed
from pipeline.approvals import ApprovalError, MemoryApprovalStore
from pipeline.challenge import MemoryChallengeStore
from pipeline.ledger import MemorySpendLedger
from pipeline.payments import PaymentError, PaymentExecutor
from pipeline.tiering import BLOCKED, TIER1, TIER2
from supplier import app as supplier_app

BASE = "http://supplier.test"
HOSTILE = functools.partial(neg.request_quote, demo_hostile=True)


@contextlib.asynccontextmanager
async def _stack(approval_clock=time.time):
    supplier = m.new_key()
    supplier_asgi = supplier_app.create_app(supplier, BASE)
    keys = pkeys.KeySet(
        user=m.new_key(), agent=m.new_key(), supplier_public=m.public_only(supplier)
    )
    events = ev.MemoryEventLog()
    ledger = MemorySpendLedger()
    approvals = MemoryApprovalStore(clock=approval_clock)
    shared = dict(
        keys=keys,
        supplier_url=BASE,
        events=events,
        challenges=MemoryChallengeStore(),
        ledger=ledger,
        interpreter=itp.RuleInterpreter(),
        executor=PaymentExecutor(ledger),
        approvals=approvals,
    )
    transport = httpx.ASGITransport(app=supplier_asgi)
    async with httpx.AsyncClient(transport=transport, base_url=BASE, timeout=10) as http:

        def make(**overrides):
            return orch.Orchestrator(http=http, **{**shared, **overrides})

        yield types.SimpleNamespace(
            make=make, events=events, ledger=ledger, approvals=approvals
        )


def _with_stack(body, **kwargs):
    async def go():
        async with _stack(**kwargs) as s:
            return await body(s), s

    return asyncio.run(go())


def _kinds(s, run_id="run-1"):
    return [e.kind for e in s.events.read(run_id)]


def test_tier_1_pays_automatically_and_records_the_spend():
    result, s = _with_stack(lambda s: s.make().run("run-1", seed.FP_88213))
    assert result.status == orch.PAID
    assert result.tier == TIER1
    assert result.reference.startswith("SIM-")
    usage = s.ledger.usage(seed.BUYER.id)
    assert (usage.total_amount, usage.total_uses) == (seed.FP_88213.agreed_minor, 1)


def test_a_paid_run_logs_the_payment_last():
    _, s = _with_stack(lambda s: s.make().run("run-1", seed.FP_88213))
    assert _kinds(s)[-3:] == ["rail.selected", "payment.executed", "run.completed"]


def test_tier_2_stores_a_pending_approval():
    result, s = _with_stack(lambda s: s.make().run("run-1", seed.FP_88214))
    assert result.status == orch.AWAITING
    assert s.approvals.peek("run-1").total_minor == seed.FP_88214.quoted_minor
    assert "approval.requested" in _kinds(s)
    assert "gate.mandate" not in _kinds(s)


def test_approve_pays_with_a_fresh_mandate():
    async def body(s):
        o = s.make()
        await o.run("run-1", seed.FP_88214)
        return o.decide("run-1", True)

    result, s = _with_stack(body)
    assert result.status == orch.PAID
    assert result.tier == TIER2
    assert result.total_minor == seed.FP_88214.quoted_minor
    assert s.ledger.usage(seed.BUYER.id).total_amount == seed.FP_88214.quoted_minor
    assert _kinds(s)[-5:] == [
        "approval.granted",
        "gate.mandate",
        "rail.selected",
        "payment.executed",
        "run.completed",
    ]


def test_an_approval_can_be_used_only_once():
    async def body(s):
        o = s.make()
        await o.run("run-1", seed.FP_88214)
        o.decide("run-1", True)
        with pytest.raises(ApprovalError):
            o.decide("run-1", True)

    _with_stack(body)


def test_reject_records_nothing():
    async def body(s):
        o = s.make()
        await o.run("run-1", seed.FP_88214)
        return o.decide("run-1", False)

    result, s = _with_stack(body)
    assert result.status == orch.REJECTED
    assert s.ledger.usage(seed.BUYER.id).total_amount == 0
    assert "payment.executed" not in _kinds(s)


def test_an_expired_approval_is_refused():
    now = [1000.0]

    async def body(s):
        o = s.make()
        await o.run("run-1", seed.FP_88214)
        now[0] += 10_000
        with pytest.raises(ApprovalError):
            o.decide("run-1", True)

    _with_stack(body, approval_clock=lambda: now[0])


def test_a_human_can_approve_an_order_flagged_by_its_note():
    async def body(s):
        o = s.make(quote=HOSTILE)
        first = await o.run("run-1", seed.FP_88213)
        return first, o.decide("run-1", True)

    (first, second), _ = _with_stack(body)
    assert first.status == orch.AWAITING
    assert second.status == orch.PAID


def test_the_budget_stops_the_fifth_payment():
    async def body(s):
        o = s.make()
        statuses = []
        for i in range(1, 6):
            statuses.append((await o.run(f"run-{i}", seed.FP_88213)).status)
        return statuses

    statuses, _ = _with_stack(body)
    assert statuses == [orch.PAID] * 4 + [orch.BLOCKED_STATUS]


class _FailingExecutor:
    def execute(self, **kwargs):
        raise PaymentError("could not record the payment")


def test_an_executor_failure_fails_closed():
    result, s = _with_stack(
        lambda s: s.make(executor=_FailingExecutor()).run("run-1", seed.FP_88213)
    )
    assert result.status == orch.FAILED
    assert result.tier == BLOCKED
    assert "payment.executed" not in _kinds(s)
    assert "run.failed" in _kinds(s)


def test_deciding_without_an_approval_store_is_refused():
    async def body(s):
        with pytest.raises(ApprovalError):
            s.make(approvals=None).decide("run-1", True)

    _with_stack(body)


@contextlib.asynccontextmanager
async def _api():
    async with _stack() as s:

        def make(hostile):
            return s.make(quote=HOSTILE if hostile else neg.request_quote)

        api = FastAPI()
        api.include_router(runs.make_router(make_orchestrator=make, events=s.events))
        transport = httpx.ASGITransport(app=api)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://corridor.test", timeout=10
        ) as client:
            yield client


async def _start(client, order_ref):
    response = await client.post("/runs", json={"order_ref": order_ref})
    first_block = response.text.strip().split("\n\n")[0]
    return json.loads(first_block.split("\n")[1].removeprefix("data: "))["run_id"]


def test_approving_over_http_pays():
    async def go():
        async with _api() as client:
            run_id = await _start(client, "FP-88214")
            return await client.post(f"/runs/{run_id}/approve")

    response = asyncio.run(go())
    assert response.status_code == 200
    assert response.json()["result"]["status"] == orch.PAID


def test_a_second_approval_over_http_is_not_found():
    async def go():
        async with _api() as client:
            run_id = await _start(client, "FP-88214")
            await client.post(f"/runs/{run_id}/approve")
            return await client.post(f"/runs/{run_id}/approve")

    assert asyncio.run(go()).status_code == 404


def test_rejecting_over_http():
    async def go():
        async with _api() as client:
            run_id = await _start(client, "FP-88214")
            return await client.post(f"/runs/{run_id}/reject")

    response = asyncio.run(go())
    assert response.status_code == 200
    assert response.json()["result"]["status"] == orch.REJECTED


def test_unknown_and_malformed_run_ids_are_refused():
    async def go():
        async with _api() as client:
            return (
                await client.post("/runs/nope/approve"),
                await client.post("/runs/bad.id/approve"),
            )

    unknown, malformed = asyncio.run(go())
    assert unknown.status_code == 404
    assert malformed.status_code == 422
