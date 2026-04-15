from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


_REPO_ENV_KEYS = (
    "BOT_DRAFT_START_DELAY_MS",
    "BOT_DRAFT_UPDATE_INTERVAL_MS",
    "BOT_DRAFT_MIN_CHARS_DELTA",
    "BOT_VIDEO_MAX_BYTES",
    "OPENAI_MODEL",
    "OPENAI_TEMPERATURE",
    "OPENAI_MAX_OUTPUT_TOKENS",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USER_IDS",
    "TELEGRAM_VIDEO_REQUEST_TIMEOUT_SECONDS",
    "VERTEX_API_KEY",
    "VERTEX_IMAGE_ASPECT_RATIO",
    "VERTEX_IMAGE_MODEL",
    "VERTEX_IMAGE_OUTPUT_MIME_TYPE",
    "VERTEX_LOCATION",
    "VERTEX_PROJECT_ID",
    "VERTEX_VIDEO_ASPECT_RATIO",
    "VERTEX_VIDEO_DURATION_SECONDS",
    "VERTEX_VIDEO_MODEL",
    "VERTEX_VIDEO_OUTPUT_GCS_URI",
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
        SQLITE_PATH=str(tmp_path / "bot.db"),
    )

    assert settings.bot_draft_start_delay_ms == 750
    assert settings.bot_draft_update_interval_ms == 1200
    assert settings.bot_draft_min_chars_delta == 80
    assert settings.vertex_project_id is None
    assert settings.vertex_location == "us-central1"
    assert settings.vertex_image_model == "imagen-4.0-fast-generate-001"
    assert settings.vertex_video_model == "veo-3.0-fast-generate-001"
    assert settings.vertex_video_duration_seconds == 4
    assert settings.bot_video_max_bytes == 50 * 1024 * 1024
    assert settings.telegram_video_request_timeout_seconds == 180
    assert settings.video_job_poll_interval_seconds == 15
    assert settings.vertex_image_generation_enabled is False
    assert settings.vertex_video_generation_enabled is False


def test_vertex_api_key_also_enables_image_generation(tmp_path, monkeypatch) -> None:
    _clear_repo_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="test-token",
        OPENAI_API_KEY="test-key",
        TELEGRAM_ALLOWED_USER_IDS="42",
        APP_UPDATE_MODE="webhook",
        SQLITE_PATH=str(tmp_path / "bot.db"),
        VERTEX_API_KEY="vertex-test-key",
    )

    assert settings.vertex_api_key is not None
    assert settings.vertex_api_key.get_secret_value() == "vertex-test-key"
    assert settings.vertex_image_generation_enabled is True
    assert settings.vertex_video_generation_enabled is True


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
        SQLITE_PATH=str(tmp_path / "bot.db"),
        VERTEX_API_KEY="vertex-test-key",
        VERTEX_IMAGE_MODEL="gemini-3-pro-image-preview",
        VERTEX_LOCATION="global",
    )

    assert settings.vertex_image_model == "gemini-3-pro-image-preview"
    assert settings.vertex_location == "global"
