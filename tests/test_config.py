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

