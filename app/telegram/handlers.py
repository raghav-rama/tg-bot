from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message, Update

from app.config import Settings
from app.domain.preferences import SETTINGS_UPDATED_TEXT, parse_settings_callback
from app.domain.services import ChatService
from app.logging import log_kv
from app.telegram.drafts import TelegramResponseEmitter, _settings_menu_markup
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
            reply_image_bytes = None
            if message.photo and not _is_reference_image_caption_command(message):
                image_bytes = await download_largest_photo_bytes(bot, message)

            inbound = normalize_message(
                message=message,
                update_id=update_id,
                image_bytes=image_bytes,
                reply_image_bytes=reply_image_bytes,
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

    async def process_callback(
        self,
        *,
        callback: CallbackQuery,
        update_id: int,
    ) -> None:
        callback_message = callback.message
        if callback.from_user is None or callback_message is None:
            await callback.answer(text="Unsupported settings action.", show_alert=True)
            return
        chat = getattr(callback_message, "chat", None)
        if chat is None:
            await callback.answer(text="Unsupported settings action.", show_alert=True)
            return

        reply = await self.chat_service.handle_settings_callback(
            chat_id=chat.id,
            user_id=callback.from_user.id,
            callback_data=callback.data,
        )
        parsed = parse_settings_callback(callback.data, settings=self.settings)
        if reply.error_type is not None:
            await callback.answer(text=reply.text, show_alert=True)
            return
        elif parsed is not None and parsed[0] == "set":
            await callback.answer(text=SETTINGS_UPDATED_TEXT)
        else:
            await callback.answer()

        edit_text = getattr(callback_message, "edit_text", None)
        if reply.text and edit_text is not None:
            await edit_text(
                text=reply.text,
                reply_markup=_settings_menu_markup(reply.settings_menu),
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

    @router.callback_query(F.data.startswith("prefs:"))
    async def on_settings_callback(
        callback: CallbackQuery,
        event_update: Update,
    ) -> None:
        await processor.process_callback(
            callback=callback,
            update_id=event_update.update_id,
        )

    return router


def _is_reference_image_reply_command(message: Message) -> bool:
    reply_message = message.reply_to_message
    if message.text is None or reply_message is None:
        return False
    if not getattr(reply_message, "photo", None):
        return False
    return _command_token(message.text) in {"/image", "/video"}


def _is_reference_image_caption_command(message: Message) -> bool:
    if not message.photo or message.caption is None:
        return False
    return _command_token(message.caption) in {"/image", "/video"}


def _command_token(text: str) -> str | None:
    stripped_text = text.strip()
    if not stripped_text:
        return None
    token = stripped_text.split(maxsplit=1)[0]
    if not token.startswith("/"):
        return None
    command = token.split("@", maxsplit=1)[0].lower()
    return command
