from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable

from app.config import Settings
from app.domain.commands import (
    ACCESS_DENIED_TEXT,
    EMPTY_TEXT_TEXT,
    GENERIC_FAILURE_TEXT,
    IMAGE_GENERATION_NOT_CONFIGURED_TEXT,
    IMAGE_GENERATION_RETRY_TEXT,
    IMAGE_PROMPT_REQUIRED_TEXT,
    PROVIDER_RETRY_TEXT,
    SUPPORTED_COMMANDS,
    VIDEO_GENERATION_NOT_CONFIGURED_TEXT,
    VIDEO_GENERATION_QUEUED_TEXT,
    VIDEO_GENERATION_RETRY_TEXT,
    VIDEO_PROMPT_REQUIRED_TEXT,
    UNSUPPORTED_MESSAGE_TEXT,
    render_help_message,
    render_reset_message,
    render_start_message,
    render_status_message,
)
from app.domain.errors import (
    DraftRateLimitedError,
    ProviderTimeoutError,
    ProviderUpstreamError,
    StorageError,
    UnsupportedMessageError,
    ValidationError,
)
from app.domain.interfaces import DraftSession, ResponseEmitter
from app.domain.models import (
    ConversationRecord,
    GeneratedImageResult,
    ImageGenerationRequest,
    InboundMessage,
    ProviderRequest,
    ServiceReply,
    StreamingProviderEvent,
    VideoGenerationRequest,
)
from app.logging import log_kv
from app.providers.base import AIProvider, ImageGenerator, VideoGenerator
from app.storage.conversations import ConversationRepository
from app.storage.generation_jobs import GenerationJobRepository
from app.storage.generated_images import GeneratedImageRepository
from app.storage.messages import MessageRepository


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _SupersededResponse(Exception):
    """Raised when a newer message replaces the current in-flight response."""


@dataclass(slots=True)
class _ActiveRun:
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_callbacks: list[Callable[[], Awaitable[None]]] = field(default_factory=list)

    async def add_cancel_callback(
        self,
        callback: Callable[[], Awaitable[None]],
    ) -> None:
        if self.cancelled.is_set():
            await callback()
            return
        self.cancel_callbacks.append(callback)

    async def cancel(self) -> None:
        if self.cancelled.is_set():
            return
        self.cancelled.set()
        callbacks = list(self.cancel_callbacks)
        self.cancel_callbacks.clear()
        for callback in callbacks:
            try:
                await callback()
            except Exception:
                continue


