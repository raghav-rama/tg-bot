from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.domain.models import (
    PreferenceType,
    SettingsButton,
    SettingsMenu,
    UserPreference,
    VideoProviderHint,
)

CALLBACK_PREFIX = "prefs"
SETTINGS_UPDATED_TEXT = "Settings updated."
UNKNOWN_SETTINGS_TEXT = "Unknown settings option."
SETTINGS_TEXT = "Settings\n\nChoose what you want to tune."


@dataclass(frozen=True, slots=True)
class VideoPreset:
    id: str
    label: str
    provider_hint: VideoProviderHint
    model: str | None = None
    aspect_ratio: str | None = None
    duration_seconds: int | None = None
    width: int | None = None
    height: int | None = None
    frame_rate: float | None = None


@dataclass(frozen=True, slots=True)
class ImagePreset:
    id: str
    label: str
    model: str
    aspect_ratio: str
    output_mime_type: str


@dataclass(frozen=True, slots=True)
class ChatPreset:
    id: str
    label: str
    temperature: float | None = None
    max_output_tokens: int | None = None
    history_max_turns: int | None = None


VIDEO_PRESETS: dict[str, VideoPreset] = {
    "auto_default": VideoPreset(
        id="auto_default",
        label="Environment default",
        provider_hint="auto",
    ),
    "vertex_landscape_4s": VideoPreset(
        id="vertex_landscape_4s",
        label="Vertex landscape 4s",
        provider_hint="vertex",
        model="veo-3.0-fast-generate-001",
        aspect_ratio="16:9",
        duration_seconds=4,
    ),
    "runpod_ltx_distilled_portrait_4s": VideoPreset(
        id="runpod_ltx_distilled_portrait_4s",
        label="Runpod LTX distilled portrait 4s",
        provider_hint="runpod",
        model="ltx-2.3-22b-distilled-1.1",
        duration_seconds=4,
        width=576,
        height=1024,
        frame_rate=24.0,
    ),
    "runpod_ltx_distilled_landscape_4s": VideoPreset(
        id="runpod_ltx_distilled_landscape_4s",
        label="Runpod LTX distilled landscape 4s",
        provider_hint="runpod",
        model="ltx-2.3-22b-distilled-1.1",
        duration_seconds=4,
        width=1024,
        height=576,
        frame_rate=24.0,
    ),
    "runpod_ltx_two_stage_portrait_4s": VideoPreset(
        id="runpod_ltx_two_stage_portrait_4s",
        label="Runpod LTX two-stage portrait 4s",
        provider_hint="runpod",
        model="ltx-2.3-22b",
        duration_seconds=4,
        width=576,
        height=1024,
        frame_rate=24.0,
    ),
}

IMAGE_PRESETS: dict[str, ImagePreset] = {
    "imagen_square_jpeg": ImagePreset(
        id="imagen_square_jpeg",
        label="Imagen square JPEG",
        model="imagen-4.0-fast-generate-001",
        aspect_ratio="1:1",
        output_mime_type="image/jpeg",
    ),
    "imagen_landscape_jpeg": ImagePreset(
        id="imagen_landscape_jpeg",
        label="Imagen landscape JPEG",
        model="imagen-4.0-fast-generate-001",
        aspect_ratio="16:9",
        output_mime_type="image/jpeg",
    ),
    "gemini_reference_square_jpeg": ImagePreset(
        id="gemini_reference_square_jpeg",
        label="Gemini reference square JPEG",
        model="gemini-3-pro-image-preview",
        aspect_ratio="1:1",
        output_mime_type="image/jpeg",
    ),
}

CHAT_PRESETS: dict[str, ChatPreset] = {
    "precise_short": ChatPreset(
        id="precise_short",
        label="Precise short",
        temperature=0.1,
        max_output_tokens=350,
        history_max_turns=10,
    ),
    "balanced_medium": ChatPreset(
        id="balanced_medium",
        label="Balanced medium",
        temperature=0.3,
        max_output_tokens=700,
        history_max_turns=20,
    ),
    "creative_long": ChatPreset(
        id="creative_long",
        label="Creative long",
        temperature=0.8,
        max_output_tokens=1200,
        history_max_turns=30,
    ),
    "no_memory": ChatPreset(
        id="no_memory",
        label="No memory",
        temperature=0.2,
        max_output_tokens=500,
        history_max_turns=0,
    ),
}


def video_preset_for(preset_id: str | None) -> VideoPreset | None:
    if preset_id is None:
        return None
    return VIDEO_PRESETS.get(preset_id)


def image_preset_for(preset_id: str | None) -> ImagePreset | None:
    if preset_id is None:
        return None
    return IMAGE_PRESETS.get(preset_id)


def chat_preset_for(preset_id: str | None) -> ChatPreset | None:
    if preset_id is None:
        return None
    return CHAT_PRESETS.get(preset_id)


def settings_menu_for(
    preference_type: PreferenceType | None = None,
    active_preset_id: str | None = None,
) -> SettingsMenu:
    if preference_type is None:
        return SettingsMenu(
            rows=(
                (
                    SettingsButton("Video", "prefs:menu:video"),
                    SettingsButton("Image", "prefs:menu:image"),
                    SettingsButton("Chat", "prefs:menu:chat"),
                ),
            )
        )

    preset_map = _preset_map_for(preference_type)
    rows: list[tuple[SettingsButton, ...]] = []
    for preset_id, preset in preset_map.items():
        marker = "[x] " if preset_id == active_preset_id else ""
        rows.append(
            (
                SettingsButton(
                    text=f"{marker}{preset.label}",
                    callback_data=f"prefs:{preference_type}:{preset_id}",
                ),
            )
        )
    rows.append((SettingsButton("Back", "prefs:menu:main"),))
    return SettingsMenu(rows=tuple(rows))


def parse_settings_callback(
    callback_data: str | None,
) -> tuple[str, PreferenceType | None, str | None] | None:
    if callback_data is None:
        return None
    parts = callback_data.split(":")
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
        return None
    action = parts[1]
    value = parts[2]
    if action == "menu":
        if value == "main":
            return ("menu", None, None)
        if value in {"video", "image", "chat"}:
            return ("menu", value, None)
        return None
    if action in {"video", "image", "chat"}:
        if value in _preset_map_for(action):
            return ("set", action, value)
    return None


def active_settings_summary(
    *,
    preferences: Mapping[str, UserPreference | None],
) -> str:
    return (
        "Settings\n"
        f"- Video: {_label_for_preference('video', preferences.get('video'))}\n"
        f"- Image: {_label_for_preference('image', preferences.get('image'))}\n"
        f"- Chat: {_label_for_preference('chat', preferences.get('chat'))}"
    )


def _label_for_preference(
    preference_type: PreferenceType,
    preference: UserPreference | None,
) -> str:
    if preference is None:
        return "Environment default"
    preset = _preset_map_for(preference_type).get(preference.preset_id)
    if preset is None:
        return "Environment default"
    return preset.label


def _preset_map_for(preference_type: PreferenceType) -> Mapping[str, object]:
    if preference_type == "video":
        return VIDEO_PRESETS
    if preference_type == "image":
        return IMAGE_PRESETS
    return CHAT_PRESETS
