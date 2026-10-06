# Phase 5 - ElevenLabs Hindi Text To Speech

Status: implemented in `phase-5-elevenlabs-tts`; live acceptance pending.

## Approved design

- `/tts <text>` synthesizes the supplied text and delivers one MP3 audio attachment by default. `/settings` → TTS delivery
  selects MP3 audio file or voice message, persisted per chat/user across resets
  and restarts. The choice is captured before generation for each request.
- Hindi is the supported target; mixed scripts are accepted without rewriting,
  translation, truncation, or chat-history context.
- Use a separate asynchronous ElevenLabs provider and a focused TTS domain service.
- Each accepted request finishes independently of chat supersession. Multiple TTS
  commands may run concurrently; each audio reply targets its originating command.
- Use the official Python SDK, `eleven_multilingual_v2`, voice
  `vIdhHAZdn1bGjKe1dFw8`, and `mp3_44100_128`. Omit `language_code` for Multilingual
  v2 because the API does not support it for that model.
- Default input limit: 3000 characters; overall generation timeout: 45 seconds;
  voice upload timeout: 60 seconds; transient audio ceiling: 10 MiB.
- Missing credentials disable TTS without preventing the rest of the bot starting.
- Persist the command before generation using an atomic claim keyed by chat and
  Telegram message ID. Duplicate updates do not spend another provider call.
- Record command outcomes and structured delivery metadata. Audio bytes never
  enter SQLite or files. There is no generation-job queue, schema migration,
  automatic generation retry, audio cache, or restart recovery for TTS.
- Generation and delivery failures have distinct safe responses. A metadata write
  failure after successful upload does not trigger a retry or a false failure reply.

## Implementation checklist

- [x] Provider, configuration, request/result types, and provider boundary tests.
- [x] Atomic command claim, independent TTS service, voice transport, and behavior tests.
- [x] Application lifecycle, command discovery/status, and ingestion tests.
- [x] Full suite, review, and current-state documentation.
- [ ] Manual configured `/tts नमस्ते, आपका स्वागत है।` acceptance in Telegram.

The approved in-chat plan is the implementation specification. Shared contracts
are the speech request/result, `ResponseEmitter.send_audio` and `send_voice`, optional provider
injection, and message-history claim. Existing chat/image/video provider contracts
and the generation-job schema remain unchanged.

## Execution evidence

- Baseline: 180 tests passed before implementation.
- Provider/configuration: 21 tests passed after the missing-interface and validation failures were observed.
- Domain/transport: 22 tests passed after missing TTS routing, provider injection, and voice transport failures were observed.
- Ingestion/lifecycle: 4 tests passed after missing startup wiring and command discovery failures were observed.
- Final combined suite: 228 tests passed on Python 3.13 using SDK 2.68.0.
- `uv sync --locked --extra dev` verified the final dependency set.
- Live provider check on 2026-09-21: the main worktree `.env` key successfully
  generated a 32,226-byte Hindi MP3 using `eleven_multilingual_v2`, voice
  `vIdhHAZdn1bGjKe1dFw8`, and `mp3_44100_128`; ElevenLabs returned a request ID.
  Local inspection confirmed MPEG Layer III, 128 kbps, 44.1 kHz, mono audio.
- Live Telegram `sendVoice` playability remains the only manual acceptance item.
- Documentation fixes the historical missing-worktree reference and the unsupported Hindi language hint.

No user choices changed during execution. The SDK minimum is 2.68.0, the version
whose raw-response interface was inspected and tested. Metadata uses the existing
assistant message fields and structured logs; no schema migration is required.

## Review resolution

- Fixed: a SQLite commit error could escape after a successful voice upload.
  The transaction helper now rolls back and maps commit errors to `StorageError`,
  preserving the service's delivery outcome and keeping SQLite usable. A regression
  test failed before the fix and passed afterward; the full suite also passed.
- Ruling: keep the existing command parser's trimming of surrounding whitespace.
  "Direct text" excludes prompt rewriting, translation, and history expansion; it
  does not promise byte-for-byte preservation of command delimiters or trailing
  whitespace. This matches the documented trimmed-input limit. Whitespace-only
  leading/trailing pauses are therefore not preserved.
- Ruling: retain the existing runtime shutdown behavior. Polling shutdown does
  not drain all child update handlers before closing resources; a shutdown may
  interrupt an in-flight TTS request. Restart recovery and broader polling shutdown
  changes are outside this milestone, so interrupted requests require a fresh
  command. This is not an exactly-once delivery or graceful-drain guarantee.

## References

- [ElevenLabs conversion API](https://elevenlabs.io/docs/api-reference/text-to-speech/convert)
- [ElevenLabs models](https://elevenlabs.io/docs/overview/models)
- [Official Python SDK](https://github.com/elevenlabs/elevenlabs-python)
- [Telegram sendVoice](https://core.telegram.org/bots/api#sendvoice)
- [aiogram uploads](https://docs.aiogram.dev/en/latest/api/upload_file.html)

## Delivery update - 2026-10-06

- MP3 audio attachments use Telegram `sendAudio` and its returned audio metadata;
  optional voice messages use `sendVoice` and voice metadata.
- `/settings` exposes only delivery style; provider model, voice, encoding, and
  limits remain environment-only. Existing SQLite preferences need no migration.
- Both delivery modes retain command deduplication, independent request lifecycles,
  transient audio, and safe handling of upload and metadata failures.
- `TELEGRAM_VOICE_REQUEST_TIMEOUT_SECONDS` applies to both speech upload styles.
- Deployment and live Telegram acceptance of the new audio attachment path are pending.

Reference: [Telegram sendAudio](https://core.telegram.org/bots/api#sendaudio).
