import asyncio
import dataclasses
import functools
import json

import httpx

import pipeline.events as ev
import pipeline.interpreter as itp
import pipeline.keys as pkeys
import pipeline.mandates as m
import pipeline.negotiation as neg
import pipeline.orchestrator as orch
import pipeline.seed as seed
from pipeline.challenge import MemoryChallengeStore
from pipeline.ledger import MemorySpendLedger
from pipeline.tiering import BLOCKED, TIER1, TIER2
from supplier import app as supplier_app

BASE = "http://supplier.test"
RUN = "run-1"


async def _lying_quote(base_url, order_ref, *, http, expected_currency="EUR"):
    offer = await neg.request_quote(
        base_url, order_ref, http=http, expected_currency=expected_currency
    )
    return dataclasses.replace(offer, claimed_total_minor=offer.claimed_total_minor - 1)


class _Crashes:
    def interpret(self, note):
        raise RuntimeError("model down")


async def _go(order, *, quote=neg.request_quote, interpreter=None):
    supplier = m.new_key()
    app = supplier_app.create_app(supplier, BASE)
    keys = pkeys.KeySet(
        user=m.new_key(), agent=m.new_key(), supplier_public=m.public_only(supplier)
    )
    events = ev.MemoryEventLog()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE, timeout=10) as http:
        o = orch.Orchestrator(
            keys=keys,
            supplier_url=BASE,
            http=http,
            events=events,
            challenges=MemoryChallengeStore(),
            ledger=MemorySpendLedger(),
            interpreter=interpreter or itp.RuleInterpreter(),
            quote=quote,
        )
        result = await o.run(RUN, order)
    return result, events


def _kinds(events):
    return [e.kind for e in events.read(RUN)]


def test_fp_88213_is_ready_to_pay_at_tier_1():
    result, _ = asyncio.run(_go(seed.FP_88213))
    assert result.tier == TIER1
    assert result.status == orch.READY
    assert result.total_minor == seed.FP_88213.agreed_minor
    assert result.rail
    assert result.transaction_id


def test_a_tier_1_run_logs_every_step_in_order():
    _, events = asyncio.run(_go(seed.FP_88213))
    assert _kinds(events) == [
        "run.started",
        "negotiation.offer",
        "interpreter.proposal",
        "gate.screening",
        "gate.mandate",
        "tier.decision",
        "rail.selected",
        "run.completed",
    ]


def test_the_signed_checkout_never_reaches_the_log():
    _, events = asyncio.run(_go(seed.FP_88213))
    text = json.dumps([ev.to_dict(e) for e in events.read(RUN)])
    assert "eyJ" not in text


def test_fp_88214_waits_for_a_human():
    result, _ = asyncio.run(_go(seed.FP_88214))
    assert result.tier == TIER2
    assert result.status == orch.AWAITING
    assert any("352 bps" in r for r in result.reasons)


def test_no_payment_is_built_when_a_human_is_needed():
    _, events = asyncio.run(_go(seed.FP_88214))
    assert "gate.mandate" not in _kinds(events)


def test_a_hostile_note_can_only_tighten():
    quote = functools.partial(neg.request_quote, demo_hostile=True)
    result, events = asyncio.run(_go(seed.FP_88213, quote=quote))
    assert result.tier == TIER2
    assert result.status == orch.AWAITING
    assert any("flagged" in r for r in result.reasons)
    gate_event = [e for e in events.read(RUN) if e.kind == "gate.mandate"][0]
    assert gate_event.data["passed"] is True


def test_a_crashing_interpreter_sends_the_order_to_a_human():
    result, _ = asyncio.run(_go(seed.FP_88213, interpreter=_Crashes()))
    assert result.tier == TIER2


def test_a_supplier_that_misstates_its_total_is_blocked():
    result, _ = asyncio.run(_go(seed.FP_88213, quote=_lying_quote))
    assert result.tier == BLOCKED
    assert result.status == orch.BLOCKED_STATUS
    assert any("differs" in r for r in result.reasons)


def test_an_unknown_order_fails_closed():
    order = seed.Scenario("FP-00000", 1000, 1000, 1)
    result, _ = asyncio.run(_go(order))
    assert result.status == orch.FAILED
    assert result.tier == BLOCKED


def test_the_gate_stops_a_payment_over_the_mandate_cap():
    quoted = seed.FP_88214.quoted_minor
    order = seed.Scenario("FP-88214", quoted, quoted, 2)
    result, _ = asyncio.run(_go(order))
    assert result.tier == BLOCKED
    assert any("mandate gate rejected" in r for r in result.reasons)
