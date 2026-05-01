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
        self._webhook_configured = False
        self._webhook_url: str | None = None

    @property
    def last_error(self) -> Exception | None:
        return self._last_error

    @property
    def started(self) -> bool:
        return self._started

    @property
    def webhook_configured(self) -> bool:
        return self._webhook_configured

    @property
    def webhook_url(self) -> str | None:
        return self._webhook_url

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_polling(), name="telegram-polling")
        self._started = True
        await asyncio.sleep(0)

    async def configure_webhook(
        self,
        *,
        url: str,
        secret_token: str,
        drop_pending_updates: bool = False,
    ) -> None:
        try:
            await self.bot.set_webhook(
                url=url,
                secret_token=secret_token,
                drop_pending_updates=drop_pending_updates,
            )
            webhook_info = await self.bot.get_webhook_info()
            if webhook_info.url != url:
                raise RuntimeError(
                    "Telegram webhook configuration did not match the requested URL"
                )
        except Exception as exc:
            self._last_error = exc
            self._webhook_configured = False
            self._webhook_url = None
            self.logger.exception(
                log_kv(
                    "webhook_configuration_failed",
                    error_type=type(exc).__name__,
                    webhook_url=url,
                )
            )
            raise

        self._last_error = None
        self._webhook_configured = True
        self._webhook_url = webhook_info.url
        self.logger.info(
            log_kv(
                "webhook_configured",
                webhook_url=webhook_info.url,
                pending_update_count=webhook_info.pending_update_count,
            )
        )

    async def delete_webhook(self, *, drop_pending_updates: bool = False) -> None:
        try:
            await self.bot.delete_webhook(
                drop_pending_updates=drop_pending_updates,
            )
        except Exception as exc:
            self._last_error = exc
            self.logger.exception(
                log_kv(
                    "webhook_delete_failed",
                    error_type=type(exc).__name__,
                    drop_pending_updates=drop_pending_updates,
                )
            )
            raise

        self._last_error = None
        self._webhook_configured = False
        self._webhook_url = None

    async def _run_polling(self) -> None:
        try:
            await self.delete_webhook(drop_pending_updates=False)
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
