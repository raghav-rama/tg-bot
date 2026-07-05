from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


_REPO_ENV_KEYS = (
    "APP_LOG_FORMAT",
    "BOT_DRAFT_START_DELAY_MS",
    "BOT_DRAFT_UPDATE_INTERVAL_MS",
    "BOT_DRAFT_MIN_CHARS_DELTA",
    "BOT_VIDEO_MAX_BYTES",
    "OPENAI_INPUT_COST_PER_1M_TOKENS_USD",
    "OPENAI_MODEL",
    "OPENAI_OUTPUT_COST_PER_1M_TOKENS_USD",
    "OPENAI_TEMPERATURE",
    "OPENAI_MAX_OUTPUT_TOKENS",
    "RUNPOD_API_KEY",
    "RUNPOD_VIDEO_BASE_URL",
    "RUNPOD_VIDEO_COST_PER_SECOND_USD",
    "RUNPOD_VIDEO_DURATION_SECONDS",
    "RUNPOD_VIDEO_ENDPOINT_ID",
    "RUNPOD_VIDEO_EXECUTION_TIMEOUT_MS",
    "RUNPOD_VIDEO_FRAME_RATE",
    "RUNPOD_VIDEO_HEIGHT",
    "RUNPOD_VIDEO_MODEL",
    "RUNPOD_VIDEO_REFERENCE_IMAGE_MAX_BYTES",
    "RUNPOD_VIDEO_SIGNED_URL_TTL_SECONDS",
    "RUNPOD_VIDEO_TTL_MS",
    "RUNPOD_VIDEO_WIDTH",
    "FAL_API_KEY",
    "FAL_VIDEO_BASE_URL",
    "FAL_VIDEO_MODEL",
    "FAL_VIDEO_IMAGE_TO_VIDEO_MODEL",
    "FAL_VIDEO_REFERENCE_IMAGE_MAX_BYTES",
    "FAL_VIDEO_COST_PER_SECOND_USD",
    "FAL_VIDEO_SUBMIT_TIMEOUT_SECONDS",
    "FAL_VIDEO_REFERENCE_TO_VIDEO_MODEL",
    "FAL_VIDEO_EDIT_MODEL",
    "FAL_VIDEO_RESOLUTION",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USER_IDS",
    "TELEGRAM_WEBHOOK_DROP_PENDING_UPDATES",
    "TELEGRAM_WEBHOOK_SECRET_TOKEN",
    "TELEGRAM_WEBHOOK_URL",
    "TELEGRAM_VIDEO_REQUEST_TIMEOUT_SECONDS",
    "VERTEX_API_KEY",
    "VERTEX_IMAGE_ASPECT_RATIO",
    "VERTEX_IMAGE_MODEL",
    "VERTEX_IMAGE_OUTPUT_MIME_TYPE",
    "VERTEX_IMAGE_COST_PER_IMAGE_USD",
    "VERTEX_LOCATION",
    "VERTEX_PROJECT_ID",
    "VERTEX_VIDEO_ASPECT_RATIO",
    "VERTEX_VIDEO_COST_PER_SECOND_USD",
    "VERTEX_VIDEO_DURATION_SECONDS",
    "VERTEX_VIDEO_MODEL",
    "VERTEX_VIDEO_OUTPUT_GCS_URI",
    "VIDEO_PROVIDER_ORDER",
    "VIDEO_JOB_POLL_INTERVAL_SECONDS",
)


