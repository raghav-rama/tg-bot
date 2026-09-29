from types import SimpleNamespace

import pytest
from aiogram.types import Message

from app.domain.models import GeneratedSpeechResult
from app.telegram.drafts import TelegramResponseEmitter


def speech():
    return GeneratedSpeechResult(
        audio_bytes=b"ID3audio", mime_type="audio/mpeg", provider="elevenlabs",
        raw_model="eleven_multilingual_v2", voice_id="test", source_text="नमस्ते",
    )


async def test_send_voice_uploads_mp3_and_returns_delivery_metadata():
    calls = []

    async def send_voice(**kwargs):
        calls.append(kwargs)
        return Message.model_validate({
            "message_id": 55, "date": 1776000000, "chat": {"id": 123, "type": "private"},
            "voice": {"file_id": "file", "file_unique_id": "unique", "duration": 3,
                      "mime_type": "audio/mpeg", "file_size": 8},
        })

    emitter = TelegramResponseEmitter(
        bot=SimpleNamespace(send_voice=send_voice), chat_id=123, voice_request_timeout_seconds=17,
    )
    sent = await emitter.send_voice(speech(), reply_to_message_id=42)
    payload, = calls
    assert payload["voice"].filename.endswith(".mp3")
    assert payload["voice"].data == b"ID3audio"
    assert payload["reply_parameters"].message_id == 42
    assert payload["reply_parameters"].allow_sending_without_reply
    assert payload["request_timeout"] == 17
    assert sent.telegram_message_id == 55
    assert sent.telegram_file_id == "file"
    assert sent.duration_seconds == 3


async def test_voice_delivery_requires_voice_metadata():
    async def send_voice(**kwargs):
        return Message.model_validate({
            "message_id": 55, "date": 1776000000, "chat": {"id": 123, "type": "private"},
        })

    emitter = TelegramResponseEmitter(bot=SimpleNamespace(send_voice=send_voice), chat_id=123)
    with pytest.raises(RuntimeError):
        await emitter.send_voice(speech(), reply_to_message_id=42)
