# AGENTS.md

## Project Context

This repository is for a `Python + FastAPI` Telegram bot that sends user input to an AI provider and stores conversation memory.

Before making implementation decisions, read the local planning docs:

- `docs/roadmap.md`
- `docs/architecture.md`
- `docs/flows.md`
- `docs/implementation-plan.md`

Use `docs/roadmap.md` as the source of truth for:

- the currently active phase
- whether a feature is current scope or planned scope
- the exit criteria that define when the repo should move to the next phase

The current repo plan is Phase 1 first, with Google Gemini / Vertex AI image and video generation deferred to later roadmap phases.

## Current State

As of `2026-04-11`, the repository is no longer docs-only.

- Phase 1 application code exists under `app/`.
- Project metadata and dependency definitions exist in `pyproject.toml` and `uv.lock`.
- Automated tests exist under `tests/` for health/readiness behavior, Telegram normalization, allowlist handling, history reuse, and reset semantics.
- Live Telegram/OpenAI verification still depends on real environment variables and a manual runtime check.

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
- Treat text replies as the only supported v1 outputs unless the docs in this repo are updated.
- Keep the bot private via an allowlist unless requirements change.
- Do not treat roadmap items as implementation requirements until their phase becomes active in `docs/roadmap.md`.
- Use tavily fetching up-to-date info about anything.
- Use context7 for fetching up-to-date documentation about any library or SDK.
- Keep AGENTS.md file updated with the current state of the repo.
- Always sign commits