def _clear_repo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _REPO_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_draft_streaming_defaults_are_conservative(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="test-token",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
        TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
        SQLITE_PATH=str(tmp_path / "bot.db"),
    )

    assert settings.bot_draft_start_delay_ms == 750
    assert settings.bot_draft_update_interval_ms == 1200
    assert settings.bot_draft_min_chars_delta == 80
    assert settings.app_log_format == "text"
    assert settings.telegram_webhook_drop_pending_updates is False
    assert settings.vertex_project_id is None
    assert settings.vertex_location == "us-central1"
    assert settings.vertex_image_model == "imagen-4.0-fast-generate-001"
    assert settings.vertex_video_model == "veo-3.0-fast-generate-001"
    assert settings.vertex_video_duration_seconds == 4
    assert settings.video_provider_order == ("vertex", "runpod")
    assert settings.runpod_video_base_url == "https://api.runpod.ai/v2"
    assert settings.runpod_video_model == "ltx-2.3-22b-distilled-1.1"
    assert settings.runpod_video_width == 576
    assert settings.runpod_video_height == 1024
    assert settings.runpod_video_duration_seconds == 4
    assert settings.runpod_video_frame_rate == 24.0
    assert settings.runpod_video_execution_timeout_ms == 1_800_000
    assert settings.runpod_video_ttl_ms == 7_200_000
    assert settings.runpod_video_reference_image_max_bytes == 6_000_000
    assert settings.runpod_video_signed_url_ttl_seconds == 3600
    assert settings.runpod_video_cost_per_second_usd == 0.0
    assert settings.bot_video_max_bytes == 50 * 1024 * 1024
    assert settings.telegram_video_request_timeout_seconds == 180
    assert settings.video_job_poll_interval_seconds == 15
    assert settings.openai_input_cost_per_1m_tokens_usd == 0.0
    assert settings.openai_output_cost_per_1m_tokens_usd == 0.0
    assert settings.vertex_image_cost_per_image_usd == 0.0
    assert settings.vertex_video_cost_per_second_usd == 0.0
    assert settings.runpod_video_cost_per_second_usd == 0.0
    assert settings.fal_video_base_url == "https://queue.fal.run"
    assert settings.fal_video_model == "fal-ai/kling-video/v3/standard/text-to-video"
    assert settings.fal_video_image_to_video_model is None
    assert settings.fal_video_reference_image_max_bytes == 6_000_000
    assert settings.fal_video_cost_per_second_usd == 0.0
    assert settings.fal_video_submit_timeout_seconds == 45
    assert settings.fal_video_reference_to_video_model is None
    assert settings.fal_video_edit_model is None
    assert settings.fal_video_resolution == "720p"
    assert settings.vertex_image_generation_enabled is False
    assert settings.vertex_video_generation_enabled is False
    assert settings.runpod_video_generation_enabled is False
    assert settings.fal_video_generation_enabled is False
    assert settings.video_generation_enabled is False



def test_cost_estimate_rates_can_be_configured(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="test-token",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
        TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
        SQLITE_PATH=str(tmp_path / "bot.db"),
        OPENAI_INPUT_COST_PER_1M_TOKENS_USD="0.4",
        OPENAI_OUTPUT_COST_PER_1M_TOKENS_USD="1.6",
        VERTEX_IMAGE_COST_PER_IMAGE_USD="0.05",
        VERTEX_VIDEO_COST_PER_SECOND_USD="0.35",
        RUNPOD_VIDEO_COST_PER_SECOND_USD="0.12",
    )

    assert settings.openai_input_cost_per_1m_tokens_usd == 0.4
    assert settings.openai_output_cost_per_1m_tokens_usd == 1.6
    assert settings.vertex_image_cost_per_image_usd == 0.05
    assert settings.vertex_video_cost_per_second_usd == 0.35
    assert settings.runpod_video_cost_per_second_usd == 0.12


def test_app_log_format_accepts_json(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="test-token",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
        TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
        SQLITE_PATH=str(tmp_path / "bot.db"),
        APP_LOG_FORMAT="json",
    )

    assert settings.app_log_format == "json"


