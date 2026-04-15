# Telegram Bot Architecture - Phase 2

## Summary

This document defines Phase 2 only.

Phase 2 adds explicit image generation to the existing private bot. A user can send `/image <prompt>`, the bot generates one image through Vertex AI, sends it back to Telegram with `sendPhoto`, and stores prompt plus delivery metadata without persisting raw image bytes.

This is a product-scope phase. It widens outbound behavior from text-only replies to text plus generated image replies, while keeping the existing OpenAI chat flow intact.

## Source-Grounded API Facts

The Phase 2 design assumes these currently documented facts:

- Telegram Bot API `sendPhoto` returns a `Message` on success.
- `aiogram` exposes `await bot.send_photo(...)` and supports in-memory uploads through `BufferedInputFile`.
- the returned Telegram `Message` includes `photo` sizes with `file_id` and `file_unique_id`, which can be stored for later reference
- the Google Gen AI Python SDK supports Vertex AI client initialization with `genai.Client(vertexai=True, project=..., location=...)`
- the current Vertex AI docs also support API-key authentication for testing, and Google recommends API keys for testing while recommending ADC for production
- the Google Gen AI Python SDK exposes a dedicated `client.models.generate_images(...)` path for Imagen models
- current Vertex AI docs note that Gemini image generation uses `client.models.generate_content(...)` with mixed `TEXT` plus `IMAGE` output, while Imagen has a dedicated image-generation API

## Goal

Let an allowed user request a generated image and receive it in Telegram without changing the normal OpenAI chat path.

## In Scope

- explicit `/image <prompt>` command flow
- one generated image per request
- Vertex AI image generation through the Python `google-genai` SDK
- Telegram `sendPhoto` delivery using in-memory bytes
- SQLite persistence of prompt metadata and Telegram file references
- user-safe failure handling for generation and delivery issues

## Explicitly Out Of Scope

- generated video replies
- public or group-chat rollout
- image editing or multi-image batches
- raw image-byte persistence in SQLite
- object storage for generated assets
- changing the existing OpenAI chat and image-understanding flow

## Current Phase 2 Implementation Choice

Phase 2 defaults to Imagen on Vertex AI and also supports Gemini image models through a separate preview path.

Reasons:

- the current Python SDK exposes a direct `generate_images` API for Imagen
- the first milestone needs one image per prompt, not conversational mixed-modality output
- Telegram delivery only needs image bytes, not combined text plus image parts
- current Vertex docs describe Gemini image generation as preview, which is a weaker default for the first production-oriented image milestone
- `gemini-3-pro-image-preview` uses the `generate_content` path and requires the `global` Vertex location

This keeps Imagen as the default while allowing explicit Gemini image-model configuration when needed.

## Architecture Delta From Phase 1.5

Phase 2 keeps the same major layers and adds one new provider path plus one new outbound transport path.

### Domain service

Add a dedicated image-generation command flow inside the chat service orchestration.

Responsibilities:

- validate `/image` prompt presence
- persist the user command as command history
- call the image-generation provider through a separate interface from OpenAI chat
- route the generated image through the response emitter
- persist generated-image metadata after Telegram delivery

### Provider layer

Keep OpenAI chat and Vertex image generation as separate provider interfaces.

- `AIProvider` remains the text and text-plus-image understanding path
- `ImageGenerator` becomes the Phase 2 image-generation path
- the Vertex implementation should return normalized image bytes plus provider metadata

### Telegram adapter

The Telegram adapter stays transport-only.

Responsibilities:

- convert generated image bytes into `BufferedInputFile`
- send the image through `sendPhoto`
- return the sent Telegram file metadata to the domain layer

### Storage

Do not widen the existing `messages` table into a raw media store.

Phase 2 persistence should keep:

- the user `/image ...` command in `messages`
- a lightweight assistant event row with `message_type="generated_image"`
- generated image metadata in a separate `generated_images` table

Store:

- prompt text
- provider name
- model name
- MIME type
- Telegram message ID
- Telegram `file_id`
- Telegram `file_unique_id`
- width and height
- Telegram-reported file size

Do not store:

- raw image bytes
- base64 output
- large provider response payloads

## Runtime Behavior

### Happy path

1. User sends `/image <prompt>`.
2. The normalizer marks it as a command and keeps the full text.
3. The chat service extracts the prompt and persists the user command.
4. The Vertex image provider generates one image.
5. The Telegram response emitter sends the image through `sendPhoto`.
6. The service persists generated-image metadata.
7. No draft streaming is involved in this path.

### Missing prompt

If the user sends `/image` with no prompt:

- do not call Vertex
- return a short usage message
- persist it as a command exchange

### Provider failure

If Vertex generation fails:

- log the failure with provider and model context
- return a short retry-later message
- do not write generated-image metadata

### Delivery failure

If Telegram photo delivery fails:

- surface a safe generic failure message
- do not claim success in persistence

## Environment Contract

Phase 2 keeps the Phase 1 and Phase 1.5 settings and adds:

- `VERTEX_API_KEY`
- `VERTEX_PROJECT_ID`
- `VERTEX_LOCATION`
- `VERTEX_IMAGE_MODEL`
- `VERTEX_IMAGE_ASPECT_RATIO`
- `VERTEX_IMAGE_OUTPUT_MIME_TYPE`

Authentication options:

- for local testing, prefer `VERTEX_API_KEY`
- for production-oriented deployments, ADC remains the safer default

When both are present, the app may prefer the explicit API key path for image generation.

Model routing notes:

- Imagen models continue to use the dedicated `generate_images` path.
- Gemini image models use `generate_content` and return mixed text plus image parts; the bot currently extracts the first returned image and ignores any Gemini text part.
- `gemini-3-pro-image-preview` requires `VERTEX_LOCATION=global`.

## Exit Criteria

Phase 2 is done when:

- an allowed user can request an image with a prompt and receive it in Telegram
- generation failures return a clear user-safe message
- generated-image metadata is traceable in logs and persistence
- the OpenAI chat flow still works unchanged
