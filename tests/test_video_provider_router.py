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
        model=model or "veo-3.0-fast-generate-001",
        aspect_ratio="9:16",
        duration_seconds=4,
        output_gcs_uri=None,
        provider_hint=provider_hint,
    )


@pytest.mark.asyncio
async def test_auto_video_uses_vertex_when_vertex_accepts() -> None:
    vertex = FakeVideoProvider(provider="vertex")
    runpod = FakeVideoProvider(provider="runpod")
    router = VideoProviderRouter(
        providers={"vertex": vertex, "runpod": runpod},
        provider_order=("vertex", "runpod"),
        provider_models={
            "vertex": "veo-3.0-fast-generate-001",
            "runpod": "ltx-2.3-22b-distilled-1.1",
        },
    )

    submitted = await router.submit_video(make_request())

    assert submitted.provider == "vertex"
    assert vertex.submit_calls[0].provider_hint == "vertex"
    assert vertex.submit_calls[0].model == "veo-3.0-fast-generate-001"
    assert runpod.submit_calls == []


@pytest.mark.asyncio
async def test_auto_video_falls_back_to_runpod_on_vertex_safety_error() -> None:
    vertex = FakeVideoProvider(
        provider="vertex",
        error=ProviderSafetyError("Vertex rejected the video prompt as unsafe"),
    )
    runpod = FakeVideoProvider(provider="runpod")
    router = VideoProviderRouter(
        providers={"vertex": vertex, "runpod": runpod},
        provider_order=("vertex", "runpod"),
        provider_models={
            "vertex": "veo-3.0-fast-generate-001",
            "runpod": "ltx-2.3-22b-distilled-1.1",
        },
    )

    submitted = await router.submit_video(make_request())

    assert submitted.provider == "runpod"
    assert runpod.submit_calls[0].provider_hint == "runpod"
    assert runpod.submit_calls[0].model == "ltx-2.3-22b-distilled-1.1"


@pytest.mark.asyncio
async def test_auto_video_does_not_fallback_to_runpod_when_excluded_from_order() -> None:
    vertex = FakeVideoProvider(
        provider="vertex",
        error=ProviderSafetyError("Vertex rejected the video prompt as unsafe"),
    )
    runpod = FakeVideoProvider(provider="runpod")
    router = VideoProviderRouter(
        providers={"vertex": vertex, "runpod": runpod},
        provider_order=("vertex", "fal"),
        provider_models={
            "vertex": "veo-3.0-fast-generate-001",
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
        vertex = FakeVideoProvider(provider="vertex", error=error)
        runpod = FakeVideoProvider(provider="runpod")
        router = VideoProviderRouter(
            providers={"vertex": vertex, "runpod": runpod},
            provider_order=("vertex", "runpod"),
            provider_models={
                "vertex": "veo-3.0-fast-generate-001",
                "runpod": "ltx-2.3-22b-distilled-1.1",
            },
        )

        with pytest.raises(type(error)):
            await router.submit_video(make_request())

        assert runpod.submit_calls == []


@pytest.mark.asyncio
async def test_video_ltx_hint_submits_directly_to_runpod() -> None:
    vertex = FakeVideoProvider(provider="vertex")
    runpod = FakeVideoProvider(provider="runpod")
    router = VideoProviderRouter(
        providers={"vertex": vertex, "runpod": runpod},
        provider_order=("vertex", "runpod"),
        provider_models={
            "vertex": "veo-3.0-fast-generate-001",
            "runpod": "ltx-2.3-22b-distilled-1.1",
        },
    )

    submitted = await router.submit_video(make_request(provider_hint="runpod"))

    assert submitted.provider == "runpod"
    assert vertex.submit_calls == []
    assert runpod.submit_calls[0].model == "ltx-2.3-22b-distilled-1.1"


@pytest.mark.asyncio
async def test_poll_video_delegates_to_persisted_provider() -> None:
    vertex = FakeVideoProvider(provider="vertex")
    runpod = FakeVideoProvider(provider="runpod")
    router = VideoProviderRouter(
        providers={"vertex": vertex, "runpod": runpod},
        provider_order=("vertex", "runpod"),
        provider_models={
            "vertex": "veo-3.0-fast-generate-001",
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
    vertex = FakeVideoProvider(provider="vertex")
    runpod = FakeVideoProvider(provider="runpod")
    fal = FakeVideoProvider(provider="fal")
    router = VideoProviderRouter(
        providers={"vertex": vertex, "runpod": runpod, "fal": fal},
        provider_order=("vertex", "runpod", "fal"),
        provider_models={
            "vertex": "veo-3.0-fast-generate-001",
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
async def test_auto_video_does_not_fallback_to_fal_on_vertex_safety_error() -> None:
    vertex = FakeVideoProvider(
        provider="vertex",
        error=ProviderSafetyError("Vertex rejected the video prompt as unsafe"),
    )
    runpod = FakeVideoProvider(provider="runpod")
    fal = FakeVideoProvider(provider="fal")
    router = VideoProviderRouter(
        providers={"vertex": vertex, "runpod": runpod, "fal": fal},
        provider_order=("vertex", "fal", "runpod"),
        provider_models={
            "vertex": "veo-3.0-fast-generate-001",
            "runpod": "ltx-2.3-22b-distilled-1.1",
            "fal": "fal-ai/kling-video/v3/standard/text-to-video",
        },
    )

    submitted = await router.submit_video(make_request())

    assert submitted.provider == "runpod"
    assert fal.submit_calls == []
    assert runpod.submit_calls[0].model == "ltx-2.3-22b-distilled-1.1"


@pytest.mark.asyncio
async def test_auto_video_uses_fal_when_first_in_order() -> None:
    vertex = FakeVideoProvider(provider="vertex")
    fal = FakeVideoProvider(provider="fal")
    router = VideoProviderRouter(
        providers={"vertex": vertex, "fal": fal},
        provider_order=("fal", "vertex"),
        provider_models={
            "vertex": "veo-3.0-fast-generate-001",
            "fal": "fal-ai/kling-video/v3/standard/text-to-video",
        },
    )

    submitted = await router.submit_video(make_request())

    assert submitted.provider == "fal"
    assert fal.submit_calls[0].model == "fal-ai/kling-video/v3/standard/text-to-video"
    assert vertex.submit_calls == []