def test_app_log_format_rejects_unknown_values(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    with pytest.raises(ValidationError, match="APP_LOG_FORMAT must be 'text' or 'json'"):
        Settings(
            _env_file=None,
            TELEGRAM_BOT_TOKEN="test-token",
            OPENAI_API_KEY="test-key",
            TELEGRAM_ALLOWED_USER_IDS="42",
            APP_UPDATE_MODE="webhook",
            TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
            TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
            SQLITE_PATH=str(tmp_path / "bot.db"),
            APP_LOG_FORMAT="pretty",
        )


def test_vertex_api_key_also_enables_image_generation(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="test-token",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
        TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
        SQLITE_PATH=str(tmp_path / "bot.db"),
        VERTEX_API_KEY="vertex-test-key",
    )

    assert settings.vertex_api_key is not None
    assert settings.vertex_api_key.get_secret_value() == "vertex-test-key"
    assert settings.vertex_image_generation_enabled is True
    assert settings.vertex_video_generation_enabled is True
    assert settings.video_generation_enabled is True


def test_runpod_only_video_config_enables_video_generation(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="test-token",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
        TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
        SQLITE_PATH=str(tmp_path / "bot.db"),
        VIDEO_PROVIDER_ORDER="runpod",
        RUNPOD_API_KEY="runpod-test-key",
        RUNPOD_VIDEO_ENDPOINT_ID="ltx-endpoint",
    )

    assert settings.vertex_video_generation_enabled is False
    assert settings.runpod_video_generation_enabled is True
    assert settings.fal_video_generation_enabled is False
    assert settings.video_generation_enabled is True
    assert settings.video_provider_order == ("runpod",)


async def test_fal_video_provider_order_requires_api_key(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    with pytest.raises(ValidationError, match="FAL_API_KEY is required"):
        Settings(
            _env_file=None,
            TELEGRAM_BOT_TOKEN="test-token",
            OPENAI_API_KEY="test-key",
            TELEGRAM_ALLOWED_USER_IDS="42",
            APP_UPDATE_MODE="webhook",
            TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
            TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
            SQLITE_PATH=str(tmp_path / "bot.db"),
            VIDEO_PROVIDER_ORDER="fal,vertex",
        )


async def test_fal_only_video_config_enables_video_generation(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="test-token",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
        TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
        SQLITE_PATH=str(tmp_path / "bot.db"),
        VIDEO_PROVIDER_ORDER="fal",
        FAL_API_KEY="fal-test-key",
    )

    assert settings.vertex_video_aspect_ratio == "9:16"
    assert settings.vertex_video_generation_enabled is False
    assert settings.runpod_video_generation_enabled is False
    assert settings.fal_video_generation_enabled is True
    assert settings.video_generation_enabled is True
    assert settings.video_provider_order == ("fal",)


async def test_fal_video_provider_order_accepted(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="test-token",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
        TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
        SQLITE_PATH=str(tmp_path / "bot.db"),
        VIDEO_PROVIDER_ORDER="fal,vertex,runpod",
        FAL_API_KEY="fal-test-key",
        VERTEX_API_KEY="vertex-test-key",
        RUNPOD_API_KEY="runpod-test-key",
        RUNPOD_VIDEO_ENDPOINT_ID="ltx-endpoint",
    )

    assert settings.video_provider_order == ("fal", "vertex", "runpod")
    assert settings.video_generation_enabled is True


def test_video_provider_order_env_accepts_comma_separated_value(
    tmp_path,
    monkeypatch,
) -> None:
    _clear_repo_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "42")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "bot.db"))
    monkeypatch.setenv("VIDEO_PROVIDER_ORDER", "runpod")
    monkeypatch.setenv("RUNPOD_API_KEY", "runpod-test-key")
    monkeypatch.setenv("RUNPOD_VIDEO_ENDPOINT_ID", "ltx-endpoint")

    settings = Settings(_env_file=None)

    assert settings.video_provider_order == ("runpod",)
    assert settings.video_generation_enabled is True


def test_runpod_video_duration_defaults_to_vertex_duration(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="test-token",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
        TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
        SQLITE_PATH=str(tmp_path / "bot.db"),
        VERTEX_VIDEO_DURATION_SECONDS="3",
    )

    assert settings.vertex_video_duration_seconds == 3
    assert settings.runpod_video_duration_seconds == 3


