from __future__ import annotations

SUPPORTED_COMMANDS = {"/start", "/help", "/status", "/reset"}

ACCESS_DENIED_TEXT = "Access denied."
UNSUPPORTED_MESSAGE_TEXT = (
    "I can only handle text messages and one photo with an optional caption right now."
)
PROVIDER_RETRY_TEXT = (
    "I couldn't get a response from the AI service just now. Please try again in a moment."
)
GENERIC_FAILURE_TEXT = "Something went wrong. Please try again in a moment."
EMPTY_TEXT_TEXT = "Please send a non-empty text message."


def render_start_message() -> str:
    return (
        "This is a private, memory-enabled bot.\n\n"
        "Supported inputs:\n"
        "- text messages\n"
        "- one photo with an optional caption\n\n"
        "Commands:\n"
        "/start\n"
        "/help\n"
        "/status\n"
        "/reset"
    )


def render_help_message() -> str:
    return (
        "Supported commands:\n"
        "/start - show the bot overview\n"
        "/help - show this help message\n"
        "/status - show runtime status\n"
        "/reset - start a fresh conversation for this chat\n\n"
        "Supported inputs:\n"
        "- text messages\n"
        "- one photo with an optional caption\n\n"
        "Unsupported inputs such as stickers, voice notes, files, video, and media groups fail safely."
    )


def render_status_message(update_mode: str, model: str, memory_enabled: bool) -> str:
    memory_state = "enabled" if memory_enabled else "disabled"
    return (
        "Status\n"
        f"- update mode: {update_mode}\n"
        f"- model: {model}\n"
        f"- memory: {memory_state}"
    )


def render_reset_message() -> str:
    return "Started a fresh conversation for this chat. Earlier history is preserved."
