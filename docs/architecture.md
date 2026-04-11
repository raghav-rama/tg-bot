# Telegram Bot Architecture

## Summary

This project is a private Telegram bot for a YouTube channel workflow. It accepts text and image messages from approved Telegram users, sends the request to OpenAI, stores conversation memory in SQLite, and returns an assistant reply back to Telegram.

The service shell is `FastAPI`. The initial runtime mode is polling, but the application structure must keep Telegram ingestion separate from business logic so webhook delivery can be added later without rewriting handlers or provider code.

## Goals

- Ship a small, understandable v1.
- Keep the bot private through a fixed allowlist.
- Preserve per-chat memory across restarts.
- Support text messages and single-image messages with optional captions.
- Isolate OpenAI behind a narrow provider interface so another provider can be added later.

## Non-Goals

- Public bot usage
- Voice notes, video, files, stickers, or media groups
- Admin panel or database-backed allowlist management
- Multi-provider orchestration in v1
- Retrieval, search, or external workflow automation beyond reply generation

## Runtime Model

### Initial delivery mode

- Default update mode: `polling`
- Future-compatible mode: `webhook`
- Polling is started in the application lifespan on process startup.
- Webhook support is reserved behind a FastAPI route and must use the same normalized update pipeline as polling.

### Service responsibilities

`FastAPI` is responsible for:

- process startup and shutdown
- health and readiness endpoints
- configuration loading
- database initialization
- starting the Telegram polling task in polling mode
- hosting the future webhook endpoint

`Telegram adapter` is responsible for:

- receiving updates from Telegram
- validating that the update contains a supported message
- downloading image bytes for supported photo messages
- normalizing Telegram-specific payloads into internal message models

`Chat service` is responsible for:

- access checks
- command handling
- memory loading and trimming
- provider request construction
- persistence of user and assistant messages
- mapping errors into safe user-facing replies

`OpenAI provider adapter` is responsible for:

- translating internal request models into OpenAI API calls
- handling text-only and text-plus-image requests
- returning normalized reply data and usage metadata

`SQLite storage` is responsible for:

- conversation persistence
- message history persistence
- reset semantics
- lightweight state lookup needed by the chat service

## Recommended Project Layout

This layout should be used when code implementation starts:

```text
app/
  main.py
  config.py
  api/
    health.py
    webhook.py
  telegram/
    polling.py
    handlers.py
    normalizer.py
    media.py
  domain/
    models.py
    commands.py
    services.py
  providers/
    base.py
    openai_provider.py
  storage/
    db.py
    conversations.py
    messages.py
tests/
docs/
```

## Internal Interfaces

### Normalized inbound message

Every supported Telegram update must be transformed into this internal shape before business logic runs:

```python
class InboundMessage(TypedDict):
    update_id: int
    telegram_message_id: int
    chat_id: int
    user_id: int
    username: str | None
    first_name: str | None
    message_type: Literal["text", "image", "command"]
    text: str | None
    command: str | None
    image: "ImageInput | None"
    sent_at: datetime
```

```python
class ImageInput(TypedDict):
    telegram_file_id: str
    telegram_file_unique_id: str
    mime_type: str
    width: int
    height: int
    byte_size: int
    bytes_b64: str
    caption: str | None
```

Rules:

- `message_type="text"` is used for non-command text messages.
- `message_type="command"` is used for `/start`, `/help`, `/reset`, `/status`.
- `message_type="image"` is used only for one photo plus optional caption.
- Telegram media groups are out of scope and must return an unsupported message reply.
- For photo messages, use the largest photo variant returned by Telegram.

### Provider request

The chat service calls exactly one provider entrypoint:

```python
class ProviderRequest(TypedDict):
    chat_id: int
    user_id: int
    system_prompt: str
    history: list["ConversationTurn"]
    user_message: str | None
    image: ImageInput | None
    model: str
    temperature: float
    max_output_tokens: int
```

```python
class ConversationTurn(TypedDict):
    role: Literal["user", "assistant"]
    text: str
    created_at: datetime
```

Notes:

- `history` is reconstructed from SQLite.
- `user_message` may be empty for pure image messages with no caption.
- `image.bytes_b64` is passed to the provider adapter, which converts it into the OpenAI multimodal input format.

### Provider response

```python
class ProviderResponse(TypedDict):
    reply_text: str
    provider_message_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    finish_reason: str | None
    raw_model: str | None
```

### Command handling

Commands are handled in the chat service, not in Telegram-specific code.

- `/start`: greet the user and explain supported inputs.
- `/help`: list supported commands and supported message types.
- `/status`: show service mode, configured model, and whether memory is enabled.
- `/reset`: archive the active conversation for that chat and start a new empty one.

## Persistence Design

### Allowlist source

The v1 allowlist lives in configuration, not in the database.

