# tg-bot

Private Telegram bot built with FastAPI, SQLite, OpenAI chat, Gemini Developer API image/video generation, Runpod video fallback, and Fal video provider support.

## Status

The repository has completed `Phase 4 - Hardening And Expansion` and `Phase 6 - Fal Video Provider Support` (merged into `dev`). `Phase 5 - ElevenLabs Hindi Text To Speech` is in progress in an isolated git worktree.

Active worktrees:

- Phase 5 TTS: `.worktrees/phase-5-elevenlabs-tts` on branch `phase-5-elevenlabs-tts`

Implemented through Phase 4 and Phase 6:

- private, allowlisted Telegram bot
- polling-first runtime plus webhook mode that self-registers with Telegram
- SQLite-backed conversation memory and reset semantics
- text chat and single-photo understanding through OpenAI
- Telegram draft streaming for long-running text replies
- `/image <prompt>` queued generation through the Gemini Developer API and later Telegram `sendPhoto` delivery
- `/video <prompt>` queued generation through Gemini, with provider fallback and optional Fal/Runpod video providers
- `/settings` inline-button presets for per-chat/per-user video provider, Fal model family (when multiple families are configured), video duration, aspect ratio, safe Runpod LTX, image, and chat request settings
- SQLite-backed media jobs, background polling, and later Telegram `sendPhoto` / `sendVideo` delivery
- photo captions that start with `/image <prompt>` or `/video <prompt>` use the photo as a transient reference image for generation; text commands can also reply to any Telegram photo to use that photo as the reference
- log-only usage observability with production JSON logs, local text logs by default, and optional config-driven cost estimates for chat, image, and video generation
- health and readiness endpoints plus automated tests

Local planning docs remain the source of truth for scope and sequencing:

- [docs/roadmap.md](docs/roadmap.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/flows.md](docs/flows.md)
- [docs/implementation-plan.md](docs/implementation-plan.md)
- [docs/phase-1-5-draft-streaming.md](docs/phase-1-5-draft-streaming.md)
- [docs/phase-2-vertex-image-generation.md](docs/phase-2-vertex-image-generation.md)
- [docs/phase-3-vertex-video-generation.md](docs/phase-3-vertex-video-generation.md)

## What The Bot Supports

Inbound inputs:

- plain text messages
- one photo with an optional caption
- one photo with a caption that starts with `/image <prompt>` or `/video <prompt>`
- text `/image` or `/video` commands that reply to one Telegram photo
- commands: `/start`, `/help`, `/status`, `/reset`, `/settings`, `/image`, `/video`

Outbound outputs:

- normal text replies
- generated images through Telegram `sendPhoto`
- generated videos through Telegram `sendVideo`

Current constraints:

- the bot stays private through `TELEGRAM_ALLOWED_USER_IDS`
- draft streaming targets private text chats first
- image-understanding requests use the final-only reply path by default
- webhook mode requires a public HTTPS URL and validates `X-Telegram-Bot-Api-Secret-Token`
- raw generated image and video bytes are not persisted in SQLite
- queued reference-photo jobs persist Telegram photo metadata plus `file_id`; raw reference photo bytes are re-downloaded by the worker when needed and are not persisted in SQLite
- `/image` and `/video` both acknowledge immediately, persist a queued job, and deliver the final media later from the background worker
- live Telegram, Gemini, Runpod, and Fal verification still depends on real credentials and manual runtime checks
- generated video bytes remain transient in memory only, and URI-backed assets should rely on external bucket or object-storage lifecycle cleanup
- `/image` now uses current Gemini image-generation models for both prompt-only and reference-image flows
- `/image` with a reference photo requires a Gemini image model; Imagen remains prompt-to-image only
- `/video` falls back only on classified safety rejections; timeout, quota, and generic upstream failures do not trigger fallback

## Architecture At A Glance

The runtime is split so Telegram transport stays separate from domain and provider logic.

