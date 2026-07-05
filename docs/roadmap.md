# Product Roadmap

## Purpose

This document separates the current repo state from the planned delivery phases.

- `architecture.md`, `flows.md`, and `implementation-plan.md` define the Phase 1 build only.
- `phase-1-5-draft-streaming.md` defines the Phase 1.5 draft-streaming work only.
- `phase-2-vertex-image-generation.md` defines the completed Phase 2 image-generation work only.
- `phase-3-vertex-video-generation.md` defines the completed Phase 3 video-generation work only.
- Phase 5 ElevenLabs Hindi text-to-speech is tracked in this roadmap until it has a dedicated planning doc.
- Phase 6 Fal provider support is tracked in this roadmap until it has a dedicated planning doc.
- This roadmap tracks the broader direction, especially the later hardening and expansion work.

## Current Phase

- Active phases:
  - `Phase 5 - ElevenLabs Hindi Text To Speech`
- Status: `in_progress`
- Updated: `2026-07-05`
- Previous phase accepted: `Phase 4 - Hardening And Expansion`
- `Phase 6 - Fal Video Provider Support` is accepted as complete and merged into `dev`.
- Parallel implementation worktree:
  - Phase 5 branch: `phase-5-elevenlabs-tts`
  - Phase 5 path: `.worktrees/phase-5-elevenlabs-tts`
- Evidence:
  - Phase 1 foundation work is accepted as complete for repo sequencing
  - Phase 1.5 draft streaming is accepted as complete and no longer blocks the next milestone
  - Phase 2 image generation is accepted as complete for repo sequencing
  - Phase 3 video generation is accepted as complete for repo sequencing
  - an explicit `/video` command path now exists alongside the existing OpenAI chat and `/image` flows
  - video generation now uses persisted `generation_jobs` rows plus a background polling worker instead of blocking the original request path
  - completed video jobs now deliver through Telegram `sendVideo`
  - video asset retention rules are now explicit: inline bytes stay transient in memory, while URI-backed outputs rely on external bucket lifecycle policy
  - Phase 4 now includes log-only usage observability, production JSON log formatting, and optional config-driven cost estimates for chat, image, and video generation
  - Phase 4 now supports Telegram photo captions that start with `/image`, `/video`, or `/video_ltx`, and text commands that reply to a Telegram photo, as reference-image generation commands
  - Phase 4 now has a provider-neutral video router: `/video` tries Vertex first and falls back to Runpod LTX only on classified Vertex safety rejections, while `/video_ltx` forces Runpod for manual testing
  - Phase 4 now includes `/settings` inline-button presets stored per chat and user for safe video provider, video duration, video aspect/orientation, Runpod LTX, image, and chat request tuning
  - the remaining quota, budget-cap, moderation-gate, and in-app provider-output URL retention/expiry items are explicitly deferred out of Phase 4
  - the optional provider strategy review is represented by active Phase 6 Fal provider support
  - Phase 5 and Phase 6 implementation worktrees were created from `dev` after the `.worktrees/` ignore-rule commit
  - Phase 6 Fal provider support has been accepted as complete and merged into `dev`
  - `uv run pytest` now passes with `172` tests on `dev` after the Fal provider and per-family model selection work

## Current State

As of `2026-07-05`, this repository contains the completed Phase 1 foundation, the completed Phase 1.5 Telegram draft-streaming work, the completed Phase 2 image-generation slice, the completed Phase 3 video-generation slice, the completed Phase 4 hardening and expansion work, and the completed Phase 6 Fal video provider support merged into `dev`. Phase 5 ElevenLabs Hindi text-to-speech remains in progress in an isolated git worktree.

