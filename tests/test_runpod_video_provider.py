from __future__ import annotations

import base64
import json
from collections.abc import Callable

import httpx
import pytest

from app.domain.models import (
    ImageInput,
    VideoGenerationPollRequest,
    VideoGenerationRequest,
)
from app.providers.runpod_video_provider import RunpodVideoProvider


def make_request(
    *,
    reference_image: ImageInput | None = None,
    pipeline: str | None = None,
    num_inference_steps: int | None = None,
    seed: int | None = None,
    image_strength: float | None = None,
) -> VideoGenerationRequest:
    return VideoGenerationRequest(
        chat_id=1,
        user_id=42,
        prompt="tracking shot through a glowing cave",
        model="ltx-2.3-22b-distilled-1.1",
        aspect_ratio="9:16",
        duration_seconds=3,
        output_gcs_uri=None,
        reference_image=reference_image,
        provider_hint="runpod",
        pipeline=pipeline,
        num_inference_steps=num_inference_steps,
        seed=seed,
        image_strength=image_strength,
    )


def make_reference_image(*, byte_size: int = 15) -> ImageInput:
    return ImageInput(
        telegram_file_id="file-ref",
        telegram_file_unique_id="uniq-ref",
        mime_type="image/jpeg",
        width=768,
        height=512,
        byte_size=byte_size,
        bytes_b64=base64.b64encode(b"reference-image").decode("ascii"),
        caption="/video_ltx animate this",
    )


def make_provider(
    handler,
    *,
    signed_url_resolver: Callable[[str], str] | None = None,
) -> RunpodVideoProvider:
    return RunpodVideoProvider(
        api_key="runpod-key",
        endpoint_id="ltx-endpoint",
        base_url="https://api.runpod.ai/v2",
        default_model="ltx-2.3-22b-distilled-1.1",
        default_width=576,
        default_height=1024,
        default_duration_seconds=3,
        default_frame_rate=24.0,
        execution_timeout_ms=1_800_000,
        ttl_ms=7_200_000,
        reference_image_max_bytes=6_000_000,
        signed_url_ttl_seconds=3600,
        signed_url_resolver=signed_url_resolver,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.asyncio
async def test_submit_video_sends_run_request_with_auth_input_and_policy() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "runpod-job-1", "status": "IN_QUEUE"})

    provider = make_provider(handler)

    submitted = await provider.submit_video(make_request())

    assert submitted.operation_name == "runpod-job-1"
    assert submitted.provider == "runpod"
    assert str(requests[0].url) == "https://api.runpod.ai/v2/ltx-endpoint/run"
    assert requests[0].headers["authorization"] == "Bearer runpod-key"
    payload = json.loads(requests[0].content)
    assert payload["input"] == {
        "prompt": "tracking shot through a glowing cave",
        "model": "ltx-2.3-22b-distilled-1.1",
        "width": 576,
        "height": 1024,
        "num_frames": 73,
        "frame_rate": 24.0,
    }
    assert payload["policy"] == {
        "executionTimeout": 1_800_000,
        "ttl": 7_200_000,
    }


@pytest.mark.asyncio
async def test_submit_video_includes_reference_image_only_under_size_cap() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": f"runpod-job-{len(requests)}"})

    provider = make_provider(handler)

    await provider.submit_video(make_request(reference_image=make_reference_image()))
    await provider.submit_video(
        make_request(reference_image=make_reference_image(byte_size=6_000_001))
    )

    assert requests[0]["input"]["image_base64"] == (
        "data:image/jpeg;base64,"
        + base64.b64encode(b"reference-image").decode("ascii")
    )
    assert "image_base64" not in requests[1]["input"]


@pytest.mark.asyncio
async def test_submit_video_sends_two_stage_pipeline_steps_seed_and_reference_strength() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "runpod-job-1"})

    provider = make_provider(handler)

    await provider.submit_video(
        make_request(
            reference_image=make_reference_image(),
            pipeline="two_stage",
            num_inference_steps=50,
            seed=12345,
            image_strength=0.9,
        )
    )

    input_payload = requests[0]["input"]
    assert input_payload["pipeline"] == "two_stage"
    assert input_payload["num_inference_steps"] == 50
    assert input_payload["seed"] == 12345
    assert input_payload["image_strength"] == 0.9
    assert "aspect_ratio" not in input_payload
    assert "steps" not in input_payload


