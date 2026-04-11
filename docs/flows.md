# Telegram Bot Flows - Phase 1

## Summary

This document defines the Phase 1 runtime behavior for supported user actions, command handling, error paths, and the difference between polling and webhook ingestion.

All flows end in the same normalized message pipeline so delivery mode does not affect business logic.

Planned post-Phase-1 flows, including Google Gemini / Vertex AI image and video generation, are tracked in [roadmap.md](roadmap.md).

## Core Processing Pipeline

Every accepted update follows this sequence:

1. Receive Telegram update.
2. Normalize the update into `InboundMessage`.
3. Check user allowlist.
4. Route commands directly to the command handler.
5. For chat messages, validate message type and payload size.
6. Load the active conversation from SQLite.
7. Build the provider request from the system prompt, trimmed history, and current user input.
8. Call the provider adapter.
9. Persist the user turn and assistant turn.
10. Send the assistant reply back to Telegram.

Phase 1 assumes a text reply back to Telegram even when the inbound message includes an image.

## Text Message Flow

### Scenario

An allowed user sends a plain text message.

### Sequence

1. Telegram delivers the update.
2. The Telegram adapter extracts:
   `chat_id`, `user_id`, `telegram_message_id`, and `text`.
3. The normalizer emits `message_type="text"`.
4. The chat service confirms the user is on the allowlist.
5. The conversation repository returns the active conversation for the chat, or creates one if none exists.
6. The message repository loads the last `BOT_HISTORY_MAX_TURNS` persisted turns for that conversation.
7. The provider adapter receives the system prompt, trimmed history, and current text.
8. OpenAI returns the assistant reply.
9. The service stores:
   one user `messages` row and one assistant `messages` row.
10. The Telegram adapter sends the reply text back to the same chat.

### Acceptance criteria

- Memory from prior turns is included.
- A new chat automatically starts a new conversation.
- Empty text messages are rejected before provider invocation.

## Image Message Flow

### Scenario

An allowed user sends one image with an optional caption.

### Sequence

1. Telegram delivers a photo update.
2. The Telegram adapter selects the largest photo size.
3. The media helper fetches the file bytes from Telegram.
4. The bytes are checked against `BOT_IMAGE_MAX_BYTES`.
5. The bytes are encoded to base64 for the current request only.
6. The normalizer emits `message_type="image"` with `ImageInput`.
7. The chat service loads the active conversation and recent turns.
8. The provider adapter sends a multimodal request to OpenAI using:
   caption text if present and the image content.
9. The reply is persisted and returned to Telegram.

### Acceptance criteria

- The image request uses the active conversation memory.
- The image itself is not stored in SQLite.
- The stored user row keeps only image metadata, not raw bytes.
- A missing caption is allowed.
- The outbound reply remains text-only in Phase 1.

## Unauthorized User Flow

### Scenario

A Telegram user not present in `TELEGRAM_ALLOWED_USER_IDS` sends any message.

### Sequence

1. Telegram delivers the update.
2. The message is normalized.
3. The access check fails.
4. No database write is required.
5. No provider call is made.
6. The bot replies with a short denial message.

### Acceptance criteria

- OpenAI is never called.
- The denial response is deterministic and short.
- Logs include the rejected `user_id`.

## Unsupported Message Flow

### Scenario

The user sends a voice note, sticker, video, file, media group, or another unsupported type.

### Sequence

1. Telegram delivers the update.
2. The adapter identifies the payload as unsupported.
3. The service returns a standard message explaining that only text and single-image messages are supported.
4. No provider call is made.

### Acceptance criteria

- Unsupported inputs do not crash the polling loop.
- The reply is stable and user-readable.

## Command Flows

### `/start`

Behavior:

- greet the user
- explain the bot is private and memory-enabled
- list supported inputs: text and one image with optional caption

### `/help`

Behavior:

- list supported commands
- explain what `/reset` does
- explain unsupported inputs

### `/status`

Behavior:

- report update mode
- report configured model name
- report whether memory is enabled
- do not reveal secrets or internal file paths

### `/reset`

Behavior:

1. Find the active conversation for the chat.
2. Mark it inactive and set `archived_at`.
3. Create a fresh active conversation row.
4. Reply with a confirmation message.

Acceptance criteria:

- Old history is excluded from future provider requests.
- The reset affects only the current chat.

## Provider Failure Flow

### Scenario

The provider times out or returns a recoverable upstream error.

### Sequence

1. The service has already validated the inbound message.
2. The provider adapter raises a typed error.
3. The service logs the error with context.
4. The user receives a short retry-later message.
5. No assistant row is stored for the failed call.

Recommended user-facing reply:

`I couldn't get a response from the AI service just now. Please try again in a moment.`

### Acceptance criteria

- The process stays healthy.
- The user is not shown stack traces or provider internals.
- The failed attempt is visible in logs.

## Storage Recovery Flow

### Scenario

The service restarts after prior conversations already exist in SQLite.

### Sequence

1. FastAPI startup initializes configuration and database connections.
2. The bot runtime starts.
3. On the next message in a chat, the conversation repository loads the active conversation row.
4. The message repository reconstructs the recent context from persisted rows.
5. The provider request resumes with the restored history.

### Acceptance criteria

- Memory survives process restart.
- No manual migration step is needed for normal restart.

## Polling vs Webhook Ingestion

### Polling mode

Used in v1.

1. FastAPI starts.
2. Lifespan startup creates the Telegram polling task.
3. The polling task reads updates from Telegram.
4. Each update is passed into the shared normalization and chat-service pipeline.

### Webhook mode

Reserved for later.

1. Telegram sends `POST /telegram/webhook`.
2. FastAPI parses the body and forwards it to the same normalization and chat-service pipeline.
3. The response can return quickly after enqueueing or processing, depending on deployment design.

### Design constraint

Delivery mode must not change:

- allowlist checks
- command behavior
- memory lookup
- provider requests
- persistence rules

## Validation Rules

Reject or short-circuit these cases before provider invocation:

- empty text messages
- images larger than `BOT_IMAGE_MAX_BYTES`
- media groups
- unsupported Telegram payload types
- messages from users outside the allowlist
- malformed updates missing required identifiers

## Deferred Flows

The following flows are intentionally excluded from this document and are tracked in [roadmap.md](roadmap.md):

- generated image replies
- generated video replies
- asynchronous generation jobs
- Google Gemini / Vertex AI provider flows
