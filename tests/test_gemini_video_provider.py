from __future__ import annotations

import base64

import pytest

from app.domain.errors import ProviderSafetyError
from app.domain.models import VideoGenerationPollRequest, VideoGenerationRequest
from app.providers.gemini_video_provider import GeminiVideoProvider


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


class _FakeClient:
    def __init__(self, interactions: _FakeInteractions) -> None:
        self.interactions = interactions


class _FakeAPIError(Exception):
    def __init__(self, code: int, message: str, *, details: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def test_gemini_video_client_kwargs_use_api_key() -> None:
    kwargs = GeminiVideoProvider._build_client_kwargs(api_key="gemini-key")

    assert kwargs == {"api_key": "gemini-key"}


@pytest.mark.asyncio
async def test_submit_video_returns_background_interaction_id() -> None:
    interaction = type("Interaction", (), {"id": "v1_interaction_123"})()
    interactions = _FakeInteractions(create_response=interaction)
    provider = GeminiVideoProvider(
        api_key="gemini-key",
        default_model="gemini-omni-flash-preview",
        default_aspect_ratio="9:16",
        default_duration_seconds=4,
        client=_FakeClient(interactions),
    )

    submitted = await provider.submit_video(
        VideoGenerationRequest(
            chat_id=1,
            user_id=42,
            prompt="tracking shot through a glowing cave",
            model="gemini-omni-flash-preview",
            aspect_ratio="9:16",
            duration_seconds=4,
            output_gcs_uri=None,
        )
    )

    assert submitted.provider == "gemini"
    assert submitted.raw_model == "gemini-omni-flash-preview"
    assert submitted.operation_name == "v1_interaction_123"
    assert interactions.create_calls[0]["model"] == "gemini-omni-flash-preview"
    assert interactions.create_calls[0]["response_format"] == {
        "type": "video",
        "aspect_ratio": "9:16",
        "duration": "4s",
    }
    assert interactions.create_calls[0]["generation_config"] == {"video_config": {"task": "text_to_video"}}
    assert interactions.create_calls[0]["background"] is True


@pytest.mark.asyncio
async def test_poll_video_returns_running_status() -> None:
    interaction = type("Interaction", (), {"status": "in_progress"})()
    interactions = _FakeInteractions(get_response=interaction)
    provider = GeminiVideoProvider(
        api_key="gemini-key",
        default_model="gemini-omni-flash-preview",
        default_aspect_ratio="9:16",
        default_duration_seconds=4,
        client=_FakeClient(interactions),
    )

    result = await provider.poll_video(
        VideoGenerationPollRequest(
            operation_name="v1_interaction_123",
            prompt="tracking shot through a glowing cave",
            model="gemini-omni-flash-preview",
            provider="gemini",
        )
    )

    assert result.status == "running"
    assert interactions.get_calls == ["v1_interaction_123"]


@pytest.mark.asyncio
async def test_poll_video_generates_inline_video_bytes() -> None:
    interaction = type(
        "Interaction",
        (),
        {
            "status": "completed",
            "output_video": type(
                "OutputVideo",
                (),
                {"data": base64.b64encode(b"video-bytes").decode("ascii")},
            )(),
        },
    )()
    interactions = _FakeInteractions(get_response=interaction)
    provider = GeminiVideoProvider(
        api_key="gemini-key",
        default_model="gemini-omni-flash-preview",
        default_aspect_ratio="9:16",
        default_duration_seconds=4,
        client=_FakeClient(interactions),
    )

    result = await provider.poll_video(
        VideoGenerationPollRequest(
            operation_name="v1_interaction_123",
            prompt="tracking shot through a glowing cave",
            model="gemini-omni-flash-preview",
            provider="gemini",
        )
    )

    assert result.status == "completed"
    assert result.generated_video is not None
    assert result.generated_video.video_bytes == b"video-bytes"
    assert result.generated_video.provider == "gemini"


@pytest.mark.asyncio
async def test_poll_video_raises_safety_error_for_classified_rejection() -> None:
    interactions = _FakeInteractions(
        error=_FakeAPIError(400, "blocked by safety policy", details="unsafe content"),
    )
    provider = GeminiVideoProvider(
        api_key="gemini-key",
        default_model="gemini-omni-flash-preview",
        default_aspect_ratio="9:16",
        default_duration_seconds=4,
        client=_FakeClient(interactions),
        api_error_type=_FakeAPIError,
    )

    with pytest.raises(ProviderSafetyError):
        await provider.poll_video(
            VideoGenerationPollRequest(
                operation_name="v1_interaction_123",
                prompt="blocked prompt",
                model="gemini-omni-flash-preview",
                provider="gemini",
            )
        )
