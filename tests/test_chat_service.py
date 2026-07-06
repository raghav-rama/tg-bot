from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from pydantic import SecretStr

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


def make_reference_image() -> ImageInput:
    return ImageInput(
        telegram_file_id="file-ref",
        telegram_file_unique_id="uniq-ref",
        mime_type="image/jpeg",
        width=768,
        height=512,
        byte_size=15,
        bytes_b64="cmVmZXJlbmNlLWltYWdl",
        caption="/image stylize this",
    )


def make_image_command_message(
    *,
    user_id: int,
    chat_id: int,
    command: str,
    update_id: int = 1,
) -> InboundMessage:
    command_name = command.split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()
    image = make_reference_image()
    image.caption = command
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
        image=image,
        sent_at=utc_datetime(),
    )


def make_reply_photo_command_message(
    *,
    user_id: int,
    chat_id: int,
    command: str,
    update_id: int = 1,
) -> InboundMessage:
    command_name = command.split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()
    image = make_reference_image()
    image.caption = None
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
        image=image,
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
        self.sent_menus = []
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

    async def send_text(self, text: str, settings_menu=None) -> None:
        self.sent_texts.append(text)
        if settings_menu is not None:
            self.sent_menus.append(settings_menu)

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


async def test_settings_command_returns_settings_menu(service_bundle) -> None:
    service = service_bundle["service"]
    provider = service_bundle["provider"]
    emitter = FakeResponseEmitter()

    reply = await service.handle_inbound(
        make_command_message(user_id=42, chat_id=100, command="/settings"),
        responder=emitter,
    )

    assert "Settings" in reply.text
    assert reply.settings_menu is not None
    assert reply.settings_menu.rows[0][0].callback_data == "prefs:menu:video"
    assert emitter.sent_texts == [reply.text]
    assert emitter.sent_menus == [reply.settings_menu]
    assert provider.calls == []


async def test_settings_callback_persists_user_preference(service_bundle) -> None:
    service = service_bundle["service"]
    preferences = service_bundle["preferences"]

    reply = await service.handle_settings_callback(
        chat_id=100,
        user_id=42,
        callback_data="prefs:video_provider:runpod",
    )
    stored = await preferences.get_preference(
        chat_id=100,
        user_id=42,
        preference_type="video_provider",
    )

    assert stored is not None
    assert stored.preset_id == "runpod"
    assert "Video provider: 🚀 Runpod LTX" in reply.text
    assert reply.settings_menu is not None


async def test_settings_callback_accepts_fal_model_from_runtime_settings(service_bundle) -> None:
    service = service_bundle["service"]
    preferences = service_bundle["preferences"]

    service.settings.fal_key = SecretStr("test-fal-key")
    service.settings.fal_video_text_to_video_model = "fal-ai/kling-video/v3/standard/text-to-video"
    service.settings.fal_video_reference_to_video_model = (
        "bytedance/seedance-2.0/reference-to-video"
    )

    reply = await service.handle_settings_callback(
        chat_id=100,
        user_id=42,
        callback_data="prefs:fal_video_model:seedance",
    )
    stored = await preferences.get_preference(
        chat_id=100,
        user_id=42,
        preference_type="fal_video_model",
    )

    assert stored is not None
    assert stored.preset_id == "seedance"
    assert "Fal model: 🌌 Seedance" in reply.text


async def test_text_message_logs_token_usage_and_cost_estimate(
    service_bundle,
    caplog,
) -> None:
    service = service_bundle["service"]

    service.settings.openai_input_cost_per_1m_tokens_usd = 0.4
    service.settings.openai_output_cost_per_1m_tokens_usd = 1.6

    with caplog.at_level("INFO", logger="app.domain.services"):
        await service.handle_inbound(
            make_text_message(user_id=42, chat_id=101, text="estimate this"),
        )

    assert "message_processed" in caplog.text
    assert "provider=openai" in caplog.text
    assert "model=gpt-4.1-mini" in caplog.text
    assert "input_tokens=10" in caplog.text
    assert "output_tokens=20" in caplog.text
    assert "total_tokens=30" in caplog.text
    assert "cost_estimate_available=True" in caplog.text
    assert "cost_estimated_usd=0.000036" in caplog.text


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


