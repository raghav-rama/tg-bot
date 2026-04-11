from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.types import Message, Update

from app.config import Settings
from app.domain.services import ChatService
from app.logging import log_kv
from app.telegram.drafts import TelegramResponseEmitter
from app.telegram.media import download_largest_photo_bytes
from app.telegram.normalizer import normalize_message


class TelegramUpdateProcessor:
    def __init__(self, *, chat_service: ChatService, settings: Settings) -> None:
        self.chat_service = chat_service
        self.settings = settings
        self.logger = logging.getLogger("app.telegram.handlers")

    async def process_message(
        self,
        *,
        message: Message,
        bot: Bot,
        update_id: int,
    ) -> None:
        if message.from_user is None or message.chat is None:
            self.logger.warning("ignored_message_without_required_ids")
            return

        try:
            image_bytes = None
            if message.photo:
                image_bytes = await download_largest_photo_bytes(bot, message)

            inbound = normalize_message(
                message=message,
                update_id=update_id,
                image_bytes=image_bytes,
                image_max_bytes=self.settings.bot_image_max_bytes,
            )
        except Exception as exc:
            reply = await self.chat_service.handle_normalization_error(
                update_id=update_id,
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                telegram_message_id=message.message_id,
                error=exc,
            )
            await bot.send_message(chat_id=message.chat.id, text=reply.text)
            return

        responder = TelegramResponseEmitter(bot=bot, chat_id=message.chat.id)
        reply = await self.chat_service.handle_inbound(inbound, responder=responder)

        if reply.delivered:
            self.logger.info(
                log_kv(
                    "telegram_reply_sent",
                    update_id=update_id,
                    chat_id=message.chat.id,
                    user_id=message.from_user.id,
                )
            )


def build_router(processor: TelegramUpdateProcessor) -> Router:
    router = Router()

    @router.message()
    async def on_message(
        message: Message,
        bot: Bot,
        event_update: Update,
    ) -> None:
        await processor.process_message(
            message=message,
            bot=bot,
            update_id=event_update.update_id,
        )

    return router
