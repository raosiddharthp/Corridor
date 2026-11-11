import asyncio

import httpx
import pytest

import app.deps as deps
import app.main as main
import pipeline.keys as pkeys
import pipeline.orchestrator as orch
import supplier.main as supplier_main
from scripts import make_keys


def _call(api, method, path, **kwargs):
    async def go():
        transport = httpx.ASGITransport(app=api)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(go())


def test_an_unconfigured_app_answers_health_but_not_runs():
    api = main.create_app({})
    assert _call(api, "GET", "/health").status_code == 200
    assert _call(api, "POST", "/runs", json={"order_ref": "FP-88213"}).status_code == 503


def test_a_configured_app_serves_the_run_api():
    api = main.create_app(make_keys.generate())
    assert _call(api, "POST", "/runs", json={"order_ref": "FP-00000"}).status_code == 404


def test_the_pause_switch_covers_runs(monkeypatch):
    monkeypatch.setenv("LIVE_ENABLED", "false")
    api = main.create_app(make_keys.generate())
    paused = _call(api, "POST", "/runs", json={"order_ref": "FP-88213"})
    assert paused.status_code == 503
    assert paused.json()["status"] == "paused"
    assert _call(api, "GET", "/health").status_code == 200


def test_missing_supplier_url_is_not_configured():
    with pytest.raises(deps.NotConfigured):
        deps.build_services({})


def test_a_bad_key_is_not_configured():
    env = make_keys.generate()
    env[pkeys.USER_ENV] = "nonsense"
    with pytest.raises(deps.NotConfigured):
        deps.build_services(env)


def test_the_factory_builds_orchestrators_for_both_modes():
    services = deps.build_services(make_keys.generate())
    make = deps.orchestrator_factory(services)
    assert isinstance(make(False), orch.Orchestrator)
    assert isinstance(make(True), orch.Orchestrator)
    asyncio.run(services.http.aclose())


def test_the_supplier_entrypoint_serves_health():
    api = supplier_main.build(make_keys.generate())
    assert _call(api, "GET", "/health").status_code == 200


def test_the_supplier_entrypoint_needs_its_public_url():
    env = make_keys.generate()
    del env["SUPPLIER_PUBLIC_URL"]
    with pytest.raises(RuntimeError):
        supplier_main.build(env)
