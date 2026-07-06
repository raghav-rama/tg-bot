from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, TypeVar

from app.config import Settings as _Settings
from app.domain.models import (
    FalVideoModelFamily,
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
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class VideoProviderPreset:
    id: str
    label: str
    provider_hint: VideoProviderHint


@dataclass(frozen=True, slots=True)
class VideoDurationPreset:
    id: str
    label: str
    duration_seconds: int


@dataclass(frozen=True, slots=True)
class VideoOrientationPreset:
    id: str
    label: str
    aspect_ratio: str
    runpod_width: int
    runpod_height: int


@dataclass(frozen=True, slots=True)
class RunpodPipelinePreset:
    id: str
    label: str
    pipeline: str
    model: str


@dataclass(frozen=True, slots=True)
class RunpodQualityPreset:
    id: str
    label: str
    num_inference_steps: int


@dataclass(frozen=True, slots=True)
class RunpodSeedPreset:
    id: str
    label: str
    seed: int | None = None
    randomize: bool = False


@dataclass(frozen=True, slots=True)
class RunpodReferenceStrengthPreset:
    id: str
    label: str
    image_strength: float


@dataclass(frozen=True, slots=True)
class FalVideoModelPreset:
    id: FalVideoModelFamily
    label: str
    family: FalVideoModelFamily


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


VIDEO_PROVIDER_PRESETS: dict[str, VideoProviderPreset] = {
    "auto": VideoProviderPreset(
        id="auto",
        label="🌐 Environment default",
        provider_hint="auto",
    ),
    "gemini": VideoProviderPreset(
        id="gemini",
        label="✨ Gemini",
        provider_hint="gemini",
    ),
    "runpod": VideoProviderPreset(
        id="runpod",
        label="🚀 Runpod LTX",
        provider_hint="runpod",
    ),
    "fal": VideoProviderPreset(
        id="fal",
        label="🌌 Fal",
        provider_hint="fal",
    ),
}

VIDEO_DURATION_PRESETS: dict[str, VideoDurationPreset] = {
    "duration_4s": VideoDurationPreset(
        id="duration_4s",
        label="⏱️ 4s",
        duration_seconds=4,
    ),
    "duration_5s": VideoDurationPreset(
        id="duration_5s",
        label="⏱️ 5s",
        duration_seconds=5,
    ),
    "duration_6s": VideoDurationPreset(
        id="duration_6s",
        label="⏱️ 6s",
        duration_seconds=6,
    ),
    "duration_8s": VideoDurationPreset(
        id="duration_8s",
        label="⏱️ 8s",
        duration_seconds=8,
    ),
}

VIDEO_ORIENTATION_PRESETS: dict[str, VideoOrientationPreset] = {
    "portrait_9_16": VideoOrientationPreset(
        id="portrait_9_16",
        label="📱 Portrait 9:16",
        aspect_ratio="9:16",
        runpod_width=576,
        runpod_height=1024,
    ),
    "landscape_16_9": VideoOrientationPreset(
        id="landscape_16_9",
        label="🌄 Landscape 16:9",
        aspect_ratio="16:9",
        runpod_width=1024,
        runpod_height=576,
    ),
    "square_1_1": VideoOrientationPreset(
        id="square_1_1",
        label="◼️ Square 1:1",
        aspect_ratio="1:1",
        runpod_width=768,
        runpod_height=768,
    ),
}

RUNPOD_PIPELINE_PRESETS: dict[str, RunpodPipelinePreset] = {
    "distilled": RunpodPipelinePreset(
        id="distilled",
        label="⚡ Distilled",
        pipeline="distilled",
        model="ltx-2.3-22b-distilled-1.1",
    ),
    "two_stage": RunpodPipelinePreset(
        id="two_stage",
        label="🎞️ Two-stage",
        pipeline="two_stage",
        model="ltx-2.3-22b",
    ),
}

RUNPOD_QUALITY_PRESETS: dict[str, RunpodQualityPreset] = {
    "fast": RunpodQualityPreset(
        id="fast",
        label="🏃 Fast quality",
        num_inference_steps=30,
    ),
    "default": RunpodQualityPreset(
        id="default",
        label="⚙️ Default quality",
        num_inference_steps=40,
    ),
    "high": RunpodQualityPreset(
        id="high",
        label="💎 High quality",
        num_inference_steps=50,
    ),
}

RUNPOD_SEED_PRESETS: dict[str, RunpodSeedPreset] = {
    "fixed": RunpodSeedPreset(
        id="fixed",
        label="📌 Fixed seed",
        seed=10,
    ),
    "random": RunpodSeedPreset(
        id="random",
        label="🎲 Random seed",
        randomize=True,
    ),
}

RUNPOD_REFERENCE_STRENGTH_PRESETS: dict[str, RunpodReferenceStrengthPreset] = {
    "low": RunpodReferenceStrengthPreset(
        id="low",
        label="🌗 Low reference strength",
        image_strength=0.6,
    ),
    "medium": RunpodReferenceStrengthPreset(
        id="medium",
        label="🌓 Medium reference strength",
        image_strength=0.8,
    ),
    "high": RunpodReferenceStrengthPreset(
        id="high",
        label="🌕 High reference strength",
        image_strength=0.9,
    ),
}

IMAGE_PRESETS: dict[str, ImagePreset] = {
    "gemini_square_jpeg": ImagePreset(
        id="gemini_square_jpeg",
        label="✨ Gemini square JPEG",
        model="gemini-3.1-flash-image",
        aspect_ratio="1:1",
        output_mime_type="image/jpeg",
    ),
    "gemini_landscape_jpeg": ImagePreset(
        id="gemini_landscape_jpeg",
        label="🌄 Gemini landscape JPEG",
        model="gemini-3.1-flash-image",
        aspect_ratio="16:9",
        output_mime_type="image/jpeg",
    ),
    "gemini_portrait_jpeg": ImagePreset(
        id="gemini_portrait_jpeg",
        label="📱 Gemini portrait JPEG",
        model="gemini-3.1-flash-image",
        aspect_ratio="9:16",
        output_mime_type="image/jpeg",
    ),
}

CHAT_PRESETS: dict[str, ChatPreset] = {
    "precise_short": ChatPreset(
        id="precise_short",
        label="🎯 Precise short",
        temperature=0.1,
        max_output_tokens=350,
        history_max_turns=10,
    ),
    "balanced_medium": ChatPreset(
        id="balanced_medium",
        label="⚖️ Balanced medium",
        temperature=0.3,
        max_output_tokens=700,
        history_max_turns=20,
    ),
    "creative_long": ChatPreset(
        id="creative_long",
        label="🎨 Creative long",
        temperature=0.8,
        max_output_tokens=1200,
        history_max_turns=30,
    ),
    "no_memory": ChatPreset(
        id="no_memory",
        label="🧹 No memory",
        temperature=0.2,
        max_output_tokens=500,
        history_max_turns=0,
    ),
}

_FAL_FAMILY_LABELS: dict[FalVideoModelFamily, str] = {
    "kling": "🎬 Kling",
    "seedance": "🌌 Seedance",
    "gemini": "✨ Gemini",
}

SETTABLE_PREFERENCE_TYPES: tuple[PreferenceType, ...] = (
    "video_provider",
    "video_duration",
    "video_orientation",
    "fal_video_model",
    "runpod_pipeline",
    "runpod_quality",
    "runpod_seed",
    "runpod_reference_strength",
    "image",
    "chat",
)
MENU_TYPES = {"main", "video", *SETTABLE_PREFERENCE_TYPES}


def video_provider_preset_for(preset_id: str | None) -> VideoProviderPreset | None:
    if preset_id == "vertex":
        preset_id = "gemini"
    return _preset_or_none(VIDEO_PROVIDER_PRESETS, preset_id)


def video_duration_preset_for(preset_id: str | None) -> VideoDurationPreset | None:
    return _preset_or_none(VIDEO_DURATION_PRESETS, preset_id)


def video_orientation_preset_for(preset_id: str | None) -> VideoOrientationPreset | None:
    return _preset_or_none(VIDEO_ORIENTATION_PRESETS, preset_id)


def runpod_pipeline_preset_for(preset_id: str | None) -> RunpodPipelinePreset | None:
    return _preset_or_none(RUNPOD_PIPELINE_PRESETS, preset_id)


def runpod_quality_preset_for(preset_id: str | None) -> RunpodQualityPreset | None:
    return _preset_or_none(RUNPOD_QUALITY_PRESETS, preset_id)


def runpod_seed_preset_for(preset_id: str | None) -> RunpodSeedPreset | None:
    return _preset_or_none(RUNPOD_SEED_PRESETS, preset_id)


def runpod_reference_strength_preset_for(
    preset_id: str | None,
) -> RunpodReferenceStrengthPreset | None:
    return _preset_or_none(RUNPOD_REFERENCE_STRENGTH_PRESETS, preset_id)


def fal_video_model_preset_for(
    preset_id: str | None,
    *,
    settings: _Settings | None = None,
) -> FalVideoModelPreset | None:
    return _preset_or_none(fal_video_model_presets_for(settings or _Settings()), preset_id)


def fal_video_model_presets_for(settings: _Settings) -> dict[str, FalVideoModelPreset]:
    families = sorted(settings.fal_video_available_families)
    return {
        family: FalVideoModelPreset(
            id=family,
            label=_FAL_FAMILY_LABELS[family],
            family=family,
        )
        for family in families
    }


def image_preset_for(preset_id: str | None) -> ImagePreset | None:
    legacy_map = {
        "imagen_square_jpeg": "gemini_square_jpeg",
        "imagen_landscape_jpeg": "gemini_landscape_jpeg",
        "gemini_reference_square_jpeg": "gemini_square_jpeg",
    }
    if preset_id in legacy_map:
        preset_id = legacy_map[preset_id]
    return _preset_or_none(IMAGE_PRESETS, preset_id)


def chat_preset_for(preset_id: str | None) -> ChatPreset | None:
    return _preset_or_none(CHAT_PRESETS, preset_id)


def preset_for_preference(
    preference_type: PreferenceType,
    preset_id: str | None,
    *,
    settings: _Settings | None = None,
) -> object | None:
    if preference_type not in SETTABLE_PREFERENCE_TYPES:
        return None
    return _preset_or_none(_preset_map_for(preference_type, settings=settings), preset_id)


def settings_menu_for(
    preference_type: PreferenceType | None = None,
    active_preset_id: str | None = None,
    *,
    settings: _Settings | None = None,
) -> SettingsMenu:
    resolved_settings = settings or _Settings()
    if preference_type is None:
        return SettingsMenu(
            rows=(
                (
                    SettingsButton("🎬 Video", "prefs:menu:video"),
                    SettingsButton("🖼️ Image", "prefs:menu:image"),
                    SettingsButton("💬 Chat", "prefs:menu:chat"),
                ),
            )
        )

    if preference_type == "video":
        rows = [
            (SettingsButton("🧭 Provider", "prefs:menu:video_provider"),),
            (SettingsButton("⏱️ Duration", "prefs:menu:video_duration"),),
            (SettingsButton("📐 Aspect ratio", "prefs:menu:video_orientation"),),
        ]
        if resolved_settings.fal_video_generation_enabled:
            fal_families = resolved_settings.fal_video_available_families
            if len(fal_families) > 1:
                rows.append(
                    (SettingsButton("🤖 Fal model", "prefs:menu:fal_video_model"),)
                )
        rows.extend(
            [
                (SettingsButton("🧬 Runpod pipeline", "prefs:menu:runpod_pipeline"),),
                (SettingsButton("🎚️ Runpod quality", "prefs:menu:runpod_quality"),),
                (SettingsButton("🎲 Runpod seed", "prefs:menu:runpod_seed"),),
                (
                    SettingsButton(
                        "🖼️ Reference strength",
                        "prefs:menu:runpod_reference_strength",
                    ),
                ),
                (SettingsButton("↩️ Back", "prefs:menu:main"),),
            ]
        )
        return SettingsMenu(rows=tuple(rows))

    preset_map = _preset_map_for(preference_type, settings=resolved_settings)
    rows: list[tuple[SettingsButton, ...]] = []
    for preset_id, preset in preset_map.items():
        marker = "✅ " if preset_id == active_preset_id else ""
        rows.append(
            (
                SettingsButton(
                    text=f"{marker}{preset.label}",
                    callback_data=f"prefs:{preference_type}:{preset_id}",
                ),
            )
        )
    back_callback_data = (
        "prefs:menu:video"
        if preference_type.startswith(("video_", "runpod_", "fal_video_"))
        else "prefs:menu:main"
    )
    rows.append((SettingsButton("↩️ Back", back_callback_data),))
    return SettingsMenu(rows=tuple(rows))


def parse_settings_callback(
    callback_data: str | None,
    *,
    settings: _Settings | None = None,
) -> tuple[str, PreferenceType | None, str | None] | None:
    if callback_data is None:
        return None
    parts = callback_data.split(":")
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
        return None
    action = parts[1]
    value = parts[2]
    if action == "menu":
        if value not in MENU_TYPES:
            return None
        return ("menu", None if value == "main" else value, None)
    if action in SETTABLE_PREFERENCE_TYPES:
        if value in _preset_map_for(action, settings=settings or _Settings()):
            return ("set", action, value)
    return None


def active_settings_summary(
    *,
    preferences: Mapping[str, UserPreference | None],
    settings: _Settings | None = None,
) -> str:
    resolved_settings = settings or _Settings()
    return (
        "Settings\n"
        f"- Video provider: {_label_for_preference('video_provider', preferences.get('video_provider'), settings=resolved_settings)}\n"
        f"- Video duration: {_label_for_preference('video_duration', preferences.get('video_duration'), settings=resolved_settings)}\n"
        f"- Video aspect ratio: {_label_for_preference('video_orientation', preferences.get('video_orientation'), settings=resolved_settings)}\n"
        f"- Fal model: {_label_for_preference('fal_video_model', preferences.get('fal_video_model'), settings=resolved_settings)}\n"
        f"- Runpod pipeline: {_label_for_preference('runpod_pipeline', preferences.get('runpod_pipeline'), settings=resolved_settings)}\n"
        f"- Runpod quality: {_label_for_preference('runpod_quality', preferences.get('runpod_quality'), settings=resolved_settings)}\n"
        f"- Runpod seed: {_label_for_preference('runpod_seed', preferences.get('runpod_seed'), settings=resolved_settings)}\n"
        f"- Reference strength: {_label_for_preference('runpod_reference_strength', preferences.get('runpod_reference_strength'), settings=resolved_settings)}\n"
        f"- Image: {_label_for_preference('image', preferences.get('image'), settings=resolved_settings)}\n"
        f"- Chat: {_label_for_preference('chat', preferences.get('chat'), settings=resolved_settings)}"
    )


def _label_for_preference(
    preference_type: PreferenceType,
    preference: UserPreference | None,
    *,
    settings: _Settings | None = None,
) -> str:
    if preference is None:
        return "Environment default"
    preset = preset_for_preference(
        preference_type,
        preference.preset_id,
        settings=settings or _Settings(),
    )
    if preset is None:
        return "Environment default"
    return preset.label


def _preset_map_for(
    preference_type: PreferenceType,
    *,
    settings: _Settings | None = None,
) -> Mapping[str, object]:
    if preference_type == "video_provider":
        return VIDEO_PROVIDER_PRESETS
    if preference_type == "video_duration":
        return VIDEO_DURATION_PRESETS
    if preference_type == "video_orientation":
        return VIDEO_ORIENTATION_PRESETS
    if preference_type == "fal_video_model":
        return fal_video_model_presets_for(settings or _Settings())
    if preference_type == "runpod_pipeline":
        return RUNPOD_PIPELINE_PRESETS
    if preference_type == "runpod_quality":
        return RUNPOD_QUALITY_PRESETS
    if preference_type == "runpod_seed":
        return RUNPOD_SEED_PRESETS
    if preference_type == "runpod_reference_strength":
        return RUNPOD_REFERENCE_STRENGTH_PRESETS
    if preference_type == "image":
        return IMAGE_PRESETS
    if preference_type == "chat":
        return CHAT_PRESETS
    return {}


def _preset_or_none(
    presets: Mapping[str, T],
    preset_id: str | None,
) -> T | None:
    if preset_id is None:
        return None
    return presets.get(preset_id)
