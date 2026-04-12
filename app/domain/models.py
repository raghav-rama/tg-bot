from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

MessageType = Literal["text", "image", "command"]
Role = Literal["user", "assistant"]
ChatType = Literal["private", "group", "supergroup", "channel"]
GenerationJobStatus = Literal["queued", "running", "completed", "failed"]


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
    chat_type: ChatType
    user_id: int
    username: str | None
    first_name: str | None
    sent_at: datetime


@dataclass(slots=True)
class InboundMessage:
    update_id: int
    telegram_message_id: int
    chat_id: int
    chat_type: ChatType
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
            chat_type=self.chat_type,
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
class StreamingProviderEvent:
    type: Literal["delta", "completed"]
    text: str | None = None
    provider_message_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    raw_model: str | None = None


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
class ImageGenerationRequest:
    chat_id: int
    user_id: int
    prompt: str
    model: str
    aspect_ratio: str
    output_mime_type: str


@dataclass(slots=True)
class GeneratedImageResult:
    image_bytes: bytes
    mime_type: str
    provider: str
    raw_model: str
    prompt: str
    caption: str | None = None


@dataclass(slots=True)
class SentPhoto:
    telegram_message_id: int
    telegram_file_id: str
    telegram_file_unique_id: str
    width: int
    height: int
    file_size: int | None


@dataclass(slots=True)
class StoredGeneratedImage:
    id: int
    conversation_id: int
    prompt_text: str
    provider: str
    model: str
    mime_type: str
    telegram_message_id: int | None
    telegram_file_id: str | None
    telegram_file_unique_id: str | None
    width: int | None
    height: int | None
    file_size: int | None
    created_at: datetime


@dataclass(slots=True)
class VideoGenerationRequest:
    chat_id: int
    user_id: int
    prompt: str
    model: str
    aspect_ratio: str
    duration_seconds: int | None
    output_gcs_uri: str | None


@dataclass(slots=True)
class VideoGenerationPollRequest:
    operation_name: str
    prompt: str
    model: str


@dataclass(slots=True)
class SubmittedVideoJob:
    operation_name: str
    provider: str
    raw_model: str


@dataclass(slots=True)
class GeneratedVideoResult:
    video_bytes: bytes
    mime_type: str
    provider: str
    raw_model: str
    prompt: str
    output_uri: str | None
    caption: str | None = None
    duration_seconds: int | None = None
    width: int | None = None
    height: int | None = None
    file_size: int | None = None


@dataclass(slots=True)
class VideoJobPollResult:
    status: Literal["running", "completed", "failed"]
    operation_name: str
    generated_video: GeneratedVideoResult | None = None
    failure_reason: str | None = None


@dataclass(slots=True)
class SentVideo:
    telegram_message_id: int
    telegram_file_id: str
    telegram_file_unique_id: str
    width: int
    height: int
    duration_seconds: int | None
    mime_type: str | None
    file_size: int | None


@dataclass(slots=True)
class StoredGenerationJob:
    id: int
    conversation_id: int
    chat_id: int
    user_id: int
    job_type: str
    status: GenerationJobStatus
    prompt_text: str
    provider: str
    model: str
    operation_name: str
    output_uri: str | None
    mime_type: str | None
    telegram_message_id: int | None
    telegram_file_id: str | None
    telegram_file_unique_id: str | None
    width: int | None
    height: int | None
    duration_seconds: int | None
    file_size: int | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(slots=True)
class ServiceReply:
    text: str
    error_type: str | None = None
    delivered: bool = False
    suppressed: bool = False
