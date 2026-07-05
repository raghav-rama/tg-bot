from __future__ import annotations

from datetime import datetime, timezone

from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SendVideo

from app.domain.errors import ProviderUpstreamError
from app.domain.models import InboundMessage, SentPhoto, SentVideo, VideoJobPollResult
from app.workers.video_jobs import VideoJobWorker


def utc_datetime() -> datetime:
    return datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc)


def make_command_message(*, user_id: int, chat_id: int, command: str, update_id: int = 1) -> InboundMessage:
    command_name = command.split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()
    return InboundMessage(
        update_id=update_id,
        telegram_message_id=update_id,
        chat_id=chat_id,
        chat_type="private",
        user_id=user_id,
        username="ritz",
        first_name="Ritz",
        message_type="command",
        text=command,
        command=command_name,
        image=None,
        sent_at=utc_datetime(),
    )


class RecordingEmitter:
    def __init__(self) -> None:
        self.sent_texts: list[str] = []
        self.sent_videos: list[bytes] = []

    async def send_text(self, text: str) -> None:
        self.sent_texts.append(text)

    async def send_photo(self, image) -> SentPhoto:
        raise AssertionError("send_photo should not be used in video job worker tests")

    async def send_video(self, video) -> SentVideo:
        self.sent_videos.append(video.video_bytes)
        return SentVideo(
            telegram_message_id=9500,
            telegram_file_id="tg-video-9500",
            telegram_file_unique_id="tg-video-uniq-9500",
            width=1280,
            height=720,
            duration_seconds=4,
            mime_type="video/mp4",
            file_size=len(video.video_bytes),
        )

    async def open_draft(self):
        raise AssertionError("open_draft should not be used in video job worker tests")


class FailingVideoEmitter(RecordingEmitter):
    async def send_video(self, video) -> SentVideo:
        raise TelegramNetworkError(
            method=SendVideo(chat_id=500, video="attach://video"),
            message="Request timeout error",
        )


async def test_worker_completes_video_job_and_delivers_video(service_bundle) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    messages = service_bundle["messages"]
    generation_jobs = service_bundle["generation_jobs"]
    settings = service_bundle["settings"]
    video_generator = service_bundle["video_generator"]

    await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=500,
            command="/video slow orbit around a crystal sculpture in morning fog",
            update_id=1,
        )
    )
    conversation = await conversations.get_active(500)
    assert conversation is not None

    emitter = RecordingEmitter()
    worker = VideoJobWorker(
        settings=settings,
        conversations=conversations,
        messages=messages,
        generation_jobs=generation_jobs,
        video_generator=video_generator,
        emitter_factory=lambda _chat_id: emitter,
    )

    processed = await worker.run_once()
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)
    stored_messages = await messages.list_for_conversation(conversation.id)

    assert processed == 1
    assert video_generator.poll_calls[0].provider == "vertex"
    assert emitter.sent_videos == [b"generated-video"]
    assert emitter.sent_texts == ["Your video is ready."]
    assert stored_jobs[0].status == "completed"
    assert stored_jobs[0].telegram_file_id == "tg-video-9500"
    assert [message.message_type for message in stored_messages] == [
        "command",
        "command",
        "command",
        "generated_video",
    ]


async def test_worker_completes_runpod_job_by_persisted_provider(service_bundle) -> None:
    conversations = service_bundle["conversations"]
    messages = service_bundle["messages"]
    generation_jobs = service_bundle["generation_jobs"]
    settings = service_bundle["settings"]
    video_generator = service_bundle["video_generator"]
    conversation = await conversations.get_or_create_active(505)
    await generation_jobs.add_video_job(
        conversation_id=conversation.id,
        chat_id=505,
        user_id=42,
        prompt_text="simple cinematic shot of clouds over a valley",
        provider="runpod",
        model=settings.runpod_video_model,
        operation_name="runpod-job-1",
        duration_seconds=4,
        created_at=utc_datetime(),
    )

    emitter = RecordingEmitter()
    worker = VideoJobWorker(
        settings=settings,
        conversations=conversations,
        messages=messages,
        generation_jobs=generation_jobs,
        video_generator=video_generator,
        emitter_factory=lambda _chat_id: emitter,
    )

    await worker.run_once()
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)

    assert video_generator.poll_calls[0].provider == "runpod"
    assert emitter.sent_videos == [b"generated-video"]
    assert stored_jobs[0].status == "completed"
    assert stored_jobs[0].provider == "runpod"


