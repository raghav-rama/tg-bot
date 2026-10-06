from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest
import pytest_asyncio
import aiosqlite

from app.domain.errors import ProviderTimeoutError, ProviderUpstreamError, StorageError
from app.domain.models import GeneratedSpeechResult, InboundMessage, SentAudio, SentVoice
from app.domain.services import ChatService
from conftest import build_settings


def command(text="/tts नमस्ते world", *, chat_id=123, user_id=42, message_id=1):
    return InboundMessage(
        update_id=message_id, telegram_message_id=message_id, chat_id=chat_id,
        chat_type="private", user_id=user_id, username=None, first_name="Test",
        message_type="command", text=text, command=text.split()[0].split("@")[0].lower(),
        image=None, sent_at=datetime.now(timezone.utc),
    )


class SpeechProvider:
    def __init__(self):
        self.calls = []
        self.started = asyncio.Event()
        self.gate = None
        self.error = None

    async def generate_speech(self, request):
        self.calls.append(request)
        self.started.set()
        if self.gate:
            await self.gate.wait()
        if self.error:
            raise self.error
        return GeneratedSpeechResult(
            audio_bytes=b"ID3transient-audio", mime_type="audio/mpeg", provider="elevenlabs",
            raw_model=request.model, voice_id=request.voice_id, source_text=request.text,
            provider_message_id="speech-request-1",
        )


class SpeechEmitter:
    def __init__(self):
        self.voices = []
        self.audios = []
        self.deliveries = []
        self.texts = []
        self.error = None

    async def send_voice(self, speech, *, reply_to_message_id):
        if self.error:
            raise self.error
        self.voices.append((speech, reply_to_message_id))
        self.deliveries.append((speech, reply_to_message_id))
        return SentVoice(
            telegram_message_id=100 + reply_to_message_id, telegram_file_id="voice-file",
            telegram_file_unique_id="voice-unique", duration_seconds=3,
            mime_type="audio/mpeg", file_size=len(speech.audio_bytes),
        )

    async def send_audio(self, speech, *, reply_to_message_id):
        if self.error:
            raise self.error
        self.audios.append((speech, reply_to_message_id))
        self.deliveries.append((speech, reply_to_message_id))
        return SentAudio(
            telegram_message_id=100 + reply_to_message_id, telegram_file_id="audio-file",
            telegram_file_unique_id="audio-unique", duration_seconds=3,
            mime_type="audio/mpeg", file_size=len(speech.audio_bytes),
        )

    async def send_text(self, text, settings_menu=None):
        self.texts.append(text)


@pytest_asyncio.fixture(params=["audio", "voice"])
async def tts_bundle(service_bundle, tmp_path, request):
    bundle = service_bundle
    settings = build_settings(
        tmp_path / "bot.db", ELEVENLABS_API_KEY="test-key", BOT_ENABLE_MESSAGE_DRAFTS=False,
    )
    speech = SpeechProvider()
    service = ChatService(
        settings=settings, conversations=bundle["conversations"], messages=bundle["messages"],
        provider=bundle["provider"], speech_provider=speech, preferences=bundle["preferences"],
    )
    if request.param == "voice":
        await service.handle_settings_callback(
            chat_id=123, user_id=42, callback_data="prefs:tts_delivery:voice",
        )
    return {**bundle, "service": service, "speech": speech, "settings": settings,
            "delivery": request.param}