@pytest.mark.asyncio
async def test_submit_video_omits_inference_steps_when_distilled_pipeline_selected() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "runpod-job-1"})

    provider = make_provider(handler)

    await provider.submit_video(
        make_request(
            pipeline="distilled",
            num_inference_steps=None,
            seed=10,
        )
    )

    input_payload = requests[0]["input"]
    assert input_payload["pipeline"] == "distilled"
    assert input_payload["seed"] == 10
    assert "num_inference_steps" not in input_payload


@pytest.mark.asyncio
async def test_poll_video_maps_runpod_status_values() -> None:
    statuses = {
        "IN_QUEUE": "running",
        "IN_PROGRESS": "running",
        "RUNNING": "running",
        "FAILED": "failed",
        "TIMED_OUT": "failed",
        "CANCELLED": "failed",
    }

    for runpod_status, expected_status in statuses.items():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "id": "runpod-job-1",
                    "status": runpod_status,
                    "error": "worker failed" if expected_status == "failed" else None,
                },
            )

        provider = make_provider(handler)
        result = await provider.poll_video(
            VideoGenerationPollRequest(
                operation_name="runpod-job-1",
                prompt="tracking shot through a glowing cave",
                model="ltx-2.3-22b-distilled-1.1",
                provider="runpod",
            )
        )

        assert result.status == expected_status


@pytest.mark.asyncio
async def test_poll_video_downloads_completed_video_url_to_transient_bytes() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if str(request.url) == "https://cdn.example.com/video.mp4":
            return httpx.Response(
                200,
                content=b"video-bytes",
                headers={"content-type": "video/mp4"},
            )
        return httpx.Response(
            200,
            json={
                "id": "runpod-job-1",
                "status": "COMPLETED",
                "output": {
                    "video_url": "https://cdn.example.com/video.mp4",
                    "mime_type": "video/mp4",
                    "duration_seconds": 4,
                    "width": 1280,
                    "height": 720,
                    "file_size": 123,
                },
            },
        )

    provider = make_provider(handler)

    result = await provider.poll_video(
        VideoGenerationPollRequest(
            operation_name="runpod-job-1",
            prompt="tracking shot through a glowing cave",
            model="ltx-2.3-22b-distilled-1.1",
            provider="runpod",
        )
    )

    assert result.status == "completed"
    assert result.generated_video is not None
    assert result.generated_video.video_bytes == b"video-bytes"
    assert result.generated_video.output_uri == "https://cdn.example.com/video.mp4"
    assert result.generated_video.provider == "runpod"
    assert requests == [
        "https://api.runpod.ai/v2/ltx-endpoint/status/runpod-job-1",
        "https://cdn.example.com/video.mp4",
    ]


@pytest.mark.asyncio
async def test_poll_video_signs_and_downloads_gcs_output_from_ltx_s3_metadata() -> None:
    requests: list[str] = []
    signed_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if str(request.url) == "https://signed.example.com/video.mp4":
            return httpx.Response(
                200,
                content=b"video-bytes",
                headers={"content-type": "video/mp4"},
            )
        return httpx.Response(
            200,
            json={
                "id": "runpod-job-1",
                "status": "COMPLETED",
                "output": {
                    "s3": {
                        "bucket": "yt-tg-bot",
                        "key": "ltx-2.3/runpod-job-1.mp4",
                        "endpoint_url": "https://storage.googleapis.com",
                    },
                    "size_bytes": 123,
                },
            },
        )

    def resolve_signed_url(uri: str) -> str:
        signed_urls.append(uri)
        return "https://signed.example.com/video.mp4"

    provider = make_provider(handler, signed_url_resolver=resolve_signed_url)

    result = await provider.poll_video(
        VideoGenerationPollRequest(
            operation_name="runpod-job-1",
            prompt="tracking shot through a glowing cave",
            model="ltx-2.3-22b-distilled-1.1",
            provider="runpod",
        )
    )

    assert result.status == "completed"
    assert result.generated_video is not None
    assert result.generated_video.video_bytes == b"video-bytes"
    assert result.generated_video.output_uri == "gs://yt-tg-bot/ltx-2.3/runpod-job-1.mp4"
    assert result.generated_video.duration_seconds == 3
    assert result.generated_video.width == 576
    assert result.generated_video.height == 1024
    assert result.generated_video.file_size == 123
    assert signed_urls == ["gs://yt-tg-bot/ltx-2.3/runpod-job-1.mp4"]
    assert requests == [
        "https://api.runpod.ai/v2/ltx-endpoint/status/runpod-job-1",
        "https://signed.example.com/video.mp4",
    ]


