from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from app.domain.models import ConversationTurn, ImageInput, StoredMessage
from app.storage.db import Database


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _placeholder_for_image() -> str:
    return "[User sent an image]"


class MessageRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def add_user_message(
        self,
        *,
        conversation_id: int,
        telegram_message_id: int | None,
        message_type: str,
        text: str | None,
        image: ImageInput | None,
        created_at: datetime,
    ) -> int:
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO messages (
                    conversation_id,
                    telegram_message_id,
                    provider_message_id,
                    role,
                    message_type,
                    text,
                    image_file_unique_id,
                    image_mime_type,
                    image_width,
                    image_height,
                    image_byte_size,
                    created_at
                )
                VALUES (?, ?, NULL, 'user', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    telegram_message_id,
                    message_type,
                    text,
                    image.telegram_file_unique_id if image else None,
                    image.mime_type if image else None,
                    image.width if image else None,
                    image.height if image else None,
                    image.byte_size if image else None,
                    _iso(created_at),
                ),
            )
            return cursor.lastrowid

    async def add_assistant_message(
        self,
        *,
        conversation_id: int,
        provider_message_id: str | None,
        text: str,
        message_type: str = "text",
        created_at: datetime | None = None,
    ) -> int:
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO messages (
                    conversation_id,
                    telegram_message_id,
                    provider_message_id,
                    role,
                    message_type,
                    text,
                    image_file_unique_id,
                    image_mime_type,
                    image_width,
                    image_height,
                    image_byte_size,
                    created_at
                )
                VALUES (?, NULL, ?, 'assistant', ?, ?, NULL, NULL, NULL, NULL, NULL, ?)
                """,
                (
                    conversation_id,
                    provider_message_id,
                    message_type,
                    text,
                    _iso(created_at or _utcnow()),
                ),
            )
            return cursor.lastrowid

    async def list_recent_history(
        self,
        *,
        conversation_id: int,
        limit: int,
    ) -> list[ConversationTurn]:
        cursor = await self.database.connection.execute(
            """
            SELECT role, message_type, text, created_at
            FROM messages
            WHERE conversation_id = ?
              AND role IN ('user', 'assistant')
              AND message_type != 'command'
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()

        history: list[ConversationTurn] = []
        for row in reversed(rows):
            text = row["text"]
            if row["message_type"] == "image" and not text:
                text = _placeholder_for_image()
            if not text:
                continue
            history.append(
                ConversationTurn(
                    role=row["role"],
                    text=text,
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return history

    async def list_for_conversation(self, conversation_id: int) -> list[StoredMessage]:
        cursor = await self.database.connection.execute(
            """
            SELECT
                id,
                conversation_id,
                telegram_message_id,
                provider_message_id,
                role,
                message_type,
                text,
                image_file_unique_id,
                image_mime_type,
                image_width,
                image_height,
                image_byte_size,
                created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (conversation_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            StoredMessage(
                id=row["id"],
                conversation_id=row["conversation_id"],
                telegram_message_id=row["telegram_message_id"],
                provider_message_id=row["provider_message_id"],
                role=row["role"],
                message_type=row["message_type"],
                text=row["text"],
                image_file_unique_id=row["image_file_unique_id"],
                image_mime_type=row["image_mime_type"],
                image_width=row["image_width"],
                image_height=row["image_height"],
                image_byte_size=row["image_byte_size"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]
