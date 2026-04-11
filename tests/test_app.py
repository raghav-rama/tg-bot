from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz_is_live_when_settings_are_missing(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)

    with TestClient(create_app()) as client:
        health_response = client.get("/healthz")
        ready_response = client.get("/readyz")

    assert health_response.status_code == 200
    assert health_response.json() == {"ok": True}
    assert ready_response.status_code == 503
    assert ready_response.json()["ok"] is False
