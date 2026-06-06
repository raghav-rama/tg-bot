from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

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


class RunpodVideoProvider:
    def __init__(
        self,
        *,
        api_key: str,
        endpoint_id: str,
        base_url: str,
        default_model: str,
        default_width: int,
        default_height: int,
        default_duration_seconds: int | None,
        default_frame_rate: float,
        execution_timeout_ms: int,
        ttl_ms: int,
        reference_image_max_bytes: int,
        signed_url_ttl_seconds: int,
        signed_url_resolver: Callable[[str], str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.logger = logging.getLogger("app.providers.runpod_video_provider")
        self.api_key = api_key
        self.endpoint_id = endpoint_id
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.default_width = default_width
        self.default_height = default_height
        self.default_duration_seconds = default_duration_seconds
        self.default_frame_rate = default_frame_rate
        self.execution_timeout_ms = execution_timeout_ms
        self.ttl_ms = ttl_ms
        self.reference_image_max_bytes = reference_image_max_bytes
        self.signed_url_ttl_seconds = signed_url_ttl_seconds
        self._signed_url_resolver = signed_url_resolver or self._generate_gcs_signed_url
        self._client = client or httpx.AsyncClient(timeout=None)

    async def close(self) -> None:
        await self._client.aclose()

    async def submit_video(
        self,
        request: VideoGenerationRequest,
    ) -> SubmittedVideoJob:
        model = request.model or self.default_model
        duration_seconds = (
            request.duration_seconds
            if request.duration_seconds is not None
            else self.default_duration_seconds
        )
        width = request.width if request.width is not None else self.default_width
        height = request.height if request.height is not None else self.default_height
        frame_rate = (
            request.frame_rate
            if request.frame_rate is not None
            else self.default_frame_rate
        )
        input_payload: dict[str, Any] = {
            "prompt": request.prompt,
            "model": model,
            "width": width,
            "height": height,
            "num_frames": self._num_frames_for_duration(
                duration_seconds,
                frame_rate,
            ),
            "frame_rate": frame_rate,
        }
        if request.pipeline is not None:
            input_payload["pipeline"] = request.pipeline
        if request.pipeline == "two_stage" and request.num_inference_steps is not None:
            input_payload["num_inference_steps"] = request.num_inference_steps
        if request.seed is not None:
            input_payload["seed"] = request.seed
        if request.reference_image is not None:
            if request.reference_image.byte_size <= self.reference_image_max_bytes:
                input_payload["image_base64"] = (
                    f"data:{request.reference_image.mime_type};base64,"
                    f"{request.reference_image.bytes_b64}"
                )
                if request.image_strength is not None:
                    input_payload["image_strength"] = request.image_strength
            else:
                self.logger.info(
                    log_kv(
                        "runpod_video_reference_image_omitted",
                        chat_id=request.chat_id,
                        user_id=request.user_id,
                        byte_size=request.reference_image.byte_size,
                        max_bytes=self.reference_image_max_bytes,
                    )
                )

        payload = {
            "input": input_payload,
            "policy": {
                "executionTimeout": self.execution_timeout_ms,
                "ttl": self.ttl_ms,
            },
        }
        self.logger.info(
            log_kv(
                "runpod_video_submit_started",
                chat_id=request.chat_id,
                user_id=request.user_id,
                endpoint_id=self.endpoint_id,
                model=model,
                width=width,
                height=height,
                duration_seconds=duration_seconds,
                frame_rate=frame_rate,
                reference_image=bool(request.reference_image),
                prompt_chars=len(request.prompt),
            )
        )

        response = await self._request(
            "POST",
            f"{self._endpoint_url()}/run",
            json=payload,
            runpod_auth=True,
        )
        body = self._json_body(response)
        job_id = body.get("id") or body.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise ProviderUpstreamError("Runpod video generation returned no job id")

        self.logger.info(
            log_kv(
                "runpod_video_submit_succeeded",
                chat_id=request.chat_id,
                user_id=request.user_id,
                endpoint_id=self.endpoint_id,
                model=model,
                operation_name=job_id,
            )
        )
        return SubmittedVideoJob(
            operation_name=job_id,
            provider="runpod",
            raw_model=model,
        )

    async def poll_video(
        self,
        request: VideoGenerationPollRequest,
    ) -> VideoJobPollResult:
        response = await self._request(
            "GET",
            f"{self._endpoint_url()}/status/{request.operation_name}",
            runpod_auth=True,
        )
        body = self._json_body(response)
        status = str(body.get("status") or "").upper()

        if status in {"IN_QUEUE", "IN_PROGRESS", "RUNNING"}:
            return VideoJobPollResult(
                status="running",
                operation_name=request.operation_name,
            )

        if status in {"FAILED", "TIMED_OUT", "CANCELLED"}:
            failure_reason = self._failure_reason(body, status)
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason=failure_reason,
            )

        if status != "COMPLETED":
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason=f"Runpod video generation returned unknown status: {status}",
            )

        output = body.get("output")
        if not isinstance(output, dict):
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason="Runpod video generation returned malformed output",
            )
        try:
            asset = await self._asset_download_target(output)
        except ProviderUpstreamError as exc:
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason=str(exc),
            )
        if asset is None:
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason="Runpod video generation returned no accessible video URL or GCS URI",
            )

        download_url, output_uri = asset
        video_response = await self._request("GET", download_url, runpod_auth=False)
        video_bytes = video_response.content
        if not video_bytes:
            return VideoJobPollResult(
                status="failed",
                operation_name=request.operation_name,
                failure_reason="Runpod video generation returned an empty video asset",
            )

        mime_type = (
            output.get("mime_type")
            or video_response.headers.get("content-type")
            or "video/mp4"
        )
        file_size = (
            self._optional_int(output.get("file_size"))
            or self._optional_int(output.get("size_bytes"))
            or len(video_bytes)
        )

        return VideoJobPollResult(
            status="completed",
            operation_name=request.operation_name,
            generated_video=GeneratedVideoResult(
                video_bytes=video_bytes,
                mime_type=str(mime_type),
                provider="runpod",
                raw_model=request.model or self.default_model,
                prompt=request.prompt,
                output_uri=output_uri,
                duration_seconds=(
                    self._optional_int(output.get("duration_seconds"))
                    or self.default_duration_seconds
                ),
                width=self._optional_int(output.get("width")) or self.default_width,
                height=self._optional_int(output.get("height")) or self.default_height,
                file_size=file_size,
            ),
        )

    async def _asset_download_target(
        self,
        output: dict[str, Any],
    ) -> tuple[str, str] | None:
        direct_url = self._first_string(
            output,
            "video_url",
            "url",
            "output_url",
            "signed_url",
        )
        if direct_url:
            return await self._download_target_from_uri(direct_url)

        s3 = output.get("s3")
        if isinstance(s3, dict):
            gcs_uri = self._gcs_uri_from_s3_metadata(s3)
            if gcs_uri:
                return await self._download_target_from_uri(gcs_uri)

            s3_url = self._first_string(
                s3,
                "url",
                "video_url",
                "output_url",
                "signed_url",
            )
            if s3_url:
                return await self._download_target_from_uri(s3_url)

        gcs_uri = self._first_string(
            output,
            "gcs_uri",
            "gcs_url",
            "output_uri",
            "uri",
        )
        if gcs_uri and gcs_uri.startswith("gs://"):
            return await self._download_target_from_uri(gcs_uri)

        return None

    async def _download_target_from_uri(self, uri: str) -> tuple[str, str]:
        if not uri.startswith("gs://"):
            return uri, uri

        try:
            signed_url = await asyncio.to_thread(self._signed_url_resolver, uri)
        except Exception as exc:
            raise ProviderUpstreamError(
                "Runpod video generation returned a GCS asset but the bot could not sign it"
            ) from exc
        if not signed_url:
            raise ProviderUpstreamError(
                "Runpod video generation returned a GCS asset but signing returned no URL"
            )
        return signed_url, uri

    async def _request(
        self,
        method: str,
        url: str,
        *,
        runpod_auth: bool,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.api_key}"} if runpod_auth else None
        try:
            response = await self._client.request(method, url, json=json, headers=headers)
            response.raise_for_status()
            return response
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("Runpod video generation timed out") from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {408, 504}:
                raise ProviderTimeoutError("Runpod video generation timed out") from exc
            raise ProviderUpstreamError("Runpod video generation failed") from exc
        except httpx.HTTPError as exc:
            raise ProviderUpstreamError("Runpod video generation failed") from exc

    def _endpoint_url(self) -> str:
        return f"{self.base_url}/{self.endpoint_id}"

    def _generate_gcs_signed_url(self, uri: str) -> str:
        try:
            from google.cloud import storage
            from google.cloud.storage.blob import Blob
        except ImportError as exc:
            raise RuntimeError(
                "google-cloud-storage must be installed to sign Runpod GCS video assets"
            ) from exc

        client = storage.Client()
        blob = Blob.from_uri(uri, client=client)
        return str(
            blob.generate_signed_url(
                expiration=timedelta(seconds=self.signed_url_ttl_seconds),
                method="GET",
                version="v4",
            )
        )

    @staticmethod
    def _json_body(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderUpstreamError("Runpod video generation returned invalid JSON") from exc
        if not isinstance(body, dict):
            raise ProviderUpstreamError("Runpod video generation returned invalid JSON")
        return body

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _first_string(source: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @classmethod
    def _is_gcs_s3_metadata(cls, source: dict[str, Any]) -> bool:
        endpoint = cls._first_string(source, "endpoint_url", "endpointUrl", "endpoint")
        if endpoint is None:
            return False
        parsed = urlparse(endpoint if "://" in endpoint else f"https://{endpoint}")
        hostname = (parsed.hostname or "").lower()
        return hostname == "storage.googleapis.com" or hostname.endswith(
            ".storage.googleapis.com"
        )

    @classmethod
    def _gcs_uri_from_s3_metadata(cls, source: dict[str, Any]) -> str | None:
        if not cls._is_gcs_s3_metadata(source):
            return None
        bucket = cls._first_string(source, "bucket", "bucketName", "bucket_name")
        key = cls._first_string(source, "key", "object", "object_name")
        if not bucket or not key:
            return None
        return f"gs://{bucket.strip('/')}/{key.lstrip('/')}"

    @staticmethod
    def _num_frames_for_duration(
        duration_seconds: int | None,
        frame_rate: float,
    ) -> int:
        if duration_seconds is None:
            return 121
        requested_frames = max(1, math.ceil(duration_seconds * frame_rate))
        if requested_frames <= 1:
            return 1
        return ((requested_frames - 1 + 7) // 8) * 8 + 1

    @staticmethod
    def _failure_reason(body: dict[str, Any], status: str) -> str:
        for key in ("error", "errorMessage", "message"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
        return f"Runpod video generation failed with status {status}"
