from __future__ import annotations

import asyncio
from typing import Any

from app.domain.errors import ProviderTimeoutError, ProviderUpstreamError
from app.domain.models import GeneratedImageResult, ImageGenerationRequest


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
        try:
            response = await asyncio.to_thread(self._generate_image_sync, request)
        except Exception as exc:
            if self._api_error_type is not None and isinstance(exc, self._api_error_type):
                error_code = getattr(exc, "code", None)
                if error_code in {408, 504}:
                    raise ProviderTimeoutError("Vertex image generation timed out") from exc
                raise ProviderUpstreamError("Vertex image generation failed") from exc
            raise

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
            raw_model=request.model,
            prompt=request.prompt,
        )

    def _generate_image_sync(self, request: ImageGenerationRequest) -> Any:
        config = {
            "number_of_images": 1,
            "output_mime_type": request.output_mime_type or self._default_output_mime_type,
            "aspect_ratio": request.aspect_ratio or self._default_aspect_ratio,
        }
        if self._types_module is not None:
            config = self._types_module.GenerateImagesConfig(**config)

        return self._client.models.generate_images(
            model=request.model or self._default_model,
            prompt=request.prompt,
            config=config,
        )
