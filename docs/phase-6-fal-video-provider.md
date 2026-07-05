# Phase 6 - Fal Video Provider Support

## Goal

Let the existing queued `/video` flow use Fal-hosted video models as an additional provider option without changing Telegram transport behavior.

## Scope

- Add a Fal video provider adapter behind the existing `VideoGenerator` interface.
- Use Fal's queued submit, status, and result workflow rather than blocking the Telegram update handler.
- Support Fal-hosted model families including Kling (`fal-ai/kling-video`), Seedance 2.0 (`bytedance/seedance-2.0`), and Gemini Omni Flash (`google/gemini-omni-flash`) for text-to-video (Kling, Seedance), image-to-video (all families), and reference-to-video (Seedance, Gemini) modes.
- Persist Fal jobs in the existing `generation_jobs` flow with `provider="fal"`.
- Download completed Fal output URLs only for Telegram delivery, keeping raw generated video bytes transient.
- Expose a `"fal"` provider choice in `/settings`; keep exact model selection environment-only.
- Keep Vertex and Runpod behavior unchanged unless Fal is explicitly configured or selected.

## Out of Scope

- Adding separate `/kling`, `/seedance`, `/gemini`, or model-specific Telegram commands.
- Implementing per-user/per-chat quotas, daily media budget caps, prompt/reference-image moderation gates, or in-app provider-output URL retention/expiry handling.
- Replacing the existing Vertex safety fallback to Runpod.
- Distributed workers or external job queues.
- Video-to-video edit flows in `/video` (the `google/gemini-omni-flash/edit` endpoint is configurable via `FAL_VIDEO_EDIT_MODEL` but requires future video-input support before it is reachable from Telegram).

## Design Notes

- Fal should be treated as a provider route, not as a new media product surface.
- The Telegram layer should continue to normalize commands and deliver videos only; Fal-specific request mapping belongs in the provider adapter.
- The adapter infers the endpoint mode (`text-to-video`, `image-to-video`, `reference-to-video`, `edit`) from the model path and the reference-image presence, then sends the appropriate parameter names and value types for each model family.
- Kling image-to-video uses `start_image_url`; all other image-to-video models use `image_url`. Reference-to-video models use a single-entry `image_urls` list.
- Kling and Seedance accept `duration` as a string. Gemini Omni Flash accepts `duration` as an integer.
- Kling text-to-video and reference-to-video use `aspect_ratio` (`16:9`, `9:16`, `1:1`); Kling image-to-video does not.
- Gemini Omni Flash supports `aspect_ratio` of `16:9` or `9:16` only.
- Seedance uses `resolution` (`480p`, `720p`, `1080p`, `4k`) and also accepts an optional `aspect_ratio` in all modes.
- Reference images are encoded as base64 data URIs. If a reference image exceeds `FAL_VIDEO_REFERENCE_IMAGE_MAX_BYTES`, it is omitted with a log line and the request falls back to the configured text-to-video endpoint.
- If a reference image is supplied but neither an image-to-video nor a reference-to-video model is configured, the image is ignored and the request uses the configured text-to-video endpoint.
- The initial implementation preserves the current asynchronous video job contract: submit a job, poll by request ID, fetch the completed asset, then deliver via `sendVideo`.
- If a Fal result URL is temporary, Phase 6 still does not add durable in-app retention. Delivery happens promptly, and durable storage remains a separate future decision.

## Decisions (Locked)

1. **Default Fal text-to-video model**: `fal-ai/kling-video/v3/standard/text-to-video`.
2. **Optional Fal image-to-video model**: configured via `FAL_VIDEO_IMAGE_TO_VIDEO_MODEL`. Recommended value: `fal-ai/kling-video/v3/standard/image-to-video`.
3. **Optional Fal reference-to-video model**: configured via `FAL_VIDEO_REFERENCE_TO_VIDEO_MODEL`. Recommended value: `bytedance/seedance-2.0/reference-to-video`.
4. **Optional Fal edit model**: configured via `FAL_VIDEO_EDIT_MODEL`. Not reachable from `/video` until video-input support is added.
5. **Provider identifier in jobs**: `provider="fal"`; the exact Fal endpoint path is stored in the `model` column of `generation_jobs`.
6. **Settings exposure**: `"fal"` is selectable as a video provider in `/settings`. Exact model selection remains environment-only.
7. **Reference-image handling**: upload Telegram photo bytes through the official `fal-client` SDK. If the image exceeds `FAL_VIDEO_REFERENCE_IMAGE_MAX_BYTES`, omit it and log; otherwise route to the configured reference-to-video or image-to-video model using the uploaded Fal CDN URL.
8. **No new fallback**: Fal failures do not trigger Vertex/Runpod fallback. The existing Vertex-safety -> Runpod fallback remains untouched.
9. **Polling policy**: Phase 6 uses polling against the queue status/result endpoints. Fal webhooks are out of scope.
10. **Raw bytes policy**: completed Fal output URLs are downloaded only for Telegram delivery; raw bytes and temporary URLs are not persisted in SQLite.

## Fal SDK Queue Contract

The implementation now uses the official Python `fal-client` SDK for queue submission, request-handle recreation, polling, result retrieval, and reference-image upload. The SDK authenticates with `FAL_KEY` and manages the queue host internally.

### Submit

Runtime flow:

1. Build the family-specific Fal input payload from the normalized `VideoGenerationRequest`.
2. If a usable Telegram reference image is present, decode the bytes and upload them through `fal_client.AsyncClient.upload(...)`.
3. Replace the family-specific image field with the returned Fal CDN URL (`start_image_url`, `image_url`, or `image_urls`).
4. Submit the queued request through `fal_client.AsyncClient.submit(model_id, arguments=payload)`.
5. Persist only the returned `request_id` plus the selected Fal model endpoint.

