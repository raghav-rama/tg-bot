from __future__ import annotations

import asyncio

import httpx
from elevenlabs.client import AsyncElevenLabs
from elevenlabs.core.api_error import ApiError

from app.domain.errors import ProviderTimeoutError, ProviderUpstreamError
from app.domain.models import GeneratedSpeechResult, SpeechGenerationRequest

MAX_AUDIO_BYTES = 10 * 1024 * 1024


class ElevenLabsProvider:
    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 45.0,
        max_audio_bytes: int = MAX_AUDIO_BYTES,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_audio_bytes = max_audio_bytes
        self._http_client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._client = AsyncElevenLabs(
            api_key=api_key,
            timeout=timeout_seconds,
            httpx_client=self._http_client,
        )

    async def close(self) -> None:
        await self._http_client.aclose()

    async def generate_speech(self, request: SpeechGenerationRequest) -> GeneratedSpeechResult:
        try:
            # Bound the entire download, not just the interval between chunks.
            return await asyncio.wait_for(self._convert(request), self.timeout_seconds)
        except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
            raise ProviderTimeoutError("ElevenLabs speech generation timed out") from exc
        except (ApiError, httpx.HTTPError) as exc:
            raise ProviderUpstreamError("ElevenLabs speech generation failed") from exc

    async def _convert(self, request: SpeechGenerationRequest) -> GeneratedSpeechResult:
        # The raw-response SDK interface exposes headers and deterministically
        # closes the response even on cancellation or an oversized stream.
        async with self._client.text_to_speech.with_raw_response.convert(
            voice_id=request.voice_id,
            text=request.text,
            model_id=request.model,
            output_format=request.output_format,
            # Multilingual v2 does not support language_code; allow detection.
            request_options={"max_retries": 0, "timeout_in_seconds": self.timeout_seconds},
        ) as response:
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type not in {"", "audio/mpeg", "audio/mp3", "application/octet-stream"}:
                raise ProviderUpstreamError("ElevenLabs returned non-audio content")
            audio = bytearray()
            async for chunk in response.data:
                if len(audio) + len(chunk) > self.max_audio_bytes:
                    raise ProviderUpstreamError("ElevenLabs audio exceeded the size limit")
                audio.extend(chunk)
            if not audio:
                raise ProviderUpstreamError("ElevenLabs returned empty audio")
            return GeneratedSpeechResult(
                audio_bytes=bytes(audio),
                mime_type="audio/mpeg",
                provider="elevenlabs",
                raw_model=request.model,
                voice_id=request.voice_id,
                source_text=request.text,
                provider_message_id=response.headers.get("request-id") or response.headers.get("x-request-id"),
            )
