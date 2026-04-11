from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest_asyncio

from app.config import Settings
from app.domain.models import ProviderResponse
from app.domain.services import ChatService
from app.storage.conversations import ConversationRepository
from app.storage.db import Database
from app.storage.messages import MessageRepository


class FakeProvider:
    def __init__(self, reply_text: str = "assistant reply") -> None:
        self.reply_text = reply_text
        self.calls = []

    async def generate_response(self, request):
        self.calls.append(request)
        return ProviderResponse(
            reply_text=self.reply_text,
            provider_message_id="resp_test",
            input_tokens=10,
            output_tokens=20,
            finish_reason="completed",
            raw_model=request.model,
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

