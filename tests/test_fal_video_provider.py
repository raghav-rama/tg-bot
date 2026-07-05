from __future__ import annotations

import base64
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


class _FakeQueued:
    pass


class _FakeInProgress:
    def __init__(self, logs: list[dict] | None = None) -> None:
        self.logs = logs or []


class _FakeCompleted:
    def __init__(
        self,
        logs: list[dict] | None = None,
        metrics: dict[str, object] | None = None,
    ) -> None:
        self.logs = logs or []
        self.metrics = metrics or {}


class _FakeHandle:
    def __init__(
        self,
        *,
        request_id: str,
        status_result: object | None = None,
        status_error: Exception | None = None,
        get_result: dict[str, object] | None = None,
        get_error: Exception | None = None,
    ) -> None:
        self.request_id = request_id
        self._status_result = status_result
        self._status_error = status_error
        self._get_result = get_result
        self._get_error = get_error
        self.status_calls: list[bool] = []
        self.get_calls = 0

    async def status(self, *, with_logs: bool = False):
        self.status_calls.append(with_logs)
        if self._status_error is not None:
            raise self._status_error
        return self._status_result

    async def get(self) -> dict[str, object]:
        self.get_calls += 1
        if self._get_error is not None:
            raise self._get_error
        return self._get_result or {}


class _FakeFalClient:
    def __init__(
        self,
        *,
        submit_handle: _FakeHandle | None = None,
        submit_error: Exception | None = None,
        upload_url: str = 'https://fal.media/uploads/reference-image.jpeg',
        upload_error: Exception | None = None,
    ) -> None:
        self.submit_handle = submit_handle or _FakeHandle(request_id='fal-req-1')
        self.submit_error = submit_error
        self.upload_url = upload_url
        self.upload_error = upload_error
        self.submit_calls: list[dict[str, object]] = []
        self.upload_calls: list[dict[str, object]] = []
        self.get_handle_calls: list[tuple[str, str]] = []
        self.handles: dict[tuple[str, str], _FakeHandle] = {}

    async def submit(self, application: str, arguments: dict[str, object], **kwargs):
        self.submit_calls.append(
            {
                'application': application,
                'arguments': arguments,
                'kwargs': kwargs,
            }
        )
        if self.submit_error is not None:
            raise self.submit_error
        return self.submit_handle

    async def upload(
        self,
        data: bytes,
        content_type: str,
        file_name: str | None = None,
        **kwargs,
    ) -> str:
        self.upload_calls.append(
            {
                'data': data,
                'content_type': content_type,
                'file_name': file_name,
                'kwargs': kwargs,
            }
        )
        if self.upload_error is not None:
            raise self.upload_error
        return self.upload_url

    def get_handle(self, application: str, request_id: str) -> _FakeHandle:
        self.get_handle_calls.append((application, request_id))
        return self.handles[(application, request_id)]


def make_request(
    *,
    reference_image: ImageInput | None = None,
    model: str | None = None,
    resolution: str | None = None,
) -> VideoGenerationRequest:
    return VideoGenerationRequest(
        chat_id=1,
        user_id=42,
        prompt='tracking shot through a glowing cave',
        model=model or 'fal-ai/kling-video/v3/standard/text-to-video',
        aspect_ratio='9:16',
        duration_seconds=5,
        output_gcs_uri=None,
        reference_image=reference_image,
        provider_hint='fal',
        resolution=resolution,
    )


def make_reference_image(*, byte_size: int = 15) -> ImageInput:
    return ImageInput(
        telegram_file_id='file-ref',
        telegram_file_unique_id='uniq-ref',
        mime_type='image/jpeg',
        width=768,
        height=512,
        byte_size=byte_size,
        bytes_b64=base64.b64encode(b'reference-image').decode('ascii'),
        caption='/video animate this',
    )


