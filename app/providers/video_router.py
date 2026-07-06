from __future__ import annotations

import logging
from dataclasses import replace

from app.domain.errors import ProviderSafetyError, ProviderUpstreamError
from app.domain.models import (
    SubmittedVideoJob,
    VideoGenerationPollRequest,
    VideoGenerationRequest,
    VideoJobPollResult,
)
from app.logging import log_kv
from app.providers.base import VideoGenerator


class VideoProviderRouter:
    def __init__(
        self,
        *,
        providers: dict[str, VideoGenerator],
        provider_order: tuple[str, ...],
        provider_models: dict[str, str],
    ) -> None:
        self.providers = providers
        self.provider_order = provider_order
        self.provider_models = provider_models
        self.logger = logging.getLogger("app.providers.video_router")

    async def submit_video(
        self,
        request: VideoGenerationRequest,
    ) -> SubmittedVideoJob:
        direct_hint = request.provider_hint in {"gemini", "runpod", "fal"}
        if direct_hint:
            return await self._submit_to_provider(request, request.provider_hint)

        last_safety_error: ProviderSafetyError | None = None
        for provider_name in self.provider_order:
            if provider_name not in self.providers:
                continue
            if last_safety_error is not None:
                continue
            try:
                return await self._submit_to_provider(request, provider_name)
            except ProviderSafetyError as exc:
                last_safety_error = exc
                fallback_provider = self._next_configured_provider(provider_name)
                self.logger.warning(
                    log_kv(
                        "video_provider_safety_rejection",
                        provider=provider_name,
                        fallback_provider=fallback_provider,
                        model=self.provider_models.get(provider_name),
                    )
                )
                if fallback_provider is None:
                    raise
                try:
                    return await self._submit_to_provider(request, fallback_provider)
                except Exception:
                    raise exc
        if last_safety_error is not None:
            raise last_safety_error
        raise ProviderUpstreamError("No configured video provider is available")

        if last_safety_error is not None:
            raise last_safety_error
        raise ProviderUpstreamError("No configured video provider is available")

    async def poll_video(
        self,
        request: VideoGenerationPollRequest,
    ) -> VideoJobPollResult:
        provider = self.providers.get(request.provider)
        if provider is None:
            if request.provider == "vertex":
                return VideoJobPollResult(
                    status="failed",
                    operation_name=request.operation_name,
                    failure_reason="Legacy Vertex video jobs are no longer supported after the Gemini migration",
                )
            raise ProviderUpstreamError(
                f"Video provider is not configured for persisted job: {request.provider}"
            )
        return await provider.poll_video(request)

    async def close(self) -> None:
        closed: set[int] = set()
        for provider in self.providers.values():
            provider_id = id(provider)
            if provider_id in closed:
                continue
            closed.add(provider_id)
            await provider.close()

    async def _submit_to_provider(
        self,
        request: VideoGenerationRequest,
        provider_name: str,
    ) -> SubmittedVideoJob:
        provider = self.providers.get(provider_name)
        if provider is None:
            raise ProviderUpstreamError(f"Video provider is not configured: {provider_name}")
        provider_request = replace(
            request,
            provider_hint=provider_name,
            model=(
                request.model
                if request.model_locked
                else self.provider_models.get(provider_name, request.model)
            ),
        )
        return await provider.submit_video(provider_request)

    def _next_configured_provider(self, provider_name: str) -> str | None:
        seen_current = False
        for candidate in self.provider_order:
            if candidate == provider_name:
                seen_current = True
                continue
            if seen_current and candidate in self.providers:
                return candidate
        return None
