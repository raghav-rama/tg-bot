# Telegram Bot Architecture - Phase 3

## Summary

This document defines Phase 3 only.

Phase 3 adds explicit video generation to the existing private bot. A user can send `/video <prompt>`, the bot queues a long-running Vertex Veo operation, polls the operation in the background, sends a completion message when the result is ready, delivers the final asset through Telegram `sendVideo`, and stores job plus delivery metadata without persisting raw video bytes in SQLite.

This is an asynchronous product-scope phase. It does not reuse the Phase 1 or Phase 2 synchronous request shape because Veo generation is operation-based and can outlive the original Telegram update handler.

## Source-Grounded API Facts

The Phase 3 design assumes these currently documented facts:

- the Google Gen AI Python SDK exposes `client.models.generate_videos(...)` and returns a long-running operation object
- the same SDK exposes `client.operations.get(operation)` for polling long-running video generation status
- the current Vertex AI Veo docs show text-to-video generation as an operation flow rather than a single synchronous response
- Telegram Bot API `sendVideo` accepts uploaded files and returns a `Message` containing a `video` object on success
- Telegram Bot API currently states that bots can send video files of up to 50 MB on the hosted Bot API service
- `aiogram` exposes `await bot.send_video(...)` and supports in-memory uploads through `BufferedInputFile`

## Goal

Let an allowed user request a short generated video and receive it later without blocking the normal chat or image paths.

## In Scope

- explicit `/video <prompt>` command flow
- one queued text-to-video job per request
- Vertex AI video generation through the Python `google-genai` SDK
- SQLite-backed job persistence with statuses such as `queued`, `running`, `completed`, and `failed`
- an in-process polling worker that checks long-running operations and performs follow-up delivery
- Telegram `sendVideo` delivery using generated video bytes
- delivery metadata persistence and user-safe failure handling

## Explicitly Out Of Scope

- image-to-video generation
- video extension flows
- public or group-chat rollout
- multi-video batches
- storing raw video bytes in SQLite
- distributed workers or external job queues
- changing the existing OpenAI chat, draft-streaming, or `/image` behavior

## Phase 3 Initial Decisions

Phase 3 starts with a deliberately small async slice.

- `/video` submits one text-to-video Veo operation and immediately returns a queued acknowledgement
- the application runs one in-process polling worker alongside the existing FastAPI plus Telegram runtime
- video job rows live in SQLite so they survive process restarts
- generated assets stay outside SQLite; SQLite stores only operation state, source URI, and Telegram delivery metadata
- the first implementation accepts either inline video bytes from Vertex or a URI-backed asset that can be fetched later
- Telegram delivery remains transport-only: the worker fetches deliverable bytes, then the Telegram adapter sends the final video

## Architecture Delta From Phase 2

Phase 3 adds a second asynchronous media path alongside the existing synchronous `/image` flow.

### Domain service

Add a dedicated `/video` command flow inside the chat service orchestration.

Responsibilities:

- validate `/video` prompt presence
- persist the user command and immediate acknowledgement
- submit a video-generation operation through a dedicated provider interface
- create a persisted job row for later polling

### Worker

Add a background polling worker owned by the application runtime.

Responsibilities:

- load queued or running jobs from SQLite
- poll Vertex operation state
- mark jobs as `running`, `completed`, or `failed`
- send follow-up text status and final video delivery through the Telegram response emitter

### Provider layer

Keep OpenAI chat, Vertex image generation, and Vertex video generation as separate provider interfaces.

- `AIProvider` remains the text and text-plus-image understanding path
- `ImageGenerator` remains the Phase 2 image-generation path
- `VideoGenerator` becomes the Phase 3 queued video-generation path

### Storage

Phase 3 introduces a jobs table instead of widening the existing `generated_images` table.

The Phase 3 job store keeps:

- conversation and chat linkage
- prompt text
- provider and model
- operation name
- status
- output asset URI
- Telegram delivery metadata
- failure reason
- timestamps for created, updated, and completed states

Do not store:

- raw video bytes
- large provider payloads
- transient draft text

## Runtime Behavior

### Happy path

1. User sends `/video <prompt>`.
2. The normalizer marks it as a command and keeps the full text.
3. The chat service extracts the prompt, submits a Vertex operation, persists a queued job, and replies immediately with a short acknowledgement.
4. The background worker polls the long-running operation.
5. When the operation completes, the worker downloads the generated asset, sends a completion message, and delivers the final video through `sendVideo`.
6. The worker persists final delivery metadata and marks the job completed.

### Missing prompt

If the user sends `/video` with no prompt:

- do not call Vertex
- return a short usage message
- persist it as a command exchange

### Submission failure

If Vertex rejects the initial request:

- log the failure with provider and model context
- return a short retry-later message
- do not create a job row

### Polling failure

If the background poll later fails or the operation returns an error:

- mark the job failed
- log the failure with operation context
- send a short user-safe failure message

### Delivery failure

If Telegram video delivery fails:

- keep the failed job visible in persistence
- send a short user-safe failure message when possible
- do not mark the job completed
- log the concrete Telegram exception type and message so upload timeouts and API validation failures can be distinguished during debugging

## Environment Contract

Phase 3 keeps the earlier settings and adds:

- `VERTEX_VIDEO_MODEL`
- `VERTEX_VIDEO_ASPECT_RATIO`
- `VERTEX_VIDEO_DURATION_SECONDS`
- `VERTEX_VIDEO_OUTPUT_GCS_URI`
- `BOT_VIDEO_MAX_BYTES`
- `TELEGRAM_VIDEO_REQUEST_TIMEOUT_SECONDS`
- `VIDEO_JOB_POLL_INTERVAL_SECONDS`

Initial implementation notes:

- `VERTEX_VIDEO_OUTPUT_GCS_URI` is optional; when omitted, the provider prefers inline video bytes returned by Vertex
- when Vertex only returns a `gs://` asset URI, the provider can fetch the result later from Cloud Storage
- Telegram video uploads should use a request timeout above the aiogram default `60s` when larger generated assets are expected, because Telegram may finish delivery after the client-side timeout window closes

## Exit Criteria

Phase 3 is done when:

- an allowed user can request a short video and receive a completion message plus the final asset
- long-running generation does not block normal chat processing
- failed video jobs are visible in logs and user-visible status
- storage cleanup rules exist for generated video files
