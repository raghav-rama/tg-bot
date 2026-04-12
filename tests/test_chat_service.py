from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.config import Settings
from app.domain.commands import (
    ACCESS_DENIED_TEXT,
    IMAGE_GENERATION_RETRY_TEXT,
    VIDEO_GENERATION_RETRY_TEXT,
)
from app.domain.errors import DraftRateLimitedError, ProviderTimeoutError
from app.domain.models import (
    ImageInput,
    InboundMessage,
    SentPhoto,
    SentVideo,
    StreamingProviderEvent,
)


def utc_datetime() -> datetime:
    return datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc)


def make_text_message(*, user_id: int, chat_id: int, text: str, update_id: int = 1) -> InboundMessage:
    return InboundMessage(
        update_id=update_id,
        telegram_message_id=update_id,
        chat_id=chat_id,
        chat_type="private",
        user_id=user_id,
        username="ritz",
        first_name="Ritz",
        message_type="text",
        text=text,
        command=None,
        image=None,
        sent_at=utc_datetime(),
    )


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


def make_image_message(
    *,
    user_id: int,
    chat_id: int,
    caption: str | None,
    update_id: int = 1,
) -> InboundMessage:
    return InboundMessage(
        update_id=update_id,
        telegram_message_id=update_id,
        chat_id=chat_id,
        chat_type="private",
        user_id=user_id,
        username="ritz",
        first_name="Ritz",
        message_type="image",
        text=caption,
        command=None,
        image=ImageInput(
            telegram_file_id="file-1",
            telegram_file_unique_id="uniq-1",
            mime_type="image/jpeg",
            width=512,
            height=512,
            byte_size=8,
            bytes_b64="aW1hZ2U=",
            caption=caption,
        ),
        sent_at=utc_datetime(),
    )


class FakeDraftSession:
    def __init__(
        self,
        *,
        draft_id: int = 1,
        fail_on_update: bool = False,
        retry_after: int | None = None,
        updated_event: asyncio.Event | None = None,
    ) -> None:
        self.draft_id = draft_id
        self.fail_on_update = fail_on_update
        self.retry_after = retry_after
        self.updated_event = updated_event
        self.updates: list[str] = []
        self.finished = False
        self.cancelled = False

    async def update(self, text: str) -> None:
        if self.fail_on_update:
            raise RuntimeError("draft update failed")
        if self.retry_after is not None:
            raise DraftRateLimitedError(retry_after=self.retry_after)
        self.updates.append(text)
        if self.updated_event is not None:
            self.updated_event.set()

    async def finish(self) -> None:
        self.finished = True

    async def cancel(self) -> None:
        self.cancelled = True


class FakeResponseEmitter:
    def __init__(self, *, draft_session: FakeDraftSession | None = None) -> None:
        self.sent_texts: list[str] = []
        self.sent_photos: list[bytes] = []
        self.sent_videos: list[bytes] = []
        self.draft_session = draft_session or FakeDraftSession()
        self.open_calls = 0
        self.photo_result = SentPhoto(
            telegram_message_id=9001,
            telegram_file_id="tg-photo-1",
            telegram_file_unique_id="tg-photo-uniq-1",
            width=1024,
            height=1024,
            file_size=2048,
        )
        self.video_result = SentVideo(
            telegram_message_id=9002,
            telegram_file_id="tg-video-1",
            telegram_file_unique_id="tg-video-uniq-1",
            width=1280,
            height=720,
            duration_seconds=4,
            mime_type="video/mp4",
            file_size=4096,
        )

    async def send_text(self, text: str) -> None:
        self.sent_texts.append(text)

    async def send_photo(self, image) -> SentPhoto:
        self.sent_photos.append(image.image_bytes)
        return self.photo_result

    async def send_video(self, video) -> SentVideo:
        self.sent_videos.append(video.video_bytes)
        return self.video_result

    async def open_draft(self) -> FakeDraftSession:
        self.open_calls += 1
        return self.draft_session


