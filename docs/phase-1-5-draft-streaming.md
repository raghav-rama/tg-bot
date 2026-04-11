# Telegram Bot Architecture - Phase 1.5

## Summary

This document defines Phase 1.5 only.

Phase 1.5 adds Telegram partial-reply streaming for the existing private bot by using the Bot API method `sendMessageDraft`. The goal is to let an allowed user see a partial assistant reply while the AI response is still being generated, while keeping the final delivered answer as a normal Telegram text message.

This is a UX phase, not a product-scope phase. It should not widen supported input types, public exposure, provider scope, or generated-media behavior.

## Why This Is A Separate Phase

This feature changes response delivery shape without changing the core chat feature set.

- Phase 1 proved end-to-end request handling, memory, and reliability.
- `sendMessageDraft` introduces a second outbound path: partial draft updates before the final send.
- The provider layer must expose incremental text generation instead of a single final string.
- Draft lifecycle and failure handling need explicit design because Telegram documents the draft-send method but does not fully spell out final cleanup behavior in the Bot API method docs.

## Source-Grounded API Facts

The Phase 1.5 design should assume these currently documented facts:

- Telegram Bot API documents `sendMessageDraft` as a method to stream a partial message while it is being generated.
- `sendMessageDraft` returns `True` on success, not a `Message` object.
- `chat_id` is documented as the identifier for the target private chat.
- `draft_id` must be non-zero, and updates with the same `draft_id` are animated.
- `text` must remain within Telegram text limits after entity parsing.
- `message_thread_id`, `parse_mode`, and `entities` are optional.
- `aiogram` 3.27.0 exposes this method as `await bot.send_message_draft(...)`.

Related Telegram draft semantics from the broader Telegram API:

- Telegram drafts are synchronized across devices.
- Telegram draft state can be cleared in MTProto-level send flows with `clear_draft` semantics or by saving an empty draft.
- The Bot API page for `sendMessageDraft` does not currently document an explicit clear method. Phase 1.5 therefore needs client-level verification that the final handoff behaves cleanly.

## Goal

Improve perceived latency for long-running text replies without changing the final Phase 1 behavior.

Current rollout decision:

- stream private text-input replies first
- keep image-understanding requests on the final-only path unless explicitly enabled later

## In Scope

- partial text updates sent with `sendMessageDraft`
- text-only outbound streaming for the existing OpenAI-backed reply flow
- private-chat support only
- polling-first implementation, while keeping webhook compatibility
- in-memory tracking of in-flight draft sessions
- fallback to the existing final-only reply path if draft streaming fails
- observability for draft start, update, completion, cancellation, and fallback

## Explicitly Out Of Scope

- generated image replies
- generated video replies
- public or group-chat rollout
- non-text partial outputs
- persistence of partial assistant text in SQLite
- adding Google Gemini / Vertex AI in this phase
- changing supported inbound message types beyond Phase 1

## User Experience Contract

For a long-running request:

1. The user sends a supported message.
2. The bot starts generation.
3. If generation takes long enough, the bot begins sending animated draft updates into the private chat.
4. When generation finishes, the bot sends the final assistant reply as a normal Telegram text message.
5. The draft should no longer remain visible after the final handoff.

For a fast request:

- The bot may skip the draft path entirely and send only the final message.

For failures:

- If draft streaming fails, the bot should continue the request and still try to send the final message.
- If provider generation fails after a draft has started, the bot should stop the draft session and send the existing retry-later message.

## Architecture Delta From Phase 1

Phase 1.5 keeps the same high-level layers but changes responsibilities around outbound text delivery.

### Telegram adapter

Add a `DraftMessenger` abstraction responsible for:

- allocating a non-zero `draft_id` for each in-flight response
- sending draft updates through `sendMessageDraft`
- throttling updates so the bot does not emit every token as a separate Telegram call
- finishing, cancelling, or abandoning the draft session cleanly

The Telegram adapter remains responsible only for Telegram transport behavior. It should not decide when to reveal or hide drafts based on product logic.

### Chat service

The chat service should orchestrate:

- access checks
- command routing
- conversation lookup
- provider streaming start
- draft-stream lifecycle
- final persistence of the assistant message
- safe fallback when draft streaming fails

The chat service should still own user-visible business rules such as:

- which message types qualify for streaming
- whether drafts are delayed for a short threshold to avoid flicker on fast replies
- how `/reset` or a newer incoming message affects an in-flight response

### Provider adapter

The provider interface should widen from final-only generation to incremental text generation.

Recommended interface shape:

```python
class StreamingProviderEvent(TypedDict):
    type: Literal["delta", "completed"]
    text: str | None
    provider_message_id: str | None
    raw_model: str | None
    finish_reason: str | None
```

```python
class AIProvider(Protocol):
    async def stream_response(
        self,
        request: ProviderRequest,
    ) -> AsyncIterator[StreamingProviderEvent]:
        ...
```

The existing final-only helper may remain for compatibility, but the draft-streaming path should consume streamed deltas.

### Storage

No schema migration is required by default.

Phase 1.5 should keep SQLite behavior narrow:

- persist the user turn once accepted
- persist the final assistant reply only
- do not persist partial draft text

This preserves current memory behavior and avoids replaying half-written assistant output after restart.

## Recommended Runtime Behavior

### Eligibility

Start Phase 1.5 with these eligibility rules:

- allowed users only
- private chats only
- text chat messages on the first rollout
- final outbound content is text

