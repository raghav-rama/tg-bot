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


def test_normalize_image_command_keeps_full_text() -> None:
    update = build_update(
        {
            "message_id": 13,
            "date": 1_776_000_000,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Ritz", "username": "ritz"},
            "text": "/image watercolor fox in a flower field",
        }
    )

    inbound = normalize_message(
        message=update.message,
        update_id=update.update_id,
        image_bytes=None,
        image_max_bytes=1024,
    )

    assert inbound.message_type == "command"
    assert inbound.command == "/image"
    assert inbound.text == "/image watercolor fox in a flower field"


def test_normalize_reply_photo_image_command_populates_reference_image() -> None:
    update = build_update(
        {
            "message_id": 17,
            "date": 1_776_000_000,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Ritz", "username": "ritz"},
            "text": "/image make this cinematic",
            "reply_to_message": {
                "message_id": 16,
                "date": 1_776_000_000,
                "chat": {"id": 123, "type": "private"},
                "from": {
                    "id": 51,
                    "is_bot": False,
                    "first_name": "Source",
                },
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

    inbound = normalize_message(
        message=update.message,
        update_id=update.update_id,
        image_bytes=None,
        reply_image_bytes=None,
        image_max_bytes=1024,
    )

    assert inbound.message_type == "command"
    assert inbound.command == "/image"
    assert inbound.text == "/image make this cinematic"
    assert inbound.image is not None
    assert inbound.image.telegram_file_id == "reply-large"
    assert inbound.image.telegram_file_unique_id == "reply-uniq-large"
    assert inbound.image.byte_size == 512
    assert inbound.image.bytes_b64 is None
    assert inbound.image.caption is None


def test_normalize_reply_to_non_photo_command_does_not_create_reference_image() -> None:
    update = build_update(
        {
            "message_id": 18,
            "date": 1_776_000_000,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Ritz", "username": "ritz"},
            "text": "/video animate this",
            "reply_to_message": {
                "message_id": 17,
                "date": 1_776_000_000,
                "chat": {"id": 123, "type": "private"},
                "from": {
                    "id": 51,
                    "is_bot": False,
                    "first_name": "Source",
                },
                "text": "plain source message",
            },
        }
    )

    inbound = normalize_message(
        message=update.message,
        update_id=update.update_id,
        image_bytes=None,
        reply_image_bytes=None,
        image_max_bytes=1024,
    )

    assert inbound.message_type == "command"
    assert inbound.command == "/video"
    assert inbound.image is None


def test_normalize_photo_caption_image_command_populates_reference_image() -> None:
    update = build_update(
        {
            "message_id": 14,
            "date": 1_776_000_000,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Ritz", "username": "ritz"},
            "caption": "/image stylize this as ink wash",
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
        image_bytes=None,
        image_max_bytes=1024,
    )

    assert inbound.message_type == "command"
    assert inbound.command == "/image"
    assert inbound.text == "/image stylize this as ink wash"
    assert inbound.image is not None
    assert inbound.image.telegram_file_id == "large"
    assert inbound.image.byte_size == 512
    assert inbound.image.bytes_b64 is None


def test_normalize_photo_caption_video_command_populates_reference_image() -> None:
    update = build_update(
        {
            "message_id": 15,
            "date": 1_776_000_000,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Ritz", "username": "ritz"},
            "caption": "/video animate this scene",
            "photo": [
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
        image_bytes=None,
        image_max_bytes=1024,
    )

    assert inbound.message_type == "command"
    assert inbound.command == "/video"
    assert inbound.text == "/video animate this scene"
    assert inbound.image is not None
    assert inbound.image.telegram_file_unique_id == "uniq-large"
    assert inbound.image.byte_size == 512
    assert inbound.image.bytes_b64 is None


def test_normalize_photo_caption_unknown_video_command_falls_back_to_image_message() -> None:
    update = build_update(
        {
            "message_id": 16,
            "date": 1_776_000_000,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Ritz", "username": "ritz"},
            "caption": "/video_ltx animate this scene",
            "photo": [
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
        image_bytes=b"reference-image",
        image_max_bytes=1024,
    )

    assert inbound.message_type == "image"
    assert inbound.command is None
    assert inbound.text == "/video_ltx animate this scene"
    assert inbound.image is not None
    assert inbound.image.telegram_file_unique_id == "uniq-large"


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
