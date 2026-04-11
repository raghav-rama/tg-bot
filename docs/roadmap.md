# Product Roadmap

## Purpose

This document separates the current repo state from the planned delivery phases.

- `architecture.md`, `flows.md`, and `implementation-plan.md` define the Phase 1 build only.
- `phase-1-5-draft-streaming.md` defines the planned Phase 1.5 draft-streaming enhancement only.
- This roadmap tracks the broader direction, especially the later Google Gemini / Vertex AI media-generation work.

## Current Phase

- Active phase: `Phase 1 - Foundation`
- Status: `in_progress`
- Last updated: `2026-04-11`
- Exit criteria source: `Phase 1 - Foundation`
- Evidence:
  - planning docs exist and are aligned around Phase 1
  - Phase 1 application code now exists under `app/` with tests under `tests/`
  - automated checks cover normalization, allowlist behavior, memory reuse, reset semantics, and readiness behavior
  - live Telegram/OpenAI runtime verification is still pending
  - Google Gemini / Vertex AI media generation remains planned work, not current repo behavior

## Current State

As of 2026-04-11, this repository contains the Phase 1 implementation and its first automated test suite.

- Application code exists under `app/` for FastAPI startup, Telegram runtime wiring, SQLite persistence, domain services, and the OpenAI adapter.
- A polling-first runtime exists, while the webhook route remains reserved behind the same shared processing path.
- SQLite-backed conversation memory, command handling, allowlist checks, and text plus single-image inbound normalization are implemented.
- Tests exist under `tests/` for health/readiness behavior, normalization, allowlist handling, memory reuse, and reset semantics.
- The current Phase 1 design still assumes text-only outbound replies.
- Telegram partial-reply draft streaming is planned as Phase 1.5 work and is not current repo behavior.

## Recommended Sequencing

Build this in order:

1. Land the smallest end-to-end bot first.
2. Add partial reply streaming with Telegram drafts next.
3. Add generated image output after draft streaming works.
4. Add generated video output only after image generation works.

This ordering keeps the first milestone small, then improves reply UX before introducing richer media.

## Phase 1 - Foundation

Status: `in_progress`

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

Status: `not_started`

Dedicated planning doc: [phase-1-5-draft-streaming.md](phase-1-5-draft-streaming.md)

### Goal

Let the bot show partial assistant text in Telegram while a long reply is still being generated.

### Proposed Scope

- use Telegram Bot API `sendMessageDraft` for partial reply updates
- keep the final assistant response as a normal text message
- add provider-side text streaming for the existing OpenAI path
- keep partial draft state in memory only
- degrade safely to final-only replies when draft streaming fails

### Design Notes

- Telegram documents `sendMessageDraft` for target private chats, which fits the current private-bot scope.
- `aiogram` already exposes `sendMessageDraft`, so the main work is service orchestration rather than framework patching.
- The Bot API docs describe how to send draft updates, but the final cleanup behavior still needs real-client validation.
- This is a UX enhancement and should not expand supported input or output types.

### New Decisions Needed

- whether Phase 1.5 should stream only text-input replies first or also image-understanding replies
- how aggressively draft updates should be throttled
- whether formatting entities should be allowed in draft text on the first rollout
- how to handle a new incoming user message while an older response is still streaming

### Exit Criteria

Phase 1.5 is done when:

- an allowed private-chat user can see partial assistant text for a long-running reply
- the final assistant reply still arrives as a normal Telegram text message
- draft-send failures fall back cleanly to the Phase 1 final-only path
- no partial draft text is persisted in SQLite
- real Telegram clients confirm the draft disappears cleanly after final handoff

## Phase 2 - Vertex Image Generation

Status: `not_started`

### Goal

Let the bot generate images and send them back to Telegram.

### Proposed Scope

- add a Google Gen AI / Vertex AI client path using the Python `google-genai` SDK
- keep chat flow separate from image-generation flow
- introduce an explicit bot entrypoint for image generation such as `/image`
- return one generated image per request first
- send generated output back through Telegram `sendPhoto`
- persist prompt metadata and generated asset references, not raw binary blobs in SQLite

### Design Notes

- Start with Vertex AI rather than a direct Gemini Developer API integration so project, region, and operational controls stay in one Google Cloud path.
- Start with Gemini image generation on Vertex AI because it fits a conversational bot flow and supports text-plus-image style generation in one response path.
- If image quality, typography, or brand control becomes more important than conversational flow, evaluate Imagen later as a separate decision instead of mixing that into the first image milestone.
- Keep generation routing out of Telegram handler code. Telegram should only normalize input and deliver output.

### New Decisions Needed

- whether chat stays on OpenAI while image generation lives on Vertex AI
- whether image generation should be command-based (`/image`) or mode-based
- where generated assets live before and after Telegram delivery
- whether generated images should be reusable across chats by storing a Telegram `file_id`

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
- Telegram message drafts overview: https://core.telegram.org/api/drafts
- aiogram API docs: https://docs.aiogram.dev/en/latest/api/index.html
- aiogram `sendMessageDraft`: https://docs.aiogram.dev/en/latest/api/methods/send_message_draft.html
- Vertex AI Gemini image generation: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/image-generation
- Vertex AI Veo overview: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/video/overview
- Google Gen AI Python SDK: https://googleapis.github.io/python-genai/