async def test_tts_delivers_direct_text_and_persists_metadata_without_audio(tts_bundle, caplog):
    bundle = tts_bundle
    emitter = SpeechEmitter()
    with caplog.at_level("INFO"):
        reply = await bundle["service"].handle_inbound(command(), responder=emitter)
    assert reply.delivered
    assert len(emitter.deliveries) == 1
    assert emitter.deliveries[0][1] == 1
    assert emitter.texts == []
    assert len(emitter.audios) == (1 if bundle["delivery"] == "audio" else 0)
    assert len(emitter.voices) == (1 if bundle["delivery"] == "voice" else 0)
    request, = bundle["speech"].calls
    assert request.text == "नमस्ते world"
    assert request.voice_id == "vIdhHAZdn1bGjKe1dFw8"
    assert request.model == "eleven_multilingual_v2"
    assert request.output_format == "mp3_44100_128"
    assert bundle["provider"].calls == []
    conversation = await bundle["conversations"].get_active(123)
    rows = await bundle["messages"].list_for_conversation(conversation.id)
    assert [row.role for row in rows] == ["user", "assistant"]
    assert all(row.message_type == "command" for row in rows)
    assert rows[0].text == "/tts नमस्ते world"
    assert rows[1].telegram_message_id == 101
    assert rows[1].provider_message_id == "speech-request-1"
    assert await bundle["messages"].list_recent_history(conversation_id=conversation.id, limit=20) == []
    dump = " ".join(str(row) for row in rows)
    assert "ID3transient-audio" not in dump
    assert "नमस्ते world" not in caplog.text
    assert "ID3transient-audio" not in caplog.text
    assert "tts_delivered" in caplog.text
    assert f"{bundle['delivery']}-file" in caplog.text


@pytest.mark.parametrize("text", ["/tts", "/tts   \n", "/tts " + "अ" * 3001], ids=["empty", "whitespace", "too-long"])
async def test_invalid_text_never_calls_provider(tts_bundle, text):
    emitter = SpeechEmitter()
    reply = await tts_bundle["service"].handle_inbound(command(text), responder=emitter)
    assert not tts_bundle["speech"].calls
    assert not emitter.deliveries
    assert emitter.texts and "/tts" in reply.text


@pytest.mark.parametrize("text", ["नमस्ते", "namaste world", "अ" * 3000], ids=["hindi", "latin", "limit"])
async def test_mixed_scripts_and_length_boundary_are_supported(tts_bundle, text):
    await tts_bundle["service"].handle_inbound(command("/tts " + text), responder=SpeechEmitter())
    assert tts_bundle["speech"].calls[0].text == text


async def test_allowlist_denies_before_any_storage_or_provider_call(tts_bundle):
    emitter = SpeechEmitter()
    reply = await tts_bundle["service"].handle_inbound(command(user_id=99), responder=emitter)
    assert reply.error_type == "UnauthorizedUserError"
    assert not tts_bundle["speech"].calls
    assert await tts_bundle["conversations"].get_active(123) is None


async def test_unconfigured_tts_has_clear_response(service_bundle):
    emitter = SpeechEmitter()
    reply = await service_bundle["service"].handle_inbound(command(), responder=emitter)
    assert "not configured" in reply.text.lower()
    assert not emitter.deliveries
    assert not service_bundle["provider"].calls


@pytest.mark.parametrize("error", [ProviderTimeoutError("private"), ProviderUpstreamError("private")])
async def test_generation_failure_is_safe_and_duplicate_is_not_retried(tts_bundle, error):
    tts_bundle["speech"].error = error
    emitter = SpeechEmitter()
    service = tts_bundle["service"]
    first = await service.handle_inbound(command(), responder=emitter)
    duplicate = await service.handle_inbound(command(), responder=emitter)
    assert "speech" in first.text.lower() and "private" not in first.text
    assert first.error_type == type(error).__name__
    assert duplicate.suppressed
    assert len(tts_bundle["speech"].calls) == 1
    assert len(emitter.texts) == 1 and not emitter.deliveries


async def test_upload_failure_does_not_regenerate(tts_bundle):
    emitter = SpeechEmitter()
    emitter.error = RuntimeError("private upload info")
    service = tts_bundle["service"]
    reply = await service.handle_inbound(command(), responder=emitter)
    await service.handle_inbound(command(), responder=emitter)
    assert "send" in reply.text.lower() and "audio" in reply.text.lower()
    assert "private" not in reply.text
    assert len(tts_bundle["speech"].calls) == 1
    assert len(emitter.texts) == 1


