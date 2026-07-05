# AGENTS.md

## Project Context

This repository is for a `Python + FastAPI` Telegram bot that sends user input to an AI provider and stores conversation memory.

Before making implementation decisions, read the local planning docs:

- `docs/roadmap.md`
- `docs/architecture.md`
- `docs/flows.md`
- `docs/implementation-plan.md`
- `docs/phase-1-5-draft-streaming.md` when working on Telegram partial-reply streaming
- `docs/phase-2-vertex-image-generation.md` when working on generated image replies
- `docs/phase-3-vertex-video-generation.md` when working on generated video replies
- Phase 5 ElevenLabs TTS is tracked in `docs/roadmap.md` until a dedicated planning doc exists.

Use `docs/roadmap.md` as the source of truth for:

- the currently active phase
- whether a feature is current scope or planned scope
- the exit criteria that define when the repo should move to the next phase

The current repo plan has `Phase 5 - ElevenLabs Hindi Text To Speech` in progress in an isolated git worktree; `Phase 6 - Fal Video Provider Support` is accepted as complete and merged into `dev`; `Phase 4 - Hardening And Expansion` is accepted complete.

Active worktrees:

- Phase 5 TTS: `.worktrees/phase-5-elevenlabs-tts` on branch `phase-5-elevenlabs-tts`

## Current State

As of `2026-07-05`, the repository is no longer docs-only. Phase 1, Phase 1.5, Phase 2, Phase 3, Phase 4, and Phase 6 are accepted as complete, and Phase 5 is in progress in a parallel worktree.

- Phase 1 foundation code exists under `app/`.
- Project metadata and dependency definitions exist in `pyproject.toml` and `uv.lock`.
- A repo-level `README.md` now exists and documents setup, configuration, runtime modes, and current phase status.
- Container build assets now exist through a repo-level `Dockerfile`, `.dockerignore`, and runtime entrypoint that prepares the configured SQLite parent directory after deployment volumes are mounted, then drops privileges to the `app` user.
- Phase 1.5 code exists for OpenAI streamed responses, Telegram draft delivery, Telegram-safe final-message formatting, and per-chat supersession handling.
- Phase 2 code now exists for `/image <prompt>`, Vertex image generation through the Python `google-genai` SDK path, Telegram photo delivery, and SQLite persistence of generated-image metadata.
- Phase 2 image generation now supports a Vertex API key for local testing and can still use ADC when needed.
- The `/image` provider now supports both Imagen models through Vertex `generate_images` and Gemini image models through Vertex `generate_content`; `gemini-3-pro-image-preview` requires `VERTEX_LOCATION=global`.
- Phase 3 code now exists for `/video <prompt>`, SQLite-backed generation jobs, an in-process polling worker, Vertex video generation through the Python `google-genai` SDK path, and Telegram video delivery.
- Phase 4 video routing now supports Runpod-hosted LTX fallback: `/video <prompt>` uses Vertex first and falls back to Runpod only on classified Vertex safety/unsafe rejections, while `/video_ltx <prompt>` forces Runpod for manual testing.
- Phase 4 now includes `/settings` inline-button presets for allowed users to tune video provider, video provider family (when multiple Fal families are configured), video duration, video aspect/orientation, safe Runpod LTX options, image settings, and chat behavior per chat/user without exposing secrets or infrastructure settings.
- Runpod LTX requests use native LTX sizing controls (`width`, `height`, `num_frames`, and `frame_rate`) instead of Vertex-style `aspect_ratio`; safe Telegram settings can also send `pipeline`, two-stage `num_inference_steps`, `seed`, and reference `image_strength`, while storage, checkpoint, LoRA, offload, quantization, and compile controls remain environment-only.
- Completed GCS-backed Runpod worker outputs are delivered by transient bot-side signed URLs while persisting only the durable `gs://` URI.
- Video generation currently supports either inline provider-returned bytes or URI-backed output that can be fetched later when needed.
- Telegram video delivery now uses a configurable request timeout and logs concrete delivery exceptions for easier debugging of slow or ambiguous uploads.
- Completed Phase 4 hardening includes a real webhook deployment path: webhook mode registers the Telegram webhook during startup, validates `X-Telegram-Bot-Api-Secret-Token`, and reports webhook misconfiguration through readiness.
- Phase 4 now includes log-only observability for chat, `/image`, `/video`, `/video_ltx`, and video job delivery, with optional config-driven cost estimates that default to disabled.
- Production logs can now use `APP_LOG_FORMAT=json` for parseable structured fields, while local logs default to readable text. Repeated still-running video poll state and successful low-level HTTP client requests no longer dominate INFO-level logs.
- Phase 4 now supports reference-image generation from Telegram photo captions and text commands that reply to a Telegram photo: `/image <prompt>` uses Gemini image models only, while `/video <prompt>` and `/video_ltx <prompt>` queue image-to-video jobs.
- Generated video bytes remain transient in memory only; when URI-backed assets are used, cleanup is expected to come from the configured bucket or object-storage lifecycle policy outside the app.
- Automated tests exist under `tests/` for health/readiness behavior, Telegram normalization, reply-to-photo reference commands, allowlist handling, history reuse, reset semantics, draft streaming, draft fallback, explicit draft rate-limit fallback, provider cleanup, supersession, image generation, video job handling, settings preferences, observability/cost-estimate helpers, Vertex provider flows, Runpod provider flows, and video provider routing.
- Draft streaming continues to target private text chats first; image-understanding requests still use the final-only chat path by default.
- Photo captions that do not start with `/image`, `/video`, or `/video_ltx` continue through the OpenAI image-understanding path.
- Generated images are sent through Telegram `sendPhoto`, while raw generated bytes are not persisted in SQLite.
- Generated videos are sent through Telegram `sendVideo`, while raw generated bytes are not persisted in SQLite.
- Live Vertex, Runpod, and Telegram verification for the `/image`, `/video`, and `/video_ltx` flows still depends on real environment variables and a manual runtime check.
- Per-user/per-chat quotas, video/image daily budget caps, prompt/reference-image moderation gates, and in-app provider-output URL retention/expiry handling were deferred out of completed Phase 4 and remain future work unless the roadmap changes.
- Fal-hosted video provider support is accepted as complete and merged into `dev`, including Kling, Seedance, and Gemini Omni Flash model families behind the existing queued `/video` path with per-family selection available in `/settings`.
- The Fal video provider now uses the official Python `fal-client` SDK for queued submit/poll/result handling and uploads Telegram reference images to Fal before image-to-video or reference-to-video requests.

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
- Treat text replies, `/settings` inline-keyboard messages, `/image`-driven generated image replies, and `/video` or `/video_ltx` generated video replies as the only supported outputs unless the docs in this repo are updated.
- Keep the bot private via an allowlist unless requirements change.
- Do not treat roadmap items as implementation requirements until their phase becomes active in `docs/roadmap.md`.
- Use tavily fetching up-to-date info about anything.
- Use context7 for fetching up-to-date documentation about any library or SDK.
- Keep AGENTS.md file updated with the current state of the repo.
- Always sign commits
