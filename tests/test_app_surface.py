import asyncio

import httpx

import app.deps as deps
import app.main as main
import pipeline.seed as seed
from scripts import make_keys


def _call(api, method, path, **kwargs):
    async def go():
        transport = httpx.ASGITransport(app=api)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(go())


def _two_calls(api, method, path):
    async def go():
        transport = httpx.ASGITransport(app=api)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.request(method, path), await client.request(method, path)

    return asyncio.run(go())


def test_security_headers_are_set():
    headers = _call(main.create_app({}), "GET", "/health").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]


def test_security_headers_are_set_on_a_paused_response(monkeypatch):
    monkeypatch.setenv("LIVE_ENABLED", "false")
    response = _call(main.create_app({}), "POST", "/runs", json={})
    assert response.status_code == 503
    assert response.headers["x-frame-options"] == "DENY"


def test_the_api_docs_are_not_exposed():
    api = main.create_app({})
    assert _call(api, "GET", "/docs").status_code == 404
    assert _call(api, "GET", "/openapi.json").status_code == 404


def test_config_describes_the_scenarios_and_mandate():
    body = _call(main.create_app({}), "GET", "/config").json()
    refs = {s["order_ref"] for s in body["scenarios"]}
    assert refs == {"FP-88213", "FP-88214"}
    assert body["mandate"]["cap_minor"] == seed.MANDATE_CAP_MINOR
    assert body["price_tolerance_bps"] == seed.PRICE_TOLERANCE_BPS


def test_config_carries_no_key_material():
    text = _call(main.create_app(make_keys.generate()), "GET", "/config").text
    assert "kty" not in text
    assert "CORRIDOR_KEY" not in text


def test_reset_clears_spend_and_pending_approvals():
    services = deps.build_services(make_keys.generate())
    services.ledger.record(seed.BUYER.id, "txn-1", 100)
    old_ledger = services.ledger
    deps.reset_demo_state(services)
    assert services.ledger is not old_ledger
    assert services.ledger.usage(seed.BUYER.id).total_amount == 0
    asyncio.run(services.http.aclose())


def test_new_orchestrators_use_the_reset_state():
    services = deps.build_services(make_keys.generate())
    make = deps.orchestrator_factory(services)
    deps.reset_demo_state(services)
    assert make(False)._ledger is services.ledger
    asyncio.run(services.http.aclose())


def test_the_reset_endpoint_works_and_has_a_cooldown():
    api = main.create_app(make_keys.generate())
    first, second = _two_calls(api, "POST", "/demo/reset")
    assert first.status_code == 200
    assert first.json() == {"status": "reset"}
    assert second.status_code == 429


def test_the_reset_endpoint_is_paused_with_everything_else(monkeypatch):
    monkeypatch.setenv("LIVE_ENABLED", "false")
    api = main.create_app(make_keys.generate())
    assert _call(api, "POST", "/demo/reset").status_code == 503


def test_the_ui_page_and_config_stay_reachable_while_paused(monkeypatch):
    monkeypatch.setenv("LIVE_ENABLED", "false")
    api = main.create_app({})
    assert _call(api, "GET", "/config").status_code == 200
    assert _call(api, "GET", "/index.html").status_code != 503


def test_an_unconfigured_app_refuses_reset():
    assert _call(main.create_app({}), "POST", "/demo/reset").status_code == 503
