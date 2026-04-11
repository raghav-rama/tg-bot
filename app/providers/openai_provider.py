from __future__ import annotations

from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from app.domain.errors import ProviderTimeoutError, ProviderUpstreamError
from app.domain.models import ProviderRequest, ProviderResponse


class OpenAIProvider:
    def __init__(self, *, api_key: str, timeout_seconds: float) -> None:
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)

    async def close(self) -> None:
        await self._client.close()

    async def generate_response(self, request: ProviderRequest) -> ProviderResponse:
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

        try:
            response = await self._client.responses.create(
                model=request.model,
                instructions=request.system_prompt,
                input=[{"role": "user", "content": input_content}],
                temperature=request.temperature,
                max_output_tokens=request.max_output_tokens,
                store=False,
            )
        except APITimeoutError as exc:
            raise ProviderTimeoutError("OpenAI request timed out") from exc
        except (APIConnectionError, APIStatusError) as exc:
            raise ProviderUpstreamError("OpenAI request failed") from exc

        reply_text = (getattr(response, "output_text", "") or "").strip()
        if not reply_text:
            raise ProviderUpstreamError("OpenAI returned an empty response")

        usage = getattr(response, "usage", None)
        return ProviderResponse(
            reply_text=reply_text,
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

