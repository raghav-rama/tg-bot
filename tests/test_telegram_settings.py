from __future__ import annotations

from types import SimpleNamespace

from app.telegram.handlers import TelegramUpdateProcessor


class FakeCallbackMessage:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(id=100)
        self.message_id = 501
        self.edits: list[dict[str, object]] = []

    async def edit_text(self, **kwargs) -> None:
        self.edits.append(kwargs)


class FakeCallbackQuery:
    def __init__(self, *, data: str, user_id: int = 42) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeCallbackMessage()
        self.answers: list[dict[str, object]] = []

    async def answer(self, **kwargs) -> None:
        self.answers.append(kwargs)


async def test_processor_handles_settings_callback(service_bundle) -> None:
    processor = TelegramUpdateProcessor(
        chat_service=service_bundle["service"],
        settings=service_bundle["settings"],
    )
    callback = FakeCallbackQuery(
        data="prefs:video_duration:duration_8s",
    )

    await processor.process_callback(callback=callback, update_id=77)

    stored = await service_bundle["preferences"].get_preference(
        chat_id=100,
        user_id=42,
        preference_type="video_duration",
    )
    assert stored is not None
    assert stored.preset_id == "duration_8s"
    assert callback.answers == [{"text": "Settings updated."}]
    assert "Video duration: ⏱️ 8s" in callback.message.edits[0]["text"]
    assert callback.message.edits[0]["reply_markup"] is not None


async def test_processor_handles_fal_provider_settings_callback(service_bundle) -> None:
    processor = TelegramUpdateProcessor(
        chat_service=service_bundle["service"],
        settings=service_bundle["settings"],
    )
    callback = FakeCallbackQuery(
        data="prefs:video_provider:fal",
    )

    await processor.process_callback(callback=callback, update_id=78)

    stored = await service_bundle["preferences"].get_preference(
        chat_id=100,
        user_id=42,
        preference_type="video_provider",
    )
    assert stored is not None
    assert stored.preset_id == "fal"
    assert "Video provider: 🌌 Fal" in callback.message.edits[0]["text"]
