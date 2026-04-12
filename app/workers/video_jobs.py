from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from app.config import Settings
from app.domain.commands import (
    VIDEO_GENERATION_READY_TEXT,
    VIDEO_GENERATION_RETRY_TEXT,
    VIDEO_GENERATION_TOO_LARGE_TEXT,
)
from app.domain.errors import ProviderTimeoutError, ProviderUpstreamError
from app.domain.interfaces import ResponseEmitter
from app.domain.models import StoredGenerationJob, VideoGenerationPollRequest
from app.logging import log_kv
from app.providers.base import VideoGenerator
from app.storage.conversations import ConversationRepository
from app.storage.generation_jobs import GenerationJobRepository
from app.storage.messages import MessageRepository


class VideoJobWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        conversations: ConversationRepository,
        messages: MessageRepository,
        generation_jobs: GenerationJobRepository,
        video_generator: VideoGenerator,
        emitter_factory: Callable[[int], ResponseEmitter],
    ) -> None:
        self.settings = settings
        self.conversations = conversations
        self.messages = messages
        self.generation_jobs = generation_jobs
        self.video_generator = video_generator
        self.emitter_factory = emitter_factory
        self.logger = logging.getLogger("app.workers.video_jobs")
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop(), name="video-job-worker")
        await asyncio.sleep(0)

    async def close(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def run_once(self) -> int:
        jobs = await self.generation_jobs.list_pending_video_jobs()
        if jobs:
            self.logger.debug(
                log_kv(
                    "video_job_scan_found_jobs",
                    pending_jobs=len(jobs),
                )
            )
        for job in jobs:
            await self._process_job(job)
        return len(jobs)

    async def _run_loop(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self.settings.video_job_poll_interval_seconds)

    async def _process_job(self, job: StoredGenerationJob) -> None:
        self.logger.info(
            log_kv(
                "video_job_processing_started",
                job_id=job.id,
                chat_id=job.chat_id,
                operation_name=job.operation_name,
                status=job.status,
                model=job.model,
            )
        )
        if job.status == "queued":
            await self.generation_jobs.mark_running(job.id)
            self.logger.info(
                log_kv(
                    "video_job_marked_running",
                    job_id=job.id,
                    chat_id=job.chat_id,
                    operation_name=job.operation_name,
                )
            )

        try:
            poll_result = await self.video_generator.poll_video(
                VideoGenerationPollRequest(
                    operation_name=job.operation_name,
                    prompt=job.prompt_text,
                    model=job.model,
                )
            )
        except (ProviderTimeoutError, ProviderUpstreamError) as exc:
            self.logger.warning(
                log_kv(
                    "video_job_poll_retry",
                    job_id=job.id,
                    chat_id=job.chat_id,
                    operation_name=job.operation_name,
                    error_type=type(exc).__name__,
                )
            )
            return
        except Exception:
            self.logger.exception(
                log_kv(
                    "video_job_poll_failed",
                    job_id=job.id,
                    chat_id=job.chat_id,
                    operation_name=job.operation_name,
                    error_type="UnhandledError",
                )
            )
            return

        if poll_result.status == "running":
            await self.generation_jobs.mark_running(job.id)
            self.logger.debug(
                log_kv(
                    "video_job_still_running",
                    job_id=job.id,
                    chat_id=job.chat_id,
                    operation_name=job.operation_name,
                )
            )
            return

        if poll_result.status == "failed":
            failure_reason = poll_result.failure_reason or "Video generation failed"
            await self.generation_jobs.mark_failed(
                job_id=job.id,
                failure_reason=failure_reason,
            )
            await self._send_status_text(
                job=job,
                text=VIDEO_GENERATION_RETRY_TEXT,
                log_event="video_job_failed",
                log_reason=failure_reason,
            )
            await self.conversations.touch(job.conversation_id)
            return

        generated_video = poll_result.generated_video
        if generated_video is None:
            await self.generation_jobs.mark_failed(
                job_id=job.id,
                failure_reason="Video generation completed without a video payload",
            )
            await self._send_status_text(
                job=job,
                text=VIDEO_GENERATION_RETRY_TEXT,
                log_event="video_job_empty_payload",
                log_reason="missing_generated_video",
            )
            await self.conversations.touch(job.conversation_id)
            return

        video_size = generated_video.file_size or len(generated_video.video_bytes)
        self.logger.info(
            log_kv(
                "video_job_generation_ready",
                job_id=job.id,
                chat_id=job.chat_id,
                operation_name=job.operation_name,
                output_uri=generated_video.output_uri,
                mime_type=generated_video.mime_type,
                file_size=video_size,
            )
        )
        if video_size > self.settings.bot_video_max_bytes:
            await self.generation_jobs.mark_failed(
                job_id=job.id,
                failure_reason="Generated video exceeded the Telegram size limit",
            )
            await self._send_status_text(
                job=job,
                text=VIDEO_GENERATION_TOO_LARGE_TEXT,
                log_event="video_job_too_large",
                log_reason=str(video_size),
            )
            await self.conversations.touch(job.conversation_id)
            return

        emitter = self.emitter_factory(job.chat_id)
        try:
            self.logger.info(
                log_kv(
                    "video_job_delivery_started",
                    job_id=job.id,
                    chat_id=job.chat_id,
                    operation_name=job.operation_name,
                    mime_type=generated_video.mime_type,
                    output_uri=generated_video.output_uri,
                    duration_seconds=generated_video.duration_seconds,
                    width=generated_video.width,
                    height=generated_video.height,
                    file_size=video_size,
                    request_timeout_seconds=(
                        self.settings.telegram_video_request_timeout_seconds
                    ),
                )
            )
            sent_video = await emitter.send_video(generated_video)
        except Exception as exc:
            failure_reason = self._format_delivery_failure_reason(exc)
            self.logger.exception(
                log_kv(
                    "video_job_delivery_exception",
                    job_id=job.id,
                    chat_id=job.chat_id,
                    operation_name=job.operation_name,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    request_timeout_seconds=(
                        self.settings.telegram_video_request_timeout_seconds
                    ),
                )
            )
            await self.generation_jobs.mark_failed(
                job_id=job.id,
                failure_reason=failure_reason,
            )
            await self._send_status_text(
                job=job,
                text=VIDEO_GENERATION_RETRY_TEXT,
                log_event="video_delivery_failed",
                log_reason=failure_reason,
            )
            await self.conversations.touch(job.conversation_id)
            return

        self.logger.info(
            log_kv(
                "video_job_delivery_succeeded",
                job_id=job.id,
                chat_id=job.chat_id,
                operation_name=job.operation_name,
                telegram_message_id=sent_video.telegram_message_id,
                telegram_file_id=sent_video.telegram_file_id,
                file_size=sent_video.file_size or video_size,
            )
        )

        try:
            await emitter.send_text(VIDEO_GENERATION_READY_TEXT)
        except Exception:
            self.logger.warning(
                log_kv(
                    "video_ready_message_failed",
                    job_id=job.id,
                    chat_id=job.chat_id,
                    operation_name=job.operation_name,
                ),
                exc_info=True,
            )
        else:
            await self.messages.add_assistant_message(
                conversation_id=job.conversation_id,
                provider_message_id=None,
                text=VIDEO_GENERATION_READY_TEXT,
                message_type="command",
            )

        await self.messages.add_assistant_message(
            conversation_id=job.conversation_id,
            provider_message_id=None,
            text=None,
            message_type="generated_video",
        )
        await self.generation_jobs.mark_completed(
            job_id=job.id,
            output_uri=generated_video.output_uri,
            mime_type=generated_video.mime_type,
            telegram_message_id=sent_video.telegram_message_id,
            telegram_file_id=sent_video.telegram_file_id,
            telegram_file_unique_id=sent_video.telegram_file_unique_id,
            width=sent_video.width,
            height=sent_video.height,
            duration_seconds=sent_video.duration_seconds,
            file_size=sent_video.file_size or video_size,
        )
        await self.conversations.touch(job.conversation_id)
        self.logger.info(
            log_kv(
                "video_job_completed",
                job_id=job.id,
                chat_id=job.chat_id,
                operation_name=job.operation_name,
            )
        )

    async def _send_status_text(
        self,
        *,
        job: StoredGenerationJob,
        text: str,
        log_event: str,
        log_reason: str,
    ) -> None:
        emitter = self.emitter_factory(job.chat_id)
        try:
            await emitter.send_text(text)
        except Exception:
            self.logger.warning(
                log_kv(
                    "video_status_message_failed",
                    job_id=job.id,
                    chat_id=job.chat_id,
                    operation_name=job.operation_name,
                    reason=log_reason,
                ),
                exc_info=True,
            )
        else:
            await self.messages.add_assistant_message(
                conversation_id=job.conversation_id,
                provider_message_id=None,
                text=text,
                message_type="command",
            )

        self.logger.warning(
            log_kv(
                log_event,
                job_id=job.id,
                chat_id=job.chat_id,
                operation_name=job.operation_name,
                reason=log_reason,
            )
        )

    @staticmethod
    def _format_delivery_failure_reason(exc: Exception) -> str:
        reason = f"Telegram video delivery failed: {type(exc).__name__}: {exc}"
        return reason[:500]
