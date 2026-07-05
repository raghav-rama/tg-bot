from __future__ import annotations

import base64
import json
from collections.abc import Callable

import httpx
import pytest

from app.domain.errors import ProviderTimeoutError, ProviderUpstreamError
from app.domain.models import (
    ImageInput,
    VideoGenerationPollRequest,
    VideoGenerationRequest,
)
from app.providers.fal_video_provider import FalVideoProvider


def make_request(
    *,
    reference_image: ImageInput | None = None,
    model: str | None = None,
    resolution: str | None = None,
) -> VideoGenerationRequest:
    return VideoGenerationRequest(
        chat_id=1,
        user_id=42,
        prompt="tracking shot through a glowing cave",
        model=model or "fal-ai/kling-video/v3/standard/text-to-video",
        aspect_ratio="9:16",
        duration_seconds=5,
        output_gcs_uri=None,
        reference_image=reference_image,
        provider_hint="fal",
        resolution=resolution,
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
        caption="/video animate this",
    )


def make_provider(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    image_to_video_model: str | None = "fal-ai/kling-video/v3/standard/image-to-video",
    reference_to_video_model: str | None = None,
    default_model: str = "fal-ai/kling-video/v3/standard/text-to-video",
) -> FalVideoProvider:
    return FalVideoProvider(
        api_key="fal-key",
        base_url="https://queue.fal.run",
        default_model=default_model,
        image_to_video_model=image_to_video_model,
        reference_to_video_model=reference_to_video_model,
        reference_image_max_bytes=6_000_000,
        submit_timeout=httpx.Timeout(45),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.asyncio
async def test_submit_text_to_video_sends_correct_url_auth_and_body() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"request_id": "fal-req-1"})

    provider = make_provider(handler, image_to_video_model=None)

    submitted = await provider.submit_video(make_request())

    assert submitted.operation_name == "fal-req-1"
    assert submitted.provider == "fal"
    assert submitted.raw_model == "fal-ai/kling-video/v3/standard/text-to-video"
    assert str(requests[0].url) == (
        "https://queue.fal.run/fal-ai/kling-video/v3/standard/text-to-video"
    )
    assert requests[0].headers["authorization"] == "Key fal-key"
    assert requests[0].headers["content-type"] == "application/json"
    payload = json.loads(requests[0].content)
    assert payload == {
        "prompt": "tracking shot through a glowing cave",
        "duration": "5",
        "aspect_ratio": "9:16",
    }


@pytest.mark.asyncio
async def test_submit_image_to_video_uses_i2v_model_and_sends_data_uri() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"request_id": "fal-req-2"})

    provider = make_provider(handler)

    submitted = await provider.submit_video(make_request(reference_image=make_reference_image()))

    assert submitted.raw_model == "fal-ai/kling-video/v3/standard/image-to-video"
    assert str(requests[0].url) == (
        "https://queue.fal.run/fal-ai/kling-video/v3/standard/image-to-video"
    )
    payload = json.loads(requests[0].content)
    assert payload["prompt"] == "tracking shot through a glowing cave"
    assert payload["duration"] == "5"
    assert "aspect_ratio" not in payload
    assert payload["start_image_url"] == (
        "data:image/jpeg;base64,"
        + base64.b64encode(b"reference-image").decode("ascii")
    )


@pytest.mark.asyncio
async def test_submit_omits_oversized_reference_image_and_falls_back_to_t2v() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"request_id": "fal-req-3"})

    provider = make_provider(handler)

    submitted = await provider.submit_video(
        make_request(reference_image=make_reference_image(byte_size=6_000_001))
    )

    assert submitted.raw_model == "fal-ai/kling-video/v3/standard/text-to-video"
    assert str(requests[0].url) == (
        "https://queue.fal.run/fal-ai/kling-video/v3/standard/text-to-video"
    )
    payload = json.loads(requests[0].content)
    assert "start_image_url" not in payload
    assert payload["prompt"] == "tracking shot through a glowing cave"


@pytest.mark.asyncio
async def test_poll_maps_in_queue_and_in_progress_to_running() -> None:
    for fal_status in ("IN_QUEUE", "IN_PROGRESS"):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": fal_status})

        provider = make_provider(handler)
        result = await provider.poll_video(
            VideoGenerationPollRequest(
                operation_name="fal-req-1",
                prompt="tracking shot through a glowing cave",
                model="fal-ai/kling-video/v3/standard/text-to-video",
                provider="fal",
            )
        )

        assert result.status == "running"
        assert result.operation_name == "fal-req-1"