- Application code exists under `app/` for FastAPI startup, Telegram runtime wiring, SQLite persistence, domain services, OpenAI chat, Vertex image plus video generation, and Runpod LTX video fallback.
- A polling-first runtime exists, and webhook mode now reuses the same shared processing path when enabled.
- SQLite-backed conversation memory, command handling, allowlist checks, and text plus single-image inbound normalization are implemented.
- OpenAI response streaming, in-memory Telegram draft sessions, and per-chat supersession handling are implemented and accepted as complete for Phase 1.5.
- `/image <prompt>` now generates one image through Vertex AI and sends it back through Telegram `sendPhoto`.
- Generated-image metadata is stored in SQLite without persisting raw image bytes.
- `/video <prompt>` now submits one long-running Vertex video job by default, stores it in SQLite, and returns an immediate queued acknowledgement.
- If Vertex rejects `/video` submission with a classified safety/unsafe error, the video router falls back to Runpod LTX; timeout, quota, and generic upstream failures do not trigger fallback.
- `/video_ltx <prompt>` submits directly to Runpod LTX and persists the resulting job with `provider="runpod"`.
- `/settings` lets an allowed user choose whitelisted video provider, video duration, video aspect/orientation, safe Runpod LTX, image, and chat settings through Telegram inline buttons; the selections are persisted per `chat_id` and `user_id`.
- Runpod LTX submission uses native LTX `width`, `height`, `num_frames`, and `frame_rate` controls; safe Telegram settings can additionally send `pipeline`, two-stage `num_inference_steps`, `seed`, and reference `image_strength`, while storage, checkpoint, LoRA, offload, quantization, and compile controls remain environment-only.
- Runpod GCS-backed outputs are downloaded through transient bot-side signed URLs while storing only durable `gs://` output URIs.
- An in-process polling worker now checks pending video jobs and delivers completed assets through Telegram `sendVideo`.
- Video job persistence stores operation state, output URIs, failure reasons, and Telegram delivery metadata without persisting raw video bytes in SQLite.
- Tests exist under `tests/` for health and readiness behavior, normalization, reply-to-photo reference commands, allowlist handling, memory reuse, reset semantics, draft streaming, draft fallback, supersession, Telegram formatting, image generation, video job submission, worker completion, worker failure handling, Vertex video, Runpod video, Fal video, provider routing, and settings provider exposure.
- Phase 6 now has a `FalVideoProvider` adapter behind the existing `VideoGenerator` interface, using the official `fal-client` SDK for queued submit, request-handle recreation, status polling, and result retrieval.
- Phase 6 supports Fal-hosted Kling, Seedance 2.0, and Gemini Omni Flash endpoints for text-to-video, image-to-video, and reference-to-video modes by inferring the model family and mode from the configured endpoint path.
- Reference images are uploaded to Fal through the SDK and then sent using the correct parameter name per model family (`start_image_url` for Kling, `image_url` for Seedance/Gemini, `image_urls` for reference-to-video).
- `/settings` exposes `"fal"` as a video provider option and, when more than one Fal family is configured, a **Fal model** sub-menu lets users pick Kling, Seedance, or Gemini per chat.
- Real Vertex, Runpod, Fal, and Telegram verification still depends on configured credentials and a manual runtime check.
- Inline generated video bytes remain transient in memory only, while URI-backed assets are expected to live in a bucket with lifecycle cleanup managed outside the app.
- Phase 4 includes a real webhook deployment path: webhook mode now registers the Telegram webhook on startup, validates the `X-Telegram-Bot-Api-Secret-Token` header on inbound requests, and reports webhook setup state through readiness.
- Phase 4 now logs usage units and optional best-effort cost estimates for OpenAI chat, Vertex image generation, Vertex/Runpod video submission, and completed video delivery without adding a metrics backend or billing reconciliation.
- Phase 4 now supports `APP_LOG_FORMAT=json` for production structured logs, keeps readable text logs as the local default, suppresses successful low-level HTTP client logs below `WARNING`, and keeps repeated still-running video poll state at `DEBUG`.
- Photo captions that start with `/image <prompt>`, or text `/image <prompt>` commands that reply to a Telegram photo, use that photo as a transient reference image for Gemini image generation; Imagen remains prompt-to-image only.
- Photo captions that start with `/video <prompt>`, or text `/video <prompt>` commands that reply to a Telegram photo, queue an image-to-video job using that photo as a transient reference image.
- Photo captions that start with `/video_ltx <prompt>`, or text `/video_ltx <prompt>` commands that reply to a Telegram photo, queue a Runpod LTX image-to-video job using that photo as a transient reference image when it is under the configured Runpod reference-image size cap.
- Normal photo captions that do not start with `/image`, `/video`, or `/video_ltx` continue through the OpenAI image-understanding path.

