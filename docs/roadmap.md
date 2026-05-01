# Product Roadmap

## Purpose

This document separates the current repo state from the planned delivery phases.

- `architecture.md`, `flows.md`, and `implementation-plan.md` define the Phase 1 build only.
- `phase-1-5-draft-streaming.md` defines the Phase 1.5 draft-streaming work only.
- `phase-2-vertex-image-generation.md` defines the completed Phase 2 image-generation work only.
- `phase-3-vertex-video-generation.md` defines the completed Phase 3 video-generation work only.
- This roadmap tracks the broader direction, especially the later hardening and expansion work.

## Current Phase

- Active phase: `Phase 4 - Hardening And Expansion`
- Status: `in_progress`
- Last updated: `2026-04-15`
- Previous phase accepted: `Phase 3 - Vertex Video Generation`
- Evidence:
  - Phase 1 foundation work is accepted as complete for repo sequencing
  - Phase 1.5 draft streaming is accepted as complete and no longer blocks the next milestone
  - Phase 2 image generation is accepted as complete for repo sequencing
  - an explicit `/video` command path now exists alongside the existing OpenAI chat and `/image` flows
  - video generation now uses persisted `generation_jobs` rows plus a background polling worker instead of blocking the original request path
  - completed video jobs now deliver through Telegram `sendVideo`
  - video asset retention rules are now explicit: inline bytes stay transient in memory, while URI-backed outputs rely on external bucket lifecycle policy

## Current State

As of `2026-04-15`, this repository contains the completed Phase 1 foundation, the completed Phase 1.5 Telegram draft-streaming work, the completed Phase 2 image-generation slice, and the completed Phase 3 video-generation slice.

- Application code exists under `app/` for FastAPI startup, Telegram runtime wiring, SQLite persistence, domain services, OpenAI chat, and Vertex image plus video generation.
- A polling-first runtime exists, and webhook mode now reuses the same shared processing path when enabled.
- SQLite-backed conversation memory, command handling, allowlist checks, and text plus single-image inbound normalization are implemented.
- OpenAI response streaming, in-memory Telegram draft sessions, and per-chat supersession handling are implemented and accepted as complete for Phase 1.5.
- `/image <prompt>` now generates one image through Vertex AI and sends it back through Telegram `sendPhoto`.
- Generated-image metadata is stored in SQLite without persisting raw image bytes.
- `/video <prompt>` now submits one long-running Vertex video job, stores it in SQLite, and returns an immediate queued acknowledgement.
- An in-process polling worker now checks pending video jobs and delivers completed assets through Telegram `sendVideo`.
- Video job persistence stores operation state, output URIs, failure reasons, and Telegram delivery metadata without persisting raw video bytes in SQLite.
- Tests exist under `tests/` for health and readiness behavior, normalization, allowlist handling, memory reuse, reset semantics, draft streaming, draft fallback, supersession, Telegram formatting, image generation, video job submission, worker completion, worker failure handling, and the new Vertex video provider.
- Real Vertex and Telegram verification still depends on configured credentials and a manual runtime check.
- Inline generated video bytes remain transient in memory only, while URI-backed assets are expected to live in a bucket with lifecycle cleanup managed outside the app.
- Phase 4 has started with a real webhook deployment path: webhook mode now registers the Telegram webhook on startup, validates the `X-Telegram-Bot-Api-Secret-Token` header on inbound requests, and reports webhook setup state through readiness.

## Recommended Sequencing

Build this in order:

1. Land the smallest end-to-end bot first.
2. Add partial reply streaming with Telegram drafts next.
3. Add generated image output after draft streaming works.
4. Add generated video output only after image generation works.

This ordering keeps the first milestone small, then improves reply UX before introducing richer media.

## Phase 1 - Foundation

Status: `complete`

### Goal

Prove that the bot works end to end before adding generated media.

### In Scope

- FastAPI application shell
- polling-first Telegram runtime
- private-user allowlist
- SQLite-backed conversation memory
- commands: `/start`, `/help`, `/status`, `/reset`
- OpenAI provider adapter for text and text-plus-image understanding
- text replies back to Telegram
- health and readiness endpoints

### Explicitly Out of Scope

- generated image replies
- generated video replies
- Google Gemini / Vertex AI integration
- background jobs
- object storage for generated assets
- webhook-first production deployment

### Exit Criteria

Phase 1 is done when:

- an allowed user can send a text message and receive a reply
- an allowed user can send one image plus optional caption and receive a reply
- conversation memory survives restart
- unsupported messages fail safely
- `/reset` starts a fresh conversation without deleting prior history

## Phase 1.5 - Telegram Partial Reply Streaming

Status: `complete`

Dedicated planning doc: [phase-1-5-draft-streaming.md](phase-1-5-draft-streaming.md)

### Goal

Let the bot show partial assistant text in Telegram while a long reply is still being generated.

### Completed Scope

- use Telegram Bot API `sendMessageDraft` for partial reply updates
- keep the final assistant response as a normal text message
- add provider-side text streaming for the existing OpenAI path
- keep partial draft state in memory only
- degrade safely to final-only replies when draft streaming fails
- start with private text-input replies first; keep image-understanding replies on the final-only path by default

### Completion Notes

- Telegram draft update cadence now defaults to conservative thresholds because aggressive updates were shown to trigger per-chat flood control during live validation.
- Final Telegram replies now pass through a Telegram-specific formatter that converts a safe subset of model markdown into Telegram HTML.
- Phase completion assumes the remaining real-client draft cleanup question was resolved outside the repo and accepted for sequencing.