@pytest.mark.asyncio
async def test_poll_completed_downloads_video_and_returns_result() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requests.append(url)
        if url == "https://cdn.example.com/output.mp4":
            return httpx.Response(
                200,
                content=b"video-bytes",
                headers={"content-type": "video/mp4"},
            )
        if "/status" in url:
            return httpx.Response(200, json={"status": "COMPLETED"})
        return httpx.Response(
            200,
            json={
                "video": {
                    "url": "https://cdn.example.com/output.mp4",
                    "file_size": 1234567,
                    "file_name": "output.mp4",
                    "content_type": "video/mp4",
                }
            },
        )

    provider = make_provider(handler)
    result = await provider.poll_video(
        VideoGenerationPollRequest(
            operation_name="fal-req-1",
            prompt="tracking shot through a glowing cave",
            model="fal-ai/kling-video/v3/standard/text-to-video",
            provider="fal",
        )
    )

    assert result.status == "completed"
    assert result.generated_video is not None
    assert result.generated_video.video_bytes == b"video-bytes"
    assert result.generated_video.mime_type == "video/mp4"
    assert result.generated_video.provider == "fal"
    assert result.generated_video.raw_model == (
        "fal-ai/kling-video/v3/standard/text-to-video"
    )
    assert result.generated_video.output_uri is None
    assert result.generated_video.file_size == 1234567
    assert result.generated_video.duration_seconds is None
    assert result.generated_video.width is None
    assert result.generated_video.height is None


@pytest.mark.asyncio
async def test_poll_result_with_error_or_error_type_returns_failed() -> None:
    for error_field, error_value in (
        ("error", "policy violation"),
        ("error_type", "content_moderation"),
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "COMPLETED", error_field: error_value})

        provider = make_provider(handler)
        result = await provider.poll_video(
            VideoGenerationPollRequest(
                operation_name="fal-req-1",
                prompt="tracking shot through a glowing cave",
                model="fal-ai/kling-video/v3/standard/text-to-video",
                provider="fal",
            )
        )

        assert result.status == "failed"
        assert result.failure_reason == error_value


@pytest.mark.asyncio
async def test_submit_missing_request_id_raises_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    provider = make_provider(handler, image_to_video_model=None)

    with pytest.raises(ProviderUpstreamError, match="no request_id"):
        await provider.submit_video(make_request())


@pytest.mark.asyncio
async def test_submit_timeout_and_gateway_status_raise_timeout_error() -> None:
    for status_code in (408, 504):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code)

        provider = make_provider(handler, image_to_video_model=None)
        with pytest.raises(ProviderTimeoutError, match="timed out"):
            await provider.submit_video(make_request())

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("request timed out")

    provider = make_provider(timeout_handler, image_to_video_model=None)
    with pytest.raises(ProviderTimeoutError, match="timed out"):
        await provider.submit_video(make_request())


@pytest.mark.asyncio
async def test_submit_http_500_raises_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    provider = make_provider(handler, image_to_video_model=None)

    with pytest.raises(ProviderUpstreamError, match="Fal video generation failed"):
        await provider.submit_video(make_request())


@pytest.mark.asyncio
async def test_submit_seedance_text_to_video_uses_resolution() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"request_id": "fal-seedance-1"})

    provider = make_provider(
        handler,
        image_to_video_model=None,
        default_model="bytedance/seedance-2.0/text-to-video",
    )
    submitted = await provider.submit_video(
        make_request(model="bytedance/seedance-2.0/text-to-video", resolution="1080p")
    )

    assert submitted.raw_model == "bytedance/seedance-2.0/text-to-video"
    payload = json.loads(requests[0].content)
    assert payload == {
        "prompt": "tracking shot through a glowing cave",
        "duration": "5",
        "resolution": "1080p",
        "aspect_ratio": "9:16",
    }