## Recommended Sequencing

Build this in order:

1. Land the smallest end-to-end bot first.
2. Add partial reply streaming with Telegram drafts next.
3. Add generated image output after draft streaming works.
4. Add generated video output only after image generation works.
5. Harden the deployed bot before adding text-to-speech output.
6. Add Hindi text-to-speech as a dedicated `/tts` command after Phase 4.
7. Add Fal video provider support as a provider expansion of the existing `/video` job path.

Phase 5 and Phase 6 are currently being implemented in parallel through isolated git worktrees because they touch separate provider surfaces: Phase 5 adds a new TTS command/provider path, while Phase 6 expands the existing queued video provider path.

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

Status: `complete`

After the foundation and media-generation phases work, the next layer is operational hardening.

- webhook deployment path
- richer observability and cost tracking
- optional provider strategy review if OpenAI chat plus Vertex media becomes hard to operate
- /image and /video command accept a reference image for generating content (gemini models eg: gemini-3-pro-image-preview)
- Runpod LTX fallback for Vertex video safety false positives, with `/video_ltx` as the manual test path

Completed Phase 4 scope:

- webhook mode now self-registers against Telegram with `setWebhook`
- webhook mode now requires and validates a Telegram secret token header
- readiness now treats missing webhook setup as not ready
- chat, `/image`, `/video`, and completed video delivery now emit structured usage fields through the existing `log_kv(...)` log path
- production can set `APP_LOG_FORMAT=json` to emit those fields as parseable JSON instead of local text
- repeated still-running video polling and successful low-level HTTP client logs no longer dominate INFO-level production logs
- cost estimates are optional, configuration-driven, and disabled by default so pricing can be updated without code changes
- `/image`, `/video`, and `/video_ltx` now accept a Telegram photo-caption or reply-to-photo reference image without storing raw reference bytes in SQLite
- `/video` now falls back from Vertex to Runpod only for classified Vertex safety/unsafe rejections
- `/video_ltx` now forces Runpod LTX and persists queued jobs with the Runpod provider
- `/settings` now exposes inline-button presets for video provider, video duration, video aspect/orientation, safe Runpod LTX, image, and chat request settings while keeping secrets and infrastructure settings environment-only

Deferred out of Phase 4:

- per-user or per-chat quotas
- video or image daily budget caps
- prompt or reference-image moderation gates
- in-app retention or expiry handling for provider output URLs

These are not required before moving past Phase 4. The current asset rule remains that generated bytes and signed URLs are transient, while URI-backed assets rely on provider, bucket, or object-storage lifecycle policy outside the app.

Completion note:

- The optional provider strategy review is satisfied for sequencing by active Phase 6 Fal provider support, which will add Fal-hosted video models behind the existing provider interface instead of changing Phase 4 runtime behavior.

## Phase 5 - ElevenLabs Hindi Text To Speech

Status: `in_progress`

Implementation worktree:

- branch: `phase-5-elevenlabs-tts`
- path: `.worktrees/phase-5-elevenlabs-tts`
- baseline verification: `uv run pytest` passed with `133` tests

### Goal

Let an allowed user send Hindi text through `/tts <text>` and receive generated speech back in Telegram without changing the normal OpenAI chat, `/image`, or `/video` paths.

