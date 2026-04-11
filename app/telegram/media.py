from __future__ import annotations

from io import BytesIO

from aiogram import Bot
from aiogram.types import Message

from app.domain.errors import ValidationError


async def download_largest_photo_bytes(bot: Bot, message: Message) -> bytes:
    if not message.photo:
        raise ValidationError("Photo payload is missing")

    buffer = BytesIO()
    await bot.download(message.photo[-1], destination=buffer)
    value = buffer.getvalue()
    if not value:
        raise ValidationError("Downloaded photo payload is empty")
    return value