async def test_image_command_queues_generation_job(service_bundle) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]
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

    assert reply.text == "Image generation started. I'll send it here when it's ready."
    assert reply.delivered is True
    assert image_generator.calls == []
    assert emitter.sent_texts == [reply.text]
    assert emitter.sent_photos == []
    assert conversation is not None

    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)
    assert len(stored_jobs) == 1
    assert stored_jobs[0].job_type == "image"
    assert stored_jobs[0].status == "queued"
    assert stored_jobs[0].provider == "gemini"
    assert stored_jobs[0].model == service.settings.gemini_image_model
    assert stored_jobs[0].provider_operation_name is None

    request_payload = json.loads(stored_jobs[0].request_payload)
    assert request_payload["prompt"] == "cinematic poster of a fox astronaut"
    assert request_payload["reference_image"] is None


async def test_image_caption_command_persists_reference_image_for_gemini_model(
    service_bundle,
) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]
    emitter = FakeResponseEmitter()

    service.settings.gemini_image_model = "gemini-3.1-flash-image"

    reply = await service.handle_inbound(
        make_image_command_message(
            user_id=42,
            chat_id=220,
            command="/image make this a watercolor poster",
            update_id=15,
        ),
        responder=emitter,
    )
    conversation = await conversations.get_active(220)

    assert reply.delivered is True
    assert emitter.sent_texts == [reply.text]
    assert conversation is not None

    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)
    request_payload = json.loads(stored_jobs[0].request_payload)
    reference_image = request_payload["reference_image"]
    assert reference_image is not None
    assert reference_image["telegram_file_unique_id"] == "uniq-ref"
    assert reference_image["bytes_b64"] is None


async def test_image_reply_photo_command_persists_reference_image_for_gemini_model(
    service_bundle,
) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]
    emitter = FakeResponseEmitter()

    service.settings.gemini_image_model = "gemini-3.1-flash-image"

    reply = await service.handle_inbound(
        make_reply_photo_command_message(
            user_id=42,
            chat_id=230,
            command="/image make this cinematic",
            update_id=24,
        ),
        responder=emitter,
    )

    assert reply.delivered is True
    conversation = await conversations.get_active(230)
    assert conversation is not None
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)
    request_payload = json.loads(stored_jobs[0].request_payload)
    assert request_payload["prompt"] == "make this cinematic"
    assert request_payload["reference_image"] is not None
    assert request_payload["reference_image"]["caption"] is None
    assert request_payload["reference_image"]["telegram_file_unique_id"] == "uniq-ref"


async def test_image_caption_command_uses_current_gemini_image_model(service_bundle) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]
    emitter = FakeResponseEmitter()

    service.settings.gemini_image_model = "gemini-3.1-flash-image"

    reply = await service.handle_inbound(
        make_image_command_message(
            user_id=42,
            chat_id=221,
            command="/image make this a watercolor poster",
            update_id=16,
        ),
        responder=emitter,
    )

    assert reply.text == "Image generation started. I'll send it here when it's ready."
    assert reply.delivered is True
    assert emitter.sent_photos == []
    conversation = await conversations.get_active(221)
    assert conversation is not None
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)
    request_payload = json.loads(stored_jobs[0].request_payload)
    assert request_payload["model"] == "gemini-3.1-flash-image"
    assert request_payload["reference_image"] is not None


async def test_image_command_logs_usage_and_cost_estimate(
    service_bundle,
    caplog,
) -> None:
    service = service_bundle["service"]
    emitter = FakeResponseEmitter()

    service.settings.gemini_image_model = "gemini-3.1-flash-image"
    service.settings.gemini_image_cost_per_image_usd = 0.05

    with caplog.at_level("INFO", logger="app.domain.services"):
        await service.handle_inbound(
            make_command_message(
                user_id=42,
                chat_id=218,
                command="/image cinematic poster of a fox astronaut",
                update_id=13,
            ),
            responder=emitter,
        )

    assert "message_processed" in caplog.text
    assert "provider=gemini" in caplog.text
    assert "model=gemini-3.1-flash-image" in caplog.text
    assert "generated_images=1" in caplog.text
    assert "prompt_chars=" in caplog.text
    assert "cost_estimate_available=True" in caplog.text
    assert "cost_estimated_usd=0.05" in caplog.text


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


async def test_image_caption_command_with_reference_image_still_requires_prompt(
    service_bundle,
) -> None:
    service = service_bundle["service"]
    image_generator = service_bundle["image_generator"]
    emitter = FakeResponseEmitter()

    reply = await service.handle_inbound(
        make_image_command_message(
            user_id=42,
            chat_id=222,
            command="/image",
            update_id=17,
        ),
        responder=emitter,
    )

    assert reply.text.startswith("Use /image followed by a prompt")
    assert reply.delivered is True
    assert image_generator.calls == []
    assert emitter.sent_photos == []