async def test_metadata_failure_after_upload_keeps_delivery_success(tts_bundle, monkeypatch, caplog):
    async def fail(**kwargs):
        raise StorageError("metadata unavailable")

    monkeypatch.setattr(tts_bundle["messages"], "add_assistant_message", fail)
    emitter = SpeechEmitter()
    with caplog.at_level("WARNING"):
        reply = await tts_bundle["service"].handle_inbound(command(), responder=emitter)
    assert reply.delivered and not reply.error_type
    assert len(emitter.deliveries) == 1 and emitter.texts == []
    assert "tts_metadata_persist_failed" in caplog.text


async def test_metadata_commit_failure_keeps_delivery_success_and_database_usable(tts_bundle, monkeypatch):
    connection = tts_bundle["database"].connection
    real_commit = connection.commit
    commits = 0

    async def commit():
        nonlocal commits
        commits += 1
        # Conversation creation and the command claim commit before synthesis.
        # Fail the assistant metadata commit after Telegram accepted the voice.
        if commits == 3:
            raise aiosqlite.OperationalError("simulated metadata commit failure")
        await real_commit()

    monkeypatch.setattr(connection, "commit", commit)
    emitter = SpeechEmitter()
    service = tts_bundle["service"]
    reply = await service.handle_inbound(command(), responder=emitter)
    assert reply.delivered and not reply.error_type
    assert len(emitter.deliveries) == 1 and not emitter.texts
    # A failed commit must be rolled back, not leave an open transaction that
    # poisons subsequent commands with 'cannot start a transaction'.
    second = await service.handle_inbound(command(message_id=2), responder=emitter)
    assert second.delivered
    assert len(emitter.deliveries) == 2 and not emitter.texts


async def test_storage_claim_failure_prevents_spending(tts_bundle, monkeypatch):
    async def fail(**kwargs):
        raise StorageError("claim failed")

    monkeypatch.setattr(tts_bundle["messages"], "claim_tts_command", fail)
    emitter = SpeechEmitter()
    reply = await tts_bundle["service"].handle_inbound(command(), responder=emitter)
    assert reply.error_type == "StorageError"
    assert not tts_bundle["speech"].calls and not emitter.deliveries


async def test_duplicate_claim_is_atomic_and_persists_across_service_recreation(tts_bundle):
    bundle = tts_bundle
    emitter = SpeechEmitter()
    replies = await asyncio.gather(*[
        bundle["service"].handle_inbound(command(), responder=emitter) for _ in range(4)
    ])
    assert sum(reply.delivered for reply in replies) == 1
    assert len(bundle["speech"].calls) == 1 and len(emitter.deliveries) == 1
    recreated = ChatService(
        settings=bundle["settings"], conversations=bundle["conversations"],
        messages=bundle["messages"], provider=bundle["provider"], speech_provider=bundle["speech"],
    )
    assert (await recreated.handle_inbound(command(), responder=emitter)).suppressed
    assert len(bundle["speech"].calls) == 1


async def test_same_message_id_in_different_chats_is_not_a_duplicate(tts_bundle):
    await asyncio.gather(*[
        tts_bundle["service"].handle_inbound(command(chat_id=chat), responder=SpeechEmitter())
        for chat in [123, 456]
    ])
    assert len(tts_bundle["speech"].calls) == 2


