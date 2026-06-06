from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.models import UserPreference
from app.domain.preferences import (
    active_settings_summary,
    image_preset_for,
    runpod_pipeline_preset_for,
    runpod_quality_preset_for,
    settings_menu_for,
    video_duration_preset_for,
    video_orientation_preset_for,
    video_provider_preset_for,
)
from app.storage.preferences import PreferenceRepository


def _utcnow() -> datetime:
    return datetime(2026, 6, 6, 10, 0, 0, tzinfo=timezone.utc)


async def test_preference_repository_upserts_per_chat_user(service_bundle) -> None:
    repository = PreferenceRepository(service_bundle["database"])

    await repository.set_preference(
        chat_id=100,
        user_id=42,
        preference_type="video_duration",
        preset_id="duration_4s",
        updated_at=_utcnow(),
    )
    await repository.set_preference(
        chat_id=100,
        user_id=42,
        preference_type="video_duration",
        preset_id="duration_8s",
        updated_at=_utcnow(),
    )

    preference = await repository.get_preference(
        chat_id=100,
        user_id=42,
        preference_type="video_duration",
    )

    assert preference == UserPreference(
        chat_id=100,
        user_id=42,
        preference_type="video_duration",
        preset_id="duration_8s",
        updated_at=_utcnow(),
    )
    assert await repository.get_preference(
        chat_id=101,
        user_id=42,
        preference_type="video_duration",
    ) is None


def test_settings_menu_uses_compact_callback_data() -> None:
    main_menu = settings_menu_for()
    menu = settings_menu_for(preference_type="video")
    duration_menu = settings_menu_for(
        preference_type="video_duration",
        active_preset_id="duration_6s",
    )

    video_menu_callback_data = [
        button.callback_data
        for row in menu.rows
        for button in row
    ]
    duration_callback_data = [
        button.callback_data
        for row in duration_menu.rows
        for button in row
        if button.callback_data.startswith("prefs:video_duration:")
    ]

    assert "prefs:menu:video_duration" in video_menu_callback_data
    assert "prefs:menu:runpod_reference_strength" in video_menu_callback_data
    assert "prefs:video_duration:duration_6s" in duration_callback_data
    assert [button.text for button in main_menu.rows[0]] == [
        "🎬 Video",
        "🖼️ Image",
        "💬 Chat",
    ]
    assert [row[0].text for row in menu.rows] == [
        "🧭 Provider",
        "⏱️ Duration",
        "📐 Aspect ratio",
        "🧬 Runpod pipeline",
        "🎚️ Runpod quality",
        "🎲 Runpod seed",
        "🖼️ Reference strength",
        "↩️ Back",
    ]
    assert any(
        button.text.startswith("✅ ⏱️ 6s")
        for row in duration_menu.rows
        for button in row
    )
    assert all("[x]" not in button.text for row in duration_menu.rows for button in row)
    assert all(
        len(value.encode("utf-8")) <= 64
        for value in video_menu_callback_data + duration_callback_data
    )


def test_presets_map_to_request_overrides() -> None:
    provider_preset = video_provider_preset_for("runpod")
    duration_preset = video_duration_preset_for("duration_8s")
    orientation_preset = video_orientation_preset_for("portrait_9_16")
    pipeline_preset = runpod_pipeline_preset_for("two_stage")
    quality_preset = runpod_quality_preset_for("high")
    image_preset = image_preset_for("imagen_landscape_jpeg")

    assert provider_preset.provider_hint == "runpod"
    assert duration_preset.duration_seconds == 8
    assert orientation_preset.vertex_aspect_ratio == "9:16"
    assert orientation_preset.runpod_width == 576
    assert orientation_preset.runpod_height == 1024
    assert pipeline_preset.pipeline == "two_stage"
    assert pipeline_preset.model == "ltx-2.3-22b"
    assert quality_preset.num_inference_steps == 50
    assert image_preset.model == "imagen-4.0-fast-generate-001"
    assert image_preset.aspect_ratio == "16:9"
    assert image_preset.output_mime_type == "image/jpeg"


def test_image_settings_menu_has_clear_gemini_portrait_option() -> None:
    menu = settings_menu_for(preference_type="image")
    labels = [button.text for row in menu.rows for button in row]
    gemini_portrait = image_preset_for("gemini_portrait_jpeg")

    assert "✨ Gemini square JPEG" in labels
    assert "📱 Gemini portrait JPEG" in labels
    assert all("reference" not in label.lower() for label in labels)
    assert gemini_portrait is not None
    assert gemini_portrait.model == "gemini-3-pro-image-preview"
    assert gemini_portrait.aspect_ratio == "9:16"
    assert gemini_portrait.output_mime_type == "image/jpeg"


def test_settings_presets_use_emoji_labels() -> None:
    menu_types = (
        "video_provider",
        "video_duration",
        "video_orientation",
        "runpod_pipeline",
        "runpod_quality",
        "runpod_seed",
        "runpod_reference_strength",
        "image",
        "chat",
    )

    for menu_type in menu_types:
        labels = [button.text for row in settings_menu_for(preference_type=menu_type).rows for button in row]
        assert labels[-1] == "↩️ Back"
        assert all(ord(label[0]) > 127 for label in labels)


def test_active_settings_summary_names_defaults_and_saved_presets() -> None:
    summary = active_settings_summary(
        preferences={
            "video": UserPreference(
                chat_id=100,
                user_id=42,
                preference_type="video",
                preset_id="runpod_ltx_distilled_portrait_4s",
                updated_at=_utcnow(),
            ),
            "video_provider": UserPreference(
                chat_id=100,
                user_id=42,
                preference_type="video_provider",
                preset_id="runpod",
                updated_at=_utcnow(),
            ),
            "video_duration": UserPreference(
                chat_id=100,
                user_id=42,
                preference_type="video_duration",
                preset_id="duration_8s",
                updated_at=_utcnow(),
            ),
            "runpod_pipeline": UserPreference(
                chat_id=100,
                user_id=42,
                preference_type="runpod_pipeline",
                preset_id="two_stage",
                updated_at=_utcnow(),
            )
        }
    )

    assert "Video provider: 🚀 Runpod LTX" in summary
    assert "Video duration: ⏱️ 8s" in summary
    assert "Runpod pipeline: 🎞️ Two-stage" in summary
    assert "Image: Environment default" in summary
    assert "Chat: Environment default" in summary
