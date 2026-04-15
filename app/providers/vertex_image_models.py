from __future__ import annotations


_GLOBAL_ONLY_GEMINI_IMAGE_MODELS = frozenset(
    {
        "gemini-3-pro-image-preview",
    }
)


def normalize_vertex_image_model(model: str | None) -> str:
    if model is None:
        return ""
    return model.strip().lower()


def is_gemini_image_model(model: str | None) -> bool:
    normalized = normalize_vertex_image_model(model)
    return normalized.startswith("gemini-") and "image" in normalized


def image_generation_api_method(model: str | None) -> str:
    if is_gemini_image_model(model):
        return "generate_content"
    return "generate_images"


def requires_global_location(model: str | None) -> bool:
    return normalize_vertex_image_model(model) in _GLOBAL_ONLY_GEMINI_IMAGE_MODELS
