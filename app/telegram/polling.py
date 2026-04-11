from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.logging import log_kv
from app.telegram.handlers import TelegramUpdateProcessor, build_router


class TelegramRuntime:
    def __init__(self, *, token: str, processor: TelegramUpdateProcessor) -> None:
        self.bot = Bot(token=token)
        self.dispatcher = Dispatcher()
        self.dispatcher.include_router(build_router(processor))
        self.logger = logging.getLogger("app.telegram.polling")
        self._task: asyncio.Task[None] | None = None
        self._started = False
        self._last_error: Exception | None = None

    @property
    def last_error(self) -> Exception | None:
        return self._last_error

    @property
    def started(self) -> bool:
        return self._started

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_polling(), name="telegram-polling")
        self._started = True
        await asyncio.sleep(0)

    async def _run_polling(self) -> None:
        try:
            await self.bot.delete_webhook(drop_pending_updates=False)
            await self.dispatcher.start_polling(self.bot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = exc
            self.logger.exception(
                log_kv("polling_loop_failed", error_type=type(exc).__name__)
            )
            raise

    async def feed_update(self, update) -> None:
        await self.dispatcher.feed_update(self.bot, update)

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        await self.bot.session.close()

