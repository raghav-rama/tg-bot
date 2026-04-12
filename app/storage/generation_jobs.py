from __future__ import annotations

from datetime import datetime, timezone

from app.domain.models import StoredGenerationJob
from app.storage.db import Database


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


class GenerationJobRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def add_video_job(
        self,
        *,
        conversation_id: int,
        chat_id: int,
        user_id: int,
        prompt_text: str,
        provider: str,
        model: str,
        operation_name: str,
        duration_seconds: int | None,
        created_at: datetime | None = None,
    ) -> int:
        now = created_at or _utcnow()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO generation_jobs (
                    conversation_id,
                    chat_id,
                    user_id,
                    job_type,
                    status,
                    prompt_text,
                    provider,
                    model,
                    operation_name,
                    duration_seconds,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, 'video', 'queued', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    chat_id,
                    user_id,
                    prompt_text,
                    provider,
                    model,
                    operation_name,
                    duration_seconds,
                    _iso(now),
                    _iso(now),
                ),
            )
            return cursor.lastrowid

    async def list_pending_video_jobs(
        self,
        *,
        limit: int = 10,
    ) -> list[StoredGenerationJob]:
        cursor = await self.database.connection.execute(
            """
            SELECT
                id,
                conversation_id,
                chat_id,
                user_id,
                job_type,
                status,
                prompt_text,
                provider,
                model,
                operation_name,
                output_uri,
                mime_type,
                telegram_message_id,
                telegram_file_id,
                telegram_file_unique_id,
                width,
                height,
                duration_seconds,
                file_size,
                failure_reason,
                created_at,
                updated_at,
                completed_at
            FROM generation_jobs
            WHERE job_type = 'video'
              AND status IN ('queued', 'running')
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [self._row_to_job(row) for row in rows]

    async def list_for_conversation(
        self,
        conversation_id: int,
    ) -> list[StoredGenerationJob]:
        cursor = await self.database.connection.execute(
            """
            SELECT
                id,
                conversation_id,
                chat_id,
                user_id,
                job_type,
                status,
                prompt_text,
                provider,
                model,
                operation_name,
                output_uri,
                mime_type,
                telegram_message_id,
                telegram_file_id,
                telegram_file_unique_id,
                width,
                height,
                duration_seconds,
                file_size,
                failure_reason,
                created_at,
                updated_at,
                completed_at
            FROM generation_jobs
            WHERE conversation_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (conversation_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [self._row_to_job(row) for row in rows]

    async def mark_running(self, job_id: int) -> None:
        now = _iso(_utcnow())
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                UPDATE generation_jobs
                SET status = 'running',
                    updated_at = ?,
                    failure_reason = NULL
                WHERE id = ?
                  AND status IN ('queued', 'running')
                """,
                (now, job_id),
            )

    async def mark_completed(
        self,
        *,
        job_id: int,
        output_uri: str | None,
        mime_type: str | None,
        telegram_message_id: int,
        telegram_file_id: str,
        telegram_file_unique_id: str,
        width: int | None,
        height: int | None,
        duration_seconds: int | None,
        file_size: int | None,
    ) -> None:
        now = _iso(_utcnow())
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                UPDATE generation_jobs
                SET status = 'completed',
                    output_uri = ?,
                    mime_type = ?,
                    telegram_message_id = ?,
                    telegram_file_id = ?,
                    telegram_file_unique_id = ?,
                    width = ?,
                    height = ?,
                    duration_seconds = COALESCE(?, duration_seconds),
                    file_size = ?,
                    failure_reason = NULL,
                    updated_at = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (
                    output_uri,
                    mime_type,
                    telegram_message_id,
                    telegram_file_id,
                    telegram_file_unique_id,
                    width,
                    height,
                    duration_seconds,
                    file_size,
                    now,
                    now,
                    job_id,
                ),
            )

    async def mark_failed(
        self,
        *,
        job_id: int,
        failure_reason: str,
    ) -> None:
        now = _iso(_utcnow())
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                UPDATE generation_jobs
                SET status = 'failed',
                    failure_reason = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (failure_reason, now, job_id),
            )

    def _row_to_job(self, row) -> StoredGenerationJob:
        return StoredGenerationJob(
            id=row["id"],
            conversation_id=row["conversation_id"],
            chat_id=row["chat_id"],
            user_id=row["user_id"],
            job_type=row["job_type"],
            status=row["status"],
            prompt_text=row["prompt_text"],
            provider=row["provider"],
            model=row["model"],
            operation_name=row["operation_name"],
            output_uri=row["output_uri"],
            mime_type=row["mime_type"],
            telegram_message_id=row["telegram_message_id"],
            telegram_file_id=row["telegram_file_id"],
            telegram_file_unique_id=row["telegram_file_unique_id"],
            width=row["width"],
            height=row["height"],
            duration_seconds=row["duration_seconds"],
            file_size=row["file_size"],
            failure_reason=row["failure_reason"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            completed_at=(
                datetime.fromisoformat(row["completed_at"])
                if row["completed_at"] is not None
                else None
            ),
        )
