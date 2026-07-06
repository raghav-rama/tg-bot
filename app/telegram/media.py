from __future__ import annotations

from io import BytesIO

from aiogram import Bot
from aiogram.types import Message

from app.domain.errors import ValidationError


async def download_largest_photo_bytes(bot: Bot, message: Message) -> bytes:
    if not message.photo:
        raise ValidationError("Photo payload is missing")

    value = await download_photo_bytes_by_file_id(bot, message.photo[-1].file_id)
    if not value:
        raise ValidationError("Downloaded photo payload is empty")
    return value


async def download_photo_bytes_by_file_id(bot: Bot, file_id: str) -> bytes:
    buffer = BytesIO()
    file = await bot.get_file(file_id)
    await bot.download(file, destination=buffer)
    value = buffer.getvalue()
    if not value:
        raise ValidationError("Downloaded photo payload is empty")
    return value
