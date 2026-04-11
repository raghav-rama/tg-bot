from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest_asyncio

from app.config import Settings
from app.domain.models import ProviderResponse, StreamingProviderEvent
from app.domain.services import ChatService
from app.storage.conversations import ConversationRepository
from app.storage.db import Database
from app.storage.messages import MessageRepository


class FakeProvider:
    def __init__(self, reply_text: str = "assistant reply") -> None:
        self.reply_text = reply_text
        self.calls = []
        self.events: list[StreamingProviderEvent] | None = None
        self.error: Exception | None = None
        self.wait_before_stream: asyncio.Event | None = None

    async def stream_response(self, request):
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        if self.wait_before_stream is not None:
            await self.wait_before_stream.wait()

        events = self.events or [
            StreamingProviderEvent(type="delta", text=self.reply_text),
            StreamingProviderEvent(
                type="completed",
                provider_message_id="resp_test",
                input_tokens=10,
                output_tokens=20,
                finish_reason="completed",
                raw_model=request.model,
            ),
        ]
        for event in events:
            yield event

    async def generate_response(self, request):
        reply_parts: list[str] = []
        completed_event: StreamingProviderEvent | None = None

        async for event in self.stream_response(request):
            if event.type == "delta" and event.text:
                reply_parts.append(event.text)
            elif event.type == "completed":
                completed_event = event

        return ProviderResponse(
            reply_text="".join(reply_parts),
            provider_message_id=(
                completed_event.provider_message_id if completed_event else "resp_test"
            ),
            input_tokens=completed_event.input_tokens if completed_event else 10,
            output_tokens=completed_event.output_tokens if completed_event else 20,
            finish_reason=(
                completed_event.finish_reason if completed_event else "completed"
            ),
            raw_model=completed_event.raw_model if completed_event else request.model,
        )

    async def close(self) -> None:
        return None


def build_settings(database_path: Path, **overrides) -> Settings:
    values = {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "OPENAI_API_KEY": "test-key",
        "TELEGRAM_ALLOWED_USER_IDS": "42",
        "APP_UPDATE_MODE": "webhook",
        "SQLITE_PATH": str(database_path),
        "OPENAI_MODEL": "gpt-4.1-mini",
        "BOT_ENABLE_MESSAGE_DRAFTS": "true",
        "BOT_DRAFT_STREAM_ON_IMAGES": "false",
        "BOT_DRAFT_START_DELAY_MS": "750",
        "BOT_DRAFT_UPDATE_INTERVAL_MS": "350",
        "BOT_DRAFT_MIN_CHARS_DELTA": "30",
    }
    values.update(overrides)
    return Settings(**values)


@pytest_asyncio.fixture
async def service_bundle(tmp_path):
    settings = build_settings(tmp_path / "bot.db")
    database = Database(settings.sqlite_path)
    await database.connect()
    await database.initialize()

    conversations = ConversationRepository(database)
    messages = MessageRepository(database)
    provider = FakeProvider()
    service = ChatService(
        settings=settings,
        conversations=conversations,
        messages=messages,
        provider=provider,
    )

    yield {
        "settings": settings,
        "database": database,
        "conversations": conversations,
        "messages": messages,
        "provider": provider,
        "service": service,
    }

    await database.close()


def utc_datetime() -> datetime:
    return datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc)
