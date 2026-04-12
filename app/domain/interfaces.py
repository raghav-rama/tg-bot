from __future__ import annotations

from typing import Protocol

from app.domain.models import GeneratedImageResult, GeneratedVideoResult, SentPhoto, SentVideo


class DraftSession(Protocol):
    draft_id: int

    async def update(self, text: str) -> None:
        """Send or refresh a partial draft."""

    async def finish(self) -> None:
        """Finish the draft lifecycle after the final reply is ready."""

    async def cancel(self) -> None:
        """Cancel the draft lifecycle because the response was superseded."""


class ResponseEmitter(Protocol):
    async def send_text(self, text: str) -> None:
        """Deliver the final text reply."""

    async def send_photo(self, image: GeneratedImageResult) -> SentPhoto:
        """Deliver a generated photo reply."""

    async def send_video(self, video: GeneratedVideoResult) -> SentVideo:
        """Deliver a generated video reply."""

    async def open_draft(self) -> DraftSession:
        """Allocate a draft session for partial updates."""
