from __future__ import annotations

from datetime import datetime

import aiosqlite

from app.domain.models import PreferenceType, UserPreference
from app.storage.db import Database


def _iso(value: datetime) -> str:
    return value.isoformat()


def _row_to_preference(row: aiosqlite.Row) -> UserPreference:
    return UserPreference(
        chat_id=row["chat_id"],
        user_id=row["user_id"],
        preference_type=row["preference_type"],
        preset_id=row["preset_id"],
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class PreferenceRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get_preference(
        self,
        *,
        chat_id: int,
        user_id: int,
        preference_type: PreferenceType,
    ) -> UserPreference | None:
        cursor = await self.database.connection.execute(
            """
            SELECT chat_id, user_id, preference_type, preset_id, updated_at
            FROM user_preferences
            WHERE chat_id = ?
              AND user_id = ?
              AND preference_type = ?
            LIMIT 1
            """,
            (chat_id, user_id, preference_type),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return _row_to_preference(row)

    async def list_for_user(
        self,
        *,
        chat_id: int,
        user_id: int,
    ) -> dict[PreferenceType, UserPreference]:
        cursor = await self.database.connection.execute(
            """
            SELECT chat_id, user_id, preference_type, preset_id, updated_at
            FROM user_preferences
            WHERE chat_id = ?
              AND user_id = ?
            """,
            (chat_id, user_id),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return {
            preference.preference_type: preference
            for preference in (_row_to_preference(row) for row in rows)
        }

    async def set_preference(
        self,
        *,
        chat_id: int,
        user_id: int,
        preference_type: PreferenceType,
        preset_id: str,
        updated_at: datetime,
    ) -> None:
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO user_preferences (
                    chat_id,
                    user_id,
                    preference_type,
                    preset_id,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, user_id, preference_type)
                DO UPDATE SET
                    preset_id = excluded.preset_id,
                    updated_at = excluded.updated_at
                """,
                (chat_id, user_id, preference_type, preset_id, _iso(updated_at)),
            )
