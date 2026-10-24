# B10 — Streaming & Stop: Partial Implementation Report

**Branch:** `claude/b04-b09-implementation-2026-10-23`
**Source:** `APPROVED_SOURCE_ARCHIVES/ORNEUR_B10_FINAL_LOCK_AND_HANDOFF.zip` (SHA-256 `9920792a3112c98350a8e4d36e394df6d97ac2446c6ddb02c78a4ec4f75d9a06`) — verified via the archive's own `verify_handoff.py`: 53/53 files + 37/37 screenshots passing, before any code was written.

## The contract's central demand, and why most of it is backend scope

`docs/B10_IMPLEMENTATION_CONTRACT.md` specifies a full race-hardened state machine (`idle → requesting → streaming → stop_requested → stopped_confirmed / completed_confirmed / interrupted_unknown / failed`) with server-authoritative cancellation: *"Resolve using the authoritative terminal event, not whichever client promise settles first... A mere HTTP 200 on a cancel request acceptance is not proof work stopped... Cancelling the browser request alone is not sufficient if backend execution/tool calls remain active."*

This requires backend changes this phase did not make: `orca/serve/api.py`'s `/api/stream` handler (grepped directly) has no `request.is_disconnected()` check and no dedicated cancel endpoint that returns a server-acknowledged terminal state keyed to a generation ID. Building the full contract's state machine without that would mean either (a) fabricating a "Stopped" confirmation the backend cannot actually back up — exactly what the contract repeatedly prohibits — or (b) silently inventing the backend cancel endpoint myself, which the CTO directive explicitly forbids ("Coordinate with backend... do not independently rewrite [backend]-owned ... code" is the same principle already applied to the session-expiry/401 backend gap this phase). Neither is acceptable, so this is reported as a genuine, disclosed blocker rather than worked around.

## What was implemented: an honest client-side Stop, reusing what already existed

This codebase already had the right internal mechanism — `_abandonActiveStream()` (aborts the client fetch via `AbortController`, with its own pre-existing comment stating plainly: *"This does NOT prove the backend stopped generating or running tools"*) — but no user-facing control ever called it. This phase:

1. **Made the composer's send button double as Stop while streaming.** A common, well-understood pattern (the same control sends while idle, stops while active); `updateSendEnabled()` now swaps its icon, `aria-label`, and `title` between "Send message" and "Stop generating response", and keeps the button **always enabled while streaming** (a pending stop must stay reachable, unlike the normal text/model-dependent disabled state).
2. **`stopGeneration()`**: calls the existing `_abandonActiveStream()`, then honestly labels the result. If content had already started streaming, it reuses the *existing* `markMessageInterrupted()` badge (now accepting an optional `reason` override) rather than inventing a new, more confident-sounding label. If generation was still in the "Thinking" phase with nothing shown yet, the placeholder is removed and an honest note appears: *"Generation stopped on this device. The response may still be completing on the server; a confirmed stop is not available from this interface."*
3. **Touch target fix**: the contract explicitly names this exact gap — *"Previous visual prototypes show 36px Stop control on desktop/tablet: production hit target and keyboard activation must meet accessibility standards without materially changing visual hierarchy."* The existing `.send` control is 32×32 CSS px. Added an invisible `-6px` inset hitbox on narrow/touch viewports, reaching the WCAG 2.2 AA 44×44 target without enlarging the visible glyph.

## Verified live, in a real browser

Selected Genesis, sent a long prompt, screenshotted the composer mid-"Thinking" with the button correctly showing a blue filled-square Stop icon; clicked it; confirmed the honest "Generation stopped on this device..." note appeared in the reading pane and the button correctly reverted to the normal disabled send-arrow state (`isStreaming: false`, `aria-label: "Send message"`).

## Tests

```
node --test tests/frontend/test_b10_stop_generation.mjs   # 8 tests, new
node --test tests/frontend/*.mjs                             # 101/101 passing (was 93)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

A structural test reads `orca/serve/api.py` directly and asserts no `is_disconnected()` check exists yet — if one is added later, this test fails, flagging that `stopGeneration()`'s honest-limitation copy needs revisiting rather than silently going stale. Another asserts the word "Stopped" never appears as a standalone terminal claim in `stopGeneration()`'s own source. Two behavioral tests exercise the real `stopGeneration()` against a minimal fake DOM for both the no-content-yet and partial-content cases; one exercises `updateSendEnabled()`'s streaming branch.

## What remains genuinely blocked, and the exact backend contract needed

Per the contract's own section D, the following is what Cursor (or whoever owns `orca/serve/api.py`) would need to add before the full B10 state machine is implementable honestly:
- A stable generation/request ID returned at stream start, bound to the authenticated user/conversation.
- A dedicated cancel endpoint (or an `is_disconnected()` check inside the existing generator loop) that genuinely halts the Cognitive Kernel/tool execution server-side, not just the HTTP response stream, and reports a real terminal state back.
- A way for the client to reconcile a `stop_requested` state against the authoritative outcome (did it actually stop, or complete anyway) rather than trusting whichever side's promise resolves first.

Until that exists, this phase's Stop control is accurately scoped to what it can truthfully deliver: stopping the browser from displaying further output, honestly labeled as such.

## What was deliberately not built, and why

- The full `idle/requesting/streaming/stop_requested/stopped_confirmed/completed_confirmed/interrupted_unknown/failed` state machine — requires the backend contract above.
- `ResponseActivityTrigger`/`ResponseActivitySurface` (the optional contextual activity popover/sheet) — a separate, larger anatomy item the contract marks optional; not attempted in this pass.
- The full 320–1920px + 200–400% zoom + RTL + high-contrast sweep (contract section F) — not run as a dedicated pass in this increment.

## Honest verdict

**`ENGINEERING PARTIAL — DOCUMENTED BLOCKERS`** for B10 specifically. A real, working, honestly-labeled Stop control now exists where none did before, reusing already-tested infrastructure rather than inventing new mechanism, with a live-verified touch-target accessibility fix the contract named explicitly. The contract's core race-hardened server-confirmed cancellation semantics remain blocked on backend work this phase correctly did not attempt to fabricate, and that gap is disclosed above with the exact API contract needed, not hidden.
