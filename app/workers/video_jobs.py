from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timezone

from app.config import Settings
from app.domain.commands import (
    IMAGE_GENERATION_RETRY_TEXT,
    VIDEO_GENERATION_READY_TEXT,
    VIDEO_GENERATION_RETRY_TEXT,
    VIDEO_GENERATION_TOO_LARGE_TEXT,
)
from app.domain.errors import ProviderTimeoutError, ProviderUpstreamError, StorageError
from app.domain.interfaces import ResponseEmitter
from app.domain.job_payloads import (
    deserialize_image_generation_request,
    deserialize_video_generation_request,
)
from app.domain.models import (
    GeneratedImageResult,
    ImageInput,
    StoredGenerationJob,
    VideoGenerationPollRequest,
)
from app.logging import log_kv
from app.observability import estimate_video_usage
from app.providers.base import ImageGenerator, VideoGenerator
from app.storage.conversations import ConversationRepository
from app.storage.generation_jobs import GenerationJobRepository
from app.storage.generated_images import GeneratedImageRepository
from app.storage.messages import MessageRepository


class VideoJobWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        conversations: ConversationRepository,
        messages: MessageRepository,
        generation_jobs: GenerationJobRepository,
        emitter_factory: Callable[[int], ResponseEmitter],
        generated_images: GeneratedImageRepository | None = None,
        image_generator: ImageGenerator | None = None,
        video_generator: VideoGenerator | None = None,
        reference_image_downloader: Callable[[str], Awaitable[bytes]] | None = None,
    ) -> None:
        self.settings = settings
        self.conversations = conversations
        self.messages = messages
        self.generation_jobs = generation_jobs
        self.generated_images = generated_images
        self.image_generator = image_generator
        self.video_generator = video_generator
        self.emitter_factory = emitter_factory
        self.reference_image_downloader = reference_image_downloader
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
        jobs = await self.generation_jobs.list_pending_jobs()
        if jobs:
            self.logger.debug(
                log_kv(
                    "media_job_scan_found_jobs",
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
        if job.job_type == "image":
            await self._process_image_job(job)
            return
        await self._process_video_job(job)

    async def _process_image_job(self, job: StoredGenerationJob) -> None:
        self.logger.debug(
            log_kv(
                "image_job_processing_started",
                job_id=job.id,
                chat_id=job.chat_id,
                operation_name=self._provider_operation_name(job),
                status=job.status,
                model=job.model,
            )
        )
        if self.image_generator is None:
            await self._fail_job(
                job=job,
                failure_reason="Image generator is not configured",
                text=IMAGE_GENERATION_RETRY_TEXT,
                log_event="image_job_not_configured",
            )
            return
        if job.request_payload is None:
            await self._fail_job(
                job=job,
                failure_reason="Image job is missing request payload",
                text=IMAGE_GENERATION_RETRY_TEXT,
                log_event="image_job_missing_payload",
            )
            return

        request = deserialize_image_generation_request(job.request_payload)
        request = replace(
            request,
            reference_image=await self._hydrate_reference_image(request.reference_image),
        )
        await self.generation_jobs.mark_running(job.id)
        try:
            generated_image = await self.image_generator.generate_image(request)
        except (ProviderTimeoutError, ProviderUpstreamError) as exc:
            self.logger.warning(
                log_kv(
                    "image_job_generation_failed",
                    job_id=job.id,
                    chat_id=job.chat_id,
                    operation_name=job.operation_name,
                    error_type=type(exc).__name__,
                )
            )
            await self._fail_job(
                job=job,
                failure_reason=f"Image generation failed: {type(exc).__name__}",
                text=IMAGE_GENERATION_RETRY_TEXT,
                log_event="image_job_failed",
            )
            return
        except Exception:
            self.logger.exception(
                log_kv(
                    "image_job_generation_exception",
                    job_id=job.id,
                    chat_id=job.chat_id,
                    operation_name=job.operation_name,
                )
            )
            await self._fail_job(
                job=job,
                failure_reason="Image generation failed",
                text=IMAGE_GENERATION_RETRY_TEXT,
                log_event="image_job_failed",
            )
            return

        emitter = self.emitter_factory(job.chat_id)
        try:
            sent_photo = await emitter.send_photo(generated_image)
        except Exception as exc:
            await self._fail_job(
                job=job,
                failure_reason=self._format_delivery_failure_reason(
                    prefix="Telegram image delivery failed",
                    exc=exc,
                ),
                text=IMAGE_GENERATION_RETRY_TEXT,
                log_event="image_delivery_failed",
            )
            return

        await self.messages.add_assistant_message(
            conversation_id=job.conversation_id,
            provider_message_id=None,
            text=None,
            message_type="generated_image",
        )
        if self.generated_images is not None:
            try:
                await self.generated_images.add_generated_image(
                    conversation_id=job.conversation_id,
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
                )
            except StorageError:
                self.logger.exception(
                    log_kv(
                        "generated_image_metadata_persist_failed",
                        job_id=job.id,
                        chat_id=job.chat_id,
                        provider=generated_image.provider,
                        model=generated_image.raw_model,
                    )
                )

        await self.generation_jobs.mark_completed(
            job_id=job.id,
            output_uri=None,
            mime_type=generated_image.mime_type,
            telegram_message_id=sent_photo.telegram_message_id,
            telegram_file_id=sent_photo.telegram_file_id,
            telegram_file_unique_id=sent_photo.telegram_file_unique_id,
            width=sent_photo.width,
            height=sent_photo.height,
            duration_seconds=None,
            file_size=sent_photo.file_size,
        )
        await self.conversations.touch(job.conversation_id)
        self.logger.info(
            log_kv(
                "image_job_completed",
                job_id=job.id,
                chat_id=job.chat_id,
                operation_name=self._provider_operation_name(job),
                provider=generated_image.provider,
                model=generated_image.raw_model,
                telegram_message_id=sent_photo.telegram_message_id,
                telegram_file_id=sent_photo.telegram_file_id,
            )
        )

    async def _process_video_job(self, job: StoredGenerationJob) -> None:
        age_seconds = self._job_age_seconds(job)
        if age_seconds > self.settings.video_job_max_age_seconds:
            await self._fail_job(
                job=job,
                failure_reason=(
                    f"Video generation abandoned after {int(age_seconds)}s "
                    "without a terminal provider result"
                ),
                text=VIDEO_GENERATION_RETRY_TEXT,
                log_event="video_job_abandoned",
            )
            return

        self.logger.debug(
            log_kv(
                "video_job_processing_started",
                job_id=job.id,
                chat_id=job.chat_id,
                operation_name=self._provider_operation_name(job),
                status=job.status,
                model=job.model,
            )
        )
        if self.video_generator is None:
            await self._fail_job(
                job=job,
                failure_reason="Video generator is not configured",
                text=VIDEO_GENERATION_RETRY_TEXT,
                log_event="video_job_not_configured",
            )
            return

        request = None
        if job.request_payload is not None:
            request = deserialize_video_generation_request(job.request_payload)
            if job.provider_operation_name is None:
                request = replace(
                    request,
                    reference_image=await self._hydrate_reference_image(
                        request.reference_image
                    ),
                )
                try:
                    submitted = await self.video_generator.submit_video(request)
                except (ProviderTimeoutError, ProviderUpstreamError) as exc:
                    await self._fail_job(
                        job=job,
                        failure_reason=(
                            f"Video job submission failed: {type(exc).__name__}"
                        ),
                        text=VIDEO_GENERATION_RETRY_TEXT,
                        log_event="video_job_submit_failed",
                    )
                    return
                except Exception:
                    self.logger.exception(
                        log_kv(
                            "video_job_submit_exception",
                            job_id=job.id,
                            chat_id=job.chat_id,
                        )
                    )
                    await self._fail_job(
                        job=job,
                        failure_reason="Video job submission failed",
                        text=VIDEO_GENERATION_RETRY_TEXT,
                        log_event="video_job_submit_failed",
                    )
                    return

                await self.generation_jobs.mark_submitted(
                    job_id=job.id,
                    provider=submitted.provider,
                    model=submitted.raw_model,
                    provider_operation_name=submitted.operation_name,
                )
                job = replace(
                    job,
                    provider=submitted.provider,
                    model=submitted.raw_model,
                    provider_operation_name=submitted.operation_name,
                    status="running",
                )
        elif job.status == "queued":
            await self.generation_jobs.mark_running(job.id)

        try:
            poll_result = await self.video_generator.poll_video(
                VideoGenerationPollRequest(
                    operation_name=self._provider_operation_name(job),
                    prompt=(request.prompt if request is not None else job.prompt_text),
                    model=job.model,
                    provider=job.provider,
                )
            )
        except (ProviderTimeoutError, ProviderUpstreamError) as exc:
            self.logger.warning(
                log_kv(
                    "video_job_poll_retry",
                    job_id=job.id,
                    chat_id=job.chat_id,
                    operation_name=self._provider_operation_name(job),
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
                    operation_name=self._provider_operation_name(job),
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
                    operation_name=self._provider_operation_name(job),
                )
            )
            return

        if poll_result.status == "failed":
            await self._fail_job(
                job=job,
                failure_reason=poll_result.failure_reason or "Video generation failed",
                text=VIDEO_GENERATION_RETRY_TEXT,
                log_event="video_job_failed",
            )
            return

        generated_video = poll_result.generated_video
        if generated_video is None:
            await self._fail_job(
                job=job,
                failure_reason="Video generation completed without a video payload",
                text=VIDEO_GENERATION_RETRY_TEXT,
                log_event="video_job_empty_payload",
            )
            return

        video_size = generated_video.file_size or len(generated_video.video_bytes)
        self.logger.info(
            log_kv(
                "video_job_generation_ready",
                job_id=job.id,
                chat_id=job.chat_id,
                operation_name=self._provider_operation_name(job),
                output_uri=generated_video.output_uri,
                mime_type=generated_video.mime_type,
                file_size=video_size,
            )
        )
        if video_size > self.settings.bot_video_max_bytes:
            await self._fail_job(
                job=job,
                failure_reason="Generated video exceeded the Telegram size limit",
                text=VIDEO_GENERATION_TOO_LARGE_TEXT,
                log_event="video_job_too_large",
            )
            return

        emitter = self.emitter_factory(job.chat_id)
        try:
            self.logger.info(
                log_kv(
                    "video_job_delivery_started",
                    job_id=job.id,
                    chat_id=job.chat_id,
                    operation_name=self._provider_operation_name(job),
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
            self.logger.exception(
                log_kv(
                    "video_job_delivery_exception",
                    job_id=job.id,
                    chat_id=job.chat_id,
                    operation_name=self._provider_operation_name(job),
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    request_timeout_seconds=(
                        self.settings.telegram_video_request_timeout_seconds
                    ),
                )
            )
            await self._fail_job(
                job=job,
                failure_reason=self._format_delivery_failure_reason(
                    prefix="Telegram video delivery failed",
                    exc=exc,
                ),
                text=VIDEO_GENERATION_RETRY_TEXT,
                log_event="video_delivery_failed",
            )
            return

        self.logger.info(
            log_kv(
                "video_job_delivery_succeeded",
                job_id=job.id,
                chat_id=job.chat_id,
                operation_name=self._provider_operation_name(job),
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
                    operation_name=self._provider_operation_name(job),
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
        delivered_duration_seconds = (
            sent_video.duration_seconds
            or generated_video.duration_seconds
            or job.duration_seconds
        )
        completed_usage_fields = estimate_video_usage(
            prompt=job.prompt_text,
            duration_seconds=delivered_duration_seconds,
            cost_per_second_usd=self._video_cost_for_provider(
                generated_video.provider or job.provider
            ),
        )
        self.logger.info(
            log_kv(
                "video_job_completed",
                job_id=job.id,
                chat_id=job.chat_id,
                operation_name=self._provider_operation_name(job),
                provider=generated_video.provider or job.provider,
                model=generated_video.raw_model or job.model,
                file_size=sent_video.file_size or video_size,
                **completed_usage_fields,
            )
        )

    async def _fail_job(
        self,
        *,
        job: StoredGenerationJob,
        failure_reason: str,
        text: str,
        log_event: str,
    ) -> None:
        await self.generation_jobs.mark_failed(
            job_id=job.id,
            failure_reason=failure_reason,
        )
        await self._send_status_text(
            job=job,
            text=text,
            log_event=log_event,
            log_reason=failure_reason,
        )
        await self.conversations.touch(job.conversation_id)

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
                    "media_status_message_failed",
                    job_id=job.id,
                    chat_id=job.chat_id,
                    operation_name=self._provider_operation_name(job),
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
                operation_name=self._provider_operation_name(job),
                reason=log_reason,
            )
        )

    async def _hydrate_reference_image(
        self,
        image: ImageInput | None,
    ) -> ImageInput | None:
        if image is None or image.bytes_b64 is not None:
            return image
        if self.reference_image_downloader is None:
            raise ProviderUpstreamError("Reference image downloader is not configured")
        image_bytes = await self.reference_image_downloader(image.telegram_file_id)
        if len(image_bytes) > self.settings.bot_image_max_bytes:
            raise ProviderUpstreamError("Reference image exceeds the configured size limit")
        return replace(
            image,
            byte_size=len(image_bytes),
            bytes_b64=base64.b64encode(image_bytes).decode("ascii"),
        )

    @staticmethod
    def _provider_operation_name(job: StoredGenerationJob) -> str:
        return job.provider_operation_name or job.operation_name

    @staticmethod
    def _job_age_seconds(job: StoredGenerationJob) -> float:
        created_at = job.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created_at).total_seconds()

    @staticmethod
    def _format_delivery_failure_reason(*, prefix: str, exc: Exception) -> str:
        reason = f"{prefix}: {type(exc).__name__}: {exc}"
        return reason[:500]

    def _video_cost_for_provider(self, provider: str) -> float:
        if provider == "runpod":
            return self.settings.runpod_video_cost_per_second_usd
        if provider == "fal":
            return self.settings.fal_video_cost_per_second_usd
        return self.settings.gemini_video_cost_per_second_usd