async def test_image_command_provider_failure_returns_retry_text(service_bundle) -> None:
    service = service_bundle["service"]
    image_generator = service_bundle["image_generator"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]
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

    conversation = await conversations.get_active(212)
    assert conversation is not None
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)

    assert reply.text == "Image generation started. I'll send it here when it's ready."
    assert reply.delivered is True
    assert stored_jobs[0].status == "queued"
    assert emitter.sent_texts == [reply.text]
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
    assert video_generator.submit_calls == []
    assert conversation is not None

    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)
    assert len(stored_jobs) == 1
    assert stored_jobs[0].status == "queued"
    assert stored_jobs[0].provider == "gemini"
    assert stored_jobs[0].prompt_text == "slow cinematic dolly shot through a rainy neon alley"
    assert stored_jobs[0].provider_operation_name is None
    request_payload = json.loads(stored_jobs[0].request_payload)
    assert request_payload["provider_hint"] == "auto"
    assert emitter.sent_texts == [reply.text]
    assert emitter.sent_videos == []


def _enable_fal_for(service, *, model: str = "fal-ai/kling-video/v3/standard/text-to-video", image_to_video_model: str | None = None, reference_to_video_model: str | None = None) -> None:
    service.settings.video_provider_order = ("fal",)
    service.settings.fal_video_model = model
    service.settings.fal_video_image_to_video_model = image_to_video_model
    service.settings.fal_video_reference_to_video_model = reference_to_video_model
    service.settings.fal_video_resolution = "720p"


async def test_video_fal_first_provider_order_uses_fal_model(service_bundle) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]

    _enable_fal_for(service)
    await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=990,
            command="/video glowing particles drifting in a dark corridor",
            update_id=90,
        ),
    )

    conversation = await conversations.get_active(990)
    assert conversation is not None
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)
    request = json.loads(stored_jobs[0].request_payload)
    assert request["provider_hint"] == "auto"
    assert request["model"] == "fal-ai/kling-video/v3/standard/text-to-video"
    assert request["resolution"] == "720p"


async def test_video_fal_provider_preference_sets_provider_hint_and_model(service_bundle) -> None:
    service = service_bundle["service"]
    preferences = service_bundle["preferences"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]

    _enable_fal_for(service)
    await preferences.set_preference(
        chat_id=992,
        user_id=42,
        preference_type="video_provider",
        preset_id="fal",
        updated_at=utc_datetime(),
    )
    await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=992,
            command="/video glowing particles drifting in a dark corridor",
            update_id=92,
        ),
    )

    conversation = await conversations.get_active(992)
    assert conversation is not None
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)
    request = json.loads(stored_jobs[0].request_payload)
    assert request["provider_hint"] == "fal"
    assert request["model"] == "fal-ai/kling-video/v3/standard/text-to-video"


async def test_video_fal_with_reference_image_prefers_reference_to_video_model(service_bundle) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]

    _enable_fal_for(
        service,
        image_to_video_model="fal-ai/kling-video/v3/standard/image-to-video",
        reference_to_video_model="bytedance/seedance-2.0/reference-to-video",
    )
    await service.handle_inbound(
        make_image_command_message(
            user_id=42,
            chat_id=991,
            command="/video slow push across the still life",
            update_id=91,
        ),
    )

    conversation = await conversations.get_active(991)
    assert conversation is not None
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)
    request = json.loads(stored_jobs[0].request_payload)
    assert request["provider_hint"] == "auto"
    assert request["model"] == "bytedance/seedance-2.0/reference-to-video"
    assert request["resolution"] == "720p"


async def test_video_command_with_runpod_preference_submits_runpod_job(service_bundle) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]
    video_generator = service_bundle["video_generator"]
    emitter = FakeResponseEmitter()

    await service_bundle["preferences"].set_preference(
        chat_id=224,
        user_id=42,
        preference_type="video_provider",
        preset_id="runpod",
        updated_at=utc_datetime(),
    )

    reply = await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=224,
            command="/video simple cinematic shot of clouds over a valley",
            update_id=19,
        ),
        responder=emitter,
    )
    conversation = await conversations.get_active(224)

    assert reply.text == "Video generation started. I'll send it here when it's ready."
    assert reply.delivered is True
    assert video_generator.submit_calls == []
    assert conversation is not None

    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)
    assert len(stored_jobs) == 1
    assert stored_jobs[0].provider == "runpod"
    assert stored_jobs[0].model == service.settings.runpod_video_model
    assert stored_jobs[0].prompt_text == "simple cinematic shot of clouds over a valley"
    request_payload = json.loads(stored_jobs[0].request_payload)
    assert request_payload["provider_hint"] == "runpod"


