from __future__ import annotations

import base64
import binascii
import inspect
import logging
from typing import Any, Literal

import httpx

from app.domain.errors import ProviderTimeoutError, ProviderUpstreamError
from app.domain.models import (
    GeneratedVideoResult,
    ImageInput,
    SubmittedVideoJob,
    VideoGenerationPollRequest,
    VideoGenerationRequest,
    VideoJobPollResult,
)
from app.logging import log_kv

FalMode = Literal["text-to-video",
                  "image-to-video", "reference-to-video", "edit"]
FalFamily = Literal["kling", "seedance", "gemini", "other"]


class FalVideoProvider:
    def __init__(
        self,
        *,
        api_key: str,
        default_model: str,
        image_to_video_model: str | None,
        reference_image_max_bytes: int,
        reference_to_video_model: str | None = None,
        edit_model: str | None = None,
        client_timeout_seconds: int | None = None,
        client: Any | None = None,
        download_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.logger = logging.getLogger("app.providers.fal_video_provider")
        self.api_key = api_key
        self.default_model = default_model
        self.image_to_video_model = image_to_video_model
        self.reference_to_video_model = reference_to_video_model
        self.edit_model = edit_model
        self.reference_image_max_bytes = reference_image_max_bytes

        if client is not None:
            self._client = client
        else:
            try:
                import fal_client
            except ImportError as exc:
                raise RuntimeError(
                    "fal-client must be installed to enable Fal video generation"
                ) from exc
            self._client = fal_client.AsyncClient(
                key=api_key,
                default_timeout=float(client_timeout_seconds or 45),
            )

        timeout = httpx.Timeout(client_timeout_seconds or 45)
        self._download_client = download_client or httpx.AsyncClient(
            timeout=timeout)

    async def close(self) -> None:
        await _maybe_close(self._download_client)
        await _maybe_close(self._client)

    async def submit_video(
        self,
        request: VideoGenerationRequest,
    ) -> SubmittedVideoJob:
        model = self._select_model_for(request)
        self.logger.info(
            log_kv(
                "fal_video_submit_started",
                chat_id=request.chat_id,
                user_id=request.user_id,
                model=model,
                prompt_chars=len(request.prompt),
                reference_image=bool(request.reference_image),
            )
        )

        try:
            arguments = await self._build_submit_arguments(request, model)
            handle = await self._client.submit(model, arguments=arguments)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                "Fal video generation timed out") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {408, 504}:
                raise ProviderTimeoutError(
                    "Fal video generation timed out") from exc
            body = _response_text(exc.response)
            self.logger.warning(
                log_kv(
                    "fal_video_http_error",
                    operation="submit",
                    model=model,
                    status_code=exc.response.status_code,
                    response_body=body,
                )
            )
            raise ProviderUpstreamError(
                f"Fal video generation failed (HTTP {exc.response.status_code}): {
                    body}"
            ) from exc
        except httpx.HTTPError as exc:
            self.logger.warning(
                log_kv(
                    "fal_video_http_error",
                    operation="submit",
                    model=model,
                    error=str(exc),
                )
            )
            raise ProviderUpstreamError("Fal video generation failed") from exc

        request_id = str(getattr(handle, "request_id", "") or "")
        if not request_id:
            raise ProviderUpstreamError(
                "Fal video generation returned no request_id")

        self.logger.info(
            log_kv(
                "fal_video_submit_succeeded",
                chat_id=request.chat_id,
                user_id=request.user_id,
                model=model,
                operation_name=request_id,
            )
        )
        return SubmittedVideoJob(
            operation_name=request_id,
            provider="fal",
            raw_model=model,
        )

    async def poll_video(
        self,
        request: VideoGenerationPollRequest,
    ) -> VideoJobPollResult:
        model = request.model
        self.logger.debug(
            log_kv(
                "fal_video_poll_started",
                operation_name=request.operation_name,
                model=model,
            )
        )

        try:
            handle = self._client.get_handle(model, request.operation_name)
            status = await handle.status(with_logs=False)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("Fal video polling timed out") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {408, 504}:
                raise ProviderTimeoutError(
                    "Fal video polling timed out") from exc
            body = _response_text(exc.response)
            self.logger.warning(
                log_kv(
                    "fal_video_http_error",
                    operation="status",
                    model=model,
                    operation_name=request.operation_name,
                    status_code=exc.response.status_code,
                    response_body=body,
                )
            )
            raise ProviderUpstreamError(
                f"Fal video polling failed (HTTP {exc.response.status_code}): {
                    body}"
            ) from exc
        except httpx.HTTPError as exc:
            self.logger.warning(
                log_kv(
                    "fal_video_http_error",
                    operation="status",
                    model=model,
                    operation_name=request.operation_name,
                    error=str(exc),
                )
            )
            raise ProviderUpstreamError("Fal video polling failed") from exc

        status_name = _queue_status_name(status)
        if status_name in {"queued", "in_progress"}:
            return VideoJobPollResult(
                status="running",
                operation_name=request.operation_name,
            )
        if status_name != "completed":
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason=(
                    "Fal video generation returned unknown status: "
                    f"{_queue_status_label(status)}"
                ),
            )

        try:
            result_body = await handle.get()
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("Fal video polling timed out") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {408, 504}:
                raise ProviderTimeoutError(
                    "Fal video polling timed out") from exc
            body = _response_text(exc.response)
            self.logger.warning(
                log_kv(
                    "fal_video_http_error",
                    operation="result",
                    model=model,
                    operation_name=request.operation_name,
                    status_code=exc.response.status_code,
                    response_body=body,
                )
            )
            raise ProviderUpstreamError(
                f"Fal video polling failed (HTTP {exc.response.status_code}): {
                    body}"
            ) from exc
        except httpx.HTTPError as exc:
            self.logger.warning(
                log_kv(
                    "fal_video_http_error",
                    operation="result",
                    model=model,
                    operation_name=request.operation_name,
                    error=str(exc),
                )
            )
            raise ProviderUpstreamError("Fal video polling failed") from exc

        if not isinstance(result_body, dict):
            raise ProviderUpstreamError(
                "Fal video generation returned invalid JSON")

        error = _first_string(result_body, "error", "error_type")
        if error is not None:
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason=error,
            )

        video = result_body.get("video")
        if not isinstance(video, dict):
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason="Fal video generation returned no video metadata",
            )

        video_url = video.get("url")
        if not isinstance(video_url, str) or not video_url:
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason="Fal video generation returned no video URL",
            )

        video_bytes, mime_type, file_size = await self._download_video(
            video_url,
            mime_type=(
                video.get("content_type")
                if isinstance(video.get("content_type"), str)
                else None
            ),
            file_size=_optional_int(video.get("file_size")),
        )
        if not video_bytes:
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason="Fal video generation returned an empty video asset",
            )

        return VideoJobPollResult(
            status="completed",
            operation_name=request.operation_name,
            generated_video=GeneratedVideoResult(
                video_bytes=video_bytes,
                mime_type=mime_type,
                provider="fal",
                raw_model=model,
                prompt=request.prompt,
                output_uri=None,
                duration_seconds=None,
                width=None,
                height=None,
                file_size=file_size,
            ),
        )

    def _select_model_for(self, request: VideoGenerationRequest) -> str:
        reference_image = request.reference_image
        image_usable = (
            reference_image is not None
            and reference_image.byte_size <= self.reference_image_max_bytes
        )

        if request.model and request.model_locked:
            selected = request.model
        else:
            selected = self.default_model
            if image_usable:
                if self.reference_to_video_model:
                    selected = self.reference_to_video_model
                elif self.image_to_video_model:
                    selected = self.image_to_video_model
            elif request.model:
                selected = request.model

        request_mode = _mode_for_model(request.model or selected)
        if not image_usable and request_mode in {
            "image-to-video",
            "reference-to-video",
            "edit",
        }:
            selected = self.default_model
        return selected

    async def _build_submit_arguments(
        self,
        request: VideoGenerationRequest,
        model: str,
    ) -> dict[str, Any]:
        family = _family_for_model(model)
        mode = _mode_for_model(model)
        arguments: dict[str, Any] = {"prompt": request.prompt}

        if request.duration_seconds is not None:
            arguments["duration"] = _duration_value(
                family, request.duration_seconds)

        arguments.update(_aspect_or_resolution_payload(family, mode, request))

        reference_image = request.reference_image
        image_url_field = _image_url_field(family, mode)
        if mode in {"image-to-video", "reference-to-video"} and reference_image is None:
            raise ProviderUpstreamError(
                f"Fal {mode} model requires a reference image"
            )

        if reference_image is None:
            return arguments

        if reference_image.byte_size > self.reference_image_max_bytes:
            self.logger.info(
                log_kv(
                    "fal_video_reference_image_omitted",
                    chat_id=request.chat_id,
                    user_id=request.user_id,
                    byte_size=reference_image.byte_size,
                    max_bytes=self.reference_image_max_bytes,
                )
            )
            return arguments

        if image_url_field is None:
            self.logger.info(
                log_kv(
                    "fal_video_reference_image_ignored",
                    chat_id=request.chat_id,
                    user_id=request.user_id,
                    reason="selected_text_to_video_model",
                )
            )
            return arguments

        data_uri = _reference_image_data_uri(reference_image)
        if image_url_field == "image_urls":
            arguments["image_urls"] = [data_uri]
        else:
            arguments[image_url_field] = data_uri
        return arguments

    async def _download_video(
        self,
        video_url: str,
        *,
        mime_type: str | None,
        file_size: int | None,
    ) -> tuple[bytes, str, int]:
        try:
            response = await self._download_client.get(video_url)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("Fal video polling timed out") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {408, 504}:
                raise ProviderTimeoutError(
                    "Fal video polling timed out") from exc
            body = _response_text(exc.response)
            self.logger.warning(
                log_kv(
                    "fal_video_http_error",
                    operation="download",
                    url=video_url,
                    status_code=exc.response.status_code,
                    response_body=body,
                )
            )
            raise ProviderUpstreamError(
                f"Fal video polling failed (HTTP {exc.response.status_code}): {
                    body}"
            ) from exc
        except httpx.HTTPError as exc:
            self.logger.warning(
                log_kv(
                    "fal_video_http_error",
                    operation="download",
                    url=video_url,
                    error=str(exc),
                )
            )
            raise ProviderUpstreamError("Fal video polling failed") from exc

        video_bytes = response.content
        resolved_mime_type = mime_type or response.headers.get(
            "content-type") or "video/mp4"
        resolved_file_size = file_size or len(video_bytes)
        return video_bytes, str(resolved_mime_type), resolved_file_size


