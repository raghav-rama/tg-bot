from __future__ import annotations

import itertools
import logging

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import BufferedInputFile

from app.domain.errors import DraftRateLimitedError
from app.domain.interfaces import DraftSession, ResponseEmitter
from app.domain.models import GeneratedImageResult, GeneratedVideoResult, SentPhoto, SentVideo
from app.logging import log_kv
from app.telegram.formatting import render_telegram_html


class TelegramDraftSession:
    def __init__(self, *, bot: Bot, chat_id: int, draft_id: int) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.draft_id = draft_id
        self.logger = logging.getLogger("app.telegram.drafts")
        self._closed = False

    async def update(self, text: str) -> None:
        if self._closed:
            return
        try:
            await self.bot.send_message_draft(
                chat_id=self.chat_id,
                draft_id=self.draft_id,
                text=text,
            )
        except TelegramRetryAfter as exc:
            raise DraftRateLimitedError(retry_after=exc.retry_after) from exc

    async def finish(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.logger.info(
            log_kv(
                "telegram_draft_finished",
                chat_id=self.chat_id,
                draft_id=self.draft_id,
            )
        )

    async def cancel(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.logger.info(
            log_kv(
                "telegram_draft_cancelled",
                chat_id=self.chat_id,
                draft_id=self.draft_id,
            )
        )


class TelegramResponseEmitter:
    _draft_ids = itertools.count(1)

    def __init__(self, *, bot: Bot, chat_id: int) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.logger = logging.getLogger("app.telegram.drafts")

    async def send_text(self, text: str) -> None:
        formatted_text = render_telegram_html(text)
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=formatted_text,
                parse_mode=ParseMode.HTML,
            )
        except TelegramBadRequest as exc:
            self.logger.warning(
                log_kv(
                    "telegram_formatted_send_fallback",
                    chat_id=self.chat_id,
                    error_type=type(exc).__name__,
                    reason=str(exc),
                )
            )
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=None,
            )

    async def send_photo(self, image: GeneratedImageResult) -> SentPhoto:
        extension = ".jpg" if image.mime_type == "image/jpeg" else ".png"
        message = await self.bot.send_photo(
            chat_id=self.chat_id,
            photo=BufferedInputFile(
                image.image_bytes,
                filename=f"generated{extension}",
            ),
            caption=image.caption,
        )
        if not message.photo:
            raise RuntimeError("Telegram did not return photo sizes for the sent image")

        largest = message.photo[-1]
        return SentPhoto(
            telegram_message_id=message.message_id,
            telegram_file_id=largest.file_id,
            telegram_file_unique_id=largest.file_unique_id,
            width=largest.width,
            height=largest.height,
            file_size=largest.file_size,
        )

    async def send_video(self, video: GeneratedVideoResult) -> SentVideo:
        extension = ".mp4" if video.mime_type == "video/mp4" else ".bin"
        message = await self.bot.send_video(
            chat_id=self.chat_id,
            video=BufferedInputFile(
                video.video_bytes,
                filename=f"generated{extension}",
            ),
            caption=video.caption,
            supports_streaming=True,
        )
        if message.video is None:
            raise RuntimeError("Telegram did not return video metadata for the sent video")

        sent_video = message.video
        return SentVideo(
            telegram_message_id=message.message_id,
            telegram_file_id=sent_video.file_id,
            telegram_file_unique_id=sent_video.file_unique_id,
            width=sent_video.width,
            height=sent_video.height,
            duration_seconds=sent_video.duration,
            mime_type=sent_video.mime_type,
            file_size=sent_video.file_size,
        )

    async def open_draft(self) -> DraftSession:
        draft_id = next(self._draft_ids)
        return TelegramDraftSession(
            bot=self.bot,
            chat_id=self.chat_id,
            draft_id=draft_id,
        )
