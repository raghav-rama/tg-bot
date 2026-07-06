from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import time
from typing import Any

from app.domain.errors import ProviderTimeoutError, ProviderUpstreamError
from app.domain.models import (
    GeneratedImageResult,
    ImageGenerationPollRequest,
    ImageGenerationRequest,
    ImageInput,
    ImageJobPollResult,
    SubmittedImageJob,
)


class GeminiImageProvider:
    def __init__(
        self,
        *,
        api_key: str,
        default_model: str,
        default_aspect_ratio: str,
        default_output_mime_type: str,
        client: Any | None = None,
        types_module: Any | None = None,
        api_error_type: type[Exception] | None = None,
        timeout_seconds: float | None = 60.0,
    ) -> None:
        self.logger = logging.getLogger("app.providers.gemini_image_provider")
        self._default_model = default_model
        self._default_aspect_ratio = default_aspect_ratio
        self._default_output_mime_type = default_output_mime_type
        self._timeout_seconds = timeout_seconds

        if client is not None:
            self._client = client
            self._types_module = types_module
            self._api_error_type = api_error_type
            return

        try:
            from google import genai
            from google.genai import errors, types
        except ImportError as exc:
            raise RuntimeError(
                "google-genai must be installed to enable Gemini image generation"
            ) from exc

        self._client = genai.Client(**self._build_client_kwargs(api_key=api_key))
        self._types_module = types
        self._api_error_type = errors.APIError

    @staticmethod
    def _build_client_kwargs(*, api_key: str) -> dict[str, Any]:
        return {"api_key": api_key}

    async def close(self) -> None:
        return None

    async def submit_image(
        self,
        request: ImageGenerationRequest,
    ) -> SubmittedImageJob:
        resolved_model = request.model or self._default_model
        start_time = time.monotonic()
        self.logger.info(
            "gemini_image_submit_started chat_id=%s user_id=%s model=%s aspect_ratio=%s reference_image=%s prompt_chars=%s timeout_seconds=%s",
            request.chat_id,
            request.user_id,
            resolved_model,
            request.aspect_ratio or self._default_aspect_ratio,
            bool(request.reference_image),
            len(request.prompt),
            self._timeout_seconds,
        )
        try:
            generation = asyncio.to_thread(self._submit_image_sync, request)
            if self._timeout_seconds is not None:
                interaction = await asyncio.wait_for(generation, timeout=self._timeout_seconds)
            else:
                interaction = await generation
        except asyncio.TimeoutError as exc:
            raise ProviderTimeoutError("Gemini image generation timed out") from exc
        except Exception as exc:
            if self._api_error_type is not None and isinstance(exc, self._api_error_type):
                error_code = getattr(exc, "code", None)
                if error_code in {408, 504}:
                    raise ProviderTimeoutError("Gemini image generation timed out") from exc
                raise ProviderUpstreamError("Gemini image generation failed") from exc
            raise

        interaction_id = getattr(interaction, "id", None)
        if not interaction_id:
            raise ProviderUpstreamError("Gemini image generation returned no interaction id")
        self.logger.info(
            "gemini_image_submit_succeeded chat_id=%s user_id=%s model=%s operation_name=%s elapsed_ms=%s",
            request.chat_id,
            request.user_id,
            resolved_model,
            interaction_id,
            int((time.monotonic() - start_time) * 1000),
        )
        return SubmittedImageJob(
            operation_name=interaction_id,
            provider="gemini",
            raw_model=resolved_model,
        )

    async def poll_image(
        self,
        request: ImageGenerationPollRequest,
    ) -> ImageJobPollResult:
        try:
            generation = asyncio.to_thread(
                self._client.interactions.get,
                request.operation_name,
            )
            if self._timeout_seconds is not None:
                interaction = await asyncio.wait_for(generation, timeout=self._timeout_seconds)
            else:
                interaction = await generation
        except asyncio.TimeoutError as exc:
            raise ProviderTimeoutError("Gemini image polling timed out") from exc
        except Exception as exc:
            if self._api_error_type is not None and isinstance(exc, self._api_error_type):
                error_code = getattr(exc, "code", None)
                if error_code in {408, 504}:
                    raise ProviderTimeoutError("Gemini image polling timed out") from exc
                raise ProviderUpstreamError("Gemini image polling failed") from exc
            raise

        status = str(getattr(interaction, "status", "")).lower()
        if status in {"in_progress", "queued", "running"}:
            return ImageJobPollResult(
                status="running",
                operation_name=request.operation_name,
            )
        if status == "failed":
            error = getattr(interaction, "error", None)
            failure_reason = (
                getattr(error, "message", None)
                or str(error)
                or "Gemini image generation failed"
            )
            return ImageJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason=failure_reason,
            )

        output_image = getattr(interaction, "output_image", None)
        image_b64 = getattr(output_image, "data", None)
        if not image_b64:
            raise ProviderUpstreamError("Gemini image generation returned no image bytes")
        return ImageJobPollResult(
            status="completed",
            operation_name=request.operation_name,
            generated_image=GeneratedImageResult(
                image_bytes=base64.b64decode(image_b64),
                mime_type=(
                    getattr(output_image, "mime_type", None)
                    or request.output_mime_type
                    or self._default_output_mime_type
                ),
                provider="gemini",
                raw_model=request.model or self._default_model,
                prompt=request.prompt,
            ),
        )

    async def generate_image(
        self,
        request: ImageGenerationRequest,
    ) -> GeneratedImageResult:
        resolved_model = request.model or self._default_model
        start_time = time.monotonic()
        self.logger.info(
            "gemini_image_generation_started chat_id=%s user_id=%s model=%s aspect_ratio=%s reference_image=%s prompt_chars=%s timeout_seconds=%s",
            request.chat_id,
            request.user_id,
            resolved_model,
            request.aspect_ratio or self._default_aspect_ratio,
            bool(request.reference_image),
            len(request.prompt),
            self._timeout_seconds,
        )
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, self._generate_image_sync, request)
        timed_out = False

        def _log_late_completion(done_future: asyncio.Future) -> None:
            if not timed_out:
                return
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            try:
                done_future.result()
            except Exception as late_exc:
                self.logger.warning(
                    "gemini_image_generation_late_error model=%s elapsed_ms=%s error_type=%s error_message=%s",
                    resolved_model,
                    elapsed_ms,
                    type(late_exc).__name__,
                    str(late_exc),
                )
            else:
                self.logger.warning(
                    "gemini_image_generation_late_success model=%s elapsed_ms=%s",
                    resolved_model,
                    elapsed_ms,
                )

        future.add_done_callback(_log_late_completion)
        try:
            if self._timeout_seconds is not None:
                response = await asyncio.wait_for(asyncio.shield(future), timeout=self._timeout_seconds)
            else:
                response = await future
        except asyncio.TimeoutError as exc:
            timed_out = True
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            self.logger.warning(
                "gemini_image_generation_timeout chat_id=%s user_id=%s model=%s aspect_ratio=%s reference_image=%s prompt_chars=%s elapsed_ms=%s timeout_seconds=%s",
                request.chat_id,
                request.user_id,
                resolved_model,
                request.aspect_ratio or self._default_aspect_ratio,
                bool(request.reference_image),
                len(request.prompt),
                elapsed_ms,
                self._timeout_seconds,
            )
            raise ProviderTimeoutError("Gemini image generation timed out") from exc
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            if self._api_error_type is not None and isinstance(exc, self._api_error_type):
                error_code = getattr(exc, "code", None)
                self.logger.warning(
                    "gemini_image_generation_api_error chat_id=%s user_id=%s model=%s error_code=%s elapsed_ms=%s error_message=%s",
                    request.chat_id,
                    request.user_id,
                    resolved_model,
                    error_code,
                    elapsed_ms,
                    str(exc),
                )
                if error_code in {408, 504}:
                    raise ProviderTimeoutError("Gemini image generation timed out") from exc
                raise ProviderUpstreamError("Gemini image generation failed") from exc
            raise

        self.logger.info(
            "gemini_image_generation_succeeded chat_id=%s user_id=%s model=%s elapsed_ms=%s",
            request.chat_id,
            request.user_id,
            resolved_model,
            int((time.monotonic() - start_time) * 1000),
        )
        return self._parse_generated_image(
            response=response,
            request=request,
            resolved_model=resolved_model,
        )

    def _generate_image_sync(self, request: ImageGenerationRequest) -> Any:
        resolved_model = request.model or self._default_model
        image_config = {
            "aspect_ratio": request.aspect_ratio or self._default_aspect_ratio,
        }
        config: Any = {
            "response_modalities": ["TEXT", "IMAGE"],
            "image_config": image_config,
        }
        if self._types_module is not None:
            image_config = self._types_module.ImageConfig(**image_config)
            config = self._types_module.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                image_config=image_config,
            )

        contents: Any = request.prompt
        if request.reference_image is not None:
            reference_image_bytes = self._decode_reference_image(request.reference_image)
            if self._types_module is not None and hasattr(self._types_module, "Part"):
                contents = [
                    self._types_module.Part.from_text(text=request.prompt),
                    self._types_module.Part.from_bytes(
                        data=reference_image_bytes,
                        mime_type=request.reference_image.mime_type,
                    ),
                ]
            else:
                contents = [
                    request.prompt,
                    {
                        "data": reference_image_bytes,
                        "mime_type": request.reference_image.mime_type,
                    },
                ]

        return self._client.models.generate_content(
            model=resolved_model,
            contents=contents,
            config=config,
        )

    def _submit_image_sync(self, request: ImageGenerationRequest) -> Any:
        resolved_model = request.model or self._default_model
        response_format: dict[str, Any] = {
            "type": "image",
            "mime_type": request.output_mime_type or self._default_output_mime_type,
        }
        if request.aspect_ratio:
            response_format["aspect_ratio"] = request.aspect_ratio

        input_value: Any = request.prompt
        if request.reference_image is not None:
            reference_image_bytes = self._decode_reference_image(request.reference_image)
            input_value = [
                {
                    "type": "image",
                    "data": base64.b64encode(reference_image_bytes).decode("ascii"),
                    "mime_type": request.reference_image.mime_type,
                },
                {
                    "type": "text",
                    "text": request.prompt,
                },
            ]

        return self._client.interactions.create(
            model=resolved_model,
            input=input_value,
            response_format=response_format,
            background=True,
        )

    def _parse_generated_image(
        self,
        *,
        response: Any,
        request: ImageGenerationRequest,
        resolved_model: str,
    ) -> GeneratedImageResult:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            raise ProviderUpstreamError("Gemini image generation returned no candidates")

        first_candidate = candidates[0]
        content = getattr(first_candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            image_bytes = getattr(inline_data, "data", None)
            if not image_bytes:
                continue
            return GeneratedImageResult(
                image_bytes=image_bytes,
                mime_type=(
                    getattr(inline_data, "mime_type", None)
                    or request.output_mime_type
                    or self._default_output_mime_type
                ),
                provider="gemini",
                raw_model=resolved_model,
                prompt=request.prompt,
            )

        raise ProviderUpstreamError("Gemini image generation returned no image bytes")

    def _decode_reference_image(self, image: ImageInput) -> bytes:
        try:
            image_bytes = base64.b64decode(image.bytes_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ProviderUpstreamError("Reference image payload is invalid") from exc
        if not image_bytes:
            raise ProviderUpstreamError("Reference image payload is empty")
        return image_bytes
