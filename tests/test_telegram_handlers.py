from __future__ import annotations

from aiogram.types import Update

from app.domain.models import ServiceReply
from app.telegram.handlers import TelegramUpdateProcessor


def build_update(message_payload: dict) -> Update:
    return Update.model_validate(
        {
            "update_id": 2001,
            "message": message_payload,
        }
    )


class CapturingChatService:
    def __init__(self) -> None:
        self.inbound_messages = []

    async def handle_inbound(self, inbound, *, responder) -> ServiceReply:
        self.inbound_messages.append(inbound)
        return ServiceReply(text="", delivered=True)

    async def handle_normalization_error(self, **_kwargs) -> ServiceReply:
        raise AssertionError("normalization should not fail")


class FakeBot:
    def __init__(self) -> None:
        self.downloaded_file_ids: list[str] = []
        self.sent_messages: list[dict[str, object]] = []

    async def download(self, file, *, destination) -> None:
        self.downloaded_file_ids.append(file.file_id)
        destination.write(b"downloaded-reply-photo")

    async def send_message(self, **kwargs) -> None:
        self.sent_messages.append(kwargs)


async def test_processor_downloads_replied_photo_for_text_image_command(
    service_bundle,
) -> None:
    chat_service = CapturingChatService()
    processor = TelegramUpdateProcessor(
        chat_service=chat_service,
        settings=service_bundle["settings"],
    )
    bot = FakeBot()
    update = build_update(
        {
            "message_id": 22,
            "date": 1_776_000_000,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Ritz", "username": "ritz"},
            "text": "/image make this cinematic",
            "reply_to_message": {
                "message_id": 21,
                "date": 1_776_000_000,
                "chat": {"id": 123, "type": "private"},
                "from": {"id": 51, "is_bot": False, "first_name": "Source"},
                "photo": [
                    {
                        "file_id": "reply-small",
                        "file_unique_id": "reply-uniq-small",
                        "width": 90,
                        "height": 90,
                        "file_size": 100,
                    },
                    {
                        "file_id": "reply-large",
                        "file_unique_id": "reply-uniq-large",
                        "width": 1280,
                        "height": 720,
                        "file_size": 512,
                    },
                ],
            },
        }
    )

    await processor.process_message(
        message=update.message,
        bot=bot,
        update_id=update.update_id,
    )

    assert bot.downloaded_file_ids == ["reply-large"]
    assert len(chat_service.inbound_messages) == 1
    inbound = chat_service.inbound_messages[0]
    assert inbound.text == "/image make this cinematic"
    assert inbound.image is not None
    assert inbound.image.telegram_file_id == "reply-large"
    assert inbound.image.bytes_b64 == "ZG93bmxvYWRlZC1yZXBseS1waG90bw=="