- `app/api/`: `healthz`, `readyz`, and webhook ingestion
- `app/telegram/`: polling runtime, handlers, normalization, formatting, media delivery, and drafts
- `app/domain/`: commands, models, interfaces, and orchestration in `ChatService`
- `app/providers/`: OpenAI chat plus Gemini image/video, Runpod video, Fal video, and video provider routing adapters
- `app/storage/`: SQLite schema and repositories for conversations, messages, generated images, generation jobs, and user preferences
- `app/workers/`: background polling worker for queued image and video jobs

## Requirements

- Python `>=3.10`
- `uv` for dependency management
- a Telegram bot token
- an OpenAI API key for chat replies
- Gemini API key configuration for `/image` and default `/video`
- optional Runpod configuration for `/video` fallback
- optional Fal configuration for `/video` provider expansion

## Quick Start

1. Install dependencies:

```bash
uv sync --extra dev
```

2. Create a `.env` file in the repo root:

```dotenv
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
OPENAI_API_KEY=your-openai-api-key
TELEGRAM_ALLOWED_USER_IDS=123456789

# Optional app settings
APP_UPDATE_MODE=polling
APP_LOG_LEVEL=INFO
# Use APP_LOG_FORMAT=json in production log viewers.
APP_LOG_FORMAT=text
SQLITE_PATH=./data/bot.db
# Required when APP_UPDATE_MODE=webhook
# TELEGRAM_WEBHOOK_URL=https://bot.example.com/telegram/webhook
# TELEGRAM_WEBHOOK_SECRET_TOKEN=your-webhook-secret
# TELEGRAM_WEBHOOK_DROP_PENDING_UPDATES=false

# Optional OpenAI overrides
OPENAI_MODEL=gpt-4.1-mini
OPENAI_TEMPERATURE=0.2
OPENAI_MAX_OUTPUT_TOKENS=500
OPENAI_TIMEOUT_SECONDS=45
# Optional log-only cost estimates; keep unset or 0 to disable.
# OPENAI_INPUT_COST_PER_1M_TOKENS_USD=0
# OPENAI_OUTPUT_COST_PER_1M_TOKENS_USD=0

# Optional Gemini configuration for /image and /video
GEMINI_API_KEY=your-gemini-api-key
# Or use GOOGLE_API_KEY instead.
# GOOGLE_API_KEY=your-google-api-key
# GEMINI_IMAGE_MODEL=gemini-3.1-flash-image
# GEMINI_IMAGE_ASPECT_RATIO=1:1
# GEMINI_IMAGE_OUTPUT_MIME_TYPE=image/jpeg
# GEMINI_IMAGE_TIMEOUT_SECONDS=60
# GEMINI_VIDEO_MODEL=gemini-omni-flash-preview
# GEMINI_VIDEO_ASPECT_RATIO=9:16
# GEMINI_VIDEO_DURATION_SECONDS=4
# GEMINI_VIDEO_TIMEOUT_SECONDS=180
# GEMINI_IMAGE_COST_PER_IMAGE_USD=0
# GEMINI_VIDEO_COST_PER_SECOND_USD=0

# Optional Fal video provider for /video
# FAL_KEY=your-fal-api-key
# FAL_VIDEO_TEXT_TO_VIDEO_MODEL=fal-ai/google/gemini-omni-flash
# FAL_VIDEO_IMAGE_TO_VIDEO_MODEL=fal-ai/google/gemini-omni-flash/image-to-video
# FAL_VIDEO_REFERENCE_TO_VIDEO_MODEL=fal-ai/google/gemini-omni-flash/reference-to-video
# FAL_VIDEO_RESOLUTION=720p
# FAL_CLIENT_TIMEOUT_SECONDS=45

# Optional Runpod configuration for /video fallback
# RUNPOD_API_KEY=your-runpod-api-key
# RUNPOD_VIDEO_ENDPOINT_ID=your-runpod-serverless-endpoint-id
# RUNPOD_VIDEO_BASE_URL=https://api.runpod.ai/v2
# RUNPOD_VIDEO_MODEL=ltx-2.3-22b-distilled-1.1
# RUNPOD_VIDEO_WIDTH=576
# RUNPOD_VIDEO_HEIGHT=1024
# RUNPOD_VIDEO_DURATION_SECONDS=4
# RUNPOD_VIDEO_FRAME_RATE=24
# RUNPOD_VIDEO_EXECUTION_TIMEOUT_MS=1800000
# RUNPOD_VIDEO_TTL_MS=7200000
# RUNPOD_VIDEO_REFERENCE_IMAGE_MAX_BYTES=6000000
# RUNPOD_VIDEO_SIGNED_URL_TTL_SECONDS=3600
# RUNPOD_VIDEO_COST_PER_SECOND_USD=0

# Example video provider order. Default is "gemini,runpod".
# Add "fal" only when FAL_KEY is configured, e.g.:
# VIDEO_PROVIDER_ORDER=gemini,runpod,fal
# RUNPOD_VIDEO_ENDPOINT_ID=your-runpod-serverless-endpoint-id
# RUNPOD_VIDEO_BASE_URL=https://api.runpod.ai/v2
# RUNPOD_VIDEO_MODEL=ltx-2.3-22b-distilled-1.1
# RUNPOD_VIDEO_WIDTH=576
# RUNPOD_VIDEO_HEIGHT=1024
# RUNPOD_VIDEO_DURATION_SECONDS=4
# RUNPOD_VIDEO_FRAME_RATE=24
# RUNPOD_VIDEO_EXECUTION_TIMEOUT_MS=1800000
# RUNPOD_VIDEO_TTL_MS=7200000
# RUNPOD_VIDEO_REFERENCE_IMAGE_MAX_BYTES=6000000
# RUNPOD_VIDEO_SIGNED_URL_TTL_SECONDS=3600
# RUNPOD_VIDEO_COST_PER_SECOND_USD=0
```