class PlannedProvider:
    def __init__(self, plans: list[list[object]]) -> None:
        self.plans = plans
        self.calls = []

    async def stream_response(self, request):
        self.calls.append(request)
        plan = self.plans[len(self.calls) - 1]
        for step in plan:
            if isinstance(step, asyncio.Event):
                await step.wait()
                continue
            yield step

    async def generate_response(self, request):
        raise NotImplementedError

    async def close(self) -> None:
        return None


async def test_allowlist_rejection_prevents_provider_invocation(service_bundle) -> None:
    service = service_bundle["service"]
    provider = service_bundle["provider"]

    reply = await service.handle_inbound(
        make_text_message(user_id=99, chat_id=100, text="hello")
    )

    assert reply.text == ACCESS_DENIED_TEXT
    assert provider.calls == []


async def test_history_is_reused_for_follow_up_messages(service_bundle) -> None:
    service = service_bundle["service"]
    provider = service_bundle["provider"]

    first_reply = await service.handle_inbound(
        make_text_message(user_id=42, chat_id=100, text="first", update_id=1)
    )
    second_reply = await service.handle_inbound(
        make_text_message(user_id=42, chat_id=100, text="second", update_id=2)
    )

    assert first_reply.text == "assistant reply"
    assert second_reply.text == "assistant reply"
    assert len(provider.calls) == 2
    assert provider.calls[0].history == []
    assert len(provider.calls[1].history) == 2
    assert provider.calls[1].history[0].role == "user"
    assert provider.calls[1].history[0].text == "first"
    assert provider.calls[1].history[1].role == "assistant"
    assert provider.calls[1].history[1].text == "assistant reply"


async def test_reset_starts_fresh_conversation_without_deleting_prior_history(service_bundle) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    messages = service_bundle["messages"]
    provider = service_bundle["provider"]
    database = service_bundle["database"]

    await service.handle_inbound(
        make_text_message(user_id=42, chat_id=200, text="before reset", update_id=1)
    )
    first_conversation = await conversations.get_active(200)

    reset_reply = await service.handle_inbound(
        make_command_message(user_id=42, chat_id=200, command="/reset", update_id=2)
    )
    second_conversation = await conversations.get_active(200)

    await service.handle_inbound(
        make_text_message(user_id=42, chat_id=200, text="after reset", update_id=3)
    )

    assert reset_reply.text.startswith("Started a fresh conversation")
    assert first_conversation is not None
    assert second_conversation is not None
    assert second_conversation.id != first_conversation.id
    assert provider.calls[-1].history == []

    archived_cursor = await database.connection.execute(
        "SELECT COUNT(*) AS count FROM conversations WHERE chat_id = ? AND is_active = 0",
        (200,),
    )
    archived_row = await archived_cursor.fetchone()
    await archived_cursor.close()

    first_messages = await messages.list_for_conversation(first_conversation.id)
    second_messages = await messages.list_for_conversation(second_conversation.id)

    assert archived_row["count"] == 1
    assert len(first_messages) == 2
    assert len(second_messages) == 4


async def test_image_command_generates_photo_and_persists_metadata(service_bundle) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    generated_images = service_bundle["generated_images"]
    image_generator = service_bundle["image_generator"]
    emitter = FakeResponseEmitter()

    reply = await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=210,
            command="/image cinematic poster of a fox astronaut",
            update_id=4,
        ),
        responder=emitter,
    )
    conversation = await conversations.get_active(210)

    assert reply.text == ""
    assert reply.delivered is True
    assert len(image_generator.calls) == 1
    assert emitter.sent_texts == []
    assert emitter.sent_photos == [b"generated-image"]
    assert conversation is not None

    stored_images = await generated_images.list_for_conversation(conversation.id)
    assert len(stored_images) == 1
    assert stored_images[0].prompt_text == "cinematic poster of a fox astronaut"
    assert stored_images[0].provider == "vertex"
    assert stored_images[0].telegram_file_id == "tg-photo-1"
    assert stored_images[0].model == service.settings.vertex_image_model


