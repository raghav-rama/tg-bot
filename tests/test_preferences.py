from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.models import UserPreference
from app.domain.preferences import (
    active_settings_summary,
    image_preset_for,
    settings_menu_for,
    video_preset_for,
)
from app.storage.preferences import PreferenceRepository


def _utcnow() -> datetime:
    return datetime(2026, 6, 6, 10, 0, 0, tzinfo=timezone.utc)


async def test_preference_repository_upserts_per_chat_user(service_bundle) -> None:
    repository = PreferenceRepository(service_bundle["database"])

    await repository.set_preference(
        chat_id=100,
        user_id=42,
        preference_type="video",
        preset_id="runpod_ltx_distilled_portrait_4s",
        updated_at=_utcnow(),
    )
    await repository.set_preference(
        chat_id=100,
        user_id=42,
        preference_type="video",
        preset_id="vertex_landscape_4s",
        updated_at=_utcnow(),
    )

    preference = await repository.get_preference(
        chat_id=100,
        user_id=42,
        preference_type="video",
    )

    assert preference == UserPreference(
        chat_id=100,
        user_id=42,
        preference_type="video",
        preset_id="vertex_landscape_4s",
        updated_at=_utcnow(),
    )
    assert await repository.get_preference(
        chat_id=101,
        user_id=42,
        preference_type="video",
    ) is None


def test_settings_menu_uses_compact_callback_data() -> None:
    menu = settings_menu_for(
        preference_type="video",
        active_preset_id="runpod_ltx_distilled_portrait_4s",
    )

    callback_data = [
        button.callback_data
        for row in menu.rows
        for button in row
        if button.callback_data.startswith("prefs:video:")
    ]

    assert "prefs:video:runpod_ltx_distilled_portrait_4s" in callback_data
    assert all(len(value.encode("utf-8")) <= 64 for value in callback_data)


def test_presets_map_to_request_overrides() -> None:
    video_preset = video_preset_for("runpod_ltx_distilled_portrait_4s")
    image_preset = image_preset_for("imagen_landscape_jpeg")

    assert video_preset.provider_hint == "runpod"
    assert video_preset.model == "ltx-2.3-22b-distilled-1.1"
    assert video_preset.width == 576
    assert video_preset.height == 1024
    assert video_preset.duration_seconds == 4
    assert video_preset.frame_rate == 24.0
    assert image_preset.model == "imagen-4.0-fast-generate-001"
    assert image_preset.aspect_ratio == "16:9"
    assert image_preset.output_mime_type == "image/jpeg"


def test_active_settings_summary_names_defaults_and_saved_presets() -> None:
    summary = active_settings_summary(
        preferences={
            "video": UserPreference(
                chat_id=100,
                user_id=42,
                preference_type="video",
                preset_id="runpod_ltx_distilled_portrait_4s",
                updated_at=_utcnow(),
            )
        }
    )

    assert "Video: Runpod LTX distilled portrait 4s" in summary
    assert "Image: Environment default" in summary
    assert "Chat: Environment default" in summary
