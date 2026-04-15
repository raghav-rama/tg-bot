from __future__ import annotations

import pytest

from app.domain.errors import ProviderTimeoutError, ProviderUpstreamError
from app.domain.models import ImageGenerationRequest
from app.providers.vertex_image_provider import VertexImageProvider


class _FakeGeneratedImage:
    def __init__(self, image_bytes: bytes) -> None:
        self.image = type("ImagePayload", (), {"image_bytes": image_bytes})()


class _FakeModels:
    def __init__(self, *, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.generate_images_calls: list[dict] = []
        self.generate_content_calls: list[dict] = []

    def generate_images(self, **kwargs):
        self.generate_images_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response

    def generate_content(self, **kwargs):
        self.generate_content_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class _FakeClient:
    def __init__(self, models: _FakeModels) -> None:
        self.models = models


class _FakeAPIError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def test_vertex_image_client_kwargs_prefer_adc_when_project_is_set() -> None:
    kwargs = VertexImageProvider._build_client_kwargs(
        api_key="vertex-key",
        project="test-project",
        location="us-central1",
    )

    assert kwargs == {
        "vertexai": True,
        "project": "test-project",
        "location": "us-central1",
    }


def test_vertex_image_client_kwargs_use_api_key_without_project() -> None:
    kwargs = VertexImageProvider._build_client_kwargs(
        api_key="vertex-key",
        project="",
        location="us-central1",
    )

    assert kwargs == {
        "vertexai": True,
        "api_key": "vertex-key",
    }


@pytest.mark.asyncio
async def test_generate_image_returns_first_image_bytes() -> None:
    models = _FakeModels(
        response=type(
            "Response",
            (),
            {"generated_images": [_FakeGeneratedImage(b"vertex-image")]},
        )()
    )
    provider = VertexImageProvider(
        project="test-project",
        location="us-central1",
        default_model="imagen-4.0-fast-generate-001",
        default_aspect_ratio="1:1",
        default_output_mime_type="image/jpeg",
        client=_FakeClient(models),
    )

    result = await provider.generate_image(
        ImageGenerationRequest(
            chat_id=1,
            user_id=42,
            prompt="A fox in a library",
            model="imagen-4.0-fast-generate-001",
            aspect_ratio="1:1",
            output_mime_type="image/jpeg",
        )
    )

    assert result.image_bytes == b"vertex-image"
    assert result.raw_model == "imagen-4.0-fast-generate-001"
    assert models.generate_images_calls[0]["prompt"] == "A fox in a library"
    assert models.generate_content_calls == []


@pytest.mark.asyncio
async def test_generate_image_routes_gemini_models_to_generate_content() -> None:
    response = type(
        "Response",
        (),
        {
            "candidates": [
                type(
                    "Candidate",
                    (),
                    {
                        "content": type(
                            "Content",
                            (),
                            {
                                "parts": [
                                    type("Part", (), {"text": "Generated image"})(),
                                    type(
                                        "Part",
                                        (),
                                        {
                                            "inline_data": type(
                                                "InlineData",
                                                (),
                                                {
                                                    "data": b"gemini-image",
                                                    "mime_type": "image/png",
                                                },
                                            )()
                                        },
                                    )(),
                                ]
                            },
                        )()
                    },
                )()
            ]
        },
    )()
    models = _FakeModels(response=response)
    provider = VertexImageProvider(
        project="test-project",
        location="global",
        default_model="imagen-4.0-fast-generate-001",
        default_aspect_ratio="1:1",
        default_output_mime_type="image/jpeg",
        client=_FakeClient(models),
    )

    result = await provider.generate_image(
        ImageGenerationRequest(
            chat_id=1,
            user_id=42,
            prompt="A fox in a library",
            model="gemini-3-pro-image-preview",
            aspect_ratio="1:1",
            output_mime_type="image/jpeg",
        )
    )

    assert result.image_bytes == b"gemini-image"
    assert result.mime_type == "image/png"
    assert result.raw_model == "gemini-3-pro-image-preview"
    assert models.generate_images_calls == []
    assert models.generate_content_calls[0]["contents"] == "A fox in a library"
    assert models.generate_content_calls[0]["config"] == {
        "response_modalities": ["TEXT", "IMAGE"],
        "image_config": {
            "aspect_ratio": "1:1",
            "output_mime_type": "image/jpeg",
        },
    }


@pytest.mark.asyncio
async def test_generate_image_maps_api_timeout_error() -> None:
    provider = VertexImageProvider(
        project="test-project",
        location="us-central1",
        default_model="imagen-4.0-fast-generate-001",
        default_aspect_ratio="1:1",
        default_output_mime_type="image/jpeg",
        client=_FakeClient(
            _FakeModels(error=_FakeAPIError(504, "gateway timeout"))
        ),
        api_error_type=_FakeAPIError,
    )

    with pytest.raises(ProviderTimeoutError):
        await provider.generate_image(
            ImageGenerationRequest(
                chat_id=1,
                user_id=42,
                prompt="A fox in a library",
                model="imagen-4.0-fast-generate-001",
                aspect_ratio="1:1",
                output_mime_type="image/jpeg",
            )
        )


@pytest.mark.asyncio
async def test_generate_image_raises_on_empty_result() -> None:
    provider = VertexImageProvider(
        project="test-project",
        location="us-central1",
        default_model="imagen-4.0-fast-generate-001",
        default_aspect_ratio="1:1",
        default_output_mime_type="image/jpeg",
        client=_FakeClient(
            _FakeModels(response=type("Response", (), {"generated_images": []})())
        ),
    )

    with pytest.raises(ProviderUpstreamError):
        await provider.generate_image(
            ImageGenerationRequest(
                chat_id=1,
                user_id=42,
                prompt="A fox in a library",
                model="imagen-4.0-fast-generate-001",
                aspect_ratio="1:1",
                output_mime_type="image/jpeg",
            )
        )


@pytest.mark.asyncio
async def test_generate_image_raises_when_gemini_returns_no_image_part() -> None:
    provider = VertexImageProvider(
        project="test-project",
        location="global",
        default_model="imagen-4.0-fast-generate-001",
        default_aspect_ratio="1:1",
        default_output_mime_type="image/jpeg",
        client=_FakeClient(
            _FakeModels(
                response=type(
                    "Response",
                    (),
                    {
                        "candidates": [
                            type(
                                "Candidate",
                                (),
                                {
                                    "content": type(
                                        "Content",
                                        (),
                                        {"parts": [type("Part", (), {"text": "Only text"})()]},
                                    )()
                                },
                            )()
                        ]
                    },
                )()
            )
        ),
    )

    with pytest.raises(ProviderUpstreamError):
        await provider.generate_image(
            ImageGenerationRequest(
                chat_id=1,
                user_id=42,
                prompt="A fox in a library",
                model="gemini-3-pro-image-preview",
                aspect_ratio="1:1",
                output_mime_type="image/jpeg",
            )
        )
