from __future__ import annotations

from typing import Protocol

from app.domain.models import ProviderRequest, ProviderResponse


class AIProvider(Protocol):
    async def generate_response(self, request: ProviderRequest) -> ProviderResponse:
        """Generate a normalized assistant response."""

    async def close(self) -> None:
        """Release provider resources."""

