from __future__ import annotations

from datetime import datetime, timezone

from app.domain.models import StoredGeneratedImage
from app.storage.db import Database


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


class GeneratedImageRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def add_generated_image(
        self,
        *,
        conversation_id: int,
        prompt_text: str,
        provider: str,
        model: str,
        mime_type: str,
        telegram_message_id: int | None,
        telegram_file_id: str | None,
        telegram_file_unique_id: str | None,
        width: int | None,
        height: int | None,
        file_size: int | None,
        created_at: datetime | None = None,
    ) -> int:
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO generated_images (
                    conversation_id,
                    prompt_text,
                    provider,
                    model,
                    mime_type,
                    telegram_message_id,
                    telegram_file_id,
                    telegram_file_unique_id,
                    width,
                    height,
                    file_size,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    prompt_text,
                    provider,
                    model,
                    mime_type,
                    telegram_message_id,
                    telegram_file_id,
                    telegram_file_unique_id,
                    width,
                    height,
                    file_size,
                    _iso(created_at or _utcnow()),
                ),
            )
            return cursor.lastrowid

    async def list_for_conversation(
        self,
        conversation_id: int,
    ) -> list[StoredGeneratedImage]:
        cursor = await self.database.connection.execute(
            """
            SELECT
                id,
                conversation_id,
                prompt_text,
                provider,
                model,
                mime_type,
                telegram_message_id,
                telegram_file_id,
                telegram_file_unique_id,
                width,
                height,
                file_size,
                created_at
            FROM generated_images
            WHERE conversation_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (conversation_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            StoredGeneratedImage(
                id=row["id"],
                conversation_id=row["conversation_id"],
                prompt_text=row["prompt_text"],
                provider=row["provider"],
                model=row["model"],
                mime_type=row["mime_type"],
                telegram_message_id=row["telegram_message_id"],
                telegram_file_id=row["telegram_file_id"],
                telegram_file_unique_id=row["telegram_file_unique_id"],
                width=row["width"],
                height=row["height"],
                file_size=row["file_size"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]