async def test_worker_does_not_log_still_running_poll_at_info(
    service_bundle,
    caplog,
) -> None:
    conversations = service_bundle["conversations"]
    messages = service_bundle["messages"]
    generation_jobs = service_bundle["generation_jobs"]
    settings = service_bundle["settings"]
    video_generator = service_bundle["video_generator"]
    conversation = await conversations.get_or_create_active(506)
    job_id = await generation_jobs.add_video_job(
        conversation_id=conversation.id,
        chat_id=506,
        user_id=42,
        prompt_text="simple cinematic shot of clouds over a valley",
        provider="runpod",
        model=settings.runpod_video_model,
        operation_name="runpod-job-running",
        duration_seconds=4,
        created_at=utc_datetime(),
    )
    await generation_jobs.mark_running(job_id)
    video_generator.poll_results = [
        VideoJobPollResult(
            status="running",
            operation_name="runpod-job-running",
        )
    ]

    emitter = RecordingEmitter()
    worker = VideoJobWorker(
        settings=settings,
        conversations=conversations,
        messages=messages,
        generation_jobs=generation_jobs,
        video_generator=video_generator,
        emitter_factory=lambda _chat_id: emitter,
    )

    with caplog.at_level("INFO", logger="app.workers.video_jobs"):
        await worker.run_once()

    assert "video_job_processing_started" not in caplog.text
    assert "video_job_still_running" not in caplog.text
    assert video_generator.poll_calls[0].provider == "runpod"


async def test_worker_logs_completion_usage_and_cost_estimate(
    service_bundle,
    caplog,
) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]
    settings = service_bundle["settings"]
    video_generator = service_bundle["video_generator"]

    settings.vertex_video_cost_per_second_usd = 0.35
    await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=504,
            command="/video slow orbit around a crystal sculpture in morning fog",
            update_id=5,
        )
    )
    conversation = await conversations.get_active(504)
    assert conversation is not None

    emitter = RecordingEmitter()
    worker = VideoJobWorker(
        settings=settings,
        conversations=conversations,
        messages=service_bundle["messages"],
        generation_jobs=generation_jobs,
        video_generator=video_generator,
        emitter_factory=lambda _chat_id: emitter,
    )

    with caplog.at_level("INFO", logger="app.workers.video_jobs"):
        await worker.run_once()

    assert "video_job_completed" in caplog.text
    assert "provider=vertex" in caplog.text
    assert "model=veo-3.0-fast-generate-001" in caplog.text
    assert "duration_seconds=4" in caplog.text
    assert "file_size=" in caplog.text
    assert "cost_estimate_available=True" in caplog.text
    assert "cost_estimated_usd=1.4" in caplog.text


async def test_worker_marks_job_failed_when_generation_fails(service_bundle) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]
    settings = service_bundle["settings"]
    video_generator = service_bundle["video_generator"]

    await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=501,
            command="/video rain hitting a train window at dusk",
            update_id=2,
        )
    )
    conversation = await conversations.get_active(501)
    assert conversation is not None

    video_generator.poll_results = [
        VideoJobPollResult(
            status="failed",
            operation_name="operations/1",
            failure_reason="quota exceeded",
        )
    ]
    emitter = RecordingEmitter()
    worker = VideoJobWorker(
        settings=settings,
        conversations=conversations,
        messages=service_bundle["messages"],
        generation_jobs=generation_jobs,
        video_generator=video_generator,
        emitter_factory=lambda _chat_id: emitter,
    )

    await worker.run_once()
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)

    assert emitter.sent_videos == []
    assert emitter.sent_texts == [
        "I couldn't generate a video just now. Please try again in a moment."
    ]
    assert stored_jobs[0].status == "failed"
    assert stored_jobs[0].failure_reason == "quota exceeded"


async def test_worker_rejects_video_larger_than_telegram_limit(service_bundle) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]
    settings = service_bundle["settings"]
    video_generator = service_bundle["video_generator"]

    await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=502,
            command="/video giant storm rolling over a city skyline",
            update_id=3,
        )
    )
    conversation = await conversations.get_active(502)
    assert conversation is not None

    settings.bot_video_max_bytes = 4
    emitter = RecordingEmitter()
    worker = VideoJobWorker(
        settings=settings,
        conversations=conversations,
        messages=service_bundle["messages"],
        generation_jobs=generation_jobs,
        video_generator=video_generator,
        emitter_factory=lambda _chat_id: emitter,
    )

    await worker.run_once()
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)

    assert emitter.sent_videos == []
    assert emitter.sent_texts == [
        "The generated video is too large to send through Telegram right now. Please try a shorter prompt."
    ]
    assert stored_jobs[0].status == "failed"
    assert stored_jobs[0].failure_reason == "Generated video exceeded the Telegram size limit"


async def test_worker_logs_and_persists_delivery_exception_details(
    service_bundle,
    caplog,
) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]
    settings = service_bundle["settings"]
    video_generator = service_bundle["video_generator"]

    await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=503,
            command="/video slow cinematic dolly shot through a rainy neon alley",
            update_id=4,
        )
    )
    conversation = await conversations.get_active(503)
    assert conversation is not None

    worker = VideoJobWorker(
        settings=settings,
        conversations=conversations,
        messages=service_bundle["messages"],
        generation_jobs=generation_jobs,
        video_generator=video_generator,
        emitter_factory=lambda _chat_id: FailingVideoEmitter(),
    )

    with caplog.at_level("INFO"):
        await worker.run_once()

    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)

    assert stored_jobs[0].status == "failed"
    assert (
        stored_jobs[0].failure_reason
        == "Telegram video delivery failed: TelegramNetworkError: HTTP Client says - Request timeout error"
    )
    assert "video_job_delivery_exception" in caplog.text
    assert "error_type=TelegramNetworkError" in caplog.text
    assert "Request timeout error" in caplog.text


