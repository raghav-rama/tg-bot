from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from app.domain.models import (
    GeneratedImageResult,
    GeneratedVideoResult,
    ImageGenerationRequest,
    ProviderRequest,
    ProviderResponse,
    SubmittedVideoJob,
    StreamingProviderEvent,
    VideoGenerationPollRequest,
    VideoGenerationRequest,
    VideoJobPollResult,
)


class AIProvider(Protocol):
    async def stream_response(
        self,
        request: ProviderRequest,
    ) -> AsyncIterator[StreamingProviderEvent]:
        """Stream normalized assistant response events."""

    async def generate_response(self, request: ProviderRequest) -> ProviderResponse:
        """Generate a normalized assistant response."""

    async def close(self) -> None:
        """Release provider resources."""


class ImageGenerator(Protocol):
    async def generate_image(
        self,
        request: ImageGenerationRequest,
    ) -> GeneratedImageResult:
        """Generate a normalized image result."""

    async def close(self) -> None:
        """Release provider resources."""


class VideoGenerator(Protocol):
    async def submit_video(
        self,
        request: VideoGenerationRequest,
    ) -> SubmittedVideoJob:
        """Submit a normalized long-running video generation job."""

    async def poll_video(
        self,
        request: VideoGenerationPollRequest,
    ) -> VideoJobPollResult:
        """Poll a previously submitted video generation job."""

    async def close(self) -> None:
        """Release provider resources."""
