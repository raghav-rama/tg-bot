from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SYSTEM_PROMPT = (
    "You are a concise assistant for a YouTube channel workflow. "
    "Help brainstorm content ideas, titles, hooks, and clear answers. "
    "Keep responses practical and safe. "
    "If the request is underspecified, ask one brief follow-up question."
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    openai_api_key: SecretStr = Field(alias="OPENAI_API_KEY")
    telegram_allowed_user_ids: str = Field(alias="TELEGRAM_ALLOWED_USER_IDS")

    app_env: str = Field(default="development", alias="APP_ENV")
    app_log_level: str = Field(default="INFO", alias="APP_LOG_LEVEL")
    app_update_mode: str = Field(default="polling", alias="APP_UPDATE_MODE")
    sqlite_path: Path = Field(default=Path("./data/bot.db"), alias="SQLITE_PATH")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    openai_temperature: float = Field(default=0.2, alias="OPENAI_TEMPERATURE")
    openai_max_output_tokens: int = Field(
        default=500,
        alias="OPENAI_MAX_OUTPUT_TOKENS",
    )
    openai_timeout_seconds: float = Field(
        default=45.0,
        alias="OPENAI_TIMEOUT_SECONDS",
    )
    bot_system_prompt: str = Field(
        default=DEFAULT_SYSTEM_PROMPT,
        alias="BOT_SYSTEM_PROMPT",
    )
    bot_history_max_turns: int = Field(default=20, alias="BOT_HISTORY_MAX_TURNS")
    bot_image_max_bytes: int = Field(
        default=10 * 1024 * 1024,
        alias="BOT_IMAGE_MAX_BYTES",
    )
    bot_enable_message_drafts: bool = Field(
        default=True,
        alias="BOT_ENABLE_MESSAGE_DRAFTS",
    )
    bot_draft_stream_on_images: bool = Field(
        default=False,
        alias="BOT_DRAFT_STREAM_ON_IMAGES",
    )
    bot_draft_start_delay_ms: int = Field(
        default=750,
        alias="BOT_DRAFT_START_DELAY_MS",
    )
    bot_draft_update_interval_ms: int = Field(
        default=350,
        alias="BOT_DRAFT_UPDATE_INTERVAL_MS",
    )
    bot_draft_min_chars_delta: int = Field(
        default=30,
        alias="BOT_DRAFT_MIN_CHARS_DELTA",
    )

    @field_validator("app_update_mode")
    @classmethod
    def validate_update_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"polling", "webhook"}:
            raise ValueError("APP_UPDATE_MODE must be 'polling' or 'webhook'")
        return normalized

    @field_validator("app_log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("telegram_allowed_user_ids")
    @classmethod
    def validate_allowed_user_ids(cls, value: str) -> str:
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if not parts:
            raise ValueError("TELEGRAM_ALLOWED_USER_IDS must not be empty")
        for part in parts:
            int(part)
        return ",".join(parts)

    @field_validator(
        "bot_draft_start_delay_ms",
        "bot_draft_update_interval_ms",
        "bot_draft_min_chars_delta",
    )
    @classmethod
    def validate_non_negative_ints(cls, value: int) -> int:
        if value < 0:
            raise ValueError("draft streaming settings must be zero or greater")
        return value

    @property
    def allowed_user_ids(self) -> set[int]:
        return {int(part) for part in self.telegram_allowed_user_ids.split(",") if part}