- Environment variable: `TELEGRAM_ALLOWED_USER_IDS`
- Format: comma-separated Telegram user IDs
- Access decision: deny any user whose `user_id` is not in the configured set

### SQLite tables

Use SQLite for v1 persistence. The schema should be simple and append-friendly.

#### `conversations`

One active conversation per Telegram chat.

Columns:

- `id` integer primary key
- `chat_id` integer not null
- `started_at` text not null
- `updated_at` text not null
- `archived_at` text null
- `is_active` integer not null default `1`

Rules:

- A chat may have multiple archived conversations.
- Exactly one row per chat is active at a time.
- Enforce the active-conversation rule with an application check plus a unique partial index on active rows.
- `/reset` marks the current row inactive and creates a new active row.

#### `messages`

Stores both user and assistant turns.

Columns:

- `id` integer primary key
- `conversation_id` integer not null
- `telegram_message_id` integer null
- `provider_message_id` text null
- `role` text not null
- `message_type` text not null
- `text` text null
- `image_file_unique_id` text null
- `image_mime_type` text null
- `image_width` integer null
- `image_height` integer null
- `image_byte_size` integer null
- `created_at` text not null

Rules:

- `role` is `user` or `assistant`.
- `message_type` is `text`, `image`, `command`, or `system`.
- Only user rows may contain image metadata.
- Assistant rows store the final reply text only.

### Memory policy

- Persist every accepted user message and every assistant reply.
- Build provider context from the active conversation only.
- Default context window: last 20 persisted user/assistant turns plus the system prompt.
- Commands are not sent to the provider.
- `/reset` starts a new conversation and prevents older turns from being included in future context.

## OpenAI Integration

### Provider strategy

- v1 implements only one concrete adapter: `OpenAIProvider`.
- All Telegram and domain code depend on the provider interface, not the OpenAI SDK directly.

### Request policy

- Text-only messages use a text generation request.
- Image messages use a multimodal request with:
  the optional caption text and the downloaded image content.
- The bot should reject unsupported file types before calling OpenAI.

### Prompting

Use a configurable system prompt with a default focused on channel-assistant behavior:

- help brainstorm content and titles
- answer clearly and concisely
- avoid unsafe or policy-sensitive outputs
- ask a brief follow-up question when the user request is under-specified

The system prompt must be configurable through environment variables so it can be tuned without code changes.

## Configuration

Use environment-driven configuration loaded once at startup.

Required variables:

- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`
- `TELEGRAM_ALLOWED_USER_IDS`

Recommended variables:

- `APP_ENV`
- `APP_LOG_LEVEL`
- `APP_UPDATE_MODE`
- `SQLITE_PATH`
- `OPENAI_MODEL`
- `OPENAI_TEMPERATURE`
- `OPENAI_MAX_OUTPUT_TOKENS`
- `BOT_SYSTEM_PROMPT`
- `BOT_HISTORY_MAX_TURNS`
- `BOT_IMAGE_MAX_BYTES`

Defaults:

- `APP_UPDATE_MODE=polling`
- `SQLITE_PATH=./data/bot.db`
- `BOT_HISTORY_MAX_TURNS=20`
- `BOT_IMAGE_MAX_BYTES=10485760`

## FastAPI Surface

The FastAPI app should expose:

- `GET /healthz`
  Returns `200` when the process is alive.
- `GET /readyz`
  Returns `200` when configuration is valid, the database is reachable, and the bot runtime has initialized.
- `POST /telegram/webhook`
  Reserved for future webhook mode. In v1 polling deployments this route may exist but remain unused.

Response bodies can stay minimal JSON:

```json
{"ok": true}
```

## Error Handling

Map failures into a small set of internal error classes:

- `UnauthorizedUserError`
- `UnsupportedMessageError`
- `ValidationError`
- `ProviderTimeoutError`
- `ProviderUpstreamError`
- `StorageError`

User-facing behavior:

- unauthorized user: no provider call, send a short access-denied message
- unsupported message: explain supported inputs
- provider timeout or upstream issue: apologize briefly and ask the user to retry
- internal/storage issue: send a generic failure message and log the incident

## Logging and Observability

Use structured logs with these fields when available:

- `update_id`
- `chat_id`
- `user_id`
- `conversation_id`
- `command`
- `message_type`
- `provider`
- `model`
- `latency_ms`
- `error_type`

Do not log raw image bytes or API keys. User text should only be logged at debug level, and image captions should follow the same rule.

## Security Notes

- The bot is private by default through the fixed allowlist.
- Secrets must only come from environment variables.
- Reject oversized images before provider invocation.
- Avoid storing full binary images in SQLite; only persist metadata and keep base64 image content in memory for the active request.
- Keep the webhook route disabled in production until signature and deployment details are finalized.