class ChatService:
    def __init__(
        self,
        *,
        settings: Settings,
        conversations: ConversationRepository,
        messages: MessageRepository,
        provider: AIProvider,
        generated_images: GeneratedImageRepository | None = None,
        image_generator: ImageGenerator | None = None,
        generation_jobs: GenerationJobRepository | None = None,
        video_generator: VideoGenerator | None = None,
    ) -> None:
        self.settings = settings
        self.conversations = conversations
        self.messages = messages
        self.provider = provider
        self.generated_images = generated_images
        self.image_generator = image_generator
        self.generation_jobs = generation_jobs
        self.video_generator = video_generator
        self.logger = logging.getLogger("app.domain.services")
        self._active_runs: dict[int, _ActiveRun] = {}
        self._active_runs_lock = asyncio.Lock()

    async def handle_inbound(
        self,
        message: InboundMessage,
        responder: ResponseEmitter | None = None,
    ) -> ServiceReply:
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
            reply = ServiceReply(text=ACCESS_DENIED_TEXT, error_type="UnauthorizedUserError")
            return await self._deliver_reply(
                reply=reply,
                responder=responder,
                active_run=None,
                message=message,
            )

        active_run = await self._begin_run(message.chat_id)
        try:
            try:
                if message.message_type == "command":
                    reply = await self._handle_command(
                        message,
                        responder=responder,
                        active_run=active_run,
                    )
                else:
                    reply = await self._handle_chat_message(
                        message,
                        responder=responder,
                        active_run=active_run,
                    )
            except _SupersededResponse:
                self.logger.info(
                    log_kv(
                        "response_superseded",
                        update_id=message.update_id,
                        chat_id=message.chat_id,
                        user_id=message.user_id,
                        message_type=message.message_type,
                    )
                )
                return ServiceReply(text="", suppressed=True)
            except (ProviderTimeoutError, ProviderUpstreamError) as exc:
                provider_name, model_name = self._provider_context(message)
                retry_text = (
                    IMAGE_GENERATION_RETRY_TEXT
                    if self._is_image_command(message)
                    else (
                        VIDEO_GENERATION_RETRY_TEXT
                        if self._is_video_command(message)
                        else PROVIDER_RETRY_TEXT
                    )
                )
                self.logger.warning(
                    log_kv(
                        "provider_failure",
                        update_id=message.update_id,
                        chat_id=message.chat_id,
                        user_id=message.user_id,
                        message_type=message.message_type,
                        provider=provider_name,
                        model=model_name,
                        error_type=type(exc).__name__,
                    )
                )
                reply = ServiceReply(text=retry_text, error_type=type(exc).__name__)
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
                reply = ServiceReply(text=GENERIC_FAILURE_TEXT, error_type="StorageError")
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
                reply = ServiceReply(text=GENERIC_FAILURE_TEXT, error_type="UnhandledError")

            reply = await self._deliver_reply(
                reply=reply,
                responder=responder,
                active_run=active_run,
                message=message,
            )
            if reply.suppressed:
                return reply

            latency_ms = int((time.perf_counter() - started) * 1000)
            provider_name, model_name = self._provider_context(message)
            self.logger.info(
                log_kv(
                    "message_processed",
                    update_id=message.update_id,
                    chat_id=message.chat_id,
                    user_id=message.user_id,
                    command=message.command,
                    message_type=message.message_type,
                    provider=provider_name,
                    model=model_name,
                    latency_ms=latency_ms,
                    delivered=reply.delivered,
                )
            )
            return reply
        finally:
            await self._finish_run(message.chat_id, active_run)

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

    async def _begin_run(self, chat_id: int) -> _ActiveRun:
        new_run = _ActiveRun()
        async with self._active_runs_lock:
            previous_run = self._active_runs.get(chat_id)
            self._active_runs[chat_id] = new_run
        if previous_run is not None:
            await previous_run.cancel()
        return new_run

    async def _finish_run(self, chat_id: int, active_run: _ActiveRun) -> None:
        async with self._active_runs_lock:
            current = self._active_runs.get(chat_id)
            if current is active_run:
                self._active_runs.pop(chat_id, None)

    async def _deliver_reply(
        self,
        *,
        reply: ServiceReply,
        responder: ResponseEmitter | None,
        active_run: _ActiveRun | None,
        message: InboundMessage,
    ) -> ServiceReply:
        if reply.suppressed or responder is None or reply.delivered or not reply.text:
            return reply
        if active_run is not None and active_run.cancelled.is_set():
            self.logger.info(
                log_kv(
                    "response_delivery_suppressed",
                    update_id=message.update_id,
                    chat_id=message.chat_id,
                    user_id=message.user_id,
                    message_type=message.message_type,
                )
            )
            return ServiceReply(
                text="",
                error_type=reply.error_type,
                suppressed=True,
            )
        await responder.send_text(reply.text)
        reply.delivered = True
        return reply

    async def _handle_command(
        self,
        message: InboundMessage,
        *,
        responder: ResponseEmitter | None,
        active_run: _ActiveRun,
    ) -> ServiceReply:
        command = (message.command or "").lower()
        if command == "/reset":
            conversation = await self.conversations.reset_active(message.chat_id)
            reply_text = render_reset_message()
            await self._persist_command_exchange(conversation, message, reply_text)
            return ServiceReply(text=reply_text)

        conversation = await self.conversations.get_or_create_active(message.chat_id)
        if command == "/start":
            reply_text = render_start_message()
        elif command == "/help":
            reply_text = render_help_message()
        elif command == "/status":
            reply_text = render_status_message(
                update_mode=self.settings.app_update_mode,
                chat_model=self.settings.openai_model,
                image_generation_enabled=self.settings.vertex_image_generation_enabled,
                image_model=self.settings.vertex_image_model,
                video_generation_enabled=self.settings.vertex_video_generation_enabled,
                video_model=self.settings.vertex_video_model,
                memory_enabled=self.settings.bot_history_max_turns > 0,
            )
        elif command == "/image":
            return await self._handle_image_command(
                conversation=conversation,
                message=message,
                responder=responder,
                active_run=active_run,
            )
        elif command == "/video":
            return await self._handle_video_command(
                conversation=conversation,
                message=message,
            )
        elif command in SUPPORTED_COMMANDS:
            reply_text = render_help_message()
        else:
            reply_text = "Unsupported command. Use /help."

        await self._persist_command_exchange(conversation, message, reply_text)
        return ServiceReply(text=reply_text)

    async def _handle_image_command(
        self,
        *,
        conversation: ConversationRecord,
        message: InboundMessage,
        responder: ResponseEmitter | None,
        active_run: _ActiveRun,
    ) -> ServiceReply:
        prompt = self._extract_image_prompt(message)
        if prompt is None:
            await self._persist_command_exchange(
                conversation,
                message,
                IMAGE_PROMPT_REQUIRED_TEXT,
            )
            return ServiceReply(text=IMAGE_PROMPT_REQUIRED_TEXT)

        await self._persist_user_command_message(conversation, message)

        if responder is None:
            reply_text = GENERIC_FAILURE_TEXT
            await self._persist_command_reply(conversation, reply_text)
            await self.conversations.touch(conversation.id)
            return ServiceReply(text=reply_text)

        if self.image_generator is None or self.generated_images is None:
            await self._persist_command_reply(
                conversation,
                IMAGE_GENERATION_NOT_CONFIGURED_TEXT,
            )
            await self.conversations.touch(conversation.id)
            return ServiceReply(text=IMAGE_GENERATION_NOT_CONFIGURED_TEXT)

        try:
            generated_image = await self.image_generator.generate_image(
                ImageGenerationRequest(
                    chat_id=message.chat_id,
                    user_id=message.user_id,
                    prompt=prompt,
                    model=self.settings.vertex_image_model,
                    aspect_ratio=self.settings.vertex_image_aspect_ratio,
                    output_mime_type=self.settings.vertex_image_output_mime_type,
                )
            )
        except (ProviderTimeoutError, ProviderUpstreamError):
            self.logger.warning(
                log_kv(
                    "image_generation_failed",
                    update_id=message.update_id,
                    chat_id=message.chat_id,
                    user_id=message.user_id,
                    provider="vertex",
                    model=self.settings.vertex_image_model,
                ),
                exc_info=True,
            )
            await self._persist_command_reply(conversation, IMAGE_GENERATION_RETRY_TEXT)
            await self.conversations.touch(conversation.id)
            return ServiceReply(text=IMAGE_GENERATION_RETRY_TEXT)

        if active_run.cancelled.is_set():
            raise _SupersededResponse()

        sent_photo = await responder.send_photo(generated_image)
        await self._persist_generated_image_delivery(
            conversation=conversation,
            generated_image=generated_image,
            sent_photo=sent_photo,
        )
        await self.conversations.touch(conversation.id)
        return ServiceReply(text="", delivered=True)

    async def _handle_video_command(
        self,
        *,
        conversation: ConversationRecord,
        message: InboundMessage,
    ) -> ServiceReply:
        prompt = self._extract_video_prompt(message)
        if prompt is None:
            await self._persist_command_exchange(
                conversation,
                message,
                VIDEO_PROMPT_REQUIRED_TEXT,
            )
            return ServiceReply(text=VIDEO_PROMPT_REQUIRED_TEXT)

        if self.video_generator is None or self.generation_jobs is None:
            await self._persist_command_exchange(
                conversation,
                message,
                VIDEO_GENERATION_NOT_CONFIGURED_TEXT,
            )
            return ServiceReply(text=VIDEO_GENERATION_NOT_CONFIGURED_TEXT)

        await self._persist_user_command_message(conversation, message)
        self.logger.info(
            log_kv(
                "video_generation_requested",
                update_id=message.update_id,
                chat_id=message.chat_id,
                user_id=message.user_id,
                model=self.settings.vertex_video_model,
                prompt_chars=len(prompt),
                aspect_ratio=self.settings.vertex_video_aspect_ratio,
                duration_seconds=self.settings.vertex_video_duration_seconds,
                output_gcs_uri=self.settings.vertex_video_output_gcs_uri,
            )
        )
        submitted_job = await self.video_generator.submit_video(
            VideoGenerationRequest(
                chat_id=message.chat_id,
                user_id=message.user_id,
                prompt=prompt,
                model=self.settings.vertex_video_model,
                aspect_ratio=self.settings.vertex_video_aspect_ratio,
                duration_seconds=self.settings.vertex_video_duration_seconds,
                output_gcs_uri=self.settings.vertex_video_output_gcs_uri,
            )
        )
        self.logger.info(
            log_kv(
                "video_generation_queued",
                update_id=message.update_id,
                chat_id=message.chat_id,
                user_id=message.user_id,
                operation_name=submitted_job.operation_name,
                model=submitted_job.raw_model,
            )
        )

        await self.generation_jobs.add_video_job(
            conversation_id=conversation.id,
            chat_id=message.chat_id,
            user_id=message.user_id,
            prompt_text=prompt,
            provider=submitted_job.provider,
            model=submitted_job.raw_model,
            operation_name=submitted_job.operation_name,
            duration_seconds=self.settings.vertex_video_duration_seconds,
            created_at=message.sent_at,
        )
        await self._persist_command_reply(conversation, VIDEO_GENERATION_QUEUED_TEXT)
        await self.conversations.touch(conversation.id)
        return ServiceReply(text=VIDEO_GENERATION_QUEUED_TEXT)

    async def _persist_command_exchange(
        self,
        conversation: ConversationRecord,
        message: InboundMessage,
        reply_text: str,
    ) -> None:
        await self._persist_user_command_message(conversation, message)
        await self._persist_command_reply(conversation, reply_text)
        await self.conversations.touch(conversation.id)

    async def _persist_user_command_message(
        self,
        conversation: ConversationRecord,
        message: InboundMessage,
    ) -> None:
        await self.messages.add_user_message(
            conversation_id=conversation.id,
            telegram_message_id=message.telegram_message_id,
            message_type="command",
            text=message.text or message.command,
            image=None,
            created_at=message.sent_at,
        )

    async def _persist_command_reply(
        self,
        conversation: ConversationRecord,
        reply_text: str,
    ) -> None:
        await self.messages.add_assistant_message(
            conversation_id=conversation.id,
            provider_message_id=None,
            text=reply_text,
            message_type="command",
            created_at=_utcnow(),
        )

    async def _handle_chat_message(
        self,
        message: InboundMessage,
        *,
        responder: ResponseEmitter | None,
        active_run: _ActiveRun,
    ) -> ServiceReply:
        conversation = await self.conversations.get_or_create_active(message.chat_id)
        history = []
        if self.settings.bot_history_max_turns > 0:
            history = await self.messages.list_recent_history(
                conversation_id=conversation.id,
                limit=self.settings.bot_history_max_turns,
            )

        await self.messages.add_user_message(
            conversation_id=conversation.id,
            telegram_message_id=message.telegram_message_id,
            message_type=message.message_type,
            text=message.text,
            image=message.image,
            created_at=message.sent_at,
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

        draft_session: DraftSession | None = None
        draft_updates_disabled = not self._drafts_enabled(
            message=message,
            responder=responder,
        )
        draft_delay_at = time.monotonic() + (
            self.settings.bot_draft_start_delay_ms / 1000
        )
        draft_last_sent_at = 0.0
        draft_last_sent_len = 0
        accumulated_text = ""
        completion_event: StreamingProviderEvent | None = None

        try:
            async for event in self.provider.stream_response(request):
                if active_run.cancelled.is_set():
                    raise _SupersededResponse()

                if event.type == "delta" and event.text:
                    accumulated_text += event.text
                    if draft_updates_disabled:
                        continue

                    now = time.monotonic()
                    if draft_session is None:
                        if now < draft_delay_at:
                            continue
                        draft_session = await self._open_draft_session(
                            responder=responder,
                            message=message,
                            active_run=active_run,
                        )
                        if draft_session is None:
                            draft_updates_disabled = True
                            continue
                        update_sent = await self._send_draft_update(
                            draft_session=draft_session,
                            text=accumulated_text,
                            message=message,
                        )
                        if not update_sent:
                            draft_updates_disabled = True
                            await self._cancel_draft_session(
                                draft_session=draft_session,
                                message=message,
                            )
                            draft_session = None
                            continue
                        draft_last_sent_at = now
                        draft_last_sent_len = len(accumulated_text)
                        continue

                    if (
                        now - draft_last_sent_at
                        < self.settings.bot_draft_update_interval_ms / 1000
                    ):
                        continue
                    if (
                        len(accumulated_text) - draft_last_sent_len
                        < self.settings.bot_draft_min_chars_delta
                    ):
                        continue

                    update_sent = await self._send_draft_update(
                        draft_session=draft_session,
                        text=accumulated_text,
                        message=message,
                    )
                    if not update_sent:
                        draft_updates_disabled = True
                        await self._cancel_draft_session(
                            draft_session=draft_session,
                            message=message,
                        )
                        draft_session = None
                        continue
                    draft_last_sent_at = now
                    draft_last_sent_len = len(accumulated_text)
                    continue

                if event.type == "completed":
                    completion_event = event

            if active_run.cancelled.is_set():
                raise _SupersededResponse()

            reply_text = accumulated_text.strip()
            if not reply_text:
                raise ProviderUpstreamError("OpenAI returned an empty response")

            await self.messages.add_assistant_message(
                conversation_id=conversation.id,
                provider_message_id=(
                    completion_event.provider_message_id if completion_event else None
                ),
                text=reply_text,
                created_at=_utcnow(),
            )
            await self.conversations.touch(conversation.id)

            if draft_session is not None:
                await self._finish_draft_session(
                    draft_session=draft_session,
                    message=message,
                )

            return ServiceReply(text=reply_text)
        except Exception:
            if draft_session is not None:
                await self._cancel_draft_session(
                    draft_session=draft_session,
                    message=message,
                )
            raise

    def _extract_image_prompt(self, message: InboundMessage) -> str | None:
        if message.text is None:
            return None
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            return None
        prompt = parts[1].strip()
        return prompt or None

    def _extract_video_prompt(self, message: InboundMessage) -> str | None:
        return self._extract_image_prompt(message)

    async def _persist_generated_image_delivery(
        self,
        *,
        conversation: ConversationRecord,
        generated_image: GeneratedImageResult,
        sent_photo: SentPhoto,
    ) -> None:
        try:
            await self.messages.add_assistant_message(
                conversation_id=conversation.id,
                provider_message_id=None,
                text=None,
                message_type="generated_image",
                created_at=_utcnow(),
            )
            if self.generated_images is not None:
                await self.generated_images.add_generated_image(
                    conversation_id=conversation.id,
                    prompt_text=generated_image.prompt,
                    provider=generated_image.provider,
                    model=generated_image.raw_model,
                    mime_type=generated_image.mime_type,
                    telegram_message_id=sent_photo.telegram_message_id,
                    telegram_file_id=sent_photo.telegram_file_id,
                    telegram_file_unique_id=sent_photo.telegram_file_unique_id,
                    width=sent_photo.width,
                    height=sent_photo.height,
                    file_size=sent_photo.file_size,
                    created_at=_utcnow(),
                )
        except StorageError:
            self.logger.exception(
                log_kv(
                    "generated_image_metadata_persist_failed",
                    chat_id=conversation.chat_id,
                    provider=generated_image.provider,
                    model=generated_image.raw_model,
                )
            )

    def _provider_context(self, message: InboundMessage) -> tuple[str | None, str | None]:
        if self._is_image_command(message):
            return ("vertex", self.settings.vertex_image_model)
        if self._is_video_command(message):
            return ("vertex", self.settings.vertex_video_model)
        if message.message_type != "command":
            return ("openai", self.settings.openai_model)
        return (None, None)

    def _is_image_command(self, message: InboundMessage) -> bool:
        return message.message_type == "command" and (message.command or "").lower() == "/image"

    def _is_video_command(self, message: InboundMessage) -> bool:
        return message.message_type == "command" and (message.command or "").lower() == "/video"

    def _drafts_enabled(
        self,
        *,
        message: InboundMessage,
        responder: ResponseEmitter | None,
    ) -> bool:
        if responder is None:
            return False
        if not self.settings.bot_enable_message_drafts:
            return False
        if message.chat_type != "private":
            return False
        if message.message_type == "text":
            return True
        if message.message_type == "image":
            return self.settings.bot_draft_stream_on_images
        return False

    async def _open_draft_session(
        self,
        *,
        responder: ResponseEmitter | None,
        message: InboundMessage,
        active_run: _ActiveRun,
    ) -> DraftSession | None:
        if responder is None:
            return None
        try:
            draft_session = await responder.open_draft()
        except Exception:
            self.logger.warning(
                log_kv(
                    "draft_start_failed",
                    update_id=message.update_id,
                    chat_id=message.chat_id,
                    user_id=message.user_id,
                ),
                exc_info=True,
            )
            return None

        async def cancel_draft() -> None:
            await self._cancel_draft_session(
                draft_session=draft_session,
                message=message,
            )

        await active_run.add_cancel_callback(cancel_draft)
        self.logger.info(
            log_kv(
                "draft_started",
                update_id=message.update_id,
                chat_id=message.chat_id,
                user_id=message.user_id,
                draft_id=draft_session.draft_id,
            )
        )
        return draft_session

    async def _send_draft_update(
        self,
        *,
        draft_session: DraftSession,
        text: str,
        message: InboundMessage,
    ) -> bool:
        try:
            await draft_session.update(text)
        except DraftRateLimitedError as exc:
            self.logger.warning(
                log_kv(
                    "draft_rate_limited",
                    update_id=message.update_id,
                    chat_id=message.chat_id,
                    user_id=message.user_id,
                    draft_id=draft_session.draft_id,
                    retry_after=exc.retry_after,
                ),
                exc_info=True,
            )
            return False
        except Exception:
            self.logger.warning(
                log_kv(
                    "draft_update_failed",
                    update_id=message.update_id,
                    chat_id=message.chat_id,
                    user_id=message.user_id,
                    draft_id=draft_session.draft_id,
                ),
                exc_info=True,
            )
            return False

        self.logger.info(
            log_kv(
                "draft_updated",
                update_id=message.update_id,
                chat_id=message.chat_id,
                user_id=message.user_id,
                draft_id=draft_session.draft_id,
                text_length=len(text),
            )
        )
        return True

    async def _finish_draft_session(
        self,
        *,
        draft_session: DraftSession,
        message: InboundMessage,
    ) -> None:
        try:
            await draft_session.finish()
        except Exception:
            self.logger.warning(
                log_kv(
                    "draft_finish_failed",
                    update_id=message.update_id,
                    chat_id=message.chat_id,
                    user_id=message.user_id,
                    draft_id=draft_session.draft_id,
                ),
                exc_info=True,
            )

    async def _cancel_draft_session(
        self,
        *,
        draft_session: DraftSession,
        message: InboundMessage,
    ) -> None:
        try:
            await draft_session.cancel()
        except Exception:
            self.logger.warning(
                log_kv(
                    "draft_cancel_failed",
                    update_id=message.update_id,
                    chat_id=message.chat_id,
                    user_id=message.user_id,
                    draft_id=draft_session.draft_id,
                ),
                exc_info=True,
            )
