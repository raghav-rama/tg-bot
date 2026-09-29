from __future__ import annotations

import json

import httpx
import pytest
from aiogram import Bot
from aiogram.types import Message, Update
from fastapi.testclient import TestClient

import app.main as main_module
from app.domain.commands import SUPPORTED_COMMANDS, render_help_message, render_start_message
from app.providers.elevenlabs_provider import ElevenLabsProvider
from app.telegram.polling import TelegramRuntime
from conftest import build_settings


def payload(text, message_id=1):
    return {
        "update_id": message_id,
        "message": {
            "message_id": message_id, "date": 1776000000,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Test"},
            "text": text,
        },
    }


@pytest.mark.parametrize("mode", ["webhook", "polling"])
def test_tts_full_ingestion_sdk_upload_and_shutdown(monkeypatch, tmp_path, mode):
    requests, uploads, texts, clients = [], [], [], []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=b"ID3speech", headers={"content-type": "audio/mpeg"})

    def provider_factory(**kwargs):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        clients.append(client)
        return ElevenLabsProvider(**kwargs, client=client)

    async def configure(self, **kwargs):
        self._webhook_configured = True
        self._webhook_url = kwargs["url"]

    async def start(self):
        self._started = True

    async def voice(self, **kwargs):
        uploads.append(kwargs)
        return Message.model_validate({
            "message_id": 90, "date": 1776000000, "chat": {"id": 123, "type": "private"},
            "voice": {"file_id": "file", "file_unique_id": "unique", "duration": 3,
                      "mime_type": "audio/mpeg", "file_size": 9},
        })

    async def text(self, **kwargs):
        texts.append(kwargs["text"])

    monkeypatch.setattr(main_module, "ElevenLabsProvider", provider_factory)
    monkeypatch.setattr(TelegramRuntime, "configure_webhook", configure)
    monkeypatch.setattr(TelegramRuntime, "start", start)
    monkeypatch.setattr(Bot, "send_voice", voice)
    monkeypatch.setattr(Bot, "send_message", text)
    settings = build_settings(
        tmp_path / "bot.db", TELEGRAM_BOT_TOKEN="123456:TESTTokenValue", APP_UPDATE_MODE=mode,
        GEMINI_API_KEY=None, ELEVENLABS_API_KEY="test-speech-key",
        ELEVENLABS_TTS_VOICE_ID="chosen-voice", ELEVENLABS_TTS_MODEL="eleven_flash_v2_5",
        ELEVENLABS_TTS_OUTPUT_FORMAT="mp3_22050_32", BOT_TTS_MAX_CHARS=20,
        TELEGRAM_VOICE_REQUEST_TIMEOUT_SECONDS=19,
    )
    with TestClient(main_module.create_app(settings)) as client:
        assert client.get("/readyz").status_code == 200
        runtime = client.app.state.container.telegram_runtime

        def feed(body):
            if mode == "webhook":
                response = client.post("/telegram/webhook", json=body, headers={
                    "X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret",
                })
                assert response.status_code == 200
            else:
                update = Update.model_validate(body, context={"bot": runtime.bot})
                client.portal.call(runtime.feed_update, update)

        feed(payload("/tts@testbot नमस्ते"))
        feed(payload("/tts@testbot नमस्ते"))
        assert len(requests) == 1 and len(uploads) == 1
        assert uploads[0]["request_timeout"] == 19
        assert uploads[0]["voice"].data == b"ID3speech"
        assert requests[0].url.path.endswith("/chosen-voice")
        assert requests[0].url.params["output_format"] == "mp3_22050_32"
        assert json.loads(requests[0].content)["model_id"] == "eleven_flash_v2_5"
        feed(payload("/tts " + "अ" * 21, message_id=2))
        assert len(requests) == 1
        assert "20" in texts[-1]
        feed(payload("/status", message_id=3))
        assert "speech generation: enabled" in texts[-1].lower()
        assert "eleven_flash_v2_5" in texts[-1]
        assert "test-speech-key" not in texts[-1]
    assert clients and all(client.is_closed for client in clients)


def test_tts_command_discovery():
    assert "/tts" in SUPPORTED_COMMANDS
    assert "/tts" in render_start_message()
    assert "/tts" in render_help_message()


def test_missing_key_skips_provider_construction_and_keeps_readiness(monkeypatch, tmp_path):
    def unexpected(**kwargs):
        raise AssertionError("TTS provider must stay disabled without a key")

    async def start(self):
        self._started = True

    monkeypatch.setattr(main_module, "ElevenLabsProvider", unexpected)
    monkeypatch.setattr(TelegramRuntime, "start", start)
    settings = build_settings(
        tmp_path / "bot.db", TELEGRAM_BOT_TOKEN="123456:TESTTokenValue",
        APP_UPDATE_MODE="polling", GEMINI_API_KEY=None,
    )
    with TestClient(main_module.create_app(settings)) as client:
        assert client.get("/readyz").status_code == 200
        assert client.app.state.container.speech_provider is None
