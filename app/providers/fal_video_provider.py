from __future__ import annotations

import logging
from typing import Any, Literal

import httpx

from app.domain.errors import ProviderTimeoutError, ProviderUpstreamError
from app.domain.models import (
    GeneratedVideoResult,
    SubmittedVideoJob,
    VideoGenerationPollRequest,
    VideoGenerationRequest,
    VideoJobPollResult,
)
from app.logging import log_kv

FalMode = Literal["text-to-video", "image-to-video", "reference-to-video", "edit"]
FalFamily = Literal["kling", "seedance", "gemini", "other"]


class FalVideoProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://queue.fal.run",
        default_model: str,
        image_to_video_model: str | None,
        reference_image_max_bytes: int,
        reference_to_video_model: str | None = None,
        edit_model: str | None = None,
        submit_timeout: httpx.Timeout | None = None,
        submit_timeout_seconds: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.logger = logging.getLogger("app.providers.fal_video_provider")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.image_to_video_model = image_to_video_model
        self.reference_to_video_model = reference_to_video_model
        self.edit_model = edit_model
        self.reference_image_max_bytes = reference_image_max_bytes
        self._request_urls: dict[str, dict[str, str]] = {}
        if client is not None:
            self._client = client
        else:
            timeout = submit_timeout or httpx.Timeout(submit_timeout_seconds or 45)
            self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def submit_video(
        self,
        request: VideoGenerationRequest,
    ) -> SubmittedVideoJob:
        model = self._select_model_for(request)
        body = self._build_submit_body(request, model)
        url = f"{self.base_url}/{model}"
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
        response = await self._request("POST", url, json=body)
        response_body = self._json_body(response)
        request_id = response_body.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise ProviderUpstreamError(
                "Fal video generation returned no request_id"
            )
        status_url = response_body.get("status_url")
        response_url = response_body.get("response_url")
        if isinstance(status_url, str) and status_url:
            self._request_urls[request_id] = {
                "status_url": status_url,
                "response_url": response_url if isinstance(response_url, str) else "",
            }
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

    def _build_submit_body(
        self,
        request: VideoGenerationRequest,
        model: str,
    ) -> dict[str, Any]:
        family = _family_for_model(model)
        mode = _mode_for_model(model)
        body: dict[str, Any] = {"prompt": request.prompt}

        if request.duration_seconds is not None:
            body["duration"] = _duration_value(family, request.duration_seconds)

        body.update(_aspect_or_resolution_payload(family, mode, request))

        reference_image = request.reference_image
        image_url_field = _image_url_field(family, mode)
        if mode in {"image-to-video", "reference-to-video"}:
            if reference_image is None:
                raise ProviderUpstreamError(
                    f"Fal {mode} model requires a reference image"
                )

        if reference_image is not None:
            data_uri = (
                f"data:{reference_image.mime_type};base64,"
                f"{reference_image.bytes_b64}"
            )
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
            elif image_url_field == "image_urls":
                body["image_urls"] = [data_uri]
            elif image_url_field is not None:
                body[image_url_field] = data_uri
            else:
                # Fal mode is text-to-video; image is ignored because no i2v/r2v
                # model was selected. Log transparently.
                self.logger.info(
                    log_kv(
                        "fal_video_reference_image_ignored",
                        chat_id=request.chat_id,
                        user_id=request.user_id,
                        reason="selected_text_to_video_model",
                    )
                )

        return body

    async def poll_video(
        self,
        request: VideoGenerationPollRequest,
    ) -> VideoJobPollResult:
        model = request.model
        urls = self._request_urls.get(request.operation_name)
        if urls is None or not urls.get("status_url"):
            self.logger.warning(
                log_kv(
                    "fal_video_poll_urls_missing",
                    operation_name=request.operation_name,
                    model=model,
                )
            )
        status_url = (urls or {}).get("status_url") or (
            f"{self.base_url}/{model}/requests/{request.operation_name}/status"
        )
        response_url = (urls or {}).get("response_url") or (
            f"{self.base_url}/{model}/requests/{request.operation_name}/response"
        )

        self.logger.debug(
            log_kv(
                "fal_video_poll_started",
                operation_name=request.operation_name,
                model=model,
                status_url=status_url,
                response_url=response_url,
            )
        )

        status_response = await self._request("GET", status_url)
        status_body = self._json_body(status_response)

        error = self._first_string(status_body, "error", "error_type")
        if error is not None:
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason=error,
            )

        status = str(status_body.get("status") or "").upper()
        if status in {"IN_QUEUE", "IN_PROGRESS"}:
            return VideoJobPollResult(
                status="running",
                operation_name=request.operation_name,
            )

        if status != "COMPLETED":
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason=f"Fal video generation returned unknown status: {status}",
            )

        result_response = await self._request("GET", response_url)
        result_body = self._json_body(result_response)

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

        video_response = await self._request("GET", video_url, auth=False)
        video_bytes = video_response.content
        if not video_bytes:
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason="Fal video generation returned an empty video asset",
            )

        mime_type = video.get("content_type") or video_response.headers.get(
            "content-type"
        ) or "video/mp4"
        file_size = self._optional_int(video.get("file_size")) or len(video_bytes)

        return VideoJobPollResult(
            status="completed",
            operation_name=request.operation_name,
            generated_video=GeneratedVideoResult(
                video_bytes=video_bytes,
                mime_type=str(mime_type),
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

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> httpx.Response:
        headers: dict[str, str] = {}
        if auth:
            headers["Authorization"] = f"Key {self.api_key}"
        if json is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = await self._client.request(
                method,
                url,
                json=json,
                headers=headers or None,
            )
            response.raise_for_status()
            return response
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("Fal video generation timed out") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {408, 504}:
                raise ProviderTimeoutError("Fal video generation timed out") from exc
            try:
                body = exc.response.text[:500]
            except Exception:
                body = "<unable to read body>"
            self.logger.warning(
                log_kv(
                    "fal_video_http_error",
                    method=method,
                    url=url,
                    status_code=exc.response.status_code,
                    response_body=body,
                )
            )
            raise ProviderUpstreamError(
                f"Fal video generation failed (HTTP {exc.response.status_code}): {body}"
            ) from exc
        except httpx.HTTPError as exc:
            self.logger.warning(
                log_kv(
                    "fal_video_http_error",
                    method=method,
                    url=url,
                    error=str(exc),
                )
            )
            raise ProviderUpstreamError("Fal video generation failed") from exc

    @staticmethod
    def _json_body(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderUpstreamError("Fal video generation returned invalid JSON") from exc
        if not isinstance(body, dict):
            raise ProviderUpstreamError("Fal video generation returned invalid JSON")
        return body

    @staticmethod
    def _first_string(source: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


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
    # Default for bare endpoints such as google/gemini-omni-flash
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
        # Gemini only supports a 16:9 or 9:16 aspect ratio; coerce unsupported values
        # silently rather than letting the provider reject the request.
        aspect_ratio = request.aspect_ratio
        if aspect_ratio not in {"16:9", "9:16"}:
            aspect_ratio = "9:16"
        return {"aspect_ratio": aspect_ratio}
    return {}
