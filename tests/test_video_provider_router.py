from __future__ import annotations

import pytest

from app.domain.errors import (
    ProviderSafetyError,
    ProviderTimeoutError,
    ProviderUpstreamError,
)
from app.domain.models import (
    SubmittedVideoJob,
    VideoGenerationPollRequest,
    VideoGenerationRequest,
    VideoJobPollResult,
)
from app.providers.video_router import VideoProviderRouter


class FakeVideoProvider:
    def __init__(self, *, provider: str, error: Exception | None = None) -> None:
        self.provider = provider
        self.error = error
        self.submit_calls: list[VideoGenerationRequest] = []
        self.poll_calls: list[VideoGenerationPollRequest] = []

    async def submit_video(self, request: VideoGenerationRequest) -> SubmittedVideoJob:
        self.submit_calls.append(request)
        if self.error is not None:
            raise self.error
        return SubmittedVideoJob(
            operation_name=f"{self.provider}-job-1",
            provider=self.provider,
            raw_model=request.model,
        )

    async def poll_video(self, request: VideoGenerationPollRequest) -> VideoJobPollResult:
        self.poll_calls.append(request)
        return VideoJobPollResult(status="running", operation_name=request.operation_name)

    async def close(self) -> None:
        return None


def make_request(*, provider_hint: str = "auto", model: str | None = None) -> VideoGenerationRequest:
    return VideoGenerationRequest(
        chat_id=1,
        user_id=42,
        prompt="tracking shot through a glowing cave",
        model=model or "gemini-omni-flash-preview",
        aspect_ratio="9:16",
        duration_seconds=4,
        output_gcs_uri=None,
        provider_hint=provider_hint,
    )


@pytest.mark.asyncio
async def test_auto_video_uses_gemini_when_gemini_accepts() -> None:
    vertex = FakeVideoProvider(provider="gemini")
    runpod = FakeVideoProvider(provider="runpod")
    router = VideoProviderRouter(
        providers={"gemini": vertex, "runpod": runpod},
        provider_order=("gemini", "runpod"),
        provider_models={
            "gemini": "gemini-omni-flash-preview",
            "runpod": "ltx-2.3-22b-distilled-1.1",
        },
    )

    submitted = await router.submit_video(make_request())

    assert submitted.provider == "gemini"
    assert vertex.submit_calls[0].provider_hint == "gemini"
    assert vertex.submit_calls[0].model == "gemini-omni-flash-preview"
    assert runpod.submit_calls == []


@pytest.mark.asyncio
async def test_auto_video_falls_back_to_runpod_on_gemini_safety_error() -> None:
    vertex = FakeVideoProvider(
        provider="gemini",
        error=ProviderSafetyError("Gemini rejected the video prompt as unsafe"),
    )
    runpod = FakeVideoProvider(provider="runpod")
    router = VideoProviderRouter(
        providers={"gemini": vertex, "runpod": runpod},
        provider_order=("gemini", "runpod"),
        provider_models={
            "gemini": "gemini-omni-flash-preview",
            "runpod": "ltx-2.3-22b-distilled-1.1",
        },
    )

    submitted = await router.submit_video(make_request())

    assert submitted.provider == "runpod"
    assert runpod.submit_calls[0].provider_hint == "runpod"
    assert runpod.submit_calls[0].model == "ltx-2.3-22b-distilled-1.1"


@pytest.mark.asyncio
async def test_auto_video_does_not_fallback_when_no_next_provider_is_available() -> None:
    vertex = FakeVideoProvider(
        provider="gemini",
        error=ProviderSafetyError("Gemini rejected the video prompt as unsafe"),
    )
    runpod = FakeVideoProvider(provider="runpod")
    router = VideoProviderRouter(
        providers={"gemini": vertex, "runpod": runpod},
        provider_order=("gemini", "fal"),
        provider_models={
            "gemini": "gemini-omni-flash-preview",
            "runpod": "ltx-2.3-22b-distilled-1.1",
            "fal": "fal-ai/kling-video/v3/standard/text-to-video",
        },
    )

    with pytest.raises(ProviderSafetyError):
        await router.submit_video(make_request())

    assert runpod.submit_calls == []


@pytest.mark.asyncio
async def test_auto_video_does_not_fallback_on_timeout_or_generic_errors() -> None:
    for error in (
        ProviderTimeoutError("timed out"),
        ProviderUpstreamError("quota exhausted"),
    ):
        vertex = FakeVideoProvider(provider="gemini", error=error)
        runpod = FakeVideoProvider(provider="runpod")
        router = VideoProviderRouter(
            providers={"gemini": vertex, "runpod": runpod},
            provider_order=("gemini", "runpod"),
            provider_models={
                "gemini": "gemini-omni-flash-preview",
                "runpod": "ltx-2.3-22b-distilled-1.1",
            },
        )

        with pytest.raises(type(error)):
            await router.submit_video(make_request())

        assert runpod.submit_calls == []