@pytest.mark.asyncio
async def test_submit_gemini_image_to_video_uses_image_url() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"request_id": "fal-gemini-1"})

    provider = make_provider(
        handler,
        default_model="google/gemini-omni-flash",
        image_to_video_model="google/gemini-omni-flash/image-to-video",
    )

    submitted = await provider.submit_video(
        make_request(model="google/gemini-omni-flash/image-to-video", reference_image=make_reference_image())
    )

    assert submitted.raw_model == "google/gemini-omni-flash/image-to-video"
    payload = json.loads(requests[0].content)
    assert payload["image_url"] == (
        "data:image/jpeg;base64,"
        + base64.b64encode(b"reference-image").decode("ascii")
    )
    assert payload["duration"] == 5
    assert "start_image_url" not in payload


@pytest.mark.asyncio
async def test_gemini_image_to_video_coerces_unsupported_aspect_ratio() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"request_id": "fal-gemini-1"})

    provider = make_provider(
        handler,
        default_model="google/gemini-omni-flash/image-to-video",
        image_to_video_model="google/gemini-omni-flash/image-to-video",
    )
    request = make_request(
        reference_image=make_reference_image(),
        model="google/gemini-omni-flash/image-to-video",
    )
    request.aspect_ratio = "1:1"

    submitted = await provider.submit_video(request)

    assert submitted.raw_model == "google/gemini-omni-flash/image-to-video"
    payload = json.loads(requests[0].content)
    assert payload["prompt"] == "tracking shot through a glowing cave"
    assert payload["duration"] == 5
    assert payload["aspect_ratio"] == "9:16"
    assert payload["image_url"] == (
        "data:image/jpeg;base64,"
        + base64.b64encode(b"reference-image").decode("ascii")
    )


@pytest.mark.asyncio
async def test_submit_reference_to_video_uses_image_urls_list() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"request_id": "fal-r2v-1"})

    provider = make_provider(
        handler,
        default_model="bytedance/seedance-2.0/text-to-video",
        reference_to_video_model="bytedance/seedance-2.0/reference-to-video",
    )

    submitted = await provider.submit_video(
        make_request(
            model="bytedance/seedance-2.0/reference-to-video",
            reference_image=make_reference_image(),
        )
    )

    assert submitted.raw_model == "bytedance/seedance-2.0/reference-to-video"
    payload = json.loads(requests[0].content)
    assert "image_urls" in payload
    assert payload["image_urls"] == [
        "data:image/jpeg;base64,"
        + base64.b64encode(b"reference-image").decode("ascii")
    ]
    assert payload["resolution"] == "720p"
    assert "start_image_url" not in payload


@pytest.mark.asyncio
async def test_locked_image_to_video_model_falls_back_to_text_when_image_oversized() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"request_id": "fal-fallback"})

    provider = make_provider(handler)
    big_image = make_reference_image(byte_size=10_000_000)
    request = make_request(
        reference_image=big_image,
        model="fal-ai/kling-video/v3/standard/image-to-video",
    )
    request.model_locked = True

    submitted = await provider.submit_video(request)

    assert submitted.raw_model == "fal-ai/kling-video/v3/standard/text-to-video"
    payload = json.loads(requests[0].content)
    assert "start_image_url" not in payload
    assert "image_url" not in payload
    assert payload["aspect_ratio"] == "9:16"


@pytest.mark.asyncio
async def test_locked_image_to_video_model_falls_back_to_text_when_no_reference() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"request_id": "fal-fallback-2"})

    provider = make_provider(handler)
    request = make_request(model="fal-ai/kling-video/v3/standard/image-to-video")
    request.model_locked = True

    submitted = await provider.submit_video(request)

    assert submitted.raw_model == "fal-ai/kling-video/v3/standard/text-to-video"
    payload = json.loads(requests[0].content)
    assert "start_image_url" not in payload
    assert "image_url" not in payload


@pytest.mark.asyncio
async def test_locked_image_to_video_model_uses_custom_text_override_on_fallback() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"request_id": "fal-fallback-3"})

    provider = make_provider(
        handler,
        default_model="fal-ai/google/gemini-omni-flash",
        image_to_video_model="fal-ai/google/gemini-omni-flash/image-to-video",
    )
    request = make_request(model="fal-ai/google/gemini-omni-flash/image-to-video")
    request.model_locked = True

    submitted = await provider.submit_video(request)

    assert submitted.raw_model == "fal-ai/google/gemini-omni-flash"
    assert requests[0].url.path == "/fal-ai/google/gemini-omni-flash"