3. Start the app:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

With `APP_UPDATE_MODE=polling`, FastAPI starts the Telegram polling runtime during application startup.

## Continuous Integration

`.github/workflows/ci.yml` runs the test suite on every push to `main` or `dev` and on every pull
request targeting them. It installs the locked dependency set with `uv sync --locked --extra dev`
on Python 3.13, matching the runtime image in `Dockerfile`, and runs `pytest`.

The suite is hermetic — `tests/conftest.py` clears every environment variable matching a `Settings`
alias — so CI needs no secrets and cannot pass by accident on a machine that happens to have a
populated `.env`.

## Configuration

Core settings:

- `TELEGRAM_BOT_TOKEN`: required
- `OPENAI_API_KEY`: required
- `TELEGRAM_ALLOWED_USER_IDS`: required comma-separated Telegram user IDs
- `APP_UPDATE_MODE`: `polling` or `webhook`
- `TELEGRAM_WEBHOOK_URL`: required HTTPS URL when webhook mode is enabled
- `TELEGRAM_WEBHOOK_SECRET_TOKEN`: required when webhook mode is enabled
- `TELEGRAM_WEBHOOK_DROP_PENDING_UPDATES`: default `false`
- `APP_LOG_LEVEL`: default `INFO`
- `APP_LOG_FORMAT`: `text` or `json`, default `text`; set `json` in production for parseable structured fields
- `SQLITE_PATH`: default `./data/bot.db`

Chat settings:

- `BOT_SYSTEM_PROMPT`
- `BOT_HISTORY_MAX_TURNS`
- `BOT_IMAGE_MAX_BYTES`
- `OPENAI_MODEL`
- `OPENAI_TEMPERATURE`
- `OPENAI_MAX_OUTPUT_TOKENS`
- `OPENAI_TIMEOUT_SECONDS`
- `OPENAI_INPUT_COST_PER_1M_TOKENS_USD`: optional log-only estimate rate, default `0`
- `OPENAI_OUTPUT_COST_PER_1M_TOKENS_USD`: optional log-only estimate rate, default `0`