@pytest.mark.asyncio
async def test_video_ltx_hint_submits_directly_to_runpod() -> None:
    vertex = FakeVideoProvider(provider="gemini")
    runpod = FakeVideoProvider(provider="runpod")
    router = VideoProviderRouter(
        providers={"gemini": vertex, "runpod": runpod},
        provider_order=("gemini", "runpod"),
        provider_models={
            "gemini": "gemini-omni-flash-preview",
            "runpod": "ltx-2.3-22b-distilled-1.1",
        },
    )

    submitted = await router.submit_video(make_request(provider_hint="runpod"))

    assert submitted.provider == "runpod"
    assert vertex.submit_calls == []
    assert runpod.submit_calls[0].model == "ltx-2.3-22b-distilled-1.1"


@pytest.mark.asyncio
async def test_poll_video_delegates_to_persisted_provider() -> None:
    vertex = FakeVideoProvider(provider="gemini")
    runpod = FakeVideoProvider(provider="runpod")
    router = VideoProviderRouter(
        providers={"gemini": vertex, "runpod": runpod},
        provider_order=("gemini", "runpod"),
        provider_models={
            "gemini": "gemini-omni-flash-preview",
            "runpod": "ltx-2.3-22b-distilled-1.1",
        },
    )

    result = await router.poll_video(
        VideoGenerationPollRequest(
            operation_name="runpod-job-1",
            prompt="tracking shot through a glowing cave",
            model="ltx-2.3-22b-distilled-1.1",
            provider="runpod",
        )
    )

    assert result.status == "running"
    assert runpod.poll_calls[0].operation_name == "runpod-job-1"
    assert vertex.poll_calls == []


@pytest.mark.asyncio
async def test_fal_hint_submits_directly_to_fal() -> None:
    vertex = FakeVideoProvider(provider="gemini")
    runpod = FakeVideoProvider(provider="runpod")
    fal = FakeVideoProvider(provider="fal")
    router = VideoProviderRouter(
        providers={"gemini": vertex, "runpod": runpod, "fal": fal},
        provider_order=("gemini", "runpod", "fal"),
        provider_models={
            "gemini": "gemini-omni-flash-preview",
            "runpod": "ltx-2.3-22b-distilled-1.1",
            "fal": "fal-ai/kling-video/v3/standard/text-to-video",
        },
    )

    submitted = await router.submit_video(
        make_request(provider_hint="fal", model="fal-ai/kling-video/v3/standard/text-to-video")
    )

    assert submitted.provider == "fal"
    assert vertex.submit_calls == []
    assert runpod.submit_calls == []
    assert fal.submit_calls[0].provider_hint == "fal"


@pytest.mark.asyncio
async def test_auto_video_falls_back_to_next_provider_on_gemini_safety_error() -> None:
    vertex = FakeVideoProvider(
        provider="gemini",
        error=ProviderSafetyError("Gemini rejected the video prompt as unsafe"),
    )
    runpod = FakeVideoProvider(provider="runpod")
    fal = FakeVideoProvider(provider="fal")
    router = VideoProviderRouter(
        providers={"gemini": vertex, "runpod": runpod, "fal": fal},
        provider_order=("gemini", "fal", "runpod"),
        provider_models={
            "gemini": "gemini-omni-flash-preview",
            "runpod": "ltx-2.3-22b-distilled-1.1",
            "fal": "fal-ai/kling-video/v3/standard/text-to-video",
        },
    )

    submitted = await router.submit_video(make_request())

    assert submitted.provider == "fal"
    assert runpod.submit_calls == []
    assert fal.submit_calls[0].model == "fal-ai/kling-video/v3/standard/text-to-video"


@pytest.mark.asyncio
async def test_auto_video_uses_fal_when_first_in_order() -> None:
    vertex = FakeVideoProvider(provider="gemini")
    fal = FakeVideoProvider(provider="fal")
    router = VideoProviderRouter(
        providers={"gemini": vertex, "fal": fal},
        provider_order=("fal", "gemini"),
        provider_models={
            "gemini": "gemini-omni-flash-preview",
            "fal": "fal-ai/kling-video/v3/standard/text-to-video",
        },
    )

    submitted = await router.submit_video(make_request())

    assert submitted.provider == "fal"
    assert fal.submit_calls[0].model == "fal-ai/kling-video/v3/standard/text-to-video"
    assert vertex.submit_calls == []