### Exit Criteria

Phase 1.5 is done when:

- an allowed private-chat user can see partial assistant text for a long-running reply
- the final assistant reply still arrives as a normal Telegram text message
- draft-send failures fall back cleanly to the Phase 1 final-only path
- no partial draft text is persisted in SQLite
- real Telegram clients confirm the draft disappears cleanly after final handoff

## Phase 2 - Vertex Image Generation

Status: `complete`

Dedicated planning doc: [phase-2-vertex-image-generation.md](phase-2-vertex-image-generation.md)

### Goal

Let the bot generate images and send them back to Telegram.

### Current Scope

- add a Google Gen AI / Vertex AI client path using the Python `google-genai` SDK
- keep chat flow separate from image-generation flow
- introduce an explicit bot entrypoint for image generation through `/image <prompt>`
- return one generated image per request first
- send generated output back through Telegram `sendPhoto`
- persist prompt metadata and generated asset references, not raw binary blobs in SQLite

### Design Notes

- Keep chat on OpenAI while image generation lives on Vertex AI.
- The current implementation keeps Imagen as the default path through the dedicated `generate_images` SDK path and also supports Gemini image models through `generate_content`.
- The implementation now supports a Vertex API key for testing and can still fall back to ADC when that key is not configured.
- This remains the default Phase 2 implementation choice: current official Vertex docs expose a straightforward Python image-generation API for Imagen, while Gemini image generation on Vertex AI uses mixed `TEXT` plus `IMAGE` output and remains a preview-oriented path.
- Telegram handler code should continue to normalize inbound updates and deliver outbound media only. Generation routing stays in the domain and provider layers.

### New Decisions Needed

- whether generated images should be reusable across chats by storing and reusing Telegram `file_id`
- whether successful `/image` generations should also write a richer assistant summary row into chat history
- whether Phase 2 should later widen from simple prompt-to-image into image editing or variation flows
- whether Gemini image generation should move from optional preview support into the default `/image` configuration later

### Exit Criteria

Phase 2 is done when:

- an allowed user can request an image with a prompt and receive it in Telegram
- generation failures return a clear user-safe message
- generated-image metadata is traceable in logs and persistence
- the OpenAI chat flow still works unchanged

## Phase 3 - Vertex Video Generation

Status: `complete`

Dedicated planning doc: [phase-3-vertex-video-generation.md](phase-3-vertex-video-generation.md)

### Goal

Let the bot generate short videos and deliver them back to Telegram.

### Why This Is A Separate Phase

Video generation should not be forced into the same synchronous shape as Phase 1 chat replies.

- Vertex Veo generation is an operation-based workflow and should be treated as asynchronous work.
- Telegram video delivery has tighter delivery and upload constraints than plain text replies.
- Generated video files will need stronger lifecycle management than text or transient image inputs.

### Completed Scope

- introduce a generation jobs table with statuses such as `queued`, `running`, `completed`, `failed`
- add a worker or polling loop for long-running Vertex operations
- introduce a dedicated entrypoint such as `/video`
- start with short text-to-video generation only
- store generated video assets outside SQLite and deliver them with Telegram `sendVideo`
- send follow-up status or completion messages instead of blocking the original request path

### Follow-Up Decisions

- local temporary storage vs GCS for generated video assets
- retry policy for failed or slow Veo operations
- maximum duration, resolution, and size limits for the first video milestone
- whether image-to-video belongs in the first video release or a later follow-up

### Exit Criteria

Phase 3 is done when:

- a user can request a short video and receive a completion message plus the final asset
- long-running generation does not block normal chat processing
- failed video jobs are visible in logs and user-visible status
- storage cleanup rules exist for generated video files

## Phase 4 - Hardening And Expansion

Status: `in_progress`

After the foundation and media-generation phases work, the next layer is operational hardening.

- webhook deployment path
- richer observability and cost tracking
- rate limits and per-user quotas
- moderation and safety controls for generated media
- stronger asset retention and cleanup policies
- optional provider strategy review if OpenAI chat plus Vertex media becomes hard to operate
- /image and /video command accept a reference image for generating content (gemini models eg: gemini-3-pro-image-preview)

Current Phase 4 progress:

- webhook mode now self-registers against Telegram with `setWebhook`
- webhook mode now requires and validates a Telegram secret token header
- readiness now treats missing webhook setup as not ready

## Decisions To Lock Early

These choices should be made before coding gets too far:

1. Phase 1 stays narrow and ships before any Vertex work.
2. Telegram partial reply streaming lands before generated media.
3. Image generation comes before video generation.
4. Video generation uses an asynchronous job model from the start.
5. Telegram-specific code stays separate from provider and asset-management code.

## Planning References

- Telegram bots overview: https://core.telegram.org/bots
- Telegram Bot API: https://core.telegram.org/bots/api
- Telegram Bot API `sendMessageDraft`: https://core.telegram.org/bots/api#sendmessagedraft
- Telegram Bot API `sendPhoto`: https://core.telegram.org/bots/api#sendphoto
- Telegram Bot API `sendVideo`: https://core.telegram.org/bots/api#sendvideo
- Vertex AI quickstart: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start
- Vertex AI API keys: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/api-keys
- Vertex AI image generation overview: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/image/overview
- Vertex AI video generation overview: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/video/generate-videos-from-text
- Google Gen AI SDK overview: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/sdks/overview