### Planned Scope

- add an explicit `/tts <Hindi text>` command flow
- generate speech through the ElevenLabs text-to-speech API
- default to the ElevenLabs voice ID `vIdhHAZdn1bGjKe1dFw8`
- start with Hindi text only
- deliver the generated speech through Telegram `sendVoice`
- keep generated audio bytes transient and out of SQLite
- persist only command text and lightweight delivery/provider metadata if persistence is needed

### Design Notes

- `/tts` should be a synchronous command path first, similar to `/image`, because short text-to-speech requests should not require the queued `/video` job model.
- Keep OpenAI chat, Vertex image/video generation, and ElevenLabs speech generation as separate provider interfaces.
- Prefer Telegram voice-message delivery for the first milestone. If ElevenLabs output is MP3, current Telegram and aiogram behavior still supports sending it as a voice message; if an OGG/Opus output is selected later, verify the container and codec against Telegram before making it the default.
- Use `eleven_multilingual_v2` as the initial quality-first model for Hindi unless latency or cost requires a switch to a faster model.
- Pass a Hindi language hint such as `language_code="hi"` when supported by the selected SDK/API path.
- Keep the first input contract simple: the text after `/tts` is the speech text. Do not mix `/tts` with chat-history rewriting, prompt expansion, or translation in the first milestone.

### Decisions Needed

- whether to reject non-Hindi or non-Devanagari input, or to trust the user and only document Hindi as supported
- whether to store a dedicated generated-audio metadata table or only append command/message rows
- whether to expose model and output-format configuration beyond environment variables
- whether repeated identical TTS outputs should reuse Telegram `file_id`
- maximum accepted text length for the first release

### Exit Criteria

Phase 5 is done when:

- an allowed user can send `/tts <Hindi text>` and receive a playable Telegram voice message
- `/tts` with missing text returns a clear usage message
- ElevenLabs failures return a clear user-safe retry message
- generated audio bytes are not persisted in SQLite
- `/start`, `/help`, and `/status` accurately report the new command and whether TTS is configured
- the existing OpenAI chat, `/image`, `/video`, polling, and webhook paths still work unchanged

## Phase 6 - Fal Video Provider Support

Status: `complete`

Merged into `dev`. The dedicated planning doc is [phase-6-fal-video-provider.md](phase-6-fal-video-provider.md).

### Goal

Let the existing queued `/video` flow use Fal-hosted video models as an additional provider option without changing Telegram transport behavior.

### Planned Scope

- add a Fal video provider adapter behind the existing `VideoGenerator` interface
- use Fal's queued submit, status, and result workflow rather than blocking the Telegram update handler
- start with provider configuration that can target Fal-hosted models such as Kling 3 and Seedance 2
- persist Fal jobs in the existing `generation_jobs` flow with `provider="fal"` or an equivalent provider identifier
- download completed Fal output URLs only for Telegram delivery, keeping raw generated video bytes transient
- expose safe model/provider presets through configuration and, where appropriate, `/settings`
- keep Vertex and Runpod behavior unchanged unless Fal is explicitly configured or selected

### Explicitly Out Of Scope

- adding separate `/kling`, `/seedance`, or model-specific Telegram commands in the first Fal milestone
- implementing per-user/per-chat quotas, daily media budget caps, prompt/reference-image moderation gates, or in-app provider-output URL retention/expiry handling
- replacing the existing Vertex safety fallback to Runpod
- distributed workers or external job queues

### Design Notes

- Fal should be treated as a provider route, not as a new media product surface.
- The Telegram layer should continue to normalize commands and deliver videos only; Fal-specific request mapping belongs in the provider adapter.
- The initial Fal adapter should preserve the current asynchronous video job contract: submit a job, poll by operation/request ID, fetch the completed asset, then deliver via `sendVideo`.
- Model-specific capabilities such as Kling 3 native audio, Seedance reference inputs, duration options, and aspect ratios should be introduced as whitelisted presets instead of free-form user controls.
- If a Fal result URL is temporary, Phase 6 still does not add durable in-app retention. Delivery should happen promptly, and durable storage remains a separate future decision.

