from __future__ import annotations

import logging
import time

from app.config import Settings
from app.domain.commands import GENERIC_FAILURE_TEXT
from app.domain.errors import StorageError
from app.domain.interfaces import ResponseEmitter
from app.domain.models import InboundMessage, ServiceReply, SpeechGenerationRequest
from app.logging import log_kv
from app.providers.base import TextToSpeechProvider
from app.storage.conversations import ConversationRepository
from app.storage.messages import MessageRepository

TTS_USAGE_TEXT = "Use /tts followed by Hindi text, for example: /tts नमस्ते, आपका स्वागत है।"
TTS_NOT_CONFIGURED_TEXT = "Speech generation is not configured right now."
TTS_GENERATION_RETRY_TEXT = "I couldn't generate speech just now. Please send a new /tts command to try again."
TTS_DELIVERY_RETRY_TEXT = "I couldn't confirm sending your voice message. Check this chat before sending a new /tts command."


class TextToSpeechService:
    """Explicit speech requests have their own lifecycle, outside chat supersession."""

    def __init__(
        self,
        *,
        settings: Settings,
        conversations: ConversationRepository,
        messages: MessageRepository,
        provider: TextToSpeechProvider | None,
    ) -> None:
        self.settings = settings
        self.conversations = conversations
        self.messages = messages
        self.provider = provider
        self.logger = logging.getLogger("app.domain.tts")

    async def handle(
        self, message: InboundMessage, *, responder: ResponseEmitter | None,
    ) -> ServiceReply:
        started = time.perf_counter()
        fields = dict(
            update_id=message.update_id,
            chat_id=message.chat_id,
            user_id=message.user_id,
            telegram_message_id=message.telegram_message_id,
            provider="elevenlabs",
            model=self.settings.elevenlabs_tts_model,
            voice_id=self.settings.elevenlabs_tts_voice_id,
        )
        parts = (message.text or "").split(maxsplit=1)
        text = parts[1].strip() if len(parts) > 1 else ""
        if not text:
            return ServiceReply(text=TTS_USAGE_TEXT, error_type="ValidationError")
        if len(text) > self.settings.bot_tts_max_chars:
            return ServiceReply(
                text=f"Please keep /tts text within {self.settings.bot_tts_max_chars} characters.",
                error_type="ValidationError",
            )
        fields["text_chars"] = len(text)
        conversation_id = None
        try:
            conversation = await self.conversations.get_or_create_active(message.chat_id)
            conversation_id = conversation.id
            claimed = await self.messages.claim_tts_command(
                conversation_id=conversation.id,
                chat_id=message.chat_id,
                telegram_message_id=message.telegram_message_id,
                text=message.text or "",
                created_at=message.sent_at,
            )
            if not claimed:
                self.logger.info(log_kv("tts_duplicate_ignored", **fields))
                return ServiceReply(text="", suppressed=True)
            if self.provider is None:
                reply = ServiceReply(text=TTS_NOT_CONFIGURED_TEXT)
                await self._record_outcome(conversation_id, reply.text, fields=fields)
                return reply

            self.logger.info(log_kv("tts_generation_started", **fields))
            speech = await self.provider.generate_speech(SpeechGenerationRequest(
                chat_id=message.chat_id,
                user_id=message.user_id,
                text=text,
                voice_id=self.settings.elevenlabs_tts_voice_id,
                model=self.settings.elevenlabs_tts_model,
                output_format=self.settings.elevenlabs_tts_output_format,
            ))
        except StorageError as exc:
            self.logger.warning(log_kv("tts_storage_failed", **fields, error_type=type(exc).__name__))
            return ServiceReply(text=GENERIC_FAILURE_TEXT, error_type="StorageError")
        except Exception as exc:
            error_type = type(exc).__name__
            self.logger.warning(log_kv(
                "tts_generation_failed", **fields, error_type=error_type,
                latency_ms=int((time.perf_counter() - started) * 1000),
            ))
            reply = ServiceReply(text=TTS_GENERATION_RETRY_TEXT, error_type=error_type)
            if conversation_id is not None:
                await self._record_outcome(conversation_id, reply.text, fields=fields)
            return reply

        if responder is None:
            return ServiceReply(text="", speech=speech, provider=speech.provider, model=speech.raw_model)
        try:
            sent = await responder.send_voice(speech, reply_to_message_id=message.telegram_message_id)
        except Exception as exc:
            self.logger.warning(log_kv(
                "tts_delivery_failed", **fields, error_type=type(exc).__name__,
                provider_message_id=speech.provider_message_id,
                latency_ms=int((time.perf_counter() - started) * 1000),
            ))
            await self._record_outcome(
                conversation_id, TTS_DELIVERY_RETRY_TEXT, fields=fields,
                provider_message_id=speech.provider_message_id,
            )
            return ServiceReply(text=TTS_DELIVERY_RETRY_TEXT, error_type="VoiceDeliveryError")

        usage = dict(
            text_chars=len(text), audio_bytes=len(speech.audio_bytes),
            duration_seconds=sent.duration_seconds,
        )
        self.logger.info(log_kv(
            "tts_delivered", **fields,
            provider_message_id=speech.provider_message_id,
            telegram_voice_message_id=sent.telegram_message_id,
            telegram_file_id=sent.telegram_file_id,
            telegram_file_unique_id=sent.telegram_file_unique_id,
            duration_seconds=sent.duration_seconds,
            mime_type=sent.mime_type,
            file_size=sent.file_size,
            audio_bytes=len(speech.audio_bytes),
            latency_ms=int((time.perf_counter() - started) * 1000),
        ))
        await self._record_outcome(
            conversation_id, "Speech delivered.", fields=fields,
            provider_message_id=speech.provider_message_id,
            telegram_message_id=sent.telegram_message_id,
        )
        return ServiceReply(
            text="", delivered=True, provider=speech.provider, model=speech.raw_model, usage_fields=usage,
        )

    async def _record_outcome(
        self,
        conversation_id: int,
        text: str,
        *,
        fields: dict,
        provider_message_id: str | None = None,
        telegram_message_id: int | None = None,
    ) -> None:
        try:
            await self.messages.add_assistant_message(
                conversation_id=conversation_id,
                provider_message_id=provider_message_id,
                telegram_message_id=telegram_message_id,
                text=text,
                message_type="command",
            )
            await self.conversations.touch(conversation_id)
        except StorageError as exc:
            # Delivery may already have succeeded. Never turn metadata failure
            # into a user-visible retry or generate/upload the audio again.
            self.logger.warning(log_kv(
                "tts_metadata_persist_failed", **fields, error_type=type(exc).__name__,
            ))
