from __future__ import annotations

from typing import Any


def _format_usd(value: float) -> str:
    formatted = f"{value:.6f}".rstrip("0").rstrip(".")
    return formatted or "0"


def estimate_openai_usage(
    *,
    input_tokens: int | None,
    output_tokens: int | None,
    input_cost_per_1m_tokens_usd: float,
    output_cost_per_1m_tokens_usd: float,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    if input_tokens is not None and output_tokens is not None:
        fields["total_tokens"] = input_tokens + output_tokens

    if (
        input_tokens is None
        or output_tokens is None
        or input_cost_per_1m_tokens_usd <= 0
        or output_cost_per_1m_tokens_usd <= 0
    ):
        fields["cost_estimate_available"] = False
        return _without_none(fields)

    cost = (
        input_tokens * input_cost_per_1m_tokens_usd
        + output_tokens * output_cost_per_1m_tokens_usd
    ) / 1_000_000
    fields["cost_estimate_available"] = True
    fields["cost_estimated_usd"] = _format_usd(cost)
    return _without_none(fields)


def estimate_image_usage(
    *,
    prompt: str,
    generated_images: int,
    cost_per_image_usd: float,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "prompt_chars": len(prompt),
        "generated_images": generated_images,
    }
    if generated_images <= 0 or cost_per_image_usd <= 0:
        fields["cost_estimate_available"] = False
        return fields

    fields["cost_estimate_available"] = True
    fields["cost_estimated_usd"] = _format_usd(generated_images * cost_per_image_usd)
    return fields


def estimate_video_usage(
    *,
    prompt: str,
    duration_seconds: int | None,
    cost_per_second_usd: float,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "prompt_chars": len(prompt),
        "duration_seconds": duration_seconds,
    }
    if duration_seconds is None or duration_seconds <= 0 or cost_per_second_usd <= 0:
        fields["cost_estimate_available"] = False
        return _without_none(fields)

    fields["cost_estimate_available"] = True
    fields["cost_estimated_usd"] = _format_usd(
        duration_seconds * cost_per_second_usd
    )
    return fields


def _without_none(fields: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}