def test_runpod_video_native_settings_can_be_configured(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="test-token",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
        TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
        SQLITE_PATH=str(tmp_path / "bot.db"),
        RUNPOD_VIDEO_WIDTH="1152",
        RUNPOD_VIDEO_HEIGHT="2048",
        RUNPOD_VIDEO_DURATION_SECONDS="5",
        RUNPOD_VIDEO_FRAME_RATE="25",
        RUNPOD_VIDEO_SIGNED_URL_TTL_SECONDS="900",
    )

    assert settings.runpod_video_width == 1152
    assert settings.runpod_video_height == 2048
    assert settings.runpod_video_duration_seconds == 5
    assert settings.runpod_video_frame_rate == 25.0
    assert settings.runpod_video_signed_url_ttl_seconds == 900


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"RUNPOD_VIDEO_WIDTH": "575"}, "RUNPOD_VIDEO_WIDTH must be divisible by 64"),
        ({"RUNPOD_VIDEO_HEIGHT": "1023"}, "RUNPOD_VIDEO_HEIGHT must be divisible by 64"),
        ({"RUNPOD_VIDEO_FRAME_RATE": "0"}, "RUNPOD_VIDEO_FRAME_RATE must be greater than zero"),
    ],
)
def test_runpod_video_native_settings_are_validated(
    tmp_path,
    monkeypatch,
    override,
    message,
) -> None:
    _clear_repo_env(monkeypatch)
    values = {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "OPENAI_API_KEY": "test-key",
        "TELEGRAM_ALLOWED_USER_IDS": "42",
        "APP_UPDATE_MODE": "webhook",
        "TELEGRAM_WEBHOOK_URL": "https://bot.example.com/telegram/webhook",
        "TELEGRAM_WEBHOOK_SECRET_TOKEN": "test-webhook-secret",
        "SQLITE_PATH": str(tmp_path / "bot.db"),
    }
    values.update(override)

    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **values)