async def test_image_command_requires_prompt(service_bundle) -> None:
    service = service_bundle["service"]
    emitter = FakeResponseEmitter()

    reply = await service.handle_inbound(
        make_command_message(user_id=42, chat_id=211, command="/image", update_id=5),
        responder=emitter,
    )

    assert reply.text.startswith("Use /image followed by a prompt")
    assert reply.delivered is True
    assert emitter.sent_texts == [reply.text]
    assert emitter.sent_photos == []


async def test_image_command_provider_failure_returns_retry_text(service_bundle) -> None:
    service = service_bundle["service"]
    image_generator = service_bundle["image_generator"]
    emitter = FakeResponseEmitter()

    image_generator.error = ProviderTimeoutError("timed out")

    reply = await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=212,
            command="/image rainy alley with cinematic lights",
            update_id=6,
        ),
        responder=emitter,
    )

    assert reply.text == IMAGE_GENERATION_RETRY_TEXT
    assert reply.delivered is True
    assert emitter.sent_texts == [IMAGE_GENERATION_RETRY_TEXT]
    assert emitter.sent_photos == []


async def test_image_command_returns_not_configured_when_generator_missing(service_bundle) -> None:
    service = service_bundle["service"]
    emitter = FakeResponseEmitter()

    service.image_generator = None

    reply = await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=213,
            command="/image charcoal sketch of a lighthouse",
            update_id=7,
        ),
        responder=emitter,
    )

    assert reply.text == "Image generation is not configured right now."
    assert reply.delivered is True
    assert emitter.sent_texts == ["Image generation is not configured right now."]
    assert emitter.sent_photos == []


async def test_video_command_queues_generation_job(service_bundle) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]
    video_generator = service_bundle["video_generator"]
    emitter = FakeResponseEmitter()

    reply = await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=214,
            command="/video slow cinematic dolly shot through a rainy neon alley",
            update_id=8,
        ),
        responder=emitter,
    )
    conversation = await conversations.get_active(214)

    assert reply.text == "Video generation started. I'll send it here when it's ready."
    assert reply.delivered is True
    assert len(video_generator.submit_calls) == 1
    assert conversation is not None

    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)
    assert len(stored_jobs) == 1
    assert stored_jobs[0].status == "queued"
    assert stored_jobs[0].prompt_text == "slow cinematic dolly shot through a rainy neon alley"
    assert stored_jobs[0].operation_name == "operations/1"
    assert emitter.sent_texts == [reply.text]
    assert emitter.sent_videos == []


async def test_video_command_requires_prompt(service_bundle) -> None:
    service = service_bundle["service"]
    emitter = FakeResponseEmitter()

    reply = await service.handle_inbound(
        make_command_message(user_id=42, chat_id=215, command="/video", update_id=9),
        responder=emitter,
    )

    assert reply.text.startswith("Use /video followed by a prompt")
    assert reply.delivered is True
    assert emitter.sent_texts == [reply.text]
    assert emitter.sent_videos == []


async def test_video_command_provider_failure_returns_retry_text(service_bundle) -> None:
    service = service_bundle["service"]
    video_generator = service_bundle["video_generator"]
    emitter = FakeResponseEmitter()

    video_generator.submit_error = ProviderTimeoutError("timed out")

    reply = await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=216,
            command="/video moonlit aerial shot above a foggy coastline",
            update_id=11,
        ),
        responder=emitter,
    )

    assert reply.text == VIDEO_GENERATION_RETRY_TEXT
    assert reply.delivered is True
    assert emitter.sent_texts == [VIDEO_GENERATION_RETRY_TEXT]
    assert emitter.sent_videos == []


async def test_video_command_returns_not_configured_when_generator_missing(service_bundle) -> None:
    service = service_bundle["service"]
    emitter = FakeResponseEmitter()

    service.video_generator = None

    reply = await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=217,
            command="/video graphite robot crossing a desert at sunset",
            update_id=12,
        ),
        responder=emitter,
    )

    assert reply.text == "Video generation is not configured right now."
    assert reply.delivered is True
    assert emitter.sent_texts == ["Video generation is not configured right now."]
    assert emitter.sent_videos == []


