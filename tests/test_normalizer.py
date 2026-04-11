from __future__ import annotations

from aiogram.types import Update

from app.telegram.normalizer import normalize_message


def build_update(message_payload: dict) -> Update:
    return Update.model_validate(
        {
            "update_id": 1001,
            "message": message_payload,
        }
    )


def test_normalize_text_message() -> None:
    update = build_update(
        {
            "message_id": 10,
            "date": 1_776_000_000,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Ritz", "username": "ritz"},
            "text": "hello world",
        }
    )

    inbound = normalize_message(
        message=update.message,
        update_id=update.update_id,
        image_bytes=None,
        image_max_bytes=1024,
    )

    assert inbound.message_type == "text"
    assert inbound.text == "hello world"
    assert inbound.command is None
    assert inbound.chat_id == 123
    assert inbound.user_id == 42


def test_normalize_photo_message() -> None:
    update = build_update(
        {
            "message_id": 11,
            "date": 1_776_000_000,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Ritz", "username": "ritz"},
            "caption": "describe this",
            "photo": [
                {
                    "file_id": "small",
                    "file_unique_id": "uniq-small",
                    "width": 90,
                    "height": 90,
                    "file_size": 100,
                },
                {
                    "file_id": "large",
                    "file_unique_id": "uniq-large",
                    "width": 1280,
                    "height": 720,
                    "file_size": 512,
                },
            ],
        }
    )

    inbound = normalize_message(
        message=update.message,
        update_id=update.update_id,
        image_bytes=b"image-bytes",
        image_max_bytes=1024,
    )

    assert inbound.message_type == "image"
    assert inbound.text == "describe this"
    assert inbound.image is not None
    assert inbound.image.telegram_file_id == "large"
    assert inbound.image.byte_size == len(b"image-bytes")


def test_normalize_unsupported_message_type() -> None:
    update = build_update(
        {
            "message_id": 12,
            "date": 1_776_000_000,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Ritz", "username": "ritz"},
            "sticker": {
                "file_id": "sticker",
                "file_unique_id": "sticker-uniq",
                "type": "regular",
                "width": 128,
                "height": 128,
                "is_animated": False,
                "is_video": False,
            },
        }
    )

    try:
        normalize_message(
            message=update.message,
            update_id=update.update_id,
            image_bytes=None,
            image_max_bytes=1024,
        )
    except Exception as exc:
        assert exc.__class__.__name__ == "UnsupportedMessageError"
    else:
        raise AssertionError("Expected UnsupportedMessageError")

