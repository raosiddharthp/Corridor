from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_live_by_default(monkeypatch):
    monkeypatch.delenv("LIVE_ENABLED", raising=False)
    assert client.get("/health").json()["live_enabled"] is True
    assert client.get("/config").status_code == 200


def test_paused_blocks_runs_and_writes_but_not_health(monkeypatch):
    monkeypatch.setenv("LIVE_ENABLED", "false")
    assert client.get("/health").json()["live_enabled"] is False
    for method, path in (
        ("POST", "/runs"),
        ("GET", "/runs/abc/events"),
        ("POST", "/runs/abc/approve"),
        ("POST", "/demo/reset"),
        ("POST", "/anything-else"),
    ):
        response = client.request(method, path)
        assert response.status_code == 503, (method, path)
        assert response.json()["status"] == "paused"


def test_paused_still_serves_the_page_and_config(monkeypatch):
    monkeypatch.setenv("LIVE_ENABLED", "false")
    assert client.get("/config").status_code == 200
    assert client.get("/").status_code == 200
