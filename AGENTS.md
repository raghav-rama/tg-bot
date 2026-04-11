# AGENTS.md

## Project Context

This repository is for a `Python + FastAPI` Telegram bot that sends user input to an AI provider and stores conversation memory.

Before making implementation decisions, read the local planning docs:

- `docs/architecture.md`
- `docs/flows.md`
- `docs/implementation-plan.md`

## Telegram Documentation

When working on Telegram bot integration, fetch current information from these sources first:

- Official Telegram bots overview: https://core.telegram.org/bots
- Official Telegram Bot API reference: https://core.telegram.org/bots/api
- Official Telegram bots FAQ: https://core.telegram.org/bots/faq
- Official Telegram bot tutorial: https://core.telegram.org/bots/tutorial
- Official `aiogram` docs: https://docs.aiogram.dev
- `aiogram` Bot API reference: https://docs.aiogram.dev/en/latest/api/index.html

Use the Telegram links for API behavior, field names, limits, update types, and webhook or polling semantics. Use the `aiogram` links for Python framework usage.

If an unofficial tutorial conflicts with these sources, trust the official Telegram docs first.

## Working Rules

- Keep Telegram-specific logic separate from domain and provider logic.
- Prefer polling-first implementation, while preserving a clean webhook path.
- Treat text and single-image messages as the only supported v1 inputs unless the docs in this repo are updated.
- Keep the bot private via an allowlist unless requirements change.
- Use tavily fetching up-to-date info about anything.
- Use context7 for fetching up-to-date documentation about any library or SDK.
