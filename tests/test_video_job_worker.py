from __future__ import annotations

from datetime import datetime, timezone

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