Draft streaming settings:

- `BOT_ENABLE_MESSAGE_DRAFTS`
- `BOT_DRAFT_STREAM_ON_IMAGES`
- `BOT_DRAFT_START_DELAY_MS`
- `BOT_DRAFT_UPDATE_INTERVAL_MS`
- `BOT_DRAFT_MIN_CHARS_DELTA`

Gemini image settings:

- `GEMINI_API_KEY` or `GOOGLE_API_KEY`
- `GEMINI_IMAGE_MODEL`
- `GEMINI_IMAGE_ASPECT_RATIO`
- `GEMINI_IMAGE_OUTPUT_MIME_TYPE`
- `GEMINI_IMAGE_TIMEOUT_SECONDS`: `/image` provider timeout in seconds, default `60`
- `GEMINI_IMAGE_COST_PER_IMAGE_USD`: optional log-only estimate rate, default `0`

Image model notes:

- `/image` uses Gemini image generation directly and supports reference-image prompts through the active Google media path.
- Slow image-generation calls time out through `GEMINI_IMAGE_TIMEOUT_SECONDS` instead of hanging indefinitely.
- To use a Telegram photo as a reference image, send the photo with a caption like `/image restyle this as a pencil sketch`, or reply to any Telegram photo with `/image <prompt>`; this requires a Gemini image model.

Gemini video settings:

- `VIDEO_PROVIDER_ORDER`: default `gemini,runpod`
- `GEMINI_VIDEO_MODEL`
- `GEMINI_VIDEO_ASPECT_RATIO`
- `GEMINI_VIDEO_DURATION_SECONDS`
- `GEMINI_VIDEO_TIMEOUT_SECONDS`
- `BOT_VIDEO_MAX_BYTES`
- `TELEGRAM_VIDEO_REQUEST_TIMEOUT_SECONDS`
- `VIDEO_JOB_POLL_INTERVAL_SECONDS`
- `VIDEO_JOB_MAX_AGE_SECONDS`: default `1800`; a video job older than this is marked failed instead of being polled forever. A submitted job is always polled once more first, so a late but completed video is still delivered; a job that was never submitted is dropped without submitting
- `GEMINI_VIDEO_COST_PER_SECOND_USD`: optional log-only estimate rate, default `0`

Fal video settings:

- `FAL_KEY`: required to enable Fal video generation
- `FAL_VIDEO_MODEL`: default text-to-video endpoint, default `fal-ai/kling-video/v3/standard/text-to-video`
- `FAL_VIDEO_TEXT_TO_VIDEO_MODEL`: optional override for the text-to-video endpoint; if set, it takes precedence over `FAL_VIDEO_MODEL`
- `FAL_VIDEO_IMAGE_TO_VIDEO_MODEL`: optional image-to-video endpoint (e.g. `fal-ai/kling-video/v3/standard/image-to-video`)
- `FAL_VIDEO_REFERENCE_TO_VIDEO_MODEL`: optional reference-to-video endpoint (e.g. `bytedance/seedance-2.0/reference-to-video`)
- `FAL_VIDEO_EDIT_MODEL`: optional video-to-video endpoint (requires future video-input support)
- `FAL_VIDEO_RESOLUTION`: Seedance resolution preset, default `720p`
- `FAL_VIDEO_REFERENCE_IMAGE_MAX_BYTES`: default `6000000`
- `FAL_VIDEO_COST_PER_SECOND_USD`: optional log-only estimate rate, default `0`
- `FAL_CLIENT_TIMEOUT_SECONDS`: Fal SDK client and upload/download timeout, default `45`

