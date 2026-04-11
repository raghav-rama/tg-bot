from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from app.domain.models import ProviderRequest, ProviderResponse, StreamingProviderEvent


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
