from __future__ import annotations

import json
from dataclasses import asdict

from app.domain.models import ImageGenerationRequest, ImageInput, VideoGenerationRequest


def serialize_image_generation_request(request: ImageGenerationRequest) -> str:
    return json.dumps(asdict(request), separators=(",", ":"), sort_keys=True)


def deserialize_image_generation_request(payload: str) -> ImageGenerationRequest:
    data = json.loads(payload)
    return ImageGenerationRequest(
        chat_id=data["chat_id"],
        user_id=data["user_id"],
        prompt=data["prompt"],
        model=data["model"],
        aspect_ratio=data["aspect_ratio"],
        output_mime_type=data["output_mime_type"],
        reference_image=_image_input_from_dict(data.get("reference_image")),
    )


def serialize_video_generation_request(request: VideoGenerationRequest) -> str:
    return json.dumps(asdict(request), separators=(",", ":"), sort_keys=True)


def deserialize_video_generation_request(payload: str) -> VideoGenerationRequest:
    data = json.loads(payload)
    return VideoGenerationRequest(
        chat_id=data["chat_id"],
        user_id=data["user_id"],
        prompt=data["prompt"],
        model=data["model"],
        aspect_ratio=data["aspect_ratio"],
        duration_seconds=data["duration_seconds"],
        output_gcs_uri=data.get("output_gcs_uri"),
        reference_image=_image_input_from_dict(data.get("reference_image")),
        provider_hint=data.get("provider_hint", "auto"),
        width=data.get("width"),
        height=data.get("height"),
        frame_rate=data.get("frame_rate"),
        pipeline=data.get("pipeline"),
        num_inference_steps=data.get("num_inference_steps"),
        seed=data.get("seed"),
        image_strength=data.get("image_strength"),
        resolution=data.get("resolution"),
        model_locked=data.get("model_locked", False),
    )


def _image_input_from_dict(data: dict | None) -> ImageInput | None:
    if data is None:
        return None
    return ImageInput(
        telegram_file_id=data["telegram_file_id"],
        telegram_file_unique_id=data["telegram_file_unique_id"],
        mime_type=data["mime_type"],
        width=data["width"],
        height=data["height"],
        byte_size=data.get("byte_size"),
        bytes_b64=data.get("bytes_b64"),
        caption=data.get("caption"),
    )
