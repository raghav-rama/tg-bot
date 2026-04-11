from __future__ import annotations

from app.domain.commands import ACCESS_DENIED_TEXT
from app.domain.models import InboundMessage

from datetime import datetime, timezone


def utc_datetime() -> datetime:
    return datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc)


def make_text_message(*, user_id: int, chat_id: int, text: str, update_id: int = 1) -> InboundMessage:
    return InboundMessage(
        update_id=update_id,
        telegram_message_id=update_id,
        chat_id=chat_id,
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
    return InboundMessage(
        update_id=update_id,
        telegram_message_id=update_id,
        chat_id=chat_id,
        user_id=user_id,
        username="ritz",
        first_name="Ritz",
        message_type="command",
        text=command,
        command=command,
        image=None,
        sent_at=utc_datetime(),
    )


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
