from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from app.config import Settings
from app.domain.commands import (
    ACCESS_DENIED_TEXT,
    EMPTY_TEXT_TEXT,
    GENERIC_FAILURE_TEXT,
    PROVIDER_RETRY_TEXT,
    SUPPORTED_COMMANDS,
    UNSUPPORTED_MESSAGE_TEXT,
    render_help_message,
    render_reset_message,
    render_start_message,
    render_status_message,
)
from app.domain.errors import ProviderTimeoutError, ProviderUpstreamError, StorageError, UnsupportedMessageError, ValidationError
from app.domain.models import ConversationRecord, InboundMessage, ProviderRequest, ServiceReply
from app.logging import log_kv
from app.providers.base import AIProvider
from app.storage.conversations import ConversationRepository
from app.storage.messages import MessageRepository


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChatService:
    def __init__(
        self,
        *,
        settings: Settings,
        conversations: ConversationRepository,
        messages: MessageRepository,
        provider: AIProvider,
    ) -> None:
        self.settings = settings
        self.conversations = conversations
        self.messages = messages
        self.provider = provider
        self.logger = logging.getLogger("app.domain.services")

    async def handle_inbound(self, message: InboundMessage) -> ServiceReply:
        started = time.perf_counter()
        if not self._is_allowed(message.user_id):
            self.logger.info(
                log_kv(
                    "unauthorized_user",
                    update_id=message.update_id,
                    chat_id=message.chat_id,
                    user_id=message.user_id,
                    message_type=message.message_type,
                )
            )
            return ServiceReply(text=ACCESS_DENIED_TEXT, error_type="UnauthorizedUserError")

        try:
            if message.message_type == "command":
                reply_text = await self._handle_command(message)
            else:
                reply_text = await self._handle_chat_message(message)
        except (ProviderTimeoutError, ProviderUpstreamError) as exc:
            self.logger.warning(
                log_kv(
                    "provider_failure",
                    update_id=message.update_id,
                    chat_id=message.chat_id,
                    user_id=message.user_id,
                    message_type=message.message_type,
                    provider="openai",
                    model=self.settings.openai_model,
                    error_type=type(exc).__name__,
                )
            )
            return ServiceReply(text=PROVIDER_RETRY_TEXT, error_type=type(exc).__name__)
        except StorageError:
            self.logger.exception(
                log_kv(
                    "storage_failure",
                    update_id=message.update_id,
                    chat_id=message.chat_id,
                    user_id=message.user_id,
                    message_type=message.message_type,
                    error_type="StorageError",
                )
            )
            return ServiceReply(text=GENERIC_FAILURE_TEXT, error_type="StorageError")
        except Exception:
            self.logger.exception(
                log_kv(
                    "unhandled_service_failure",
                    update_id=message.update_id,
                    chat_id=message.chat_id,
                    user_id=message.user_id,
                    message_type=message.message_type,
                    error_type="UnhandledError",
                )
            )
            return ServiceReply(text=GENERIC_FAILURE_TEXT, error_type="UnhandledError")

        latency_ms = int((time.perf_counter() - started) * 1000)
        self.logger.info(
            log_kv(
                "message_processed",
                update_id=message.update_id,
                chat_id=message.chat_id,
                user_id=message.user_id,
                command=message.command,
                message_type=message.message_type,
                provider="openai" if message.message_type != "command" else None,
                model=self.settings.openai_model if message.message_type != "command" else None,
                latency_ms=latency_ms,
            )
        )
        return ServiceReply(text=reply_text)

    async def handle_normalization_error(
        self,
        *,
        update_id: int,
        chat_id: int,
        user_id: int,
        telegram_message_id: int,
        error: Exception,
    ) -> ServiceReply:
        if not self._is_allowed(user_id):
            self.logger.info(
                log_kv(
                    "unauthorized_user",
                    update_id=update_id,
                    chat_id=chat_id,
                    user_id=user_id,
                    message_type="unknown",
                )
            )
            return ServiceReply(text=ACCESS_DENIED_TEXT, error_type="UnauthorizedUserError")

        if isinstance(error, UnsupportedMessageError):
            return ServiceReply(
                text=UNSUPPORTED_MESSAGE_TEXT,
                error_type="UnsupportedMessageError",
            )
        if isinstance(error, ValidationError):
            text = EMPTY_TEXT_TEXT if "empty" in str(error).lower() else str(error)
            return ServiceReply(text=text, error_type="ValidationError")

        self.logger.exception(
            log_kv(
                "normalization_failure",
                update_id=update_id,
                chat_id=chat_id,
                user_id=user_id,
                telegram_message_id=telegram_message_id,
                error_type=type(error).__name__,
            )
        )
        return ServiceReply(text=GENERIC_FAILURE_TEXT, error_type=type(error).__name__)

    def _is_allowed(self, user_id: int) -> bool:
        return user_id in self.settings.allowed_user_ids

    async def _handle_command(self, message: InboundMessage) -> str:
        command = (message.command or "").lower()
        if command == "/reset":
            conversation = await self.conversations.reset_active(message.chat_id)
            reply_text = render_reset_message()
            await self._persist_command_exchange(conversation, message, reply_text)
            return reply_text

        conversation = await self.conversations.get_or_create_active(message.chat_id)
        if command == "/start":
            reply_text = render_start_message()
        elif command == "/help":
            reply_text = render_help_message()
        elif command == "/status":
            reply_text = render_status_message(
                update_mode=self.settings.app_update_mode,
                model=self.settings.openai_model,
                memory_enabled=self.settings.bot_history_max_turns > 0,
            )
        elif command in SUPPORTED_COMMANDS:
            reply_text = render_help_message()
        else:
            reply_text = "Unsupported command. Use /help."

        await self._persist_command_exchange(conversation, message, reply_text)
        return reply_text

    async def _persist_command_exchange(
        self,
        conversation: ConversationRecord,
        message: InboundMessage,
        reply_text: str,
    ) -> None:
        await self.messages.add_user_message(
            conversation_id=conversation.id,
            telegram_message_id=message.telegram_message_id,
            message_type="command",
            text=message.command or message.text,
            image=None,
            created_at=message.sent_at,
        )
        await self.messages.add_assistant_message(
            conversation_id=conversation.id,
            provider_message_id=None,
            text=reply_text,
            message_type="command",
            created_at=_utcnow(),
        )
        await self.conversations.touch(conversation.id)

    async def _handle_chat_message(self, message: InboundMessage) -> str:
        conversation = await self.conversations.get_or_create_active(message.chat_id)
        history = []
        if self.settings.bot_history_max_turns > 0:
            history = await self.messages.list_recent_history(
                conversation_id=conversation.id,
                limit=self.settings.bot_history_max_turns,
            )

        request = ProviderRequest(
            chat_id=message.chat_id,
            user_id=message.user_id,
            system_prompt=self.settings.bot_system_prompt,
            history=history,
            user_message=message.text,
            image=message.image,
            model=self.settings.openai_model,
            temperature=self.settings.openai_temperature,
            max_output_tokens=self.settings.openai_max_output_tokens,
        )

        provider_response = await self.provider.generate_response(request)

        await self.messages.add_user_message(
            conversation_id=conversation.id,
            telegram_message_id=message.telegram_message_id,
            message_type=message.message_type,
            text=message.text,
            image=message.image,
            created_at=message.sent_at,
        )
        await self.messages.add_assistant_message(
            conversation_id=conversation.id,
            provider_message_id=provider_response.provider_message_id,
            text=provider_response.reply_text,
            created_at=_utcnow(),
        )
        await self.conversations.touch(conversation.id)
        return provider_response.reply_text

