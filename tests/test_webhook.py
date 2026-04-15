from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.telegram.polling import TelegramRuntime


def _build_webhook_settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="123456:TESTWebhookTokenValueForRouteTests123456789",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
        TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
        SQLITE_PATH=str(tmp_path / "bot.db"),
    )


def _sample_update_payload() -> dict[str, object]:
    return {
        "update_id": 1001,
        "message": {
            "message_id": 99,
            "date": 1_744_662_400,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Test"},
            "text": "hello",
        },
    }


def test_webhook_route_rejects_invalid_secret(monkeypatch, tmp_path) -> None:
    fed_updates: list[int] = []

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

    async def fake_feed_update(self, update) -> None:
        fed_updates.append(update.update_id)

    monkeypatch.setattr(TelegramRuntime, "configure_webhook", fake_configure_webhook)
    monkeypatch.setattr(TelegramRuntime, "feed_update", fake_feed_update)

    with TestClient(create_app(_build_webhook_settings(tmp_path))) as client:
        response = client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
            json=_sample_update_payload(),
        )

    assert response.status_code == 401
    assert response.json() == {"ok": False, "detail": "invalid webhook secret"}
    assert fed_updates == []


def test_webhook_route_accepts_valid_secret_and_feeds_update(
    monkeypatch,
    tmp_path,
) -> None:
    fed_updates: list[int] = []

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

    async def fake_feed_update(self, update) -> None:
        fed_updates.append(update.update_id)

    monkeypatch.setattr(TelegramRuntime, "configure_webhook", fake_configure_webhook)
    monkeypatch.setattr(TelegramRuntime, "feed_update", fake_feed_update)

    with TestClient(create_app(_build_webhook_settings(tmp_path))) as client:
        response = client.post(
            "/telegram/webhook",
            headers={
                "X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret",
            },
            json=_sample_update_payload(),
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert fed_updates == [1001]
