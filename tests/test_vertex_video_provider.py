from __future__ import annotations

import pytest

from app.domain.errors import ProviderTimeoutError
from app.domain.models import VideoGenerationPollRequest, VideoGenerationRequest
from app.providers.vertex_video_provider import VertexVideoProvider


class _FakeModels:
    def __init__(self, *, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    def generate_videos(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class _FakeOperations:
    def __init__(self, *, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[object] = []

    def get(self, *, operation):
        self.calls.append(operation)
        if self.error is not None:
            raise self.error
        return self.response


class _FakeClient:
    def __init__(self, models: _FakeModels, operations: _FakeOperations) -> None:
        self.models = models
        self.operations = operations


class _FakeOperationType:
    def __init__(self, *, name: str) -> None:
        self.name = name


class _FakeAPIError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def test_vertex_video_client_kwargs_prefer_adc_when_project_is_set() -> None:
    kwargs = VertexVideoProvider._build_client_kwargs(
        api_key="vertex-key",
        project="test-project",
        location="us-central1",
    )

    assert kwargs == {
        "vertexai": True,
        "project": "test-project",
        "location": "us-central1",
    }


def test_vertex_video_client_kwargs_use_api_key_without_project() -> None:
    kwargs = VertexVideoProvider._build_client_kwargs(
        api_key="vertex-key",
        project="",
        location="us-central1",
    )

    assert kwargs == {
        "vertexai": True,
        "api_key": "vertex-key",
    }


@pytest.mark.asyncio
async def test_submit_video_returns_operation_name() -> None:
    models = _FakeModels(response=type("Operation", (), {"name": "operations/123"})())
    provider = VertexVideoProvider(
        project="test-project",
        location="us-central1",
        default_model="veo-3.0-fast-generate-001",
        default_aspect_ratio="16:9",
        default_duration_seconds=4,
        default_output_gcs_uri=None,
        client=_FakeClient(models, _FakeOperations()),
    )

    submitted = await provider.submit_video(
        VideoGenerationRequest(
            chat_id=1,
            user_id=42,
            prompt="tracking shot through a glowing cave",
            model="veo-3.0-fast-generate-001",
            aspect_ratio="16:9",
            duration_seconds=4,
            output_gcs_uri=None,
        )
    )

    assert submitted.operation_name == "operations/123"
    assert submitted.raw_model == "veo-3.0-fast-generate-001"
    assert models.calls[0]["prompt"] == "tracking shot through a glowing cave"
    assert models.calls[0]["config"]["duration_seconds"] == 4


@pytest.mark.asyncio
async def test_poll_video_returns_running_status() -> None:
    operations = _FakeOperations(response=type("Operation", (), {"done": False})())
    provider = VertexVideoProvider(
        project="test-project",
        location="us-central1",
        default_model="veo-3.0-fast-generate-001",
        default_aspect_ratio="16:9",
        default_duration_seconds=4,
        default_output_gcs_uri=None,
        client=_FakeClient(_FakeModels(), operations),
        operation_type=_FakeOperationType,
    )

    result = await provider.poll_video(
        VideoGenerationPollRequest(
            operation_name="operations/123",
            prompt="tracking shot through a glowing cave",
            model="veo-3.0-fast-generate-001",
        )
    )

    assert result.status == "running"
    assert operations.calls[0].name == "operations/123"


@pytest.mark.asyncio
async def test_poll_video_returns_inline_video_bytes() -> None:
    operations = _FakeOperations(
        response=type(
            "Operation",
            (),
            {
                "done": True,
                "error": None,
                "result": type(
                    "Result",
                    (),
                    {
                        "generated_videos": [
                            type(
                                "GeneratedVideo",
                                (),
                                {
                                    "video": type(
                                        "Video",
                                        (),
                                        {
                                            "uri": None,
                                            "video_bytes": b"video-bytes",
                                            "mime_type": "video/mp4",
                                        },
                                    )()
                                },
                            )()
                        ]
                    },
                )(),
            },
        )()
    )
    provider = VertexVideoProvider(
        project="test-project",
        location="us-central1",
        default_model="veo-3.0-fast-generate-001",
        default_aspect_ratio="16:9",
        default_duration_seconds=4,
        default_output_gcs_uri=None,
        client=_FakeClient(_FakeModels(), operations),
        operation_type=_FakeOperationType,
    )

    result = await provider.poll_video(
        VideoGenerationPollRequest(
            operation_name="operations/123",
            prompt="tracking shot through a glowing cave",
            model="veo-3.0-fast-generate-001",
        )
    )

    assert result.status == "completed"
    assert result.generated_video is not None
    assert result.generated_video.video_bytes == b"video-bytes"
    assert result.generated_video.mime_type == "video/mp4"


@pytest.mark.asyncio
async def test_poll_video_downloads_from_uri_when_bytes_are_missing() -> None:
    operations = _FakeOperations(
        response=type(
            "Operation",
            (),
            {
                "done": True,
                "error": None,
                "result": type(
                    "Result",
                    (),
                    {
                        "generated_videos": [
                            type(
                                "GeneratedVideo",
                                (),
                                {
                                    "video": type(
                                        "Video",
                                        (),
                                        {
                                            "uri": "gs://bucket/video.mp4",
                                            "video_bytes": None,
                                            "mime_type": None,
                                        },
                                    )()
                                },
                            )()
                        ]
                    },
                )(),
            },
        )()
    )
    provider = VertexVideoProvider(
        project="test-project",
        location="us-central1",
        default_model="veo-3.0-fast-generate-001",
        default_aspect_ratio="16:9",
        default_duration_seconds=4,
        default_output_gcs_uri=None,
        client=_FakeClient(_FakeModels(), operations),
        operation_type=_FakeOperationType,
        video_uri_resolver=lambda _uri: (b"downloaded-video", "video/mp4", 16),
    )

    result = await provider.poll_video(
        VideoGenerationPollRequest(
            operation_name="operations/123",
            prompt="tracking shot through a glowing cave",
            model="veo-3.0-fast-generate-001",
        )
    )

    assert result.status == "completed"
    assert result.generated_video is not None
    assert result.generated_video.video_bytes == b"downloaded-video"
    assert result.generated_video.output_uri == "gs://bucket/video.mp4"
    assert result.generated_video.file_size == 16


@pytest.mark.asyncio
async def test_submit_video_maps_api_timeout_error() -> None:
    provider = VertexVideoProvider(
        project="test-project",
        location="us-central1",
        default_model="veo-3.0-fast-generate-001",
        default_aspect_ratio="16:9",
        default_duration_seconds=4,
        default_output_gcs_uri=None,
        client=_FakeClient(
            _FakeModels(error=_FakeAPIError(504, "gateway timeout")),
            _FakeOperations(),
        ),
        api_error_type=_FakeAPIError,
    )

    with pytest.raises(ProviderTimeoutError):
        await provider.submit_video(
            VideoGenerationRequest(
                chat_id=1,
                user_id=42,
                prompt="tracking shot through a glowing cave",
                model="veo-3.0-fast-generate-001",
                aspect_ratio="16:9",
                duration_seconds=4,
                output_gcs_uri=None,
            )
        )