def test_video_provider_order_rejects_unknown_providers(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    with pytest.raises(ValidationError, match="VIDEO_PROVIDER_ORDER"):
        Settings(
            _env_file=None,
            TELEGRAM_BOT_TOKEN="test-token",
            OPENAI_API_KEY="test-key",
            TELEGRAM_ALLOWED_USER_IDS="42",
            APP_UPDATE_MODE="webhook",
            TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
            TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
            SQLITE_PATH=str(tmp_path / "bot.db"),
            VIDEO_PROVIDER_ORDER="vertex,banana",
        )


def test_runpod_video_requires_api_key_and_endpoint_id(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    with pytest.raises(
        ValidationError,
        match="RUNPOD_API_KEY and RUNPOD_VIDEO_ENDPOINT_ID must be configured together",
    ):
        Settings(
            _env_file=None,
            TELEGRAM_BOT_TOKEN="test-token",
            OPENAI_API_KEY="test-key",
            TELEGRAM_ALLOWED_USER_IDS="42",
            APP_UPDATE_MODE="webhook",
            TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
            TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
            SQLITE_PATH=str(tmp_path / "bot.db"),
            RUNPOD_API_KEY="runpod-test-key",
        )


def test_gemini_3_pro_image_requires_global_location_when_enabled(
    tmp_path, monkeypatch
) -> None:
    _clear_repo_env(monkeypatch)
    with pytest.raises(
        ValidationError,
        match="VERTEX_LOCATION must be 'global' when VERTEX_IMAGE_MODEL is 'gemini-3-pro-image-preview'",
    ):
        Settings(
            _env_file=None,
            TELEGRAM_BOT_TOKEN="test-token",
            OPENAI_API_KEY="test-key",
            TELEGRAM_ALLOWED_USER_IDS="42",
            APP_UPDATE_MODE="webhook",
            TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
            TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
            SQLITE_PATH=str(tmp_path / "bot.db"),
            VERTEX_API_KEY="vertex-test-key",
            VERTEX_IMAGE_MODEL="gemini-3-pro-image-preview",
            VERTEX_LOCATION="us-central1",
        )


def test_gemini_3_pro_image_accepts_global_location(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="test-token",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
        TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
        SQLITE_PATH=str(tmp_path / "bot.db"),
        VERTEX_API_KEY="vertex-test-key",
        VERTEX_IMAGE_MODEL="gemini-3-pro-image-preview",
        VERTEX_LOCATION="global",
    )

    assert settings.vertex_image_model == "gemini-3-pro-image-preview"
    assert settings.vertex_location == "global"


def test_webhook_mode_requires_public_url(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    with pytest.raises(
        ValidationError,
        match="TELEGRAM_WEBHOOK_URL is required when APP_UPDATE_MODE is 'webhook'",
    ):
        Settings(
            _env_file=None,
            TELEGRAM_BOT_TOKEN="test-token",
            OPENAI_API_KEY="test-key",
            TELEGRAM_ALLOWED_USER_IDS="42",
            APP_UPDATE_MODE="webhook",
            TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
            SQLITE_PATH=str(tmp_path / "bot.db"),
        )


def test_webhook_mode_requires_secret_token(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    with pytest.raises(
        ValidationError,
        match="TELEGRAM_WEBHOOK_SECRET_TOKEN is required when APP_UPDATE_MODE is 'webhook'",
    ):
        Settings(
            _env_file=None,
            TELEGRAM_BOT_TOKEN="test-token",
            OPENAI_API_KEY="test-key",
            TELEGRAM_ALLOWED_USER_IDS="42",
            APP_UPDATE_MODE="webhook",
            TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
            SQLITE_PATH=str(tmp_path / "bot.db"),
        )


def test_webhook_url_must_be_https(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    with pytest.raises(
        ValidationError,
        match="TELEGRAM_WEBHOOK_URL must be a valid HTTPS URL",
    ):
        Settings(
            _env_file=None,
            TELEGRAM_BOT_TOKEN="test-token",
            OPENAI_API_KEY="test-key",
            TELEGRAM_ALLOWED_USER_IDS="42",
            APP_UPDATE_MODE="webhook",
            TELEGRAM_WEBHOOK_URL="http://bot.example.com/telegram/webhook",
            TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
            SQLITE_PATH=str(tmp_path / "bot.db"),
        )


def test_fal_video_family_detection_from_mode_endpoints(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="test-token",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
        TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
        SQLITE_PATH=str(tmp_path / "bot.db"),
        FAL_API_KEY="test-fal-key",
        FAL_VIDEO_TEXT_TO_VIDEO_MODEL="fal-ai/google/gemini-omni-flash",
        FAL_VIDEO_IMAGE_TO_VIDEO_MODEL="fal-ai/google/gemini-omni-flash/image-to-video",
        FAL_VIDEO_REFERENCE_TO_VIDEO_MODEL="fal-ai/google/gemini-omni-flash/reference-to-video",
    )

    assert settings.fal_video_available_families == {"gemini"}
    assert settings.fal_video_default_family == "gemini"
    assert settings.fal_video_model_for_mode("gemini") == "fal-ai/google/gemini-omni-flash"
    assert (
        settings.fal_video_model_for_mode("gemini", has_reference_image=True)
        == "fal-ai/google/gemini-omni-flash/reference-to-video"
    )


def test_fal_video_model_for_mode_falls_back_to_text_model(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="test-token",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
        TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
        SQLITE_PATH=str(tmp_path / "bot.db"),
        FAL_API_KEY="test-fal-key",
        FAL_VIDEO_TEXT_TO_VIDEO_MODEL="fal-ai/google/gemini-omni-flash",
    )

    assert settings.fal_video_model_for_mode("gemini", has_reference_image=True) == (
        "fal-ai/google/gemini-omni-flash"
    )


def test_fal_video_available_families_includes_multiple_families(
    tmp_path,
    monkeypatch,
) -> None:
    _clear_repo_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="test-token",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
        TELEGRAM_WEBHOOK_SECRET_TOKEN="test-webhook-secret",
        SQLITE_PATH=str(tmp_path / "bot.db"),
        FAL_API_KEY="test-fal-key",
        FAL_VIDEO_TEXT_TO_VIDEO_MODEL="fal-ai/kling-video/v3/standard/text-to-video",
        FAL_VIDEO_REFERENCE_TO_VIDEO_MODEL="bytedance/seedance-2.0/reference-to-video",
    )

    assert settings.fal_video_available_families == {"kling", "seedance"}


def test_webhook_secret_token_is_restricted_to_telegram_charset(
    tmp_path,
    monkeypatch,
) -> None:
    _clear_repo_env(monkeypatch)
    with pytest.raises(
        ValidationError,
        match="TELEGRAM_WEBHOOK_SECRET_TOKEN must be 1-256 characters",
    ):
        Settings(
            _env_file=None,
            TELEGRAM_BOT_TOKEN="test-token",
            OPENAI_API_KEY="test-key",
            TELEGRAM_ALLOWED_USER_IDS="42",
            APP_UPDATE_MODE="webhook",
            TELEGRAM_WEBHOOK_URL="https://bot.example.com/telegram/webhook",
            TELEGRAM_WEBHOOK_SECRET_TOKEN="bad secret!",
            SQLITE_PATH=str(tmp_path / "bot.db"),
        )
