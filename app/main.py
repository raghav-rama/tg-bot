from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from pydantic import ValidationError as SettingsValidationError

from app.api.health import router as health_router
from app.api.webhook import router as webhook_router
from app.config import Settings
from app.domain.services import ChatService
from app.logging import configure_logging, log_kv
from app.providers.base import AIProvider, ImageGenerator, VideoGenerator
from app.providers.openai_provider import OpenAIProvider
from app.providers.vertex_image_provider import VertexImageProvider
from app.providers.vertex_video_provider import VertexVideoProvider
from app.storage.conversations import ConversationRepository
from app.storage.db import Database
from app.storage.generation_jobs import GenerationJobRepository
from app.storage.generated_images import GeneratedImageRepository
from app.storage.messages import MessageRepository
from app.telegram.drafts import TelegramResponseEmitter
from app.telegram.handlers import TelegramUpdateProcessor
from app.telegram.polling import TelegramRuntime
from app.workers.video_jobs import VideoJobWorker


@dataclass(slots=True)
class AppContainer:
    settings: Settings | None = None
    database: Database | None = None
    conversations: ConversationRepository | None = None
    messages: MessageRepository | None = None
    generated_images: GeneratedImageRepository | None = None
    generation_jobs: GenerationJobRepository | None = None
    provider: AIProvider | None = None
    image_generator: ImageGenerator | None = None
    video_generator: VideoGenerator | None = None
    chat_service: ChatService | None = None
    telegram_runtime: TelegramRuntime | None = None
    video_job_worker: VideoJobWorker | None = None
    startup_error: str | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    logger = logging.getLogger("app.main")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = AppContainer()
        app.state.container = container
        configure_logging("INFO")

        try:
            loaded_settings = settings or Settings()
            configure_logging(loaded_settings.app_log_level)

            database = Database(loaded_settings.sqlite_path)
            await database.connect()
            await database.initialize()

            conversations = ConversationRepository(database)
            messages = MessageRepository(database)
            generated_images = GeneratedImageRepository(database)
            generation_jobs = GenerationJobRepository(database)
            provider = OpenAIProvider(
                api_key=loaded_settings.openai_api_key.get_secret_value(),
                timeout_seconds=loaded_settings.openai_timeout_seconds,
            )
            image_generator = None
            if loaded_settings.vertex_image_generation_enabled:
                image_generator = VertexImageProvider(
                    api_key=(
                        loaded_settings.vertex_api_key.get_secret_value()
                        if loaded_settings.vertex_api_key is not None
                        else None
                    ),
                    project=loaded_settings.vertex_project_id or "",
                    location=loaded_settings.vertex_location,
                    default_model=loaded_settings.vertex_image_model,
                    default_aspect_ratio=loaded_settings.vertex_image_aspect_ratio,
                    default_output_mime_type=loaded_settings.vertex_image_output_mime_type,
                )
            video_generator = None
            if loaded_settings.vertex_video_generation_enabled:
                video_generator = VertexVideoProvider(
                    api_key=(
                        loaded_settings.vertex_api_key.get_secret_value()
                        if loaded_settings.vertex_api_key is not None
                        else None
                    ),
                    project=loaded_settings.vertex_project_id or "",
                    location=loaded_settings.vertex_location,
                    default_model=loaded_settings.vertex_video_model,
                    default_aspect_ratio=loaded_settings.vertex_video_aspect_ratio,
                    default_duration_seconds=loaded_settings.vertex_video_duration_seconds,
                    default_output_gcs_uri=loaded_settings.vertex_video_output_gcs_uri,
                )
            chat_service = ChatService(
                settings=loaded_settings,
                conversations=conversations,
                messages=messages,
                provider=provider,
                generated_images=generated_images,
                image_generator=image_generator,
                generation_jobs=generation_jobs,
                video_generator=video_generator,
            )
            processor = TelegramUpdateProcessor(
                chat_service=chat_service,
                settings=loaded_settings,
            )
            telegram_runtime = TelegramRuntime(
                token=loaded_settings.telegram_bot_token,
                processor=processor,
            )
            if loaded_settings.app_update_mode == "polling":
                await telegram_runtime.start()
            else:
                await telegram_runtime.configure_webhook(
                    url=loaded_settings.telegram_webhook_url or "",
                    secret_token=(
                        loaded_settings.telegram_webhook_secret_token.get_secret_value()
                        if loaded_settings.telegram_webhook_secret_token is not None
                        else ""
                    ),
                    drop_pending_updates=(
                        loaded_settings.telegram_webhook_drop_pending_updates
                    ),
                )
            video_job_worker = None
            if video_generator is not None:
                video_job_worker = VideoJobWorker(
                    settings=loaded_settings,
                    conversations=conversations,
                    messages=messages,
                    generation_jobs=generation_jobs,
                    video_generator=video_generator,
                    emitter_factory=lambda chat_id: TelegramResponseEmitter(
                        bot=telegram_runtime.bot,
                        chat_id=chat_id,
                        video_request_timeout_seconds=(
                            loaded_settings.telegram_video_request_timeout_seconds
                        ),
                    ),
                )
                await video_job_worker.start()

            container = AppContainer(
                settings=loaded_settings,
                database=database,
                conversations=conversations,
                messages=messages,
                generated_images=generated_images,
                generation_jobs=generation_jobs,
                provider=provider,
                image_generator=image_generator,
                video_generator=video_generator,
                chat_service=chat_service,
                telegram_runtime=telegram_runtime,
                video_job_worker=video_job_worker,
            )
            app.state.container = container
            logger.info(
                log_kv(
                    "application_started",
                    update_mode=loaded_settings.app_update_mode,
                    webhook_url=(
                        telegram_runtime.webhook_url
                        if loaded_settings.app_update_mode == "webhook"
                        else None
                    ),
                    model=loaded_settings.openai_model,
                    video_generation_enabled=loaded_settings.vertex_video_generation_enabled,
                    video_model=(
                        loaded_settings.vertex_video_model
                        if loaded_settings.vertex_video_generation_enabled
                        else None
                    ),
                    video_output_gcs_uri=loaded_settings.vertex_video_output_gcs_uri,
                    video_poll_interval_seconds=loaded_settings.video_job_poll_interval_seconds,
                )
            )
        except SettingsValidationError as exc:
            container.startup_error = str(exc)
            logger.error(log_kv("settings_validation_failed", error_type="ValidationError"))
            app.state.container = container
        except Exception as exc:
            container.startup_error = str(exc)
            logger.exception(
                log_kv("application_startup_failed", error_type=type(exc).__name__)
            )
            app.state.container = container

        try:
            yield
        finally:
            shutdown_container: AppContainer = app.state.container
            if shutdown_container.video_job_worker is not None:
                await shutdown_container.video_job_worker.close()
            if shutdown_container.telegram_runtime is not None:
                await shutdown_container.telegram_runtime.close()
            if shutdown_container.provider is not None:
                await shutdown_container.provider.close()
            if shutdown_container.image_generator is not None:
                await shutdown_container.image_generator.close()
            if shutdown_container.video_generator is not None:
                await shutdown_container.video_generator.close()
            if shutdown_container.database is not None:
                await shutdown_container.database.close()

    app = FastAPI(lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(webhook_router)
    return app


app = create_app()
