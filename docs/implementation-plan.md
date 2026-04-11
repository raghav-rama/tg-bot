# Implementation Plan

## Summary

This document translates the agreed architecture into a concrete build order for the code phase. The goal is to implement a private `Python + FastAPI` Telegram bot with SQLite-backed memory, OpenAI-backed replies, polling-first execution, and text plus single-image support.

## Recommended Dependencies

Primary packages:

- `fastapi`
- `uvicorn`
- `aiogram`
- `openai`
- `pydantic-settings`
- `aiosqlite`
- `httpx`

Optional packages:

- `pytest`
- `pytest-asyncio`
- `anyio`

## Build Order

### 1. Bootstrap the application shell

Create the FastAPI app, configuration layer, and startup lifecycle.

Deliverables:

- settings object backed by environment variables
- `GET /healthz`
- `GET /readyz`
- startup hook for database initialization
- startup hook for Telegram polling when `APP_UPDATE_MODE=polling`

Acceptance:

- the app starts with valid env vars
- readiness fails when required env vars are missing

### 2. Implement storage

Add SQLite initialization and repositories for conversations and messages.

Deliverables:

- schema creation on startup
- active conversation lookup per chat
- conversation reset operation
- append-only message persistence
- recent-history query limited by `BOT_HISTORY_MAX_TURNS`

Acceptance:

- a new chat gets a new active conversation
- `/reset` archives the old conversation and creates a new one
- stored history can be reloaded after restart

### 3. Implement Telegram normalization

Build the Telegram-facing layer that converts updates into normalized internal models.

Deliverables:

- support for text messages
- support for commands
- support for one photo message with optional caption
- image download helper using Telegram file APIs
- unsupported-message detection

Acceptance:

- supported payloads are normalized consistently
- unsupported payloads fail safely without process crashes

### 4. Implement the chat service

Add the domain service that coordinates access control, commands, memory, persistence, and provider calls.

Deliverables:

- allowlist gate using `TELEGRAM_ALLOWED_USER_IDS`
- command handling for `/start`, `/help`, `/status`, `/reset`
- provider request assembly from system prompt, history, and current input
- assistant reply persistence
- typed error mapping to user-safe messages

Acceptance:

- disallowed users never trigger provider calls
- commands bypass provider execution except `/status` data lookup
- memory is included for normal chat messages

### 5. Implement the OpenAI provider adapter

Add the provider interface and the single concrete OpenAI implementation.

Deliverables:

- text-only request support
- text-plus-image request support
- normalized `ProviderResponse`
- timeout and upstream error translation

Acceptance:

- text requests return plain assistant text
- image requests include the caption when present
- provider failures do not produce stack traces in user replies

### 6. Wire delivery to Telegram replies

Connect the polling loop and handlers to the chat service and send replies back to Telegram.

Deliverables:

- incoming updates routed through one shared service
- bot replies posted to the correct chat
- structured logging around update processing

Acceptance:

- an allowed user can send a message and receive a reply end-to-end
- logs contain `chat_id`, `user_id`, `message_type`, and error classification

## Suggested Environment Contract

Required:

- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`
- `TELEGRAM_ALLOWED_USER_IDS`

Recommended:

- `APP_UPDATE_MODE`
- `APP_LOG_LEVEL`
- `SQLITE_PATH`
- `OPENAI_MODEL`
- `OPENAI_TEMPERATURE`
- `OPENAI_MAX_OUTPUT_TOKENS`
- `BOT_SYSTEM_PROMPT`
- `BOT_HISTORY_MAX_TURNS`
- `BOT_IMAGE_MAX_BYTES`

## Test Plan

### Unit tests

- normalize a text update into `InboundMessage`
- normalize a photo update into `InboundMessage`
- reject unsupported payload types
- build provider context from recent stored turns
- `/reset` archives the active conversation and creates a fresh one
- allowlist rejection prevents provider invocation

### Integration tests

- text message flow from normalized input to stored assistant reply
- image message flow with caption
- restart-and-recover flow using the same SQLite database
- provider timeout flow returns the standard retry message

### Manual verification

- start the service locally with polling enabled
- send `/start`, `/help`, `/status`, and `/reset`
- send a plain text prompt
- send a single image with caption
- restart the process and confirm conversation memory still works

## Default Decisions

- update mode starts as `polling`
- allowlist is environment-driven, not database-driven
- SQLite is the only persistence store in v1
- only one active conversation exists per chat
- history window defaults to the last 20 turns
- only text and single-image messages are supported
- OpenAI is the only concrete provider in v1

## Out of Scope for This Build

- webhook production deployment
- public bot exposure
- voice transcription
- media groups
- admin interfaces
- provider switching UI or runtime routing
