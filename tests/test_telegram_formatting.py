from __future__ import annotations

from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from app.domain.models import GeneratedVideoResult
from app.telegram.drafts import TelegramResponseEmitter
from app.telegram.formatting import render_telegram_html


class FakeBot:
    def __init__(self, *, fail_first_send: bool = False) -> None:
        self.fail_first_send = fail_first_send
        self.sent_messages: list[dict] = []
        self.sent_videos: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)
        if self.fail_first_send and len(self.sent_messages) == 1:
            raise TelegramBadRequest(
                method=SendMessage(chat_id=kwargs["chat_id"], text=kwargs["text"]),
                message="can't parse entities",
            )
        return None

    async def send_video(self, **kwargs):
        self.sent_videos.append(kwargs)

        class _Video:
            file_id = "tg-video-1"
            file_unique_id = "tg-video-uniq-1"
            width = kwargs.get("width") or 720
            height = kwargs.get("height") or 1280
            duration = kwargs.get("duration") or 8
            mime_type = "video/mp4"
            file_size = 1024

        class _Message:
            message_id = 99
            video = _Video()

        return _Message()


def test_render_telegram_html_converts_common_markdown_subset() -> None:
    rendered = render_telegram_html(
        "## Video idea\n"
        "**Topic:** 10 facts about **Ramanathaswamy Temple**\n"
        "1. **First title**\n"
        "- Visit [official site](https://example.com)\n"
        "Use `slugify()` for filenames.\n"
        "```python\n"
        'print("<hi>")\n'
        "```"
    )

    assert rendered == (
        "<b>Video idea</b>\n"
        "<b>Topic:</b> 10 facts about <b>Ramanathaswamy Temple</b>\n"
        "1. <b>First title</b>\n"
        '- Visit <a href="https://example.com">official site</a>\n'
        "Use <code>slugify()</code> for filenames.\n"
        '<pre>print("&lt;hi&gt;")</pre>'
    )


def test_render_telegram_html_escapes_raw_html() -> None:
    rendered = render_telegram_html("<b>unsafe</b> and **safe**")

    assert rendered == "&lt;b&gt;unsafe&lt;/b&gt; and <b>safe</b>"


async def test_response_emitter_sends_formatted_html() -> None:
    bot = FakeBot()
    emitter = TelegramResponseEmitter(bot=bot, chat_id=123)

    await emitter.send_text("## Video idea\n**Topic:** great hooks")

    assert bot.sent_messages == [
        {
            "chat_id": 123,
            "text": "<b>Video idea</b>\n<b>Topic:</b> great hooks",
            "parse_mode": ParseMode.HTML,
        }
    ]


async def test_response_emitter_falls_back_to_plain_text_on_bad_request() -> None:
    bot = FakeBot(fail_first_send=True)
    emitter = TelegramResponseEmitter(bot=bot, chat_id=456)

    await emitter.send_text("## Video idea\n**Topic:** great hooks")

    assert bot.sent_messages == [
        {
            "chat_id": 456,
            "text": "<b>Video idea</b>\n<b>Topic:</b> great hooks",
            "parse_mode": ParseMode.HTML,
        },
        {
            "chat_id": 456,
            "text": "## Video idea\n**Topic:** great hooks",
            "parse_mode": None,
        },
    ]


async def test_response_emitter_passes_video_metadata_and_timeout() -> None:
    bot = FakeBot()
    emitter = TelegramResponseEmitter(
        bot=bot,
        chat_id=789,
        video_request_timeout_seconds=180,
    )

    sent_video = await emitter.send_video(
        GeneratedVideoResult(
            video_bytes=b"video-bytes",
            mime_type="video/mp4",
            provider="vertex",
            raw_model="veo-3.1-fast-generate-001",
            prompt="vertical city pan",
            output_uri="gs://bucket/video.mp4",
            duration_seconds=8,
            width=720,
            height=1280,
        )
    )

    assert bot.sent_videos == [
        {
            "chat_id": 789,
            "video": bot.sent_videos[0]["video"],
            "caption": None,
            "duration": 8,
            "width": 720,
            "height": 1280,
            "supports_streaming": True,
            "request_timeout": 180,
        }
    ]
    assert sent_video.telegram_message_id == 99
    assert sent_video.width == 720
    assert sent_video.height == 1280
