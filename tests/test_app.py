from __future__ import annotations

import asyncio

from aiogram import Dispatcher

import app.main as app_main
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers.openai_provider import OpenAIProvider
from app.storage.db import Database
from app.telegram.polling import TelegramRuntime


def test_healthz_is_live_when_settings_are_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.chdir(tmp_path)

    with TestClient(create_app()) as client:
        health_response = client.get("/healthz")
        ready_response = client.get("/readyz")

    assert health_response.status_code == 200
    assert health_response.json() == {"ok": True}
    assert ready_response.status_code == 503
    assert ready_response.json()["ok"] is False


async def test_polling_runtime_leaves_process_signals_to_uvicorn(monkeypatch) -> None:
    start_polling_kwargs: list[dict[str, object]] = []
    polling_started = asyncio.Event()

    class StubProcessor:
        async def process_message(self, **_kwargs) -> None:
            return None

    async def fake_delete_webhook(
        self,
        *,
        drop_pending_updates: bool = False,
    ) -> None:
        return None

    async def fake_start_polling(self, bot, **kwargs) -> None:
        start_polling_kwargs.append(kwargs)
        polling_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(TelegramRuntime, "delete_webhook", fake_delete_webhook)
    monkeypatch.setattr(Dispatcher, "start_polling", fake_start_polling)

    runtime = TelegramRuntime(
        token="123456:TESTPollingTokenValueForAppTests1234567890",
        processor=StubProcessor(),
    )

    await runtime.start()
    await polling_started.wait()
    await runtime.close()

    assert start_polling_kwargs == [
        {
            "handle_signals": False,
            "close_bot_session": False,
            "allowed_updates": ["message", "callback_query"],
        }
    ]


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


def test_create_app_passes_gemini_image_timeout_to_provider(
    monkeypatch,
    tmp_path,
) -> None:
    captured: dict[str, object] = {}

    class FakeGeminiImageProvider:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        async def close(self) -> None:
            return None

    class FakeGeminiVideoProvider:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        async def close(self) -> None:
            return None

    async def fake_configure_webhook(
        self,
        *,
        url: str,
        secret_token: str,
        drop_pending_updates: bool = False,
        allowed_updates: list[str] | None = None,
    ) -> None:
        self._webhook_configured = True
        self._webhook_url = url
        self._last_error = None

    monkeypatch.setattr(app_main, "GeminiImageProvider", FakeGeminiImageProvider)
    monkeypatch.setattr(app_main, "GeminiVideoProvider", FakeGeminiVideoProvider)
    monkeypatch.setattr(TelegramRuntime, "configure_webhook", fake_configure_webhook)

    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="123456:TESTWebhookTokenValueForAppTests1234567890",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
        TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
        SQLITE_PATH=str(tmp_path / "bot.db"),
        GEMINI_API_KEY="gemini-test-key",
        GEMINI_IMAGE_TIMEOUT_SECONDS="180",
    )

    with TestClient(create_app(settings)) as client:
        ready_response = client.get("/readyz")

    assert ready_response.status_code == 200
    assert captured["timeout_seconds"] == 180


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
        allowed_updates: list[str] | None = None,
    ) -> None:
        assert allowed_updates == ["message", "callback_query"]
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
        allowed_updates: list[str] | None = None,
    ) -> None:
        raise RuntimeError("webhook setup failed")

    monkeypatch.setattr(TelegramRuntime, "configure_webhook", fake_configure_webhook)

    with TestClient(create_app(_build_webhook_settings(tmp_path))) as client:
        ready_response = client.get("/readyz")

    assert ready_response.status_code == 503
    assert ready_response.json()["ok"] is False
    assert "webhook setup failed" in ready_response.json()["detail"]


def test_webhook_startup_failure_closes_initialized_resources(
    monkeypatch,
    tmp_path,
) -> None:
    closed_resources: list[str] = []

    async def fake_configure_webhook(
        self,
        *,
        url: str,
        secret_token: str,
        drop_pending_updates: bool = False,
        allowed_updates: list[str] | None = None,
    ) -> None:
        raise RuntimeError("webhook setup failed")

    original_runtime_close = TelegramRuntime.close
    original_provider_close = OpenAIProvider.close
    original_database_close = Database.close

    async def tracked_runtime_close(self) -> None:
        closed_resources.append("telegram_runtime")
        await original_runtime_close(self)

    async def tracked_provider_close(self) -> None:
        closed_resources.append("provider")
        await original_provider_close(self)

    async def tracked_database_close(self) -> None:
        closed_resources.append("database")
        await original_database_close(self)

    monkeypatch.setattr(TelegramRuntime, "configure_webhook", fake_configure_webhook)
    monkeypatch.setattr(TelegramRuntime, "close", tracked_runtime_close)
    monkeypatch.setattr(OpenAIProvider, "close", tracked_provider_close)
    monkeypatch.setattr(Database, "close", tracked_database_close)

    with TestClient(create_app(_build_webhook_settings(tmp_path))) as client:
        ready_response = client.get("/readyz")

    assert ready_response.status_code == 503
    assert closed_resources == ["telegram_runtime", "provider", "database"]
