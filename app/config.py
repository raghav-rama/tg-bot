from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.providers.vertex_image_models import requires_global_location

DEFAULT_SYSTEM_PROMPT = (
    "You are a concise assistant for a YouTube channel workflow. "
    "Help brainstorm content ideas, titles, hooks, and clear answers. "
    "Keep responses practical and safe. "
    "If the request is underspecified, ask one brief follow-up question."
)
WEBHOOK_SECRET_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


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
    app_log_format: str = Field(default="text", alias="APP_LOG_FORMAT")
    app_update_mode: str = Field(default="polling", alias="APP_UPDATE_MODE")
    telegram_webhook_url: str | None = Field(
        default=None,
        alias="TELEGRAM_WEBHOOK_URL",
    )
    telegram_webhook_secret_token: SecretStr | None = Field(
        default=None,
        alias="TELEGRAM_WEBHOOK_SECRET_TOKEN",
    )
    telegram_webhook_drop_pending_updates: bool = Field(
        default=False,
        alias="TELEGRAM_WEBHOOK_DROP_PENDING_UPDATES",
    )
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
    openai_input_cost_per_1m_tokens_usd: float = Field(
        default=0.0,
        alias="OPENAI_INPUT_COST_PER_1M_TOKENS_USD",
    )
    openai_output_cost_per_1m_tokens_usd: float = Field(
        default=0.0,
        alias="OPENAI_OUTPUT_COST_PER_1M_TOKENS_USD",
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
        default=1200,
        alias="BOT_DRAFT_UPDATE_INTERVAL_MS",
    )
    bot_draft_min_chars_delta: int = Field(
        default=80,
        alias="BOT_DRAFT_MIN_CHARS_DELTA",
    )
    vertex_api_key: SecretStr | None = Field(default=None, alias="VERTEX_API_KEY")
    vertex_project_id: str | None = Field(default=None, alias="VERTEX_PROJECT_ID")
    vertex_location: str = Field(default="us-central1", alias="VERTEX_LOCATION")
    vertex_image_model: str = Field(
        default="imagen-4.0-fast-generate-001",
        alias="VERTEX_IMAGE_MODEL",
    )
    vertex_image_aspect_ratio: str = Field(
        default="1:1",
        alias="VERTEX_IMAGE_ASPECT_RATIO",
    )
    vertex_image_output_mime_type: str = Field(
        default="image/jpeg",
        alias="VERTEX_IMAGE_OUTPUT_MIME_TYPE",
    )
    vertex_image_cost_per_image_usd: float = Field(
        default=0.0,
        alias="VERTEX_IMAGE_COST_PER_IMAGE_USD",
    )
    vertex_video_model: str = Field(
        default="veo-3.0-fast-generate-001",
        alias="VERTEX_VIDEO_MODEL",
    )
    vertex_video_aspect_ratio: str = Field(
        default="16:9",
        alias="VERTEX_VIDEO_ASPECT_RATIO",
    )
    vertex_video_duration_seconds: int | None = Field(
        default=4,
        alias="VERTEX_VIDEO_DURATION_SECONDS",
    )
    vertex_video_output_gcs_uri: str | None = Field(
        default=None,
        alias="VERTEX_VIDEO_OUTPUT_GCS_URI",
    )
    vertex_video_cost_per_second_usd: float = Field(
        default=0.0,
        alias="VERTEX_VIDEO_COST_PER_SECOND_USD",
    )
    video_provider_order: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("vertex", "runpod"),
        alias="VIDEO_PROVIDER_ORDER",
    )
    runpod_api_key: SecretStr | None = Field(default=None, alias="RUNPOD_API_KEY")
    runpod_video_endpoint_id: str | None = Field(
        default=None,
        alias="RUNPOD_VIDEO_ENDPOINT_ID",
    )
    runpod_video_base_url: str = Field(
        default="https://api.runpod.ai/v2",
        alias="RUNPOD_VIDEO_BASE_URL",
    )
    runpod_video_model: str = Field(
        default="ltx-2.3-22b-distilled-1.1",
        alias="RUNPOD_VIDEO_MODEL",
    )
    runpod_video_width: int = Field(default=576, alias="RUNPOD_VIDEO_WIDTH")
    runpod_video_height: int = Field(default=1024, alias="RUNPOD_VIDEO_HEIGHT")
    runpod_video_duration_seconds: int | None = Field(
        default=None,
        alias="RUNPOD_VIDEO_DURATION_SECONDS",
    )
    runpod_video_frame_rate: float = Field(
        default=24.0,
        alias="RUNPOD_VIDEO_FRAME_RATE",
    )
    runpod_video_execution_timeout_ms: int = Field(
        default=1_800_000,
        alias="RUNPOD_VIDEO_EXECUTION_TIMEOUT_MS",
    )
    runpod_video_ttl_ms: int = Field(
        default=7_200_000,
        alias="RUNPOD_VIDEO_TTL_MS",
    )
    runpod_video_reference_image_max_bytes: int = Field(
        default=6_000_000,
        alias="RUNPOD_VIDEO_REFERENCE_IMAGE_MAX_BYTES",
    )
    runpod_video_signed_url_ttl_seconds: int = Field(
        default=3600,
        alias="RUNPOD_VIDEO_SIGNED_URL_TTL_SECONDS",
    )
    runpod_video_cost_per_second_usd: float = Field(
        default=0.0,
        alias="RUNPOD_VIDEO_COST_PER_SECOND_USD",
    )
    bot_video_max_bytes: int = Field(
        default=50 * 1024 * 1024,
        alias="BOT_VIDEO_MAX_BYTES",
    )
    telegram_video_request_timeout_seconds: int = Field(
        default=180,
        alias="TELEGRAM_VIDEO_REQUEST_TIMEOUT_SECONDS",
    )
    video_job_poll_interval_seconds: int = Field(
        default=15,
        alias="VIDEO_JOB_POLL_INTERVAL_SECONDS",
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

    @field_validator("app_log_format")
    @classmethod
    def validate_log_format(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"text", "json"}:
            raise ValueError("APP_LOG_FORMAT must be 'text' or 'json'")
        return normalized

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

    @field_validator(
        "vertex_project_id",
        "vertex_location",
        "vertex_image_model",
        "vertex_image_aspect_ratio",
        "vertex_image_output_mime_type",
        "telegram_webhook_url",
        "vertex_video_model",
        "vertex_video_aspect_ratio",
        "vertex_video_output_gcs_uri",
        "runpod_video_endpoint_id",
        "runpod_video_base_url",
        "runpod_video_model",
        mode="before",
    )
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("telegram_webhook_secret_token", "runpod_api_key", mode="before")
    @classmethod
    def normalize_optional_secret(
        cls,
        value: SecretStr | str | None,
    ) -> str | None:
        if value is None:
            return None
        secret = (
            value.get_secret_value()
            if isinstance(value, SecretStr)
            else str(value)
        ).strip()
        return secret or None

    @field_validator("telegram_webhook_url")
    @classmethod
    def validate_webhook_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("TELEGRAM_WEBHOOK_URL must be a valid HTTPS URL")
        return value

    @field_validator("telegram_webhook_secret_token")
    @classmethod
    def validate_webhook_secret_token(
        cls,
        value: SecretStr | None,
    ) -> SecretStr | None:
        if value is None:
            return None
        secret = value.get_secret_value()
        if not WEBHOOK_SECRET_TOKEN_PATTERN.fullmatch(secret):
            raise ValueError(
                "TELEGRAM_WEBHOOK_SECRET_TOKEN must be 1-256 characters of "
                "A-Z, a-z, 0-9, '_' or '-'"
            )
        return value

    @field_validator("video_provider_order", mode="before")
    @classmethod
    def normalize_video_provider_order(
        cls,
        value: str | tuple[str, ...],
    ) -> tuple[str, ...]:
        if isinstance(value, str):
            providers = tuple(
                part.strip().lower() for part in value.split(",") if part.strip()
            )
        else:
            providers = tuple(
                str(part).strip().lower() for part in value if str(part).strip()
            )
        allowed = {"vertex", "runpod"}
        if not providers:
            raise ValueError("VIDEO_PROVIDER_ORDER must include at least one provider")
        unknown = sorted(set(providers) - allowed)
        if unknown:
            raise ValueError(
                "VIDEO_PROVIDER_ORDER contains unsupported providers: "
                + ", ".join(unknown)
            )
        if len(set(providers)) != len(providers):
            raise ValueError("VIDEO_PROVIDER_ORDER must not contain duplicate providers")
        return providers

    @field_validator(
        "vertex_video_duration_seconds",
        "bot_video_max_bytes",
        "telegram_video_request_timeout_seconds",
        "video_job_poll_interval_seconds",
        "runpod_video_width",
        "runpod_video_height",
        "runpod_video_duration_seconds",
        "runpod_video_execution_timeout_ms",
        "runpod_video_ttl_ms",
        "runpod_video_reference_image_max_bytes",
        "runpod_video_signed_url_ttl_seconds",
    )
    @classmethod
    def validate_positive_ints(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value <= 0:
            raise ValueError("video settings must be greater than zero")
        return value

    @field_validator("runpod_video_width")
    @classmethod
    def validate_runpod_video_width(cls, value: int) -> int:
        if value % 64 != 0:
            raise ValueError("RUNPOD_VIDEO_WIDTH must be divisible by 64")
        return value

    @field_validator("runpod_video_height")
    @classmethod
    def validate_runpod_video_height(cls, value: int) -> int:
        if value % 64 != 0:
            raise ValueError("RUNPOD_VIDEO_HEIGHT must be divisible by 64")
        return value

    @field_validator("runpod_video_frame_rate")
    @classmethod
    def validate_runpod_video_frame_rate(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("RUNPOD_VIDEO_FRAME_RATE must be greater than zero")
        return value

    @field_validator(
        "openai_input_cost_per_1m_tokens_usd",
        "openai_output_cost_per_1m_tokens_usd",
        "vertex_image_cost_per_image_usd",
        "vertex_video_cost_per_second_usd",
        "runpod_video_cost_per_second_usd",
    )
    @classmethod
    def validate_non_negative_floats(cls, value: float) -> float:
        if value < 0:
            raise ValueError("cost estimate rates must be zero or greater")
        return value

    @model_validator(mode="after")
    def validate_vertex_image_model_location(self) -> Settings:
        if (
            self.vertex_image_generation_enabled
            and requires_global_location(self.vertex_image_model)
            and self.vertex_location != "global"
        ):
            raise ValueError(
                "VERTEX_LOCATION must be 'global' when "
                "VERTEX_IMAGE_MODEL is 'gemini-3-pro-image-preview'"
            )
        return self

    @model_validator(mode="after")
    def validate_webhook_mode_settings(self) -> Settings:
        if self.app_update_mode != "webhook":
            return self
        if self.telegram_webhook_url is None:
            raise ValueError(
                "TELEGRAM_WEBHOOK_URL is required when APP_UPDATE_MODE is 'webhook'"
            )
        if self.telegram_webhook_secret_token is None:
            raise ValueError(
                "TELEGRAM_WEBHOOK_SECRET_TOKEN is required when APP_UPDATE_MODE "
                "is 'webhook'"
            )
        return self

    @model_validator(mode="after")
    def validate_runpod_video_settings(self) -> Settings:
        has_api_key = self.runpod_api_key is not None
        has_endpoint_id = self.runpod_video_endpoint_id is not None
        if has_api_key != has_endpoint_id:
            raise ValueError(
                "RUNPOD_API_KEY and RUNPOD_VIDEO_ENDPOINT_ID must be configured together"
            )
        if self.runpod_video_duration_seconds is None:
            self.runpod_video_duration_seconds = self.vertex_video_duration_seconds
        return self

    @property
    def allowed_user_ids(self) -> set[int]:
        return {int(part) for part in self.telegram_allowed_user_ids.split(",") if part}

    @property
    def vertex_image_generation_enabled(self) -> bool:
        return self.vertex_api_key is not None or self.vertex_project_id is not None

    @property
    def vertex_video_generation_enabled(self) -> bool:
        return self.vertex_api_key is not None or self.vertex_project_id is not None

    @property
    def runpod_video_generation_enabled(self) -> bool:
        return self.runpod_api_key is not None and self.runpod_video_endpoint_id is not None

    @property
    def video_generation_enabled(self) -> bool:
        enabled_by_provider = {
            "vertex": self.vertex_video_generation_enabled,
            "runpod": self.runpod_video_generation_enabled,
        }
        return any(enabled_by_provider[provider] for provider in self.video_provider_order)
