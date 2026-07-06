from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import time
from typing import Any

from app.domain.errors import ProviderSafetyError, ProviderTimeoutError, ProviderUpstreamError
from app.domain.models import GeneratedVideoResult, ImageInput, SubmittedVideoJob, VideoGenerationPollRequest, VideoGenerationRequest, VideoJobPollResult
from app.logging import log_kv


class GeminiVideoProvider:
    def __init__(
        self,
        *,
        api_key: str,
        default_model: str,
        default_aspect_ratio: str,
        default_duration_seconds: int | None,
        client: Any | None = None,
        api_error_type: type[Exception] | None = None,
        timeout_seconds: float | None = 180.0,
    ) -> None:
        self.logger = logging.getLogger("app.providers.gemini_video_provider")
        self._default_model = default_model
        self._default_aspect_ratio = default_aspect_ratio
        self._default_duration_seconds = default_duration_seconds
        self._timeout_seconds = timeout_seconds

        if client is not None:
            self._client = client
            self._api_error_type = api_error_type
            return

        try:
            from google import genai
            from google.genai import errors
        except ImportError as exc:
            raise RuntimeError(
                "google-genai must be installed to enable Gemini video generation"
            ) from exc

        self._client = genai.Client(**self._build_client_kwargs(api_key=api_key))
        self._api_error_type = errors.APIError

    @staticmethod
    def _build_client_kwargs(*, api_key: str) -> dict[str, Any]:
        return {"api_key": api_key}

    async def close(self) -> None:
        return None

    async def submit_video(self, request: VideoGenerationRequest) -> SubmittedVideoJob:
        resolved_model = request.model or self._default_model
        start_time = time.monotonic()
        self.logger.info(
            log_kv(
                "gemini_video_submit_started",
                chat_id=request.chat_id,
                user_id=request.user_id,
                model=resolved_model,
                aspect_ratio=request.aspect_ratio or self._default_aspect_ratio,
                duration_seconds=(
                    request.duration_seconds
                    if request.duration_seconds is not None
                    else self._default_duration_seconds
                ),
                reference_image=bool(request.reference_image),
                prompt_chars=len(request.prompt),
                timeout_seconds=self._timeout_seconds,
            )
        )
        try:
            generation = asyncio.to_thread(self._submit_video_sync, request)
            if self._timeout_seconds is not None:
                interaction = await asyncio.wait_for(generation, timeout=self._timeout_seconds)
            else:
                interaction = await generation
        except asyncio.TimeoutError as exc:
            self.logger.warning(
                log_kv(
                    "gemini_video_submit_timeout",
                    chat_id=request.chat_id,
                    user_id=request.user_id,
                    model=resolved_model,
                    aspect_ratio=request.aspect_ratio or self._default_aspect_ratio,
                    reference_image=bool(request.reference_image),
                    prompt_chars=len(request.prompt),
                    elapsed_ms=int((time.monotonic() - start_time) * 1000),
                    timeout_seconds=self._timeout_seconds,
                )
            )
            raise ProviderTimeoutError("Gemini video generation timed out") from exc
        except Exception as exc:
            if self._api_error_type is not None and isinstance(exc, self._api_error_type):
                error_code = getattr(exc, "code", None)
                self.logger.warning(
                    log_kv(
                        "gemini_video_submit_api_error",
                        chat_id=request.chat_id,
                        user_id=request.user_id,
                        model=resolved_model,
                        error_code=error_code,
                        elapsed_ms=int((time.monotonic() - start_time) * 1000),
                        error_message=self._error_message(exc),
                        error_details=self._error_details(exc),
                    )
                )
                if error_code in {408, 504}:
                    raise ProviderTimeoutError("Gemini video generation timed out") from exc
                if self._is_safety_error(exc):
                    raise ProviderSafetyError(
                        "Gemini video generation was rejected by provider safety policy"
                    ) from exc
                raise ProviderUpstreamError("Gemini video generation failed") from exc
            raise

        interaction_id = getattr(interaction, "id", None)
        if not interaction_id:
            raise ProviderUpstreamError("Gemini video generation returned no interaction id")

        self.logger.info(
            log_kv(
                "gemini_video_submit_succeeded",
                chat_id=request.chat_id,
                user_id=request.user_id,
                model=resolved_model,
                operation_name=interaction_id,
                elapsed_ms=int((time.monotonic() - start_time) * 1000),
            )
        )
        return SubmittedVideoJob(
            operation_name=interaction_id,
            provider="gemini",
            raw_model=resolved_model,
        )

    async def poll_video(self, request: VideoGenerationPollRequest) -> VideoJobPollResult:
        self.logger.debug(
            log_kv(
                "gemini_video_poll_started",
                operation_name=request.operation_name,
                model=request.model or self._default_model,
            )
        )
        try:
            generation = asyncio.to_thread(self._client.interactions.get, request.operation_name)
            if self._timeout_seconds is not None:
                interaction = await asyncio.wait_for(generation, timeout=self._timeout_seconds)
            else:
                interaction = await generation
        except asyncio.TimeoutError as exc:
            raise ProviderTimeoutError("Gemini video polling timed out") from exc
        except Exception as exc:
            if self._api_error_type is not None and isinstance(exc, self._api_error_type):
                error_code = getattr(exc, "code", None)
                if error_code in {408, 504}:
                    raise ProviderTimeoutError("Gemini video polling timed out") from exc
                if self._is_safety_error(exc):
                    raise ProviderSafetyError(
                        "Gemini video generation was rejected by provider safety policy"
                    ) from exc
                raise ProviderUpstreamError("Gemini video polling failed") from exc
            raise

        status = str(getattr(interaction, "status", "")).lower()
        if status in {"in_progress", "queued", "running"}:
            return VideoJobPollResult(status="running", operation_name=request.operation_name)
        if status == "failed":
            error = getattr(interaction, "error", None)
            failure_reason = getattr(error, "message", None) or str(error) or "Gemini video generation failed"
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason=failure_reason,
            )

        video_bytes = self._extract_video_bytes(interaction)
        return VideoJobPollResult(
            status="completed",
            operation_name=request.operation_name,
            generated_video=GeneratedVideoResult(
                video_bytes=video_bytes,
                mime_type="video/mp4",
                provider="gemini",
                raw_model=request.model or self._default_model,
                prompt=request.prompt,
                output_uri=None,
                file_size=len(video_bytes),
            ),
        )

    def _submit_video_sync(self, request: VideoGenerationRequest) -> Any:
        resolved_model = request.model or self._default_model
        aspect_ratio = request.aspect_ratio or self._default_aspect_ratio
        duration_seconds = (
            request.duration_seconds
            if request.duration_seconds is not None
            else self._default_duration_seconds
        )
        response_format: dict[str, Any] = {
            "type": "video",
            "aspect_ratio": aspect_ratio,
        }
        if duration_seconds is not None:
            response_format["duration"] = f"{duration_seconds}s"

        body: dict[str, Any] = {
            "model": resolved_model,
            "response_format": response_format,
        }
        task = "image_to_video" if request.reference_image is not None else "text_to_video"
        body["generation_config"] = {"video_config": {"task": task}}
        if request.reference_image is not None:
            body["input"] = self._interaction_input_with_reference(
                request.prompt,
                request.reference_image,
            )
        else:
            body["input"] = request.prompt
        body["background"] = True
        return self._client.interactions.create(**body)

    def _interaction_input_with_reference(
        self,
        prompt: str,
        image: ImageInput,
    ) -> list[dict[str, str]]:
        self._decode_reference_image(image)
        return [
            {
                "type": "image",
                "data": image.bytes_b64,
                "mime_type": image.mime_type,
            },
            {
                "type": "text",
                "text": prompt,
            },
        ]

    def _extract_video_bytes(self, interaction: Any) -> bytes:
        output_video = getattr(interaction, "output_video", None)
        video_b64 = getattr(output_video, "data", None)
        if video_b64:
            return base64.b64decode(video_b64)

        if hasattr(interaction, "model_dump"):
            raw = interaction.model_dump(mode="json", exclude_none=True)
        else:
            raw = {}
        for step in raw.get("steps", []):
            for item in step.get("content", []):
                if item.get("type") == "video" and item.get("data"):
                    return base64.b64decode(item["data"])
        raise ProviderUpstreamError("Gemini video generation returned no video bytes")

    def _decode_reference_image(self, image: ImageInput) -> bytes:
        try:
            image_bytes = base64.b64decode(image.bytes_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ProviderUpstreamError("Reference image payload is invalid") from exc
        if not image_bytes:
            raise ProviderUpstreamError("Reference image payload is empty")
        return image_bytes

    def _error_message(self, exc: Exception) -> str:
        message = getattr(exc, "message", None)
        if isinstance(message, str) and message:
            return message
        return str(exc)

    def _error_details(self, exc: Exception) -> str | None:
        for field_name in ("details", "errors", "response"):
            value = getattr(exc, field_name, None)
            if value is None:
                continue
            try:
                return str(value)
            except Exception:
                continue
        return None

    def _is_safety_error(self, exc: Exception) -> bool:
        text = " ".join(
            part
            for part in (
                self._error_message(exc),
                self._error_details(exc),
            )
            if part
        ).lower()
        safety_markers = (
            "safety",
            "unsafe",
            "responsible ai",
            "policy violation",
            "blocked",
            "prohibited",
        )
        return any(marker in text for marker in safety_markers)