Supported Fal model families include Kling (`fal-ai/kling-video`), Seedance 2.0 (`bytedance/seedance-2.0`), and Gemini Omni Flash (`google/gemini-omni-flash`). The bot infers which families are available from the configured endpoints. When more than one family is available, the `/settings` menu shows a **Fal model** option so users can pick Kling, Seedance, or Gemini per chat. The chosen family is then mapped to the right mode-specific endpoint, and usable reference photos are uploaded through the official `fal-client` SDK before the mode-specific Fal argument (`start_image_url`, `image_url`, or `image_urls`) is sent:

- text-only `/video` uses `FAL_VIDEO_TEXT_TO_VIDEO_MODEL` or `FAL_VIDEO_MODEL`
- `/video` with a reference photo looks for a matching-family reference-to-video endpoint, then image-to-video, then falls back to the text-to-video endpoint for that family
- oversized reference photos are omitted and logged before the request falls back to the configured text-to-video endpoint
- unsupported aspect ratios for Gemini are coerced to `9:16`

Runpod video settings:

- `RUNPOD_API_KEY`
- `RUNPOD_VIDEO_ENDPOINT_ID`
- `RUNPOD_VIDEO_BASE_URL`: default `https://api.runpod.ai/v2`
- `RUNPOD_VIDEO_MODEL`: default `ltx-2.3-22b-distilled-1.1`
- `RUNPOD_VIDEO_WIDTH`: default `576`, must be divisible by `64`
- `RUNPOD_VIDEO_HEIGHT`: default `1024`, must be divisible by `64`
- `RUNPOD_VIDEO_DURATION_SECONDS`: defaults to `GEMINI_VIDEO_DURATION_SECONDS` when unset
- `RUNPOD_VIDEO_FRAME_RATE`: default `24`
- `RUNPOD_VIDEO_EXECUTION_TIMEOUT_MS`: default `1800000`
- `RUNPOD_VIDEO_TTL_MS`: default `7200000`
- `RUNPOD_VIDEO_REFERENCE_IMAGE_MAX_BYTES`: default `6000000`
- `RUNPOD_VIDEO_SIGNED_URL_TTL_SECONDS`: default `3600`
- `RUNPOD_VIDEO_COST_PER_SECOND_USD`: optional log-only estimate rate, default `0`

Runpod worker contract:

- deploy a queue-based Serverless endpoint that accepts `/run` and `/status/{job_id}`
- the endpoint ID setting is the plain Runpod endpoint ID, not the `/v2/.../run` URL path
- request input is `prompt`, `model`, `width`, `height`, `num_frames`, `frame_rate`, optional `pipeline`, optional two-stage `num_inference_steps`, optional `seed`, and optional reference-image fields such as `image_base64` and `image_strength`
- the bot keeps Runpod-specific sizing and quality parameters separate from the Gemini-backed default video path
- for LTX, `num_frames` is snapped to the nearest valid `8k+1` frame count at or above the requested duration
- completed output may include a direct URL such as `video_url`, or LTX durable-upload metadata under `s3.bucket`, `s3.key`, and `s3.endpoint_url`
- for GCS-backed `s3` output, the bot signs the derived `gs://bucket/key` URL transiently, downloads it for Telegram delivery, and persists only the durable `gs://` URI
- the bot does not persist raw video, signed URLs, or reference-image bytes in SQLite

Observability notes:

- usage and cost estimate fields are emitted through normal application logs
- local logs default to readable text; production can set `APP_LOG_FORMAT=json` for one JSON object per line
- successful low-level `httpx` and `httpcore` request logs are suppressed below `WARNING`
- repeated video-job polling for still-running jobs is logged at `DEBUG`, while queueing, completion, delivery, and failure events stay visible at `INFO` or `WARNING`
- cost estimates are disabled by default and are not billing reconciliation
- keep the estimate rates current in configuration when provider pricing changes

The complete environment contract lives in [app/config.py](app/config.py).

## Running Modes

Polling mode:

