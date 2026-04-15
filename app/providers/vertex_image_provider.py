from __future__ import annotations

import asyncio
from typing import Any

from app.domain.errors import ProviderTimeoutError, ProviderUpstreamError
from app.domain.models import GeneratedImageResult, ImageGenerationRequest
from app.providers.vertex_image_models import is_gemini_image_model


class VertexImageProvider:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        project: str,
        location: str,
        default_model: str,
        default_aspect_ratio: str,
        default_output_mime_type: str,
        client: Any | None = None,
        types_module: Any | None = None,
        api_error_type: type[Exception] | None = None,
    ) -> None:
        self._default_model = default_model
        self._default_aspect_ratio = default_aspect_ratio
        self._default_output_mime_type = default_output_mime_type

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
                "google-genai must be installed to enable Vertex image generation"
            ) from exc

        self._client = genai.Client(
            **self._build_client_kwargs(
                api_key=api_key,
                project=project,
                location=location,
            )
        )
        self._types_module = types
        self._api_error_type = errors.APIError

    @staticmethod
    def _build_client_kwargs(
        *,
        api_key: str | None,
        project: str,
        location: str,
    ) -> dict[str, Any]:
        if project:
            return {
                "vertexai": True,
                "project": project,
                "location": location,
            }

        client_kwargs: dict[str, Any] = {
            "vertexai": True,
        }
        if api_key is not None:
            client_kwargs["api_key"] = api_key
        return client_kwargs

    async def close(self) -> None:
        return None

    async def generate_image(
        self,
        request: ImageGenerationRequest,
    ) -> GeneratedImageResult:
        resolved_model = request.model or self._default_model
        try:
            response = await asyncio.to_thread(self._generate_image_sync, request)
        except Exception as exc:
            if self._api_error_type is not None and isinstance(exc, self._api_error_type):
                error_code = getattr(exc, "code", None)
                if error_code in {408, 504}:
                    raise ProviderTimeoutError("Vertex image generation timed out") from exc
                raise ProviderUpstreamError("Vertex image generation failed") from exc
            raise

        if is_gemini_image_model(resolved_model):
            return self._parse_gemini_generated_image(
                response=response,
                request=request,
                resolved_model=resolved_model,
            )

        return self._parse_imagen_generated_image(
            response=response,
            request=request,
            resolved_model=resolved_model,
        )

    def _parse_imagen_generated_image(
        self,
        *,
        response: Any,
        request: ImageGenerationRequest,
        resolved_model: str,
    ) -> GeneratedImageResult:
        generated_images = getattr(response, "generated_images", None) or []
        if not generated_images:
            raise ProviderUpstreamError("Vertex image generation returned no images")

        first_image = generated_images[0]
        image_payload = getattr(first_image, "image", None)
        image_bytes = getattr(image_payload, "image_bytes", None)
        if not image_bytes:
            raise ProviderUpstreamError("Vertex image generation returned empty image bytes")

        return GeneratedImageResult(
            image_bytes=image_bytes,
            mime_type=request.output_mime_type,
            provider="vertex",
            raw_model=resolved_model,
            prompt=request.prompt,
        )

    def _parse_gemini_generated_image(
        self,
        *,
        response: Any,
        request: ImageGenerationRequest,
        resolved_model: str,
    ) -> GeneratedImageResult:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            raise ProviderUpstreamError("Vertex image generation returned no candidates")

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
                provider="vertex",
                raw_model=resolved_model,
                prompt=request.prompt,
            )

        raise ProviderUpstreamError("Vertex image generation returned no image bytes")

    def _generate_image_sync(self, request: ImageGenerationRequest) -> Any:
        resolved_model = request.model or self._default_model
        if is_gemini_image_model(resolved_model):
            return self._generate_gemini_image_sync(request, resolved_model)

        return self._generate_imagen_image_sync(request, resolved_model)

    def _generate_imagen_image_sync(
        self,
        request: ImageGenerationRequest,
        resolved_model: str,
    ) -> Any:
        config = {
            "number_of_images": 1,
            "output_mime_type": request.output_mime_type or self._default_output_mime_type,
            "aspect_ratio": request.aspect_ratio or self._default_aspect_ratio,
        }
        if self._types_module is not None:
            config = self._types_module.GenerateImagesConfig(**config)

        return self._client.models.generate_images(
            model=resolved_model,
            prompt=request.prompt,
            config=config,
        )

    def _generate_gemini_image_sync(
        self,
        request: ImageGenerationRequest,
        resolved_model: str,
    ) -> Any:
        image_config = {
            "aspect_ratio": request.aspect_ratio or self._default_aspect_ratio,
            "output_mime_type": request.output_mime_type or self._default_output_mime_type,
        }
        config = {
            "response_modalities": ["TEXT", "IMAGE"],
            "image_config": image_config,
        }
        if self._types_module is not None:
            image_config = self._types_module.ImageConfig(**image_config)
            config = self._types_module.GenerateContentConfig(
                response_modalities=[
                    self._types_module.Modality.TEXT,
                    self._types_module.Modality.IMAGE,
                ],
                image_config=image_config,
            )

        return self._client.models.generate_content(
            model=resolved_model,
            contents=request.prompt,
            config=config,
        )
