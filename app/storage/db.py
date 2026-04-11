from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from app.domain.errors import StorageError

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY,
        chat_id INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        archived_at TEXT NULL,
        is_active INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_active_chat
    ON conversations(chat_id)
    WHERE is_active = 1
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY,
        conversation_id INTEGER NOT NULL,
        telegram_message_id INTEGER NULL,
        provider_message_id TEXT NULL,
        role TEXT NOT NULL,
        message_type TEXT NOT NULL,
        text TEXT NULL,
        image_file_unique_id TEXT NULL,
        image_mime_type TEXT NULL,
        image_width INTEGER NULL,
        image_height INTEGER NULL,
        image_byte_size INTEGER NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (conversation_id) REFERENCES conversations (id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
    ON messages(conversation_id, created_at)
    """,
)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._connection: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise StorageError("database connection is not initialized")
        return self._connection

    async def connect(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = await aiosqlite.connect(self.path)
            self._connection.row_factory = aiosqlite.Row
            await self._connection.execute("PRAGMA foreign_keys = ON")
            await self._connection.execute("PRAGMA journal_mode = WAL")
            await self._connection.commit()
        except aiosqlite.Error as exc:
            raise StorageError("failed to connect to SQLite") from exc

    async def initialize(self) -> None:
        connection = self.connection
        try:
            for statement in SCHEMA_STATEMENTS:
                await connection.execute(statement)
            await connection.commit()
        except aiosqlite.Error as exc:
            raise StorageError("failed to initialize SQLite schema") from exc

    async def close(self) -> None:
        if self._connection is None:
            return
        await self._connection.close()
        self._connection = None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        connection = self.connection
        async with self._write_lock:
            try:
                await connection.execute("BEGIN IMMEDIATE")
                yield connection
            except aiosqlite.Error as exc:
                await connection.rollback()
                raise StorageError("SQLite transaction failed") from exc
            except Exception:
                await connection.rollback()
                raise
            else:
                await connection.commit()