Body shape still depends on model family and mode:

**Kling text-to-video**

```json
{
  "prompt": "...",
  "duration": "5",
  "aspect_ratio": "9:16"
}
```

**Kling image-to-video**

```json
{
  "prompt": "...",
  "start_image_url": "https://fal.media/...",
  "duration": "5"
}
```

**Gemini Omni Flash image-to-video / reference-to-video**

```json
{
  "prompt": "...",
  "image_url": "https://fal.media/...",
  "duration": 8,
  "aspect_ratio": "16:9" | "9:16"
}
```

**Seedance 2.0 text-to-video**

```json
{
  "prompt": "...",
  "duration": "5",
  "resolution": "720p",
  "aspect_ratio": "9:16"
}
```

**Reference-to-video**

```json
{
  "prompt": "...",
  "image_urls": ["https://fal.media/..."],
  "duration": "5" | 8,
  "aspect_ratio": "9:16" | "16:9" | "resolution": "720p"
}
```

### Poll And Result

Polling flow:

1. Recreate the queued request handle after restart with `fal_client.AsyncClient.get_handle(model_id, request_id)`.
2. Call `await handle.status(with_logs=False)` to classify `Queued`, `InProgress`, or `Completed`.
3. When completed, call `await handle.get()` to fetch the model-specific result payload.
4. Download the returned `video.url` through `httpx` for Telegram delivery only.

The adapter still returns `VideoJobPollResult(status="running")` for queued/in-progress work, `status="failed"` for queue/result errors, and `status="completed"` only after the final asset bytes have been fetched successfully.

## Configuration

New environment variables in `app/config.py`:

| Env Var | Type | Default | Purpose |
|---------|------|---------|---------|
| `FAL_KEY` | `SecretStr` | `None` | Required if `VIDEO_PROVIDER_ORDER` includes `fal` |
| `FAL_VIDEO_MODEL` | `str` | `fal-ai/kling-video/v3/standard/text-to-video` | Default text-to-video endpoint |
| `FAL_VIDEO_TEXT_TO_VIDEO_MODEL` | `str \| None` | `None` | Optional override for the text-to-video endpoint |
| `FAL_VIDEO_IMAGE_TO_VIDEO_MODEL` | `str \| None` | `None` | Optional image-to-video endpoint |
| `FAL_VIDEO_REFERENCE_TO_VIDEO_MODEL` | `str \| None` | `None` | Optional reference-to-video endpoint |
| `FAL_VIDEO_EDIT_MODEL` | `str \| None` | `None` | Optional video-to-video endpoint (future use) |
| `FAL_VIDEO_RESOLUTION` | `str` | `720p` | Seedance resolution preset when a model is Seedance |
| `FAL_VIDEO_REFERENCE_IMAGE_MAX_BYTES` | `int` | `6_000_000` | Max Telegram reference image bytes to upload through the SDK |
| `FAL_VIDEO_COST_PER_SECOND_USD` | `float` | `0.0` | Optional log-only cost estimate |
| `FAL_CLIENT_TIMEOUT_SECONDS` | `int` | `45` | Fal SDK client timeout plus final asset download timeout |

`VIDEO_PROVIDER_ORDER` now accepts `fal` in addition to `vertex` and `runpod`.

The bot detects available model families from the configured endpoints. When more than one family is configured, users can choose a family via the `/settings` **Fal model** option.

## Code Changes

1. `app/domain/models.py`: extend `VideoProviderName`/`VideoProviderHint` with `"fal"`; add `resolution` to `VideoGenerationRequest`.
2. `app/config.py`: add Fal env fields, validation, properties, and include `fal` in `VIDEO_PROVIDER_ORDER` and `video_generation_enabled`.
3. `app/providers/fal_video_provider.py`: new adapter with model-family dispatch for request/response fields.
4. `app/providers/video_router.py`: accept `"fal"` direct hint.
5. `app/main.py`: construct `FalVideoProvider` when enabled and add to router/provider models/startup logs.
6. `app/workers/video_jobs.py`: add Fal branch in `_video_cost_for_provider`.
7. `app/domain/services.py`: update `_handle_video_command` to select per-mode Fal model, pass resolution, and set `model_locked=True`.
8. `app/domain/preferences.py`: add `"fal"` to `VIDEO_PROVIDER_PRESETS`.
9. `app/domain/commands.py`: update `/help` and `/status`-related strings so `/video` no longer appears Vertex-only.
10. Tests: `tests/test_fal_video_provider.py` (new), updates to `test_video_provider_router.py`, `test_video_job_worker.py`, `test_chat_service.py`, `test_preferences.py`, `test_telegram_settings.py`, `test_config.py`.
11. `README.md` and `docs/roadmap.md`: update to reflect Fal provider and resolved decisions.

## Exit Criteria

- An allowed user can submit a `/video <prompt>` job through a configured Fal provider and receive the generated video in Telegram.
- A reference-photo `/video <prompt>` command can route to a compatible Fal image-to-video or reference-to-video model when configured.
- Fal submission, polling, completion, failure, and Telegram delivery are covered by automated tests for multiple model families.
- Fal failures return `VIDEO_GENERATION_RETRY_TEXT` and do not break the existing Vertex or Runpod paths.
- Generated video bytes and temporary provider URLs are not persisted in SQLite.
- README, `/status`, and `/settings` accurately report the configured Fal provider behavior.
- `uv run pytest` passes with all existing tests plus new Fal tests in the Phase 6 worktree.