Image-plus-caption requests may still qualify because the final response remains text-only, but this should stay behind an explicit implementation toggle rather than becoming the default assumption.

### Draft start threshold

Do not show a draft immediately on every request.

Start with a short threshold such as:

- wait `500-1000 ms` for the first streamed text before sending the first draft update
- if the final response completes before that threshold, send only the final message

This keeps fast replies from producing distracting UI churn.

### Update cadence

Do not send a draft update for every tiny token delta.

Start conservatively:

- update every `250-500 ms` at most
- or when at least `20-40` new visible characters have accumulated
- whichever happens later

These numbers are implementation defaults, not Telegram guarantees. They should be validated manually against real chats.

### Final handoff

When generation completes:

1. stop draft updates
2. send the final reply with the normal Telegram `sendMessage` path
3. verify that the draft no longer remains visible

Because the Bot API `sendMessageDraft` docs do not currently describe explicit draft cleanup behavior, the disappearance of the draft must be treated as an exit criterion, not an assumption.

## OpenAI Path

The existing OpenAI adapter is a good fit for this phase because the Python SDK already supports streamed `Responses API` events.

Recommended approach:

- call `client.responses.create(..., stream=True)`
- listen for `response.output_text.delta`
- append deltas into an accumulated string buffer
- publish throttled snapshots of that buffer to the Telegram draft messenger
- on completion, send the final accumulated reply text through the normal send path

This keeps provider streaming separate from Telegram transport decisions.

## Concurrency Rules

To keep the first rollout small:

- allow only one in-flight assistant generation per chat
- a new user message in the same chat should cancel or supersede the earlier draft session
- `/reset` during an active generation should cancel the draft session before starting the new conversation

Cross-chat concurrency can still exist, but per-chat overlap should stay simple.

## Failure Handling

### Draft send failure

If `sendMessageDraft` fails:

- log the failure with `chat_id`, `user_id`, and `draft_id`
- disable draft updates for that response
- continue provider generation
- still attempt to send the final text reply normally

This feature must be optional at runtime, not a single point of failure.

### Provider failure after draft start

If the provider times out or fails after drafts were already shown:

- stop the draft session
- do not persist an assistant reply row
- send the existing retry-later message

### Process restart during streaming

If the process restarts mid-response:

- partial draft state is lost
- no partial assistant text should be recovered from SQLite
- the next user message should continue from persisted final history only

## Configuration Additions

Recommended Phase 1.5 settings:

- `BOT_ENABLE_MESSAGE_DRAFTS`
- `BOT_DRAFT_STREAM_ON_IMAGES`
- `BOT_DRAFT_START_DELAY_MS`
- `BOT_DRAFT_UPDATE_INTERVAL_MS`
- `BOT_DRAFT_MIN_CHARS_DELTA`

Defaults should keep the feature easy to disable and easy to tune without code changes.

## Implementation Order

1. Add the dedicated Phase 1.5 config flags.
2. Add a `DraftMessenger` wrapper around `sendMessageDraft`.
3. Extend the provider interface to support streamed text deltas.
4. Update the OpenAI adapter to consume streamed `Responses API` events.
5. Update the chat service to coordinate draft lifecycle, final send, and fallback.
6. Add logs and metrics for draft usage.
7. Add automated tests and manual verification coverage.

## Test Plan

### Unit tests

- streamed provider deltas are coalesced into throttled draft updates
- the same `draft_id` is reused for successive updates within one response
- final assistant text is persisted, but partial draft text is not
- draft send failure falls back to final-only send
- `/reset` cancels the in-flight draft session

### Integration tests

- text message flow with streamed partial updates and final reply
- image-plus-caption input still produces text draft updates and final text reply
- provider timeout after draft start returns the standard retry message
- restart-and-recover flow does not replay partial assistant text

### Manual verification

- send a long text prompt and confirm animated partial updates appear
- confirm fast prompts skip drafts and still send a normal final message
- confirm the final message arrives once and the draft disappears
- send `/reset` during a long-running generation and confirm the old draft stops
- confirm unsupported message types never trigger draft streaming
- confirm unauthorized users never trigger draft streaming

## Exit Criteria

Phase 1.5 is done when:

- an allowed private-chat user can see partial assistant text while a long reply is generated
- the final assistant text still arrives as a normal Telegram message
- fast replies can skip draft mode without regression
- draft-send failures degrade safely to the Phase 1 final-only behavior
- no partial assistant text is persisted in SQLite
- manual verification confirms draft cleanup behavior in real Telegram clients

## Open Questions

- Does the Bot API final send path always clear or replace the visible draft in all Telegram clients, or is an extra cleanup step needed?
- Are there undocumented practical rate limits for repeated `sendMessageDraft` calls in one private chat?
- Should Phase 1.5 stream image-understanding replies immediately, or start with text-input replies only?
- Should the first rollout keep draft text plain only, or allow formatted entities once cleanup and cadence are proven stable?

## References

- Telegram Bot API `sendMessageDraft`: https://core.telegram.org/bots/api#sendmessagedraft
- Telegram message drafts overview: https://core.telegram.org/api/drafts
- Telegram bots overview: https://core.telegram.org/bots
- aiogram `sendMessageDraft`: https://docs.aiogram.dev/en/latest/api/methods/send_message_draft.html
- OpenAI Python streaming examples: https://github.com/openai/openai-python/blob/v2.11.0/README.md
