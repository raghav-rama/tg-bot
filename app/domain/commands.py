from __future__ import annotations

SUPPORTED_COMMANDS = {"/start", "/help", "/status", "/reset", "/image", "/video"}

ACCESS_DENIED_TEXT = "Access denied."
UNSUPPORTED_MESSAGE_TEXT = (
    "I can only handle text messages and one photo with an optional caption right now."
)
PROVIDER_RETRY_TEXT = (
    "I couldn't get a response from the AI service just now. Please try again in a moment."
)
GENERIC_FAILURE_TEXT = "Something went wrong. Please try again in a moment."
EMPTY_TEXT_TEXT = "Please send a non-empty text message."
IMAGE_PROMPT_REQUIRED_TEXT = (
    "Use /image followed by a prompt, for example: /image cinematic neon city skyline at night"
)
IMAGE_GENERATION_NOT_CONFIGURED_TEXT = "Image generation is not configured right now."
IMAGE_GENERATION_RETRY_TEXT = (
    "I couldn't generate an image just now. Please try again in a moment."
)
VIDEO_PROMPT_REQUIRED_TEXT = (
    "Use /video followed by a prompt, for example: /video slow cinematic dolly shot through a neon alley"
)
VIDEO_GENERATION_NOT_CONFIGURED_TEXT = "Video generation is not configured right now."
VIDEO_GENERATION_QUEUED_TEXT = (
    "Video generation started. I'll send it here when it's ready."
)
VIDEO_GENERATION_RETRY_TEXT = (
    "I couldn't generate a video just now. Please try again in a moment."
)
VIDEO_GENERATION_READY_TEXT = "Your video is ready."
VIDEO_GENERATION_TOO_LARGE_TEXT = (
    "The generated video is too large to send through Telegram right now. Please try a shorter prompt."
)


def render_start_message() -> str:
    return (
        "This is a private, memory-enabled bot.\n\n"
        "Supported inputs:\n"
        "- text messages\n"
        "- one photo with an optional caption\n"
        "- /image followed by a prompt to generate one image\n"
        "- /video followed by a prompt to generate one short video\n\n"
        "Commands:\n"
        "/start\n"
        "/help\n"
        "/status\n"
        "/reset\n"
        "/image <prompt>\n"
        "/video <prompt>"
    )


def render_help_message() -> str:
    return (
        "Supported commands:\n"
        "/start - show the bot overview\n"
        "/help - show this help message\n"
        "/status - show runtime status\n"
        "/reset - start a fresh conversation for this chat\n"
        "/image <prompt> - generate one image with Vertex AI\n"
        "/video <prompt> - queue one short video with Vertex AI\n\n"
        "Supported inputs:\n"
        "- text messages\n"
        "- one photo with an optional caption\n\n"
        "Unsupported inputs such as stickers, voice notes, files, video, and media groups fail safely."
    )


def render_status_message(
    *,
    update_mode: str,
    chat_model: str,
    image_generation_enabled: bool,
    image_model: str,
    video_generation_enabled: bool,
    video_model: str,
    memory_enabled: bool,
) -> str:
    memory_state = "enabled" if memory_enabled else "disabled"
    image_state = f"enabled ({image_model})" if image_generation_enabled else "disabled"
    video_state = f"enabled ({video_model})" if video_generation_enabled else "disabled"
    return (
        "Status\n"
        f"- update mode: {update_mode}\n"
        f"- chat model: {chat_model}\n"
        f"- image generation: {image_state}\n"
        f"- video generation: {video_state}\n"
        f"- memory: {memory_state}"
    )


def render_reset_message() -> str:
    return "Started a fresh conversation for this chat. Earlier history is preserved."