async def test_worker_uses_fal_cost_rate_for_fal_jobs(service_bundle) -> None:
    settings = service_bundle["settings"]
    worker = VideoJobWorker(
        settings=settings,
        conversations=service_bundle["conversations"],
        messages=service_bundle["messages"],
        generation_jobs=service_bundle["generation_jobs"],
        video_generator=service_bundle["video_generator"],
        emitter_factory=lambda _chat_id: RecordingEmitter(),
    )
    settings.fal_video_cost_per_second_usd = 0.42
    settings.vertex_video_cost_per_second_usd = 0.10
    settings.runpod_video_cost_per_second_usd = 0.20

    assert worker._video_cost_for_provider("fal") == 0.42
    assert worker._video_cost_for_provider("runpod") == 0.20
    assert worker._video_cost_for_provider("vertex") == 0.10


async def test_worker_completes_fal_job_and_delivers_video(service_bundle) -> None:
    settings = service_bundle["settings"]
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    messages = service_bundle["messages"]
    generation_jobs = service_bundle["generation_jobs"]
    video_generator = service_bundle["video_generator"]
    preferences = service_bundle["preferences"]

    settings.fal_api_key = "fake-fal-key"
    settings.fal_video_model = "fal-ai/kling-video/v3/standard/text-to-video"
    settings.video_provider_order = ("fal",)
    await preferences.set_preference(
        chat_id=510,
        user_id=42,
        preference_type="video_provider",
        preset_id="fal",
        updated_at=utc_datetime(),
    )

    await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=510,
            command="/video tracking shot through a luminous underground cave",
            update_id=10,
        )
    )
    conversation = await conversations.get_active(510)
    assert conversation is not None

    emitter = RecordingEmitter()
    worker = VideoJobWorker(
        settings=settings,
        conversations=conversations,
        messages=messages,
        generation_jobs=generation_jobs,
        video_generator=video_generator,
        emitter_factory=lambda _chat_id: emitter,
    )

    processed = await worker.run_once()
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)

    assert processed == 1
    assert video_generator.submit_calls[0].provider_hint == "fal"
    assert video_generator.submit_calls[0].model == "fal-ai/kling-video/v3/standard/text-to-video"
    assert video_generator.poll_calls[0].provider == "fal"
    assert emitter.sent_videos == [b"generated-video"]
    assert emitter.sent_texts == ["Your video is ready."]
    assert stored_jobs[0].status == "completed"
    assert stored_jobs[0].provider == "fal"
    assert stored_jobs[0].model == "fal-ai/kling-video/v3/standard/text-to-video"
    assert stored_jobs[0].telegram_file_id == "tg-video-9500"
    assert stored_jobs[0].output_uri is None


async def test_worker_marks_fal_job_failed_on_poll_failure(service_bundle) -> None:
    settings = service_bundle["settings"]
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    messages = service_bundle["messages"]
    generation_jobs = service_bundle["generation_jobs"]
    video_generator = service_bundle["video_generator"]
    preferences = service_bundle["preferences"]

    settings.fal_api_key = "fake-fal-key"
    settings.fal_video_model = "fal-ai/kling-video/v3/standard/text-to-video"
    settings.video_provider_order = ("fal",)
    await preferences.set_preference(
        chat_id=511,
        user_id=42,
        preference_type="video_provider",
        preset_id="fal",
        updated_at=utc_datetime(),
    )
    video_generator.poll_results = [
        VideoJobPollResult(
            status="failed",
            operation_name="operations/1",
            failure_reason="Fal capacity exhausted",
        ),
    ]

    await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=511,
            command="/video ocean waves crashing against black volcanic rock",
            update_id=11,
        )
    )
    conversation = await conversations.get_active(511)
    assert conversation is not None

    emitter = RecordingEmitter()
    worker = VideoJobWorker(
        settings=settings,
        conversations=conversations,
        messages=messages,
        generation_jobs=generation_jobs,
        video_generator=video_generator,
        emitter_factory=lambda _chat_id: emitter,
    )

    processed = await worker.run_once()
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)

    assert processed == 1
    assert video_generator.submit_calls[0].provider_hint == "fal"
    assert video_generator.poll_calls[0].provider == "fal"
    assert emitter.sent_videos == []
    assert [
        text for text in emitter.sent_texts
        if "couldn't generate a video" in text
    ]
    assert stored_jobs[0].status == "failed"
    assert "Fal capacity exhausted" in (stored_jobs[0].failure_reason or "")
