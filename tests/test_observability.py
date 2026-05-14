from __future__ import annotations

from app.observability import (
    estimate_image_usage,
    estimate_openai_usage,
    estimate_video_usage,
)


def test_openai_usage_estimates_cost_from_token_rates() -> None:
    fields = estimate_openai_usage(
        input_tokens=1000,
        output_tokens=2000,
        input_cost_per_1m_tokens_usd=0.40,
        output_cost_per_1m_tokens_usd=1.60,
    )

    assert fields["input_tokens"] == 1000
    assert fields["output_tokens"] == 2000
    assert fields["total_tokens"] == 3000
    assert fields["cost_estimate_available"] is True
    assert fields["cost_estimated_usd"] == "0.0036"


def test_openai_usage_omits_estimate_when_units_or_rates_are_missing() -> None:
    fields = estimate_openai_usage(
        input_tokens=None,
        output_tokens=2000,
        input_cost_per_1m_tokens_usd=0.40,
        output_cost_per_1m_tokens_usd=1.60,
    )

    assert fields["output_tokens"] == 2000
    assert fields["cost_estimate_available"] is False
    assert "cost_estimated_usd" not in fields


def test_image_usage_estimates_cost_per_generated_image() -> None:
    fields = estimate_image_usage(
        prompt="cinematic poster",
        generated_images=1,
        cost_per_image_usd=0.05,
    )

    assert fields["prompt_chars"] == 16
    assert fields["generated_images"] == 1
    assert fields["cost_estimate_available"] is True
    assert fields["cost_estimated_usd"] == "0.05"


def test_video_usage_estimates_cost_from_duration() -> None:
    fields = estimate_video_usage(
        prompt="rainy alley",
        duration_seconds=4,
        cost_per_second_usd=0.35,
    )

    assert fields["prompt_chars"] == 11
    assert fields["duration_seconds"] == 4
    assert fields["cost_estimate_available"] is True
    assert fields["cost_estimated_usd"] == "1.4"
