from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from app.domain.errors import ProviderTimeoutError, ProviderUpstreamError
from app.domain.models import (
    GeneratedVideoResult,
    SubmittedVideoJob,
    VideoGenerationPollRequest,
    VideoGenerationRequest,
    VideoJobPollResult,
)
from app.logging import log_kv


class VertexVideoProvider:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        project: str,
        location: str,
        default_model: str,
        default_aspect_ratio: str,
        default_duration_seconds: int | None,
        default_output_gcs_uri: str | None,
        client: Any | None = None,
        types_module: Any | None = None,
        operation_type: type | None = None,
        api_error_type: type[Exception] | None = None,
        video_uri_resolver: (
            Callable[[str], tuple[bytes, str | None, int | None]] | None
        ) = None,
    ) -> None:
        self.logger = logging.getLogger("app.providers.vertex_video_provider")
        self._auth_mode = "adc" if project else ("api_key" if api_key is not None else "adc")
        self._project = project
        self._default_model = default_model
        self._default_aspect_ratio = default_aspect_ratio
        self._default_duration_seconds = default_duration_seconds
        self._default_output_gcs_uri = default_output_gcs_uri
        self._video_uri_resolver = video_uri_resolver or self._download_video_from_uri

        if client is not None:
            self._client = client
            self._types_module = types_module
            self._operation_type = operation_type
            self._api_error_type = api_error_type
            return

        try:
            from google import genai
            from google.genai import errors, types
        except ImportError as exc:
            raise RuntimeError(
                "google-genai must be installed to enable Vertex video generation"
            ) from exc

        self._client = genai.Client(
            **self._build_client_kwargs(
                api_key=api_key,
                project=project,
                location=location,
            )
        )
        self._types_module = types
        self._operation_type = types.GenerateVideosOperation
        self._api_error_type = errors.APIError

    async def close(self) -> None:
        return None

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

    async def submit_video(
        self,
        request: VideoGenerationRequest,
    ) -> SubmittedVideoJob:
        self.logger.info(
            log_kv(
                "vertex_video_submit_started",
                chat_id=request.chat_id,
                user_id=request.user_id,
                model=request.model or self._default_model,
                aspect_ratio=request.aspect_ratio or self._default_aspect_ratio,
                duration_seconds=(
                    request.duration_seconds
                    if request.duration_seconds is not None
                    else self._default_duration_seconds
                ),
                output_gcs_uri=request.output_gcs_uri or self._default_output_gcs_uri,
                prompt_chars=len(request.prompt),
                auth_mode=self._auth_mode,
            )
        )
        try:
            operation = await asyncio.to_thread(self._submit_video_sync, request)
        except Exception as exc:
            if self._api_error_type is not None and isinstance(exc, self._api_error_type):
                self.logger.warning(
                    log_kv(
                        "vertex_video_submit_api_error",
                        chat_id=request.chat_id,
                        user_id=request.user_id,
                        model=request.model or self._default_model,
                        aspect_ratio=request.aspect_ratio or self._default_aspect_ratio,
                        duration_seconds=(
                            request.duration_seconds
                            if request.duration_seconds is not None
                            else self._default_duration_seconds
                        ),
                        output_gcs_uri=(
                            request.output_gcs_uri or self._default_output_gcs_uri
                        ),
                        error_code=getattr(exc, "code", None),
                        error_message=self._error_message(exc),
                        error_details=self._error_details(exc),
                    )
                )
                error_code = getattr(exc, "code", None)
                if error_code in {408, 504}:
                    raise ProviderTimeoutError("Vertex video generation timed out") from exc
                raise ProviderUpstreamError("Vertex video generation failed") from exc
            self.logger.exception(
                log_kv(
                    "vertex_video_submit_unhandled_error",
                    chat_id=request.chat_id,
                    user_id=request.user_id,
                    model=request.model or self._default_model,
                )
            )
            raise

        operation_name = getattr(operation, "name", None)
        if not operation_name:
            self.logger.warning(
                log_kv(
                    "vertex_video_submit_missing_operation_name",
                    chat_id=request.chat_id,
                    user_id=request.user_id,
                    model=request.model or self._default_model,
                )
            )
            raise ProviderUpstreamError("Vertex video generation returned no operation name")

        self.logger.info(
            log_kv(
                "vertex_video_submit_succeeded",
                chat_id=request.chat_id,
                user_id=request.user_id,
                model=request.model or self._default_model,
                operation_name=operation_name,
            )
        )
        return SubmittedVideoJob(
            operation_name=operation_name,
            provider="vertex",
            raw_model=request.model or self._default_model,
        )

    async def poll_video(
        self,
        request: VideoGenerationPollRequest,
    ) -> VideoJobPollResult:
        self.logger.debug(
            log_kv(
                "vertex_video_poll_started",
                operation_name=request.operation_name,
                model=request.model or self._default_model,
            )
        )
        try:
            return await asyncio.to_thread(self._poll_video_sync, request)
        except Exception as exc:
            if self._api_error_type is not None and isinstance(exc, self._api_error_type):
                self.logger.warning(
                    log_kv(
                        "vertex_video_poll_api_error",
                        operation_name=request.operation_name,
                        model=request.model or self._default_model,
                        error_code=getattr(exc, "code", None),
                        error_message=self._error_message(exc),
                        error_details=self._error_details(exc),
                    )
                )
                error_code = getattr(exc, "code", None)
                if error_code in {408, 504}:
                    raise ProviderTimeoutError("Vertex video polling timed out") from exc
                raise ProviderUpstreamError("Vertex video polling failed") from exc
            self.logger.exception(
                log_kv(
                    "vertex_video_poll_unhandled_error",
                    operation_name=request.operation_name,
                    model=request.model or self._default_model,
                )
            )
            raise

    def _submit_video_sync(self, request: VideoGenerationRequest) -> Any:
        config_kwargs: dict[str, Any] = {
            "number_of_videos": 1,
            "aspect_ratio": request.aspect_ratio or self._default_aspect_ratio,
        }
        duration_seconds = (
            request.duration_seconds
            if request.duration_seconds is not None
            else self._default_duration_seconds
        )
        if duration_seconds is not None:
            config_kwargs["duration_seconds"] = duration_seconds

        output_gcs_uri = request.output_gcs_uri or self._default_output_gcs_uri
        if output_gcs_uri is not None:
            config_kwargs["output_gcs_uri"] = output_gcs_uri

        config: Any = config_kwargs
        if self._types_module is not None:
            config = self._types_module.GenerateVideosConfig(**config_kwargs)

        model = request.model or self._default_model
        if self._types_module is not None and hasattr(
            self._types_module,
            "GenerateVideosSource",
        ):
            source = self._types_module.GenerateVideosSource(prompt=request.prompt)
            return self._client.models.generate_videos(
                model=model,
                source=source,
                config=config,
            )

        return self._client.models.generate_videos(
            model=model,
            prompt=request.prompt,
            config=config,
        )

    def _poll_video_sync(
        self,
        request: VideoGenerationPollRequest,
    ) -> VideoJobPollResult:
        operation = self._make_operation_stub(request.operation_name)
        operation = self._client.operations.get(operation=operation)

        if not getattr(operation, "done", False):
            self.logger.debug(
                log_kv(
                    "vertex_video_poll_running",
                    operation_name=request.operation_name,
                    model=request.model or self._default_model,
                )
            )
            return VideoJobPollResult(
                status="running",
                operation_name=request.operation_name,
            )

        operation_error = getattr(operation, "error", None)
        if operation_error is not None:
            failure_reason = getattr(operation_error, "message", None) or str(operation_error)
            self.logger.warning(
                log_kv(
                    "vertex_video_poll_operation_failed",
                    operation_name=request.operation_name,
                    model=request.model or self._default_model,
                    failure_reason=failure_reason,
                )
            )
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason=failure_reason or "Vertex video generation failed",
            )

        result = getattr(operation, "result", None) or getattr(operation, "response", None)
        generated_videos = getattr(result, "generated_videos", None) or []
        if not generated_videos:
            self.logger.warning(
                log_kv(
                    "vertex_video_poll_empty_result",
                    operation_name=request.operation_name,
                    model=request.model or self._default_model,
                )
            )
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason="Vertex video generation returned no videos",
            )

        video = getattr(generated_videos[0], "video", None)
        if video is None:
            self.logger.warning(
                log_kv(
                    "vertex_video_poll_missing_video_payload",
                    operation_name=request.operation_name,
                    model=request.model or self._default_model,
                )
            )
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason="Vertex video generation returned an empty video payload",
            )

        output_uri = getattr(video, "uri", None)
        video_bytes = getattr(video, "video_bytes", None)
        mime_type = getattr(video, "mime_type", None) or "video/mp4"
        file_size = len(video_bytes) if video_bytes is not None else None

        if not video_bytes:
            if output_uri is None:
                self.logger.warning(
                    log_kv(
                        "vertex_video_poll_missing_downloadable_asset",
                        operation_name=request.operation_name,
                        model=request.model or self._default_model,
                    )
                )
                return VideoJobPollResult(
                    status="failed",
                    operation_name=request.operation_name,
                    failure_reason="Vertex video generation returned no downloadable asset",
                )
            try:
                self.logger.info(
                    log_kv(
                        "vertex_video_download_started",
                        operation_name=request.operation_name,
                        model=request.model or self._default_model,
                        output_uri=output_uri,
                    )
                )
                video_bytes, resolved_mime_type, resolved_size = self._video_uri_resolver(
                    output_uri
                )
            except Exception as exc:
                self.logger.exception(
                    log_kv(
                        "vertex_video_download_failed",
                        operation_name=request.operation_name,
                        model=request.model or self._default_model,
                        output_uri=output_uri,
                    )
                )
                raise ProviderUpstreamError(
                    "Vertex video generation returned an unreadable asset"
                ) from exc
            if resolved_mime_type:
                mime_type = resolved_mime_type
            file_size = resolved_size or len(video_bytes)
            self.logger.info(
                log_kv(
                    "vertex_video_download_succeeded",
                    operation_name=request.operation_name,
                    model=request.model or self._default_model,
                    output_uri=output_uri,
                    mime_type=mime_type,
                    file_size=file_size,
                )
            )

        self.logger.info(
            log_kv(
                "vertex_video_poll_completed",
                operation_name=request.operation_name,
                model=request.model or self._default_model,
                output_uri=output_uri,
                mime_type=mime_type,
                file_size=file_size or len(video_bytes),
            )
        )
        return VideoJobPollResult(
            status="completed",
            operation_name=request.operation_name,
            generated_video=GeneratedVideoResult(
                video_bytes=video_bytes,
                mime_type=mime_type,
                provider="vertex",
                raw_model=request.model or self._default_model,
                prompt=request.prompt,
                output_uri=output_uri,
                file_size=file_size or len(video_bytes),
            ),
        )

    def _make_operation_stub(self, operation_name: str) -> Any:
        if self._operation_type is not None:
            return self._operation_type(name=operation_name)
        return type("GenerateVideosOperation", (), {"name": operation_name})()

    def _error_message(self, exc: Exception) -> str:
        message = getattr(exc, "message", None)
        if isinstance(message, str) and message:
            return message
        return str(exc)

    def _error_details(self, exc: Exception) -> str | None:
        for field_name in ("details", "errors", "response"):
            value = getattr(exc, field_name, None)
            if value is None:
                continue
            try:
                return str(value)
            except Exception:
                continue
        return None

    def _download_video_from_uri(self, uri: str) -> tuple[bytes, str | None, int | None]:
        if not uri.startswith("gs://"):
            raise RuntimeError("only gs:// video URIs are supported")

        try:
            from google.cloud import storage
            from google.cloud.storage.blob import Blob
        except ImportError as exc:
            raise RuntimeError(
                "google-cloud-storage must be installed to download Vertex video assets from GCS"
            ) from exc

        client = storage.Client(project=self._project or None)
        blob = Blob.from_uri(uri, client=client)
        blob.reload()
        data = blob.download_as_bytes()
        return data, blob.content_type, blob.size