def _reference_image_data_uri(image: ImageInput) -> str:
    try:
        image_bytes = base64.b64decode(image.bytes_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProviderUpstreamError(
            "Reference image payload is invalid") from exc
    if not image_bytes:
        raise ProviderUpstreamError("Reference image payload is empty")
    return f"data:{image.mime_type};base64,{image.bytes_b64}"


def _family_for_model(model: str) -> FalFamily:
    lower = model.lower()
    if "kling" in lower:
        return "kling"
    if "seedance" in lower:
        return "seedance"
    if "gemini" in lower or "google" in lower:
        return "gemini"
    return "other"


def _mode_for_model(model: str) -> FalMode:
    lower = model.lower()
    if lower.endswith("/text-to-video") or lower.endswith("/text-to-video/"):
        return "text-to-video"
    if lower.endswith("/image-to-video") or lower.endswith("/image-to-video/"):
        return "image-to-video"
    if lower.endswith("/reference-to-video") or lower.endswith("/reference-to-video/"):
        return "reference-to-video"
    if lower.endswith("/edit") or lower.endswith("/edit/"):
        return "edit"
    return "text-to-video"


def _image_url_field(family: FalFamily, mode: FalMode) -> str | None:
    if mode == "edit":
        return "video_url"
    if mode == "reference-to-video":
        return "image_urls"
    if mode == "image-to-video":
        return "start_image_url" if family == "kling" else "image_url"
    return None


def _duration_value(family: FalFamily, duration_seconds: int) -> int | str:
    return duration_seconds if family == "gemini" else str(duration_seconds)


def _aspect_or_resolution_payload(
    family: FalFamily,
    mode: FalMode,
    request: VideoGenerationRequest,
) -> dict[str, Any]:
    if family == "seedance":
        payload: dict[str, Any] = {"resolution": request.resolution or "720p"}
        if request.aspect_ratio is not None:
            payload["aspect_ratio"] = request.aspect_ratio
        return payload
    if family == "kling":
        if mode in {"text-to-video", "reference-to-video"} and request.aspect_ratio:
            return {"aspect_ratio": request.aspect_ratio}
    if family == "gemini":
        aspect_ratio = request.aspect_ratio
        if aspect_ratio not in {"16:9", "9:16"}:
            aspect_ratio = "9:16"
        return {"aspect_ratio": aspect_ratio}
    return {}


async def _maybe_close(resource: object) -> None:
    close = getattr(resource, "aclose", None)
    if callable(close):
        result = close()
        if inspect.isawaitable(result):
            await result
        return
    close = getattr(resource, "close", None)
    if callable(close):
        result = close()
        if inspect.isawaitable(result):
            await result


def _response_text(response: httpx.Response) -> str:
    try:
        return response.text[:500]
    except Exception:
        return "<unable to read body>"


def _queue_status_name(status: object) -> str:
    class_name = type(status).__name__.lower()
    if class_name.endswith("queued"):
        return "queued"
    if class_name.endswith("inprogress"):
        return "in_progress"
    if class_name.endswith("completed"):
        return "completed"

    raw_status = str(getattr(status, "status", "") or "").strip().upper()
    if raw_status == "IN_QUEUE":
        return "queued"
    if raw_status == "IN_PROGRESS":
        return "in_progress"
    if raw_status == "COMPLETED":
        return "completed"
    return raw_status.lower()


def _queue_status_label(status: object) -> str:
    raw_status = str(getattr(status, "status", "") or "").strip().upper()
    return raw_status or type(status).__name__ or "unknown"


def _first_string(source: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