async def test_video_command_uses_saved_video_preferences(service_bundle, monkeypatch) -> None:
    service = service_bundle["service"]
    preferences = service_bundle["preferences"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]

    monkeypatch.setattr("app.domain.services.random.randint", lambda _min, _max: 12345)
    await preferences.set_preference(
        chat_id=226,
        user_id=42,
        preference_type="video_provider",
        preset_id="runpod",
        updated_at=utc_datetime(),
    )
    await preferences.set_preference(
        chat_id=226,
        user_id=42,
        preference_type="video_duration",
        preset_id="duration_10s",
        updated_at=utc_datetime(),
    )
    await preferences.set_preference(
        chat_id=226,
        user_id=42,
        preference_type="video_orientation",
        preset_id="portrait_9_16",
        updated_at=utc_datetime(),
    )
    await preferences.set_preference(
        chat_id=226,
        user_id=42,
        preference_type="runpod_pipeline",
        preset_id="two_stage",
        updated_at=utc_datetime(),
    )
    await preferences.set_preference(
        chat_id=226,
        user_id=42,
        preference_type="runpod_quality",
        preset_id="high",
        updated_at=utc_datetime(),
    )
    await preferences.set_preference(
        chat_id=226,
        user_id=42,
        preference_type="runpod_seed",
        preset_id="random",
        updated_at=utc_datetime(),
    )

    await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=226,
            command="/video foggy mountain reveal",
            update_id=21,
        ),
    )

    conversation = await conversations.get_active(226)
    assert conversation is not None
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)
    request = json.loads(stored_jobs[0].request_payload)
    assert request["provider_hint"] == "runpod"
    assert request["model"] == "ltx-2.3-22b"
    assert request["width"] == 576
    assert request["height"] == 1024
    assert request["duration_seconds"] == 10
    assert request["frame_rate"] == 24.0
    assert request["pipeline"] == "two_stage"
    assert request["num_inference_steps"] == 50
    assert request["seed"] == 12345
    assert request["model_locked"] is True


async def test_video_reference_uses_saved_runpod_reference_strength(service_bundle) -> None:
    service = service_bundle["service"]
    preferences = service_bundle["preferences"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]

    await preferences.set_preference(
        chat_id=229,
        user_id=42,
        preference_type="runpod_reference_strength",
        preset_id="high",
        updated_at=utc_datetime(),
    )

    await preferences.set_preference(
        chat_id=229,
        user_id=42,
        preference_type="video_provider",
        preset_id="runpod",
        updated_at=utc_datetime(),
    )

    await service.handle_inbound(
        make_image_command_message(
            user_id=42,
            chat_id=229,
            command="/video animate the subject",
            update_id=23,
        ),
    )

    conversation = await conversations.get_active(229)
    assert conversation is not None
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)
    request = json.loads(stored_jobs[0].request_payload)
    assert request["provider_hint"] == "runpod"
    assert request["reference_image"] is not None
    assert request["image_strength"] == 0.9


async def test_video_reply_photo_command_passes_reference_image_to_submission(
    service_bundle,
) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]
    emitter = FakeResponseEmitter()

    reply = await service.handle_inbound(
        make_reply_photo_command_message(
            user_id=42,
            chat_id=231,
            command="/video animate this with a slow camera push",
            update_id=25,
        ),
        responder=emitter,
    )

    assert reply.text == "Video generation started. I'll send it here when it's ready."
    conversation = await conversations.get_active(231)
    assert conversation is not None
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)
    request_payload = json.loads(stored_jobs[0].request_payload)
    assert request_payload["provider_hint"] == "auto"
    assert request_payload["prompt"] == "animate this with a slow camera push"
    assert request_payload["reference_image"] is not None
    assert request_payload["reference_image"]["caption"] is None
    assert request_payload["reference_image"]["telegram_file_unique_id"] == "uniq-ref"


