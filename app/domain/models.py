from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

MessageType = Literal["text", "image", "command"]
Role = Literal["user", "assistant"]


@dataclass(slots=True)
class ImageInput:
    telegram_file_id: str
    telegram_file_unique_id: str
    mime_type: str
    width: int
    height: int
    byte_size: int
    bytes_b64: str
    caption: str | None


@dataclass(slots=True)
class MessageContext:
    update_id: int
    telegram_message_id: int
    chat_id: int
    user_id: int
    username: str | None
    first_name: str | None
    sent_at: datetime


@dataclass(slots=True)
class InboundMessage:
    update_id: int
    telegram_message_id: int
    chat_id: int
    user_id: int
    username: str | None
    first_name: str | None
    message_type: MessageType
    text: str | None
    command: str | None
    image: ImageInput | None
    sent_at: datetime

    def context(self) -> MessageContext:
        return MessageContext(
            update_id=self.update_id,
            telegram_message_id=self.telegram_message_id,
            chat_id=self.chat_id,
            user_id=self.user_id,
            username=self.username,
            first_name=self.first_name,
            sent_at=self.sent_at,
        )


@dataclass(slots=True)
class ConversationTurn:
    role: Role
    text: str
    created_at: datetime


@dataclass(slots=True)
class ProviderRequest:
    chat_id: int
    user_id: int
    system_prompt: str
    history: list[ConversationTurn]
    user_message: str | None
    image: ImageInput | None
    model: str
    temperature: float
    max_output_tokens: int


@dataclass(slots=True)
class ProviderResponse:
    reply_text: str
    provider_message_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    finish_reason: str | None
    raw_model: str | None


@dataclass(slots=True)
class ConversationRecord:
    id: int
    chat_id: int
    started_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    is_active: bool


@dataclass(slots=True)
class StoredMessage:
    id: int
    conversation_id: int
    telegram_message_id: int | None
    provider_message_id: str | None
    role: Role
    message_type: str
    text: str | None
    image_file_unique_id: str | None
    image_mime_type: str | None
    image_width: int | None
    image_height: int | None
    image_byte_size: int | None
    created_at: datetime


@dataclass(slots=True)
class ServiceReply:
    text: str
    error_type: str | None = None

