# Product Roadmap

## Purpose

This document separates the current repo state from the planned delivery phases.

- `architecture.md`, `flows.md`, and `implementation-plan.md` define the Phase 1 build only.
- `phase-1-5-draft-streaming.md` defines the Phase 1.5 draft-streaming work only.
- `phase-2-vertex-image-generation.md` defines the active Phase 2 image-generation work only.
- This roadmap tracks the broader direction, especially the later Vertex video-generation work.

## Current Phase

- Active phase: `Phase 2 - Vertex Image Generation`
- Status: `in_progress`
- Last updated: `2026-04-12`
- Exit criteria source: `Phase 2 - Vertex Image Generation`
- Evidence:
  - Phase 1 foundation work is accepted as complete for repo sequencing
  - Phase 1.5 draft streaming is accepted as complete and no longer blocks the next milestone
  - an explicit `/image` command path now exists alongside the existing OpenAI chat flow
  - generated image delivery now uses Telegram `sendPhoto` through the Telegram adapter
  - generated-image prompt and Telegram file metadata are now persisted separately from chat history in SQLite
  - OpenAI text and image-understanding chat remains unchanged while Vertex image generation is added as a separate path
  - live Vertex and Telegram runtime verification for the new `/image` flow is still pending

## Current State

As of `2026-04-12`, this repository contains the completed Phase 1 foundation, the completed Phase 1.5 Telegram draft-streaming work, and an in-progress Phase 2 image-generation slice.

- Application code exists under `app/` for FastAPI startup, Telegram runtime wiring, SQLite persistence, domain services, OpenAI chat, and Vertex image generation.
- A polling-first runtime exists, while the webhook route remains reserved behind the same shared processing path.
- SQLite-backed conversation memory, command handling, allowlist checks, and text plus single-image inbound normalization are implemented.
- OpenAI response streaming, in-memory Telegram draft sessions, and per-chat supersession handling are implemented and accepted as complete for Phase 1.5.
- `/image <prompt>` now generates one image through Vertex AI and sends it back through Telegram `sendPhoto`.
- Generated-image metadata is stored in SQLite without persisting raw image bytes.
- Tests exist under `tests/` for health and readiness behavior, normalization, allowlist handling, memory reuse, reset semantics, draft streaming, draft fallback, supersession, Telegram formatting, and the new image-generation flow.
- Real Vertex and Telegram verification still depends on configured credentials and a manual runtime check.

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

Status: `in_progress`

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
- The current implementation starts with Imagen on Vertex AI through the dedicated `generate_images` SDK path.
- The implementation now supports a Vertex API key for testing and can still fall back to ADC when that key is not configured.
- This is an intentional Phase 2 implementation choice: current official Vertex docs expose a straightforward Python image-generation API for Imagen, while Gemini image generation on Vertex AI is still documented as preview and requires mixed `TEXT` plus `IMAGE` output.
- Telegram handler code should continue to normalize inbound updates and deliver outbound media only. Generation routing stays in the domain and provider layers.

### New Decisions Needed

- whether generated images should be reusable across chats by storing and reusing Telegram `file_id`
- whether successful `/image` generations should also write a richer assistant summary row into chat history
- whether Phase 2 should later widen from simple prompt-to-image into image editing or variation flows
- whether Gemini image generation should be evaluated later once its API surface stabilizes for production use

### Exit Criteria

Phase 2 is done when:

- an allowed user can request an image with a prompt and receive it in Telegram
- generation failures return a clear user-safe message
- generated-image metadata is traceable in logs and persistence
- the OpenAI chat flow still works unchanged

## Phase 3 - Vertex Video Generation

Status: `not_started`

### Goal

Let the bot generate short videos and deliver them back to Telegram.

### Why This Is A Separate Phase

Video generation should not be forced into the same synchronous shape as Phase 1 chat replies.

- Vertex Veo generation is an operation-based workflow and should be treated as asynchronous work.
- Telegram video delivery has tighter delivery and upload constraints than plain text replies.
- Generated video files will need stronger lifecycle management than text or transient image inputs.

### Proposed Scope

- introduce a generation jobs table with statuses such as `queued`, `running`, `completed`, `failed`
- add a worker or polling loop for long-running Vertex operations
- introduce a dedicated entrypoint such as `/video`
- start with short text-to-video generation only
- store generated video assets outside SQLite and deliver them with Telegram `sendVideo`
- send follow-up status or completion messages instead of blocking the original request path

### New Decisions Needed

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

Status: `not_started`

After the foundation and media-generation phases work, the next layer is operational hardening.

- webhook deployment path
- richer observability and cost tracking
- rate limits and per-user quotas
- moderation and safety controls for generated media
- stronger asset retention and cleanup policies
- optional provider strategy review if OpenAI chat plus Vertex media becomes hard to operate

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
- Vertex AI quickstart: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start
- Vertex AI API keys: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/api-keys
- Vertex AI image generation overview: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/image/overview
- Google Gen AI SDK overview: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/sdks/overview