async def test_video_reply_photo_with_runpod_preference_passes_reference_image_to_runpod_submission(
    service_bundle,
) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]
    emitter = FakeResponseEmitter()

    await service_bundle["preferences"].set_preference(
        chat_id=232,
        user_id=42,
        preference_type="video_provider",
        preset_id="runpod",
        updated_at=utc_datetime(),
    )

    reply = await service.handle_inbound(
        make_reply_photo_command_message(
            user_id=42,
            chat_id=232,
            command="/video animate this subject",
            update_id=26,
        ),
        responder=emitter,
    )

    assert reply.text == "Video generation started. I'll send it here when it's ready."
    conversation = await conversations.get_active(232)
    assert conversation is not None
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)
    request_payload = json.loads(stored_jobs[0].request_payload)
    assert request_payload["provider_hint"] == "runpod"
    assert request_payload["prompt"] == "animate this subject"
    assert request_payload["reference_image"] is not None
    assert request_payload["reference_image"]["caption"] is None
    assert request_payload["reference_image"]["telegram_file_unique_id"] == "uniq-ref"


async def test_image_command_uses_saved_image_preset(service_bundle) -> None:
    service = service_bundle["service"]
    preferences = service_bundle["preferences"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]
    emitter = FakeResponseEmitter()

    await preferences.set_preference(
        chat_id=227,
        user_id=42,
        preference_type="image",
        preset_id="gemini_landscape_jpeg",
        updated_at=utc_datetime(),
    )

    await service.handle_inbound(
        make_command_message(
            user_id=42,
            chat_id=227,
            command="/image cinematic desert road at sunrise",
            update_id=22,
        ),
        responder=emitter,
    )

    conversation = await conversations.get_active(227)
    assert conversation is not None
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)
    request_payload = json.loads(stored_jobs[0].request_payload)
    assert request_payload["model"] == "gemini-3.1-flash-image"
    assert request_payload["aspect_ratio"] == "16:9"
    assert request_payload["output_mime_type"] == "image/jpeg"


async def test_chat_message_uses_saved_chat_preset(service_bundle) -> None:
    service = service_bundle["service"]
    preferences = service_bundle["preferences"]
    provider = service_bundle["provider"]

    await preferences.set_preference(
        chat_id=228,
        user_id=42,
        preference_type="chat",
        preset_id="creative_long",
        updated_at=utc_datetime(),
    )

    await service.handle_inbound(
        make_text_message(user_id=42, chat_id=228, text="give me title ideas")
    )

    request = provider.calls[0]
    assert request.temperature == 0.8
    assert request.max_output_tokens == 1200


async def test_video_caption_command_passes_reference_image_to_submission(
    service_bundle,
) -> None:
    service = service_bundle["service"]
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]
    emitter = FakeResponseEmitter()

    reply = await service.handle_inbound(
        make_image_command_message(
            user_id=42,
            chat_id=223,
            command="/video animate the subject with a slow camera push",
            update_id=18,
        ),
        responder=emitter,
    )
    conversation = await conversations.get_active(223)

    assert reply.text == "Video generation started. I'll send it here when it's ready."
    assert reply.delivered is True
    assert conversation is not None

    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)
    assert len(stored_jobs) == 1
    assert stored_jobs[0].prompt_text == "animate the subject with a slow camera push"
    request_payload = json.loads(stored_jobs[0].request_payload)
    assert request_payload["reference_image"] is not None
    assert request_payload["reference_image"]["telegram_file_unique_id"] == "uniq-ref"


async def test_video_command_logs_submission_usage_and_cost_estimate(
    service_bundle,
    caplog,
) -> None:
    service = service_bundle["service"]

    service.settings.gemini_video_cost_per_second_usd = 0.35

    with caplog.at_level("INFO", logger="app.domain.services"):
        await service.handle_inbound(
            make_command_message(
                user_id=42,
                chat_id=219,
                command="/video slow orbit around a crystal sculpture",
                update_id=14,
            ),
        )

    assert "video_generation_requested" in caplog.text
    assert "provider=gemini" in caplog.text
    assert "model=gemini-omni-flash-preview" in caplog.text
    assert "duration_seconds=4" in caplog.text
    assert "prompt_chars=" in caplog.text
    assert "cost_estimate_available=True" in caplog.text
    assert "cost_estimated_usd=1.4" in caplog.text


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
    conversations = service_bundle["conversations"]
    generation_jobs = service_bundle["generation_jobs"]
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

    conversation = await conversations.get_active(216)
    assert conversation is not None
    stored_jobs = await generation_jobs.list_for_conversation(conversation.id)

    assert reply.text == "Video generation started. I'll send it here when it's ready."
    assert reply.delivered is True
    assert stored_jobs[0].status == "queued"
    assert emitter.sent_texts == [reply.text]
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
        TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
        TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
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