### Decisions (Resolved)

- The first Fal model preset targets `fal-ai/kling-video/v3/standard/text-to-video` for text-to-video and supports additional per-mode endpoints via `FAL_VIDEO_IMAGE_TO_VIDEO_MODEL`, `FAL_VIDEO_REFERENCE_TO_VIDEO_MODEL`, and `FAL_VIDEO_EDIT_MODEL`.
- Persisted jobs use `provider="fal"`; the exact endpoint path is stored in the `model` column.
- Per-mode model endpoints are selected automatically based on whether the `/video` command includes a reference image and which endpoints are configured.
- Aspect ratio (Kling, Gemini) and resolution (Seedance) are controlled by the existing orientation presets and `FAL_VIDEO_RESOLUTION`; duration is passed in the type expected by each model family.
- `/settings` exposes `"fal"` as a video provider option and, when more than one Fal family is configured, a **Fal model** sub-menu lets users pick Kling, Seedance, or Gemini per chat.
- Cost estimates reuse the same log-only `cost_per_second_usd` pattern via `FAL_VIDEO_COST_PER_SECOND_USD`.

### Exit Criteria

Phase 6 is done when:

- an allowed user can submit a `/video <prompt>` job through a configured Fal provider and receive the generated video in Telegram
- a reference-photo `/video <prompt>` command can route to a compatible Fal image-to-video or reference-to-video model when configured
- Fal submission, polling, completion, failure, and Telegram delivery are covered by automated tests
- Fal failures return user-safe messages and do not break the existing Vertex or Runpod paths
- generated video bytes and temporary provider URLs are not persisted in SQLite
- README, `/status`, and `/settings` accurately report the configured Fal provider behavior

Phase 6 exit criteria are satisfied on `dev` as of `2026-07-05` with `172` passing tests.

## Decisions To Lock Early

These choices should be made before coding gets too far:

1. Phase 1 stays narrow and ships before any Vertex work.
2. Telegram partial reply streaming lands before generated media.
3. Image generation comes before video generation.
4. Video generation uses an asynchronous job model from the start.
5. Telegram-specific code stays separate from provider and asset-management code.
6. Text-to-speech generation stays separate from OpenAI chat and Vertex media providers.
7. Fal provider support stays behind the video provider interface and does not introduce model-specific Telegram transport logic.

## Planning References

- Telegram bots overview: https://core.telegram.org/bots
- Telegram Bot API: https://core.telegram.org/bots/api
- Telegram Bot API `sendMessageDraft`: https://core.telegram.org/bots/api#sendmessagedraft
- Telegram Bot API `sendPhoto`: https://core.telegram.org/bots/api#sendphoto
- Telegram Bot API `sendVideo`: https://core.telegram.org/bots/api#sendvideo
- Telegram Bot API `sendVoice`: https://core.telegram.org/bots/api#sendvoice
- Vertex AI quickstart: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start
- Vertex AI API keys: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/api-keys
- Vertex AI image generation overview: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/image/overview
- Vertex AI video generation overview: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/video/generate-videos-from-text
- Google Gen AI SDK overview: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/sdks/overview
- ElevenLabs text-to-speech API: https://elevenlabs.io/docs/api-reference/text-to-speech/convert
- ElevenLabs text-to-speech capabilities: https://elevenlabs.io/docs/overview/capabilities/text-to-speech
- Fal queue API docs: https://docs.fal.ai/model-endpoints/queue
- Fal Kling 3 video API docs: https://fal.ai/models/fal-ai/kling-video/v3/standard/image-to-video/api
- Fal Seedance 2 video API docs: https://fal.ai/models/bytedance/seedance-2.0/image-to-video/api
