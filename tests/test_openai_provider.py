from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.models import ProviderRequest
from app.providers.openai_provider import OpenAIProvider


class _FakeStream:
    def __init__(self, events: list[object]) -> None:
        self._events = iter(events)
        self.close_awaited = False

    def __aiter__(self) -> "_FakeStream":
        return self

    async def __anext__(self) -> object:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def close(self) -> None:
        self.close_awaited = True


@pytest.mark.asyncio
async def test_stream_response_awaits_stream_close() -> None:
    provider = OpenAIProvider(api_key="test-key", timeout_seconds=5.0)
    stream = _FakeStream(
        [
            SimpleNamespace(type="response.output_text.delta", delta="hello"),
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    id="resp_123",
                    model="gpt-5.4",
                    status="completed",
                    usage=SimpleNamespace(input_tokens=3, output_tokens=5),
                ),
            ),
        ]
    )
    provider._client = SimpleNamespace(
        responses=SimpleNamespace(
            create=_fake_create(stream),
        ),
        close=_fake_close,
    )

    events = [
        event
        async for event in provider.stream_response(
            ProviderRequest(
                chat_id=1,
                user_id=42,
                system_prompt="system",
                history=[],
                user_message="hello",
                image=None,
                model="gpt-5.4",
                temperature=0.2,
                max_output_tokens=50,
            )
        )
    ]

    assert [event.type for event in events] == ["delta", "completed"]
    assert stream.close_awaited is True


def _fake_create(stream: _FakeStream):
    async def create(**_kwargs):
        return stream

    return create


async def _fake_close() -> None:
    return None
