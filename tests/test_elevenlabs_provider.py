from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.domain.errors import ProviderTimeoutError, ProviderUpstreamError
from app.domain.models import SpeechGenerationRequest
from app.providers.elevenlabs_provider import ElevenLabsProvider


def speech_request(**overrides) -> SpeechGenerationRequest:
    values = dict(
        chat_id=123, user_id=42, text="नमस्ते world", voice_id="test-voice",
        model="eleven_multilingual_v2", output_format="mp3_44100_128",
    )
    values.update(overrides)
    return SpeechGenerationRequest(**values)


async def test_speech_uses_official_sdk_and_collects_audio_without_language_hint():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=b"ID3audio", headers={
            "content-type": "audio/mpeg", "request-id": "speech-123",
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    provider = ElevenLabsProvider(api_key="secret-test-key", client=client)
    try:
        result = await provider.generate_speech(speech_request())
        assert result.audio_bytes == b"ID3audio"
        assert result.mime_type == "audio/mpeg"
        assert result.provider_message_id == "speech-123"
        assert result.source_text == "नमस्ते world"
        assert result.voice_id == "test-voice"
        assert result.raw_model == "eleven_multilingual_v2"
        request, = requests
        assert request.method == "POST"
        assert request.url.path == "/v1/text-to-speech/test-voice"
        assert request.url.params["output_format"] == "mp3_44100_128"
        assert request.headers["xi-api-key"] == "secret-test-key"
        body = json.loads(request.content)
        assert body["text"] == "नमस्ते world"
        assert body["model_id"] == "eleven_multilingual_v2"
        assert "language_code" not in body
    finally:
        await provider.close()
    assert client.is_closed


@pytest.mark.parametrize("status", [401, 403, 422, 429, 500])
async def test_speech_errors_are_typed_and_never_retry(status):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, json={"detail": "private provider details"})

    provider = ElevenLabsProvider(
        api_key="test", client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    try:
        with pytest.raises(ProviderUpstreamError) as error:
            await provider.generate_speech(speech_request())
        assert len(requests) == 1
        assert "private provider details" not in str(error.value)
    finally:
        await provider.close()


@pytest.mark.parametrize("body,content_type", [
    (b"", "audio/mpeg"), (b"oversized", "audio/mpeg"),
    (b"{}", "application/json"),
])
async def test_speech_rejects_empty_oversized_or_non_audio_output(body, content_type):
    provider = ElevenLabsProvider(
        api_key="test", max_audio_bytes=4,
        client=httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=body, headers={"content-type": content_type}),
        )),
    )
    try:
        with pytest.raises(ProviderUpstreamError):
            await provider.generate_speech(speech_request())
    finally:
        await provider.close()


class HangingAudio(httpx.AsyncByteStream):
    def __init__(self):
        self.closed = False
        self.started = asyncio.Event()

    async def __aiter__(self):
        yield b"ID3"
        self.started.set()
        await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


async def test_total_generation_timeout_closes_incomplete_audio_stream():
    stream = HangingAudio()
    provider = ElevenLabsProvider(
        api_key="test", timeout_seconds=0.05,
        client=httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, stream=stream, headers={"content-type": "audio/mpeg"}),
        )),
    )
    try:
        with pytest.raises(ProviderTimeoutError):
            await provider.generate_speech(speech_request())
        assert stream.closed
    finally:
        await provider.close()


async def test_external_cancellation_propagates_and_closes_audio_stream():
    stream = HangingAudio()
    provider = ElevenLabsProvider(
        api_key="test",
        client=httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, stream=stream),
        )),
    )
    task = asyncio.create_task(provider.generate_speech(speech_request()))
    try:
        await asyncio.wait_for(stream.started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed
    finally:
        task.cancel()
        await provider.close()


async def test_transport_timeout_is_classified():
    def handle(request):
        raise httpx.ReadTimeout("private error", request=request)

    provider = ElevenLabsProvider(
        api_key="test", client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    try:
        with pytest.raises(ProviderTimeoutError):
            await provider.generate_speech(speech_request())
    finally:
        await provider.close()