async def test_text_message_streams_drafts_and_delivers_final_reply(service_bundle) -> None:
    service = service_bundle["service"]
    provider = service_bundle["provider"]
    emitter = FakeResponseEmitter()

    service.settings.bot_draft_start_delay_ms = 0
    service.settings.bot_draft_update_interval_ms = 0
    service.settings.bot_draft_min_chars_delta = 1
    provider.events = [
        StreamingProviderEvent(type="delta", text="assistant"),
        StreamingProviderEvent(type="delta", text=" reply"),
        StreamingProviderEvent(
            type="completed",
            provider_message_id="resp_stream",
            input_tokens=10,
            output_tokens=20,
            finish_reason="completed",
            raw_model=service.settings.openai_model,
        ),
    ]

    reply = await service.handle_inbound(
        make_text_message(user_id=42, chat_id=300, text="stream this"),
        responder=emitter,
    )

    assert reply.text == "assistant reply"
    assert reply.delivered is True
    assert emitter.sent_texts == ["assistant reply"]
    assert emitter.open_calls == 1
    assert emitter.draft_session.updates == ["assistant", "assistant reply"]
    assert emitter.draft_session.finished is True
    assert emitter.draft_session.cancelled is False


async def test_draft_update_failure_falls_back_to_final_only_reply(service_bundle) -> None:
    service = service_bundle["service"]
    provider = service_bundle["provider"]
    emitter = FakeResponseEmitter(
        draft_session=FakeDraftSession(fail_on_update=True)
    )

    service.settings.bot_draft_start_delay_ms = 0
    service.settings.bot_draft_update_interval_ms = 0
    service.settings.bot_draft_min_chars_delta = 1
    provider.events = [
        StreamingProviderEvent(type="delta", text="assistant"),
        StreamingProviderEvent(type="delta", text=" reply"),
        StreamingProviderEvent(
            type="completed",
            provider_message_id="resp_stream",
            input_tokens=10,
            output_tokens=20,
            finish_reason="completed",
            raw_model=service.settings.openai_model,
        ),
    ]

    reply = await service.handle_inbound(
        make_text_message(user_id=42, chat_id=301, text="stream this"),
        responder=emitter,
    )

    assert reply.text == "assistant reply"
    assert reply.delivered is True
    assert emitter.sent_texts == ["assistant reply"]
    assert emitter.open_calls == 1
    assert emitter.draft_session.cancelled is True
    assert emitter.draft_session.finished is False


async def test_draft_rate_limit_falls_back_to_final_only_reply(service_bundle) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    messages = service_bundle["messages"]
    provider = service_bundle["provider"]
    emitter = FakeResponseEmitter(
        draft_session=FakeDraftSession(retry_after=14)
    )

    service.settings.bot_draft_start_delay_ms = 0
    service.settings.bot_draft_update_interval_ms = 0
    service.settings.bot_draft_min_chars_delta = 1
    provider.events = [
        StreamingProviderEvent(type="delta", text="assistant"),
        StreamingProviderEvent(type="delta", text=" reply"),
        StreamingProviderEvent(
            type="completed",
            provider_message_id="resp_stream",
            input_tokens=10,
            output_tokens=20,
            finish_reason="completed",
            raw_model=service.settings.openai_model,
        ),
    ]

    reply = await service.handle_inbound(
        make_text_message(user_id=42, chat_id=305, text="stream this"),
        responder=emitter,
    )
    conversation = await conversations.get_active(305)

    assert conversation is not None
    stored_messages = await messages.list_for_conversation(conversation.id)
    assert reply.text == "assistant reply"
    assert reply.delivered is True
    assert emitter.sent_texts == ["assistant reply"]
    assert emitter.open_calls == 1
    assert emitter.draft_session.updates == []
    assert emitter.draft_session.cancelled is True
    assert emitter.draft_session.finished is False
    assert [message.role for message in stored_messages] == ["user", "assistant"]
    assert stored_messages[-1].text == "assistant reply"


