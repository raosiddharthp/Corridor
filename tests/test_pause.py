from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_live_by_default(monkeypatch):
    monkeypatch.delenv("LIVE_ENABLED", raising=False)
    assert client.get("/health").json()["live_enabled"] is True
    assert client.get("/docs").status_code == 200


def test_paused_blocks_everything_but_health(monkeypatch):
    monkeypatch.setenv("LIVE_ENABLED", "false")
    assert client.get("/health").json()["live_enabled"] is False
    response = client.get("/docs")
    assert response.status_code == 503
    assert response.json()["status"] == "paused"