- default mode
- starts Telegram polling inside the FastAPI lifespan
- best fit for local development and the current repo shape

Webhook mode:

- set `APP_UPDATE_MODE=webhook`
- set `TELEGRAM_WEBHOOK_URL` to the public HTTPS endpoint that Telegram can reach
- set `TELEGRAM_WEBHOOK_SECRET_TOKEN`; Telegram sends it back in `X-Telegram-Bot-Api-Secret-Token`
- startup registers the webhook with Telegram before readiness turns healthy
- POST updates to `/telegram/webhook`
- keeps the same normalized processing path as polling

Health endpoints:

- `GET /healthz`
- `GET /readyz`

## Docker

Build:

```bash
docker build -t tg-bot .
```

Run:

```bash
docker run --rm \
  --env-file .env \
  -p 8000:8000 \
  -v "$(pwd)/data:/app/data" \
  tg-bot
```

The container entrypoint prepares the parent directory of `SQLITE_PATH` at runtime,
then drops privileges to the `app` user before starting Uvicorn. This matters for
Railway volumes because the mounted filesystem appears after the image is built.
For a Railway volume mounted at `/app/volume`, set:

```dotenv
SQLITE_PATH=/app/volume/data/bot.db
```

## Bot Commands

- `/start`: show the bot overview
- `/help`: list supported commands and message types
- `/status`: show update mode, configured models, and memory status
- `/reset`: archive the current conversation and start a fresh one
- `/settings`: choose per-chat/per-user video, image, and chat settings with inline buttons
- `/image <prompt>`: generate one image through Gemini
- `/video <prompt>`: queue one short video through the configured providers (Gemini, Runpod, or Fal), with safety-only fallback based on provider order

Reference-image commands:

- send one photo with caption `/image <prompt>` to use that photo as the image-generation reference; this path requires a Gemini image model
- send one photo with caption `/video <prompt>` to queue an image-to-video job using that photo as the first-frame reference
- reply to any Telegram photo with text `/image <prompt>` or `/video <prompt>` to use the replied photo as the reference image
- send one photo with any other caption to keep using the normal OpenAI image-understanding path

Settings presets:

- `/settings` stores preferences per `chat_id` and `user_id`; missing preferences use the environment defaults
- video settings can independently choose provider, Fal model family (when multiple families are configured), duration, and aspect ratio/orientation
- Runpod settings can choose LTX pipeline, two-stage quality, fixed or random seed, and reference-image strength
- image presets can choose the image model, aspect ratio, and output MIME type
- chat presets can choose creativity, response length, and memory depth
- secrets, endpoint IDs, storage paths, checkpoint paths, LoRA paths, offload/quantization/compile controls, and infrastructure timeouts remain environment-only

## Testing

Run the test suite:

```bash
uv run pytest
```

The repository already includes tests for health and readiness, normalization, allowlist handling, history reuse, reset behavior, draft streaming and fallback, Telegram formatting, image generation, reference-image command captions and reply-to-photo commands, video job handling, Gemini provider flows, Runpod provider flows, Fal provider flows, video provider routing, Fal family settings, and runtime callback validation.

## Project Layout

```text
app/
  api/
  domain/
  providers/
  storage/
  telegram/
  workers/
  config.py
  main.py
docs/
tests/
Dockerfile
pyproject.toml
uv.lock
```

## Notes For Future Work

- distributed workers and external job queues are out of scope today
- per-user/per-chat quotas, daily media budget caps, prompt/reference-image moderation gates, and in-app provider-output URL retention/expiry handling were deferred out of completed Phase 4 and remain future work unless the roadmap changes
- Fal-hosted video provider support is accepted as complete and merged into `dev` for `Phase 6 - Fal Video Provider Support`, with Kling, Seedance, and Gemini Omni Flash model families available behind the existing queued `/video` path and per-family selection in `/settings`
- Phase 5 ElevenLabs Hindi text-to-speech remains in progress in a separate worktree