@pytest.mark.asyncio
async def test_poll_video_signs_gcs_s3_metadata_before_trusting_unsigned_url() -> None:
    requests: list[str] = []
    signed_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if str(request.url) == "https://signed.example.com/video.mp4":
            return httpx.Response(
                200,
                content=b"video-bytes",
                headers={"content-type": "video/mp4"},
            )
        if str(request.url) == "https://storage.googleapis.com/yt-tg-bot/ltx-2.3/runpod-job-1.mp4":
            return httpx.Response(403)
        return httpx.Response(
            200,
            json={
                "id": "runpod-job-1",
                "status": "COMPLETED",
                "output": {
                    "s3": {
                        "bucket": "yt-tg-bot",
                        "key": "ltx-2.3/runpod-job-1.mp4",
                        "endpoint_url": "https://storage.googleapis.com",
                        "url": "https://storage.googleapis.com/yt-tg-bot/ltx-2.3/runpod-job-1.mp4",
                    },
                    "size_bytes": 123,
                },
            },
        )

    def resolve_signed_url(uri: str) -> str:
        signed_urls.append(uri)
        return "https://signed.example.com/video.mp4"

    provider = make_provider(handler, signed_url_resolver=resolve_signed_url)

    result = await provider.poll_video(
        VideoGenerationPollRequest(
            operation_name="runpod-job-1",
            prompt="tracking shot through a glowing cave",
            model="ltx-2.3-22b-distilled-1.1",
            provider="runpod",
        )
    )

    assert result.status == "completed"
    assert result.generated_video is not None
    assert result.generated_video.video_bytes == b"video-bytes"
    assert result.generated_video.output_uri == "gs://yt-tg-bot/ltx-2.3/runpod-job-1.mp4"
    assert signed_urls == ["gs://yt-tg-bot/ltx-2.3/runpod-job-1.mp4"]
    assert requests == [
        "https://api.runpod.ai/v2/ltx-endpoint/status/runpod-job-1",
        "https://signed.example.com/video.mp4",
    ]


@pytest.mark.asyncio
async def test_poll_video_does_not_sign_non_gcs_s3_metadata() -> None:
    signed_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "runpod-job-1",
                "status": "COMPLETED",
                "output": {
                    "s3": {
                        "bucket": "private-bucket",
                        "key": "ltx-2.3/runpod-job-1.mp4",
                        "endpoint_url": "https://s3.example.com",
                    },
                    "size_bytes": 123,
                },
            },
        )

    def resolve_signed_url(uri: str) -> str:
        signed_urls.append(uri)
        return "https://signed.example.com/video.mp4"

    provider = make_provider(handler, signed_url_resolver=resolve_signed_url)

    result = await provider.poll_video(
        VideoGenerationPollRequest(
            operation_name="runpod-job-1",
            prompt="tracking shot through a glowing cave",
            model="ltx-2.3-22b-distilled-1.1",
            provider="runpod",
        )
    )

    assert result.status == "failed"
    assert result.failure_reason == "Runpod video generation returned no accessible video URL or GCS URI"
    assert signed_urls == []


@pytest.mark.asyncio
async def test_poll_video_marks_completed_output_without_accessible_asset_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "runpod-job-1",
                "status": "COMPLETED",
                "output": {"mime_type": "video/mp4"},
            },
        )

    provider = make_provider(handler)

    result = await provider.poll_video(
        VideoGenerationPollRequest(
            operation_name="runpod-job-1",
            prompt="tracking shot through a glowing cave",
            model="ltx-2.3-22b-distilled-1.1",
            provider="runpod",
        )
    )

    assert result.status == "failed"
    assert result.failure_reason == "Runpod video generation returned no accessible video URL or GCS URI"