async def test_new_chat_and_reset_do_not_suppress_running_tts(tts_bundle):
    bundle = tts_bundle
    speech = bundle["speech"]
    speech.gate = asyncio.Event()
    emitter = SpeechEmitter()
    task = asyncio.create_task(bundle["service"].handle_inbound(command(), responder=emitter))
    try:
        await asyncio.wait_for(speech.started.wait(), 1)
        original = await bundle["conversations"].get_active(123)
        chat = replace(command(message_id=2), text="hello", message_type="text", command=None)
        assert (await bundle["service"].handle_inbound(chat, responder=SpeechEmitter())).delivered
        await bundle["service"].handle_inbound(command("/reset", message_id=3), responder=SpeechEmitter())
        speech.gate.set()
        assert (await task).delivered
        assert len(emitter.deliveries) == 1
        rows = await bundle["messages"].list_for_conversation(original.id)
        assert rows[-1].provider_message_id == "speech-request-1"
        assert (await bundle["service"].handle_inbound(command(), responder=emitter)).suppressed
    finally:
        speech.gate.set()
        await task


async def test_tts_does_not_supersede_running_chat(tts_bundle):
    bundle = tts_bundle
    bundle["provider"].wait_before_stream = asyncio.Event()
    chat = replace(command(message_id=2), text="hello", message_type="text", command=None)
    emitter = SpeechEmitter()
    task = asyncio.create_task(bundle["service"].handle_inbound(chat, responder=emitter))
    try:
        for _ in range(100):
            if bundle["provider"].calls:
                break
            await asyncio.sleep(0.001)
        assert bundle["provider"].calls
        await bundle["service"].handle_inbound(command(), responder=SpeechEmitter())
        bundle["provider"].wait_before_stream.set()
        assert (await task).delivered
        assert emitter.texts == ["assistant reply"]
    finally:
        bundle["provider"].wait_before_stream.set()
        await task


async def test_overlapping_distinct_tts_requests_both_deliver(tts_bundle):
    speech = tts_bundle["speech"]
    speech.gate = asyncio.Event()
    emitter = SpeechEmitter()
    first = asyncio.create_task(tts_bundle["service"].handle_inbound(command(), responder=emitter))
    try:
        await asyncio.wait_for(speech.started.wait(), 1)
        second = asyncio.create_task(tts_bundle["service"].handle_inbound(
            command("/tts दूसरा", message_id=2), responder=emitter,
        ))
        speech.gate.set()
        replies = await asyncio.gather(first, second)
        assert all(reply.delivered for reply in replies)
        assert {reply_id for _, reply_id in emitter.deliveries} == {1, 2}
    finally:
        speech.gate.set()
        await first


async def test_service_without_transport_returns_transient_speech(tts_bundle):
    reply = await tts_bundle["service"].handle_inbound(command())
    assert not reply.delivered
    assert reply.speech.audio_bytes == b"ID3transient-audio"


async def test_delivery_setting_survives_reset_and_service_recreation(tts_bundle):
    bundle = tts_bundle
    service = bundle["service"]
    for preset in ["voice", "audio"]:
        selected = await service.handle_settings_callback(
            chat_id=123, user_id=42, callback_data=f"prefs:tts_delivery:{preset}",
        )
        assert not selected.error_type
        await service.handle_inbound(command("/reset", message_id=10))
        service = ChatService(
            settings=bundle["settings"], conversations=bundle["conversations"],
            messages=bundle["messages"], provider=bundle["provider"],
            speech_provider=bundle["speech"], preferences=bundle["preferences"],
        )
        emitter = SpeechEmitter()
        reply = await service.handle_inbound(
            command(message_id=20 if preset == "voice" else 21), responder=emitter,
        )
        assert reply.delivered
        assert len(emitter.voices) == (preset == "voice")
        assert len(emitter.audios) == (preset == "audio")


async def test_delivery_preference_does_not_leak_to_other_chats(tts_bundle):
    await tts_bundle["service"].handle_settings_callback(
        chat_id=123, user_id=42, callback_data="prefs:tts_delivery:voice",
    )
    emitter = SpeechEmitter()
    reply = await tts_bundle["service"].handle_inbound(command(chat_id=456), responder=emitter)
    assert reply.delivered and len(emitter.audios) == 1 and not emitter.voices