def make_provider(
    client: _FakeFalClient,
    *,
    image_to_video_model: str | None = 'fal-ai/kling-video/v3/standard/image-to-video',
    reference_to_video_model: str | None = None,
    default_model: str = 'fal-ai/kling-video/v3/standard/text-to-video',
    download_handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> FalVideoProvider:
    download_client = None
    if download_handler is not None:
        download_client = httpx.AsyncClient(
            transport=httpx.MockTransport(download_handler)
        )
    return FalVideoProvider(
        api_key='fal-key',
        default_model=default_model,
        image_to_video_model=image_to_video_model,
        reference_to_video_model=reference_to_video_model,
        reference_image_max_bytes=6_000_000,
        client_timeout_seconds=45,
        client=client,
        download_client=download_client,
    )


@pytest.mark.asyncio
async def test_submit_text_to_video_sends_correct_model_and_payload() -> None:
    client = _FakeFalClient(submit_handle=_FakeHandle(request_id='fal-req-1'))
    provider = make_provider(client, image_to_video_model=None)

    submitted = await provider.submit_video(make_request())

    assert submitted.operation_name == 'fal-req-1'
    assert submitted.provider == 'fal'
    assert submitted.raw_model == 'fal-ai/kling-video/v3/standard/text-to-video'
    assert client.submit_calls == [
        {
            'application': 'fal-ai/kling-video/v3/standard/text-to-video',
            'arguments': {
                'prompt': 'tracking shot through a glowing cave',
                'duration': '5',
                'aspect_ratio': '9:16',
            },
            'kwargs': {},
        }
    ]
    assert client.upload_calls == []


@pytest.mark.asyncio
async def test_submit_image_to_video_uses_data_uri_without_sdk_upload() -> None:
    client = _FakeFalClient(submit_handle=_FakeHandle(request_id='fal-req-2'))
    provider = make_provider(client)

    submitted = await provider.submit_video(
        make_request(reference_image=make_reference_image())
    )

    assert submitted.raw_model == 'fal-ai/kling-video/v3/standard/image-to-video'
    assert client.upload_calls == []
    assert client.submit_calls[0]['application'] == (
        'fal-ai/kling-video/v3/standard/image-to-video'
    )
    assert client.submit_calls[0]['arguments'] == {
        'prompt': 'tracking shot through a glowing cave',
        'duration': '5',
        'start_image_url': 'data:image/jpeg;base64,'
        + base64.b64encode(b'reference-image').decode('ascii'),
    }


@pytest.mark.asyncio
async def test_submit_omits_oversized_reference_image_and_falls_back_to_t2v() -> None:
    client = _FakeFalClient(submit_handle=_FakeHandle(request_id='fal-req-3'))
    provider = make_provider(client)

    submitted = await provider.submit_video(
        make_request(reference_image=make_reference_image(byte_size=6_000_001))
    )

    assert submitted.raw_model == 'fal-ai/kling-video/v3/standard/text-to-video'
    assert client.upload_calls == []
    assert client.submit_calls[0]['application'] == (
        'fal-ai/kling-video/v3/standard/text-to-video'
    )
    assert client.submit_calls[0]['arguments'] == {
        'prompt': 'tracking shot through a glowing cave',
        'duration': '5',
        'aspect_ratio': '9:16',
    }


@pytest.mark.asyncio
async def test_poll_maps_queued_and_in_progress_to_running() -> None:
    for status in (_FakeQueued(), _FakeInProgress()):
        client = _FakeFalClient()
        handle = _FakeHandle(request_id='fal-req-1', status_result=status)
        client.handles[
            ('fal-ai/kling-video/v3/standard/text-to-video', 'fal-req-1')
        ] = handle
        provider = make_provider(client)

        result = await provider.poll_video(
            VideoGenerationPollRequest(
                operation_name='fal-req-1',
                prompt='tracking shot through a glowing cave',
                model='fal-ai/kling-video/v3/standard/text-to-video',
                provider='fal',
            )
        )

        assert result.status == 'running'
        assert result.operation_name == 'fal-req-1'
        assert client.get_handle_calls == [
            ('fal-ai/kling-video/v3/standard/text-to-video', 'fal-req-1')
        ]
        assert handle.status_calls == [False]


@pytest.mark.asyncio
async def test_poll_completed_recreates_handle_downloads_video_and_returns_result() -> None:
    client = _FakeFalClient()
    handle = _FakeHandle(
        request_id='fal-req-1',
        status_result=_FakeCompleted(),
        get_result={
            'video': {
                'url': 'https://cdn.example.com/output.mp4',
                'file_size': 1234567,
                'file_name': 'output.mp4',
                'content_type': 'video/mp4',
            }
        },
    )
    client.handles[
        ('fal-ai/kling-video/v3/standard/text-to-video', 'fal-req-1')
    ] = handle

    def download_handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == 'https://cdn.example.com/output.mp4'
        return httpx.Response(
            200,
            content=b'video-bytes',
            headers={'content-type': 'video/mp4'},
        )

    provider = make_provider(client, download_handler=download_handler)
    result = await provider.poll_video(
        VideoGenerationPollRequest(
            operation_name='fal-req-1',
            prompt='tracking shot through a glowing cave',
            model='fal-ai/kling-video/v3/standard/text-to-video',
            provider='fal',
        )
    )

    assert client.get_handle_calls == [
        ('fal-ai/kling-video/v3/standard/text-to-video', 'fal-req-1')
    ]
    assert handle.status_calls == [False]
    assert handle.get_calls == 1
    assert result.status == 'completed'
    assert result.generated_video is not None
    assert result.generated_video.video_bytes == b'video-bytes'
    assert result.generated_video.mime_type == 'video/mp4'
    assert result.generated_video.provider == 'fal'
    assert result.generated_video.raw_model == (
        'fal-ai/kling-video/v3/standard/text-to-video'
    )
    assert result.generated_video.output_uri is None
    assert result.generated_video.file_size == 1234567
    assert result.generated_video.duration_seconds is None
    assert result.generated_video.width is None
    assert result.generated_video.height is None
    await provider.close()


@pytest.mark.asyncio
async def test_poll_result_with_error_or_error_type_returns_failed() -> None:
    for result_payload, failure_reason in (
        ({'error': 'policy violation'}, 'policy violation'),
        ({'error_type': 'content_moderation'}, 'content_moderation'),
    ):
        client = _FakeFalClient()
        handle = _FakeHandle(
            request_id='fal-req-1',
            status_result=_FakeCompleted(),
            get_result=result_payload,
        )
        client.handles[
            ('fal-ai/kling-video/v3/standard/text-to-video', 'fal-req-1')
        ] = handle
        provider = make_provider(client)

        result = await provider.poll_video(
            VideoGenerationPollRequest(
                operation_name='fal-req-1',
                prompt='tracking shot through a glowing cave',
                model='fal-ai/kling-video/v3/standard/text-to-video',
                provider='fal',
            )
        )

        assert result.status == 'failed'
        assert result.failure_reason == failure_reason


@pytest.mark.asyncio
async def test_submit_missing_request_id_raises_upstream_error() -> None:
    client = _FakeFalClient(submit_handle=_FakeHandle(request_id=''))
    provider = make_provider(client, image_to_video_model=None)

    with pytest.raises(ProviderUpstreamError, match='no request_id'):
        await provider.submit_video(make_request())


@pytest.mark.asyncio
async def test_submit_timeout_raises_timeout_error() -> None:
    client = _FakeFalClient(
        submit_error=httpx.TimeoutException('request timed out')
    )
    provider = make_provider(client, image_to_video_model=None)

    with pytest.raises(ProviderTimeoutError, match='timed out'):
        await provider.submit_video(make_request())


@pytest.mark.asyncio
async def test_submit_http_500_raises_upstream_error() -> None:
    request = httpx.Request('POST', 'https://queue.fal.run/fal-ai/kling-video')
    response = httpx.Response(500, request=request, text='provider exploded')
    client = _FakeFalClient(
        submit_error=httpx.HTTPStatusError(
            'provider exploded',
            request=request,
            response=response,
        )
    )
    provider = make_provider(client, image_to_video_model=None)

    with pytest.raises(ProviderUpstreamError, match='Fal video generation failed'):
        await provider.submit_video(make_request())


@pytest.mark.asyncio
async def test_submit_seedance_text_to_video_uses_resolution() -> None:
    client = _FakeFalClient(submit_handle=_FakeHandle(request_id='fal-seedance-1'))
    provider = make_provider(
        client,
        image_to_video_model=None,
        default_model='bytedance/seedance-2.0/text-to-video',
    )

    submitted = await provider.submit_video(
        make_request(model='bytedance/seedance-2.0/text-to-video', resolution='1080p')
    )

    assert submitted.raw_model == 'bytedance/seedance-2.0/text-to-video'
    assert client.submit_calls[0]['arguments'] == {
        'prompt': 'tracking shot through a glowing cave',
        'duration': '5',
        'resolution': '1080p',
        'aspect_ratio': '9:16',
    }


@pytest.mark.asyncio
async def test_submit_gemini_image_to_video_uses_data_uri_without_sdk_upload() -> None:
    client = _FakeFalClient(submit_handle=_FakeHandle(request_id='fal-gemini-1'))
    provider = make_provider(
        client,
        default_model='google/gemini-omni-flash',
        image_to_video_model='google/gemini-omni-flash/image-to-video',
    )

    submitted = await provider.submit_video(
        make_request(
            model='google/gemini-omni-flash/image-to-video',
            reference_image=make_reference_image(),
        )
    )

    assert submitted.raw_model == 'google/gemini-omni-flash/image-to-video'
    assert client.submit_calls[0]['arguments']['image_url'] == (
        'data:image/jpeg;base64,'
        + base64.b64encode(b'reference-image').decode('ascii')
    )
    assert client.submit_calls[0]['arguments']['duration'] == 5
    assert 'start_image_url' not in client.submit_calls[0]['arguments']


@pytest.mark.asyncio
async def test_gemini_image_to_video_coerces_unsupported_aspect_ratio() -> None:
    client = _FakeFalClient(submit_handle=_FakeHandle(request_id='fal-gemini-1'))
    provider = make_provider(
        client,
        default_model='google/gemini-omni-flash/image-to-video',
        image_to_video_model='google/gemini-omni-flash/image-to-video',
    )
    request = make_request(
        reference_image=make_reference_image(),
        model='google/gemini-omni-flash/image-to-video',
    )
    request.aspect_ratio = '1:1'

    submitted = await provider.submit_video(request)

    assert submitted.raw_model == 'google/gemini-omni-flash/image-to-video'
    assert client.submit_calls[0]['arguments'] == {
        'prompt': 'tracking shot through a glowing cave',
        'duration': 5,
        'aspect_ratio': '9:16',
        'image_url': 'data:image/jpeg;base64,'
        + base64.b64encode(b'reference-image').decode('ascii'),
    }


@pytest.mark.asyncio
async def test_submit_reference_to_video_uses_image_urls_list() -> None:
    client = _FakeFalClient(submit_handle=_FakeHandle(request_id='fal-r2v-1'))
    provider = make_provider(
        client,
        default_model='bytedance/seedance-2.0/text-to-video',
        reference_to_video_model='bytedance/seedance-2.0/reference-to-video',
    )

    submitted = await provider.submit_video(
        make_request(
            model='bytedance/seedance-2.0/reference-to-video',
            reference_image=make_reference_image(),
        )
    )

    assert submitted.raw_model == 'bytedance/seedance-2.0/reference-to-video'
    assert client.submit_calls[0]['arguments'] == {
        'prompt': 'tracking shot through a glowing cave',
        'duration': '5',
        'resolution': '720p',
        'aspect_ratio': '9:16',
        'image_urls': [
            'data:image/jpeg;base64,'
            + base64.b64encode(b'reference-image').decode('ascii')
        ],
    }


@pytest.mark.asyncio
async def test_locked_image_to_video_model_falls_back_to_text_when_image_oversized() -> None:
    client = _FakeFalClient(submit_handle=_FakeHandle(request_id='fal-fallback'))
    provider = make_provider(client)
    big_image = make_reference_image(byte_size=10_000_000)
    request = make_request(
        reference_image=big_image,
        model='fal-ai/kling-video/v3/standard/image-to-video',
    )
    request.model_locked = True

    submitted = await provider.submit_video(request)

    assert submitted.raw_model == 'fal-ai/kling-video/v3/standard/text-to-video'
    assert client.upload_calls == []
    assert client.submit_calls[0]['arguments'] == {
        'prompt': 'tracking shot through a glowing cave',
        'duration': '5',
        'aspect_ratio': '9:16',
    }


@pytest.mark.asyncio
async def test_locked_image_to_video_model_falls_back_to_text_when_no_reference() -> None:
    client = _FakeFalClient(submit_handle=_FakeHandle(request_id='fal-fallback-2'))
    provider = make_provider(client)
    request = make_request(model='fal-ai/kling-video/v3/standard/image-to-video')
    request.model_locked = True

    submitted = await provider.submit_video(request)

    assert submitted.raw_model == 'fal-ai/kling-video/v3/standard/text-to-video'
    assert client.upload_calls == []
    assert client.submit_calls[0]['arguments'] == {
        'prompt': 'tracking shot through a glowing cave',
        'duration': '5',
        'aspect_ratio': '9:16',
    }


@pytest.mark.asyncio
async def test_locked_image_to_video_model_uses_custom_text_override_on_fallback() -> None:
    client = _FakeFalClient(submit_handle=_FakeHandle(request_id='fal-fallback-3'))
    provider = make_provider(
        client,
        default_model='fal-ai/google/gemini-omni-flash',
        image_to_video_model='fal-ai/google/gemini-omni-flash/image-to-video',
    )
    request = make_request(model='fal-ai/google/gemini-omni-flash/image-to-video')
    request.model_locked = True

    submitted = await provider.submit_video(request)

    assert submitted.raw_model == 'fal-ai/google/gemini-omni-flash'
    assert client.submit_calls[0]['application'] == 'fal-ai/google/gemini-omni-flash'
