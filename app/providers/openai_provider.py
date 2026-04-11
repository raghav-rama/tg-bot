from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from app.domain.errors import ProviderTimeoutError, ProviderUpstreamError
from app.domain.models import ProviderRequest, ProviderResponse, StreamingProviderEvent


class OpenAIProvider:
    def __init__(self, *, api_key: str, timeout_seconds: float) -> None:
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)

    async def close(self) -> None:
        await self._client.close()

    async def stream_response(
        self,
        request: ProviderRequest,
    ) -> AsyncIterator[StreamingProviderEvent]:
        stream = None
        response = None
        saw_terminal_event = False

        try:
            stream = await self._client.responses.create(
                model=request.model,
                instructions=request.system_prompt,
                input=[{"role": "user", "content": self._build_input_content(request)}],
                temperature=request.temperature,
                max_output_tokens=request.max_output_tokens,
                store=False,
                stream=True,
            )

            async for event in stream:
                event_type = getattr(event, "type", "")
                if event_type == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        yield StreamingProviderEvent(type="delta", text=delta)
                    continue

                if event_type in {"response.completed", "response.incomplete"}:
                    response = getattr(event, "response", None)
                    saw_terminal_event = True
                    continue

                if event_type == "response.failed":
                    raise ProviderUpstreamError("OpenAI request failed")

                if event_type == "error":
                    raise ProviderUpstreamError(
                        getattr(event, "message", "OpenAI request failed")
                    )
        except APITimeoutError as exc:
            raise ProviderTimeoutError("OpenAI request timed out") from exc
        except (APIConnectionError, APIStatusError) as exc:
            raise ProviderUpstreamError("OpenAI request failed") from exc
        finally:
            if stream is not None:
                stream.close()

        if not saw_terminal_event:
            raise ProviderUpstreamError("OpenAI stream ended without completion")

        yield self._build_completed_event(response)

    async def generate_response(self, request: ProviderRequest) -> ProviderResponse:
        reply_parts: list[str] = []
        completed_event: StreamingProviderEvent | None = None

        async for event in self.stream_response(request):
            if event.type == "delta" and event.text:
                reply_parts.append(event.text)
            elif event.type == "completed":
                completed_event = event

        reply_text = "".join(reply_parts).strip()
        if not reply_text:
            raise ProviderUpstreamError("OpenAI returned an empty response")
        if completed_event is None:
            raise ProviderUpstreamError("OpenAI stream ended without completion")

        return ProviderResponse(
            reply_text=reply_text,
            provider_message_id=completed_event.provider_message_id,
            input_tokens=completed_event.input_tokens,
            output_tokens=completed_event.output_tokens,
            finish_reason=completed_event.finish_reason,
            raw_model=completed_event.raw_model,
        )

    def _build_input_content(self, request: ProviderRequest) -> list[dict[str, Any]]:
        input_content: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": self._render_user_prompt(
                    history=request.history,
                    user_message=request.user_message,
                    has_image=request.image is not None,
                ),
            }
        ]

        if request.image is not None:
            input_content.append(
                {
                    "type": "input_image",
                    "image_url": (
                        f"data:{request.image.mime_type};base64,{request.image.bytes_b64}"
                    ),
                }
            )

        return input_content

    def _build_completed_event(self, response: Any) -> StreamingProviderEvent:
        usage = getattr(response, "usage", None) if response is not None else None
        return StreamingProviderEvent(
            type="completed",
            provider_message_id=getattr(response, "id", None),
            input_tokens=getattr(usage, "input_tokens", None) if usage else None,
            output_tokens=getattr(usage, "output_tokens", None) if usage else None,
            finish_reason=getattr(response, "status", None),
            raw_model=getattr(response, "model", None),
        )

    def _render_user_prompt(
        self,
        *,
        history: list,
        user_message: str | None,
        has_image: bool,
    ) -> str:
        sections: list[str] = []
        if history:
            sections.append("Conversation history:")
            for turn in history:
                sections.append(f"{turn.role.title()}: {turn.text}")

        if user_message:
            sections.append("")
            sections.append(f"Current user message: {user_message}")
        elif has_image:
            sections.append("")
            sections.append("Current user sent an image with no caption.")

        if not sections:
            return "Respond to the user's message."
        return "\n".join(sections).strip()
