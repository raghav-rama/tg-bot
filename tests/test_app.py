from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.telegram.polling import TelegramRuntime


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


def _build_webhook_settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="123456:TESTWebhookTokenValueForAppTests1234567890",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
        TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
        SQLITE_PATH=str(tmp_path / "bot.db"),
    )


def test_readyz_is_healthy_when_webhook_mode_is_configured(
    monkeypatch,
    tmp_path,
) -> None:
    async def fake_configure_webhook(
        self,
        *,
        url: str,
        secret_token: str,
        drop_pending_updates: bool = False,
    ) -> None:
        self._webhook_configured = True
        self._webhook_url = url
        self._last_error = None

    monkeypatch.setattr(TelegramRuntime, "configure_webhook", fake_configure_webhook)

    with TestClient(create_app(_build_webhook_settings(tmp_path))) as client:
        ready_response = client.get("/readyz")

    assert ready_response.status_code == 200
    assert ready_response.json() == {"ok": True}


def test_readyz_reports_webhook_startup_failure(monkeypatch, tmp_path) -> None:
    async def fake_configure_webhook(
        self,
        *,
        url: str,
        secret_token: str,
        drop_pending_updates: bool = False,
    ) -> None:
        raise RuntimeError("webhook setup failed")

    monkeypatch.setattr(TelegramRuntime, "configure_webhook", fake_configure_webhook)

    with TestClient(create_app(_build_webhook_settings(tmp_path))) as client:
        ready_response = client.get("/readyz")

    assert ready_response.status_code == 503
    assert ready_response.json()["ok"] is False
    assert "webhook setup failed" in ready_response.json()["detail"]
