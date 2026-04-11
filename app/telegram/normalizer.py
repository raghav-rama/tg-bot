from __future__ import annotations

import base64
from datetime import timezone

from aiogram.types import Message

from app.domain.errors import UnsupportedMessageError, ValidationError
from app.domain.models import ImageInput, InboundMessage


def normalize_message(
    *,
    message: Message,
    update_id: int,
    image_bytes: bytes | None,
    image_max_bytes: int,
) -> InboundMessage:
    if message.from_user is None or message.chat is None or message.date is None:
        raise ValidationError("Malformed Telegram update")

    if message.media_group_id is not None:
        raise UnsupportedMessageError("Media groups are not supported")

    sent_at = message.date
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)

    if message.text is not None:
        stripped_text = message.text.strip()
        if not stripped_text:
            raise ValidationError("Please send a non-empty text message.")

        command = _extract_command(stripped_text)
        if command is not None:
            return InboundMessage(
                update_id=update_id,
                telegram_message_id=message.message_id,
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                message_type="command",
                text=stripped_text,
                command=command,
                image=None,
                sent_at=sent_at,
            )

        return InboundMessage(
            update_id=update_id,
            telegram_message_id=message.message_id,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            message_type="text",
            text=stripped_text,
            command=None,
            image=None,
            sent_at=sent_at,
        )

    if message.photo:
        if image_bytes is None:
            raise ValidationError("Photo bytes were not downloaded")
        if len(image_bytes) > image_max_bytes:
            raise ValidationError(
                f"That image is too large. Please send one under {image_max_bytes} bytes."
            )
        largest = message.photo[-1]
        caption = message.caption.strip() if message.caption else None
        return InboundMessage(
            update_id=update_id,
            telegram_message_id=message.message_id,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            message_type="image",
            text=caption,
            command=None,
            image=ImageInput(
                telegram_file_id=largest.file_id,
                telegram_file_unique_id=largest.file_unique_id,
                mime_type="image/jpeg",
                width=largest.width,
                height=largest.height,
                byte_size=len(image_bytes),
                bytes_b64=base64.b64encode(image_bytes).decode("ascii"),
                caption=caption,
            ),
            sent_at=sent_at,
        )

    raise UnsupportedMessageError("Unsupported Telegram message type")


def _extract_command(text: str) -> str | None:
    token = text.split(maxsplit=1)[0]
    if not token.startswith("/"):
        return None
    return token.split("@", maxsplit=1)[0].lower()

