import pytest
from pydantic import ValidationError

from conftest import build_settings


def test_tts_is_optional_and_normalizes_blank_credentials(tmp_path):
    assert not build_settings(tmp_path / "bot.db").tts_enabled
    assert not build_settings(tmp_path / "bot.db", ELEVENLABS_API_KEY="  ").tts_enabled
    settings = build_settings(tmp_path / "bot.db", ELEVENLABS_API_KEY=" test ")
    assert settings.tts_enabled
    assert settings.elevenlabs_api_key.get_secret_value() == "test"


@pytest.mark.parametrize("overrides", [
    {"BOT_TTS_MAX_CHARS": 0}, {"ELEVENLABS_TTS_TIMEOUT_SECONDS": -1},
    {"ELEVENLABS_TTS_TIMEOUT_SECONDS": "nan"},
    {"TELEGRAM_VOICE_REQUEST_TIMEOUT_SECONDS": 0},
    {"ELEVENLABS_TTS_VOICE_ID": " "}, {"ELEVENLABS_TTS_MODEL": ""},
    {"ELEVENLABS_TTS_OUTPUT_FORMAT": "pcm_44100"},
    {"ELEVENLABS_TTS_OUTPUT_FORMAT": "mp3_invalid"},
])
def test_invalid_tts_configuration_fails_early(tmp_path, overrides):
    with pytest.raises(ValidationError):
        build_settings(tmp_path / "bot.db", **overrides)
