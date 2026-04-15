# tg-bot

Private Telegram bot built with FastAPI, SQLite, OpenAI chat, and Vertex AI image/video generation.

## Status

The repository is currently in `Phase 3 - Vertex Video Generation`.

Implemented today:

- private, allowlisted Telegram bot
- polling-first runtime with a webhook path kept available
- SQLite-backed conversation memory and reset semantics
- text chat and single-photo understanding through OpenAI
- Telegram draft streaming for long-running text replies
- `/image <prompt>` generation through Vertex AI and Telegram `sendPhoto`
- `/video <prompt>` queued generation through Vertex AI, SQLite-backed jobs, background polling, and Telegram `sendVideo`
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
- commands: `/start`, `/help`, `/status`, `/reset`, `/image`, `/video`

Outbound outputs:

- normal text replies
- generated images through Telegram `sendPhoto`
- generated videos through Telegram `sendVideo`

Current constraints:

- the bot stays private through `TELEGRAM_ALLOWED_USER_IDS`
- draft streaming targets private text chats first
- image-understanding requests use the final-only reply path by default
- raw generated image and video bytes are not persisted in SQLite
- live Telegram and Vertex verification still depends on real credentials and manual runtime checks
- generated video storage cleanup is still an open Phase 3 task
- Gemini image models use a separate preview path from Imagen; `gemini-3-pro-image-preview` requires `VERTEX_LOCATION=global`

## Architecture At A Glance

The runtime is split so Telegram transport stays separate from domain and provider logic.

- `app/api/`: `healthz`, `readyz`, and reserved webhook ingestion
- `app/telegram/`: polling runtime, handlers, normalization, formatting, media delivery, and drafts
- `app/domain/`: commands, models, interfaces, and orchestration in `ChatService`
- `app/providers/`: OpenAI chat plus Vertex image and video adapters
- `app/storage/`: SQLite schema and repositories for conversations, messages, generated images, and generation jobs
- `app/workers/`: background polling worker for queued video jobs

## Requirements

- Python `>=3.10`
- `uv` for dependency management
- a Telegram bot token
- an OpenAI API key for chat replies
- Vertex configuration for `/image` and `/video`

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
SQLITE_PATH=./data/bot.db

# Optional OpenAI overrides
OPENAI_MODEL=gpt-4.1-mini
OPENAI_TEMPERATURE=0.2
OPENAI_MAX_OUTPUT_TOKENS=500
OPENAI_TIMEOUT_SECONDS=45

# Optional Vertex configuration for /image and /video
# For local testing, an API key is enough.
VERTEX_API_KEY=your-vertex-api-key

# For ADC / project-based auth, use these instead or in addition.
# VERTEX_PROJECT_ID=your-gcp-project-id
# VERTEX_LOCATION=us-central1
# For Gemini 3 Pro Image preview, set:
# VERTEX_IMAGE_MODEL=gemini-3-pro-image-preview
# VERTEX_LOCATION=global
```

3. Start the app:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

With `APP_UPDATE_MODE=polling`, FastAPI starts the Telegram polling runtime during application startup.

## Configuration

Core settings:

- `TELEGRAM_BOT_TOKEN`: required
- `OPENAI_API_KEY`: required
- `TELEGRAM_ALLOWED_USER_IDS`: required comma-separated Telegram user IDs
- `APP_UPDATE_MODE`: `polling` or `webhook`
- `APP_LOG_LEVEL`: default `INFO`
- `SQLITE_PATH`: default `./data/bot.db`

Chat settings:

- `BOT_SYSTEM_PROMPT`
- `BOT_HISTORY_MAX_TURNS`
- `BOT_IMAGE_MAX_BYTES`
- `OPENAI_MODEL`
- `OPENAI_TEMPERATURE`
- `OPENAI_MAX_OUTPUT_TOKENS`
- `OPENAI_TIMEOUT_SECONDS`

Draft streaming settings:

- `BOT_ENABLE_MESSAGE_DRAFTS`
- `BOT_DRAFT_STREAM_ON_IMAGES`
- `BOT_DRAFT_START_DELAY_MS`
- `BOT_DRAFT_UPDATE_INTERVAL_MS`
- `BOT_DRAFT_MIN_CHARS_DELTA`

Vertex image settings:

- `VERTEX_API_KEY`
- `VERTEX_PROJECT_ID`
- `VERTEX_LOCATION`
- `VERTEX_IMAGE_MODEL`
- `VERTEX_IMAGE_ASPECT_RATIO`
- `VERTEX_IMAGE_OUTPUT_MIME_TYPE`

Image model notes:

- Imagen remains the default `/image` model path and uses the dedicated Vertex `generate_images` API.
- Gemini image models are supported through the Vertex `generate_content` API.
- `gemini-3-pro-image-preview` requires `VERTEX_LOCATION=global`.

Vertex video settings:

- `VERTEX_VIDEO_MODEL`
- `VERTEX_VIDEO_ASPECT_RATIO`
- `VERTEX_VIDEO_DURATION_SECONDS`
- `VERTEX_VIDEO_OUTPUT_GCS_URI`
- `BOT_VIDEO_MAX_BYTES`
- `TELEGRAM_VIDEO_REQUEST_TIMEOUT_SECONDS`
- `VIDEO_JOB_POLL_INTERVAL_SECONDS`

The complete environment contract lives in [app/config.py](app/config.py).

## Running Modes

Polling mode:

- default mode
- starts Telegram polling inside the FastAPI lifespan
- best fit for local development and the current repo shape

Webhook mode:

- set `APP_UPDATE_MODE=webhook`
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

## Bot Commands

- `/start`: show the bot overview
- `/help`: list supported commands and message types
- `/status`: show update mode, configured models, and memory status
- `/reset`: archive the current conversation and start a fresh one
- `/image <prompt>`: generate one image through Vertex AI
- `/video <prompt>`: queue one short video through Vertex AI

## Testing

Run the test suite:

```bash
uv run pytest
```

The repository already includes tests for health and readiness, normalization, allowlist handling, history reuse, reset behavior, draft streaming and fallback, Telegram formatting, image generation, video job handling, and the Vertex provider flows.

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

- storage cleanup policy for generated video assets is still pending
- distributed workers and external job queues are out of scope today
- webhook-first deployment remains a later hardening step
