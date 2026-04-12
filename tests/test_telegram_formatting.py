from __future__ import annotations

from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from app.telegram.drafts import TelegramResponseEmitter
from app.telegram.formatting import render_telegram_html


class FakeBot:
    def __init__(self, *, fail_first_send: bool = False) -> None:
        self.fail_first_send = fail_first_send
        self.sent_messages: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)
        if self.fail_first_send and len(self.sent_messages) == 1:
            raise TelegramBadRequest(
                method=SendMessage(chat_id=kwargs["chat_id"], text=kwargs["text"]),
                message="can't parse entities",
            )
        return None


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
