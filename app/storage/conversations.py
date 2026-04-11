from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from app.domain.models import ConversationRecord
from app.storage.db import Database


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _row_to_conversation(row: aiosqlite.Row) -> ConversationRecord:
    return ConversationRecord(
        id=row["id"],
        chat_id=row["chat_id"],
        started_at=datetime.fromisoformat(row["started_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        archived_at=_parse_datetime(row["archived_at"]),
        is_active=bool(row["is_active"]),
    )


class ConversationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get_active(self, chat_id: int) -> ConversationRecord | None:
        cursor = await self.database.connection.execute(
            """
            SELECT id, chat_id, started_at, updated_at, archived_at, is_active
            FROM conversations
            WHERE chat_id = ? AND is_active = 1
            LIMIT 1
            """,
            (chat_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return _row_to_conversation(row)

    async def get_or_create_active(self, chat_id: int) -> ConversationRecord:
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT id, chat_id, started_at, updated_at, archived_at, is_active
                FROM conversations
                WHERE chat_id = ? AND is_active = 1
                LIMIT 1
                """,
                (chat_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is not None:
                return _row_to_conversation(row)

            now = _utcnow()
            insert = await connection.execute(
                """
                INSERT INTO conversations (chat_id, started_at, updated_at, archived_at, is_active)
                VALUES (?, ?, ?, NULL, 1)
                """,
                (chat_id, _iso(now), _iso(now)),
            )
            return ConversationRecord(
                id=insert.lastrowid,
                chat_id=chat_id,
                started_at=now,
                updated_at=now,
                archived_at=None,
                is_active=True,
            )

    async def reset_active(self, chat_id: int) -> ConversationRecord:
        async with self.database.transaction() as connection:
            now = _utcnow()
            await connection.execute(
                """
                UPDATE conversations
                SET is_active = 0, archived_at = ?, updated_at = ?
                WHERE chat_id = ? AND is_active = 1
                """,
                (_iso(now), _iso(now), chat_id),
            )

            insert = await connection.execute(
                """
                INSERT INTO conversations (chat_id, started_at, updated_at, archived_at, is_active)
                VALUES (?, ?, ?, NULL, 1)
                """,
                (chat_id, _iso(now), _iso(now)),
            )

            return ConversationRecord(
                id=insert.lastrowid,
                chat_id=chat_id,
                started_at=now,
                updated_at=now,
                archived_at=None,
                is_active=True,
            )

    async def touch(self, conversation_id: int) -> None:
        now = _iso(_utcnow())
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                UPDATE conversations
                SET updated_at = ?
                WHERE id = ?
                """,
                (now, conversation_id),
            )

