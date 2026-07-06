from __future__ import annotations

from app.domain.commands import SUPPORTED_COMMANDS, render_help_message, render_start_message


def test_supported_commands_remove_video_ltx() -> None:
    assert "/video_ltx" not in SUPPORTED_COMMANDS
    assert {"/start", "/help", "/status", "/reset", "/settings", "/image", "/video"} <= SUPPORTED_COMMANDS


def test_command_texts_reference_gemini_and_omit_video_ltx() -> None:
    start = render_start_message()
    help_text = render_help_message()

    assert "/video_ltx" not in start
    assert "/video_ltx" not in help_text
    assert "Vertex" not in help_text
    assert "Gemini" in help_text
