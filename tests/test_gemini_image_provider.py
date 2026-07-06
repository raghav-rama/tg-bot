from __future__ import annotations

import asyncio
import base64

import pytest

from app.domain.models import (
    ImageGenerationPollRequest,
    ImageGenerationRequest,
    ImageInput,
)
from app.providers.gemini_image_provider import GeminiImageProvider


class _FakeModels:
    def __init__(self, *, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.generate_content_calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.generate_content_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class _FakeClient:
    def __init__(self, models: _FakeModels, interactions=None) -> None:
        self.models = models
        self.interactions = interactions


class _FakeInteractions:
    def __init__(self, *, create_response=None, get_response=None, error: Exception | None = None) -> None:
        self.create_response = create_response
        self.get_response = get_response
        self.error = error
        self.create_calls: list[dict] = []
        self.get_calls: list[str] = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.create_response

    def get(self, interaction_id: str):
        self.get_calls.append(interaction_id)
        if self.error is not None:
            raise self.error
        return self.get_response




class _SlowModels(_FakeModels):
    def __init__(self, *, sleep_seconds: float, response=None, error: Exception | None = None) -> None:
        super().__init__(response=response, error=error)
        self.sleep_seconds = sleep_seconds

    def generate_content(self, **kwargs):
        import time

        self.generate_content_calls.append(kwargs)
        time.sleep(self.sleep_seconds)
        if self.error is not None:
            raise self.error
        return self.response

class _FakeAPIError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _FakeTypesModule:
    class Part:
        @staticmethod
        def from_text(*, text: str):
            return {"type": "text", "text": text}

        @staticmethod
        def from_bytes(*, data: bytes, mime_type: str):
            return {"type": "bytes", "data": data, "mime_type": mime_type}

    @staticmethod
    def ImageConfig(**kwargs):
        return kwargs

    @staticmethod
    def GenerateContentConfig(**kwargs):
        return kwargs


def make_reference_image() -> ImageInput:
    image_bytes = b"reference-image"
    return ImageInput(
        telegram_file_id="file-ref",
        telegram_file_unique_id="uniq-ref",
        mime_type="image/png",
        width=640,
        height=480,
        byte_size=len(image_bytes),
        bytes_b64=base64.b64encode(image_bytes).decode("ascii"),
        caption="/image stylize this",
    )


def test_gemini_image_client_kwargs_use_api_key() -> None:
    kwargs = GeminiImageProvider._build_client_kwargs(api_key="gemini-key")

    assert kwargs == {"api_key": "gemini-key"}


@pytest.mark.asyncio
async def test_generate_image_returns_first_inline_image_bytes() -> None:
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
    provider = GeminiImageProvider(
        api_key="gemini-key",
        default_model="gemini-3.1-flash-lite-image",
        default_aspect_ratio="1:1",
        default_output_mime_type="image/jpeg",
        client=_FakeClient(models),
    )

    result = await provider.generate_image(
        ImageGenerationRequest(
            chat_id=1,
            user_id=42,
            prompt="A fox in a library",
            model="gemini-3.1-flash-lite-image",
            aspect_ratio="1:1",
            output_mime_type="image/jpeg",
        )
    )

    assert result.image_bytes == b"gemini-image"
    assert result.mime_type == "image/png"
    assert result.raw_model == "gemini-3.1-flash-lite-image"
    assert models.generate_content_calls[0]["contents"] == "A fox in a library"


@pytest.mark.asyncio
async def test_submit_image_returns_background_interaction_id() -> None:
    interactions = _FakeInteractions(
        create_response=type("Interaction", (), {"id": "v1_image_123"})()
    )
    provider = GeminiImageProvider(
        api_key="gemini-key",
        default_model="gemini-3.1-flash-lite-image",
        default_aspect_ratio="1:1",
        default_output_mime_type="image/jpeg",
        client=_FakeClient(_FakeModels(), interactions=interactions),
    )

    submitted = await provider.submit_image(
        ImageGenerationRequest(
            chat_id=1,
            user_id=42,
            prompt="A fox in a library",
            model="gemini-3.1-flash-lite-image",
            aspect_ratio="16:9",
            output_mime_type="image/png",
        )
    )

    assert submitted.operation_name == "v1_image_123"
    assert submitted.provider == "gemini"
    assert interactions.create_calls[0]["background"] is True
    assert interactions.create_calls[0]["response_format"] == {
        "type": "image",
        "mime_type": "image/png",
        "aspect_ratio": "16:9",
    }


@pytest.mark.asyncio
async def test_poll_image_parses_output_image_data() -> None:
    interactions = _FakeInteractions(
        get_response=type(
            "Interaction",
            (),
            {
                "status": "completed",
                "output_image": type(
                    "OutputImage",
                    (),
                    {
                        "data": base64.b64encode(b"gemini-image").decode("ascii"),
                        "mime_type": "image/png",
                    },
                )(),
            },
        )()
    )
    provider = GeminiImageProvider(
        api_key="gemini-key",
        default_model="gemini-3.1-flash-lite-image",
        default_aspect_ratio="1:1",
        default_output_mime_type="image/jpeg",
        client=_FakeClient(_FakeModels(), interactions=interactions),
    )

    result = await provider.poll_image(
        ImageGenerationPollRequest(
            operation_name="v1_image_123",
            prompt="A fox in a library",
            model="gemini-3.1-flash-lite-image",
            provider="gemini",
            output_mime_type="image/jpeg",
        )
    )

    assert result.status == "completed"
    assert result.generated_image is not None
    assert result.generated_image.image_bytes == b"gemini-image"
    assert result.generated_image.mime_type == "image/png"


@pytest.mark.asyncio
async def test_generate_image_sends_reference_image_parts() -> None:
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
                                    type(
                                        "Part",
                                        (),
                                        {
                                            "inline_data": type(
                                                "InlineData",
                                                (),
                                                {
                                                    "data": b"gemini-image",
                                                    "mime_type": "image/jpeg",
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
    provider = GeminiImageProvider(
        api_key="gemini-key",
        default_model="gemini-3.1-flash-lite-image",
        default_aspect_ratio="1:1",
        default_output_mime_type="image/jpeg",
        client=_FakeClient(models),
        types_module=_FakeTypesModule,
    )

    await provider.generate_image(
        ImageGenerationRequest(
            chat_id=1,
            user_id=42,
            prompt="Restyle this",
            model="gemini-3.1-flash-lite-image",
            aspect_ratio="9:16",
            output_mime_type="image/jpeg",
            reference_image=make_reference_image(),
        )
    )

    assert models.generate_content_calls[0]["contents"] == [
        {"type": "text", "text": "Restyle this"},
        {"type": "bytes", "data": b"reference-image", "mime_type": "image/png"},
    ]


@pytest.mark.asyncio
async def test_generate_image_does_not_send_output_mime_type_to_developer_api() -> None:
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
    provider = GeminiImageProvider(
        api_key="gemini-key",
        default_model="gemini-3.1-flash-lite-image",
        default_aspect_ratio="1:1",
        default_output_mime_type="image/jpeg",
        client=_FakeClient(models),
        types_module=_FakeTypesModule,
    )

    await provider.generate_image(
        ImageGenerationRequest(
            chat_id=1,
            user_id=42,
            prompt="A fox in a library",
            model="gemini-3.1-flash-lite-image",
            aspect_ratio="1:1",
            output_mime_type="image/jpeg",
        )
    )

    assert models.generate_content_calls[0]["config"] == {
        "response_modalities": ["TEXT", "IMAGE"],
        "image_config": {
            "aspect_ratio": "1:1",
        },
    }


@pytest.mark.asyncio
async def test_generate_image_timeout_logs_request_context(caplog) -> None:
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
    models = _SlowModels(sleep_seconds=0.05, response=response)
    provider = GeminiImageProvider(
        api_key="gemini-key",
        default_model="gemini-3.1-flash-lite-image",
        default_aspect_ratio="1:1",
        default_output_mime_type="image/jpeg",
        client=_FakeClient(models),
        timeout_seconds=0.01,
    )

    with pytest.raises(Exception):
        with caplog.at_level("WARNING", logger="app.providers.gemini_image_provider"):
            await provider.generate_image(
                ImageGenerationRequest(
                    chat_id=1,
                    user_id=42,
                    prompt="A fox in a library",
                    model="gemini-3.1-flash-lite-image",
                    aspect_ratio="1:1",
                    output_mime_type="image/jpeg",
                )
            )

    assert "gemini_image_generation_timeout" in caplog.text
    assert "model=gemini-3.1-flash-lite-image" in caplog.text


@pytest.mark.asyncio
async def test_generate_image_timeout_logs_late_error(caplog) -> None:
    models = _SlowModels(
        sleep_seconds=0.05,
        error=_FakeAPIError(500, "late upstream error"),
    )
    provider = GeminiImageProvider(
        api_key="gemini-key",
        default_model="gemini-3.1-flash-lite-image",
        default_aspect_ratio="1:1",
        default_output_mime_type="image/jpeg",
        client=_FakeClient(models),
        timeout_seconds=0.01,
        api_error_type=_FakeAPIError,
    )

    with caplog.at_level("WARNING", logger="app.providers.gemini_image_provider"):
        with pytest.raises(Exception):
            await provider.generate_image(
                ImageGenerationRequest(
                    chat_id=1,
                    user_id=42,
                    prompt="A fox in a library",
                    model="gemini-3.1-flash-lite-image",
                    aspect_ratio="1:1",
                    output_mime_type="image/jpeg",
                )
            )
        await asyncio.sleep(0.1)

    assert "gemini_image_generation_late_error" in caplog.text
    assert "late upstream error" in caplog.text