async def test_image_messages_skip_drafts_by_default(service_bundle) -> None:
    service = service_bundle["service"]
    emitter = FakeResponseEmitter()

    service.settings.bot_draft_start_delay_ms = 0
    service.settings.bot_draft_update_interval_ms = 0
    service.settings.bot_draft_min_chars_delta = 1

    reply = await service.handle_inbound(
        make_image_message(
            user_id=42,
            chat_id=302,
            caption="describe this",
            update_id=10,
        ),
        responder=emitter,
    )

    assert reply.text == "assistant reply"
    assert reply.delivered is True
    assert emitter.sent_texts == ["assistant reply"]
    assert emitter.open_calls == 0
    assert emitter.draft_session.updates == []


async def test_provider_failure_persists_user_turn_without_assistant_reply(service_bundle) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    messages = service_bundle["messages"]
    provider = service_bundle["provider"]

    provider.error = ProviderTimeoutError("timed out")

    reply = await service.handle_inbound(
        make_text_message(user_id=42, chat_id=303, text="will fail"),
    )
    conversation = await conversations.get_active(303)

    assert reply.text.startswith("I couldn't get a response")
    assert conversation is not None

    stored_messages = await messages.list_for_conversation(conversation.id)
    assert [message.role for message in stored_messages] == ["user"]
    assert stored_messages[0].text == "will fail"


async def test_newer_message_supersedes_older_streaming_reply(tmp_path) -> None:
    from app.domain.services import ChatService
    from app.storage.conversations import ConversationRepository
    from app.storage.db import Database
    from app.storage.messages import MessageRepository

    gate = asyncio.Event()
    provider = PlannedProvider(
        plans=[
            [
                StreamingProviderEvent(type="delta", text="old"),
                gate,
                StreamingProviderEvent(type="delta", text=" reply"),
                StreamingProviderEvent(
                    type="completed",
                    provider_message_id="resp_old",
                    finish_reason="completed",
                    raw_model="gpt-4.1-mini",
                ),
            ],
            [
                StreamingProviderEvent(type="delta", text="new reply"),
                StreamingProviderEvent(
                    type="completed",
                    provider_message_id="resp_new",
                    finish_reason="completed",
                    raw_model="gpt-4.1-mini",
                ),
            ],
        ]
    )
    settings = Settings(
        TELEGRAM_BOT_TOKEN="test-token",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        SQLITE_PATH=str(tmp_path / "supersede.db"),
        OPENAI_MODEL="gpt-4.1-mini",
        BOT_ENABLE_MESSAGE_DRAFTS="true",
        BOT_DRAFT_START_DELAY_MS="0",
        BOT_DRAFT_UPDATE_INTERVAL_MS="0",
        BOT_DRAFT_MIN_CHARS_DELTA="1",
    )
    database = Database(settings.sqlite_path)
    await database.connect()
    await database.initialize()

    conversations = ConversationRepository(database)
    messages = MessageRepository(database)
    service = ChatService(
        settings=settings,
        conversations=conversations,
        messages=messages,
        provider=provider,
    )

    first_draft_updated = asyncio.Event()
    first_emitter = FakeResponseEmitter(
        draft_session=FakeDraftSession(draft_id=11, updated_event=first_draft_updated)
    )
    second_emitter = FakeResponseEmitter(draft_session=FakeDraftSession(draft_id=22))

    first_task = asyncio.create_task(
        service.handle_inbound(
            make_text_message(user_id=42, chat_id=304, text="first", update_id=1),
            responder=first_emitter,
        )
    )
    await first_draft_updated.wait()
    second_reply = await service.handle_inbound(
        make_text_message(user_id=42, chat_id=304, text="second", update_id=2),
        responder=second_emitter,
    )
    gate.set()
    first_reply = await first_task

    conversation = await conversations.get_active(304)
    assert conversation is not None
    stored_messages = await messages.list_for_conversation(conversation.id)

    assert first_reply.suppressed is True
    assert first_reply.delivered is False
    assert first_emitter.sent_texts == []
    assert first_emitter.draft_session.cancelled is True
    assert second_reply.text == "new reply"
    assert second_reply.delivered is True
    assert second_emitter.sent_texts == ["new reply"]
    assert [message.role for message in stored_messages] == ["user", "user", "assistant"]
    assert stored_messages[-1].text == "new reply"

    await database.close()
