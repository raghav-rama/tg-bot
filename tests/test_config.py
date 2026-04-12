from __future__ import annotations

from app.config import Settings


def test_draft_streaming_defaults_are_conservative(tmp_path) -> None:
    settings = Settings(
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


def test_vertex_api_key_also_enables_image_generation(tmp_path) -> None:
    settings = Settings(
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
