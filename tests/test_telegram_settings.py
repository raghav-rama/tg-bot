from __future__ import annotations

from types import SimpleNamespace

from app.telegram.handlers import TelegramUpdateProcessor
from test_tts_service import command


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
        data="prefs:video_duration:duration_10s",
    )

    await processor.process_callback(callback=callback, update_id=77)

    stored = await service_bundle["preferences"].get_preference(
        chat_id=100,
        user_id=42,
        preference_type="video_duration",
    )
    assert stored is not None
    assert stored.preset_id == "duration_10s"
    assert callback.answers == [{"text": "Settings updated."}]
    assert "Video duration: ⏱️ 10s" in callback.message.edits[0]["text"]
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


async def test_tts_delivery_menu_and_saved_choice(service_bundle):
    service = service_bundle["service"]
    main = await service.handle_inbound(command("/settings"))
    assert any(button.callback_data == "prefs:menu:tts_delivery"
               for row in main.settings_menu.rows for button in row)
    menu = await service.handle_settings_callback(
        chat_id=100, user_id=42, callback_data="prefs:menu:tts_delivery",
    )
    buttons = [button for row in menu.settings_menu.rows for button in row]
    assert any(button.callback_data == "prefs:tts_delivery:audio" and button.text.startswith("✅")
               for button in buttons)
    assert any(button.callback_data == "prefs:tts_delivery:voice" for button in buttons)
    processor = TelegramUpdateProcessor(chat_service=service, settings=service_bundle["settings"])
    callback = FakeCallbackQuery(data="prefs:tts_delivery:voice")
    await processor.process_callback(callback=callback, update_id=79)
    stored = await service_bundle["preferences"].get_preference(
        chat_id=100, user_id=42, preference_type="tts_delivery",
    )
    assert stored.preset_id == "voice"
    assert "Voice message" in callback.message.edits[0]["text"]
    invalid = await service.handle_settings_callback(
        chat_id=100, user_id=42, callback_data="prefs:tts_delivery:bogus",
    )
    assert invalid.error_type == "ValidationError"
    denied = await service.handle_settings_callback(
        chat_id=100, user_id=99, callback_data="prefs:tts_delivery:audio",
    )
    assert denied.error_type == "UnauthorizedUserError"
