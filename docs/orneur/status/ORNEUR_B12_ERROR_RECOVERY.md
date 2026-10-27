# B12 — Error & Recovery: Partial Implementation Report

**Branch:** `claude/b04-b09-implementation-2026-10-23`
**Source:** `APPROVED_SOURCE_ARCHIVES/ORNEUR_B12_FINAL_LOCK_AND_HANDOFF.zip` (SHA-256 `9280131546e906c3694554b7a5310056f868955be6b9893aa5e03d130213929a`) — verified via the archive's own `manifests/verify_handoff.py`: 37/37 packaged files passing, before any code was written.

## Scope decision: the same honest boundary as B10

`docs/B12_IMPLEMENTATION_CONTRACT.md` specifies a `RecoveryStateAdapter` backed by "a server-authenticated status endpoint or authenticated event channel," stable authenticated request IDs, and server-validated retry eligibility — none of which exist in this backend today (the same gap already documented for B10's Stop control). Building the full `GuidedRecoverySurface`/server-confirmed reconciliation would mean either fabricating backend capability or silently inventing it, both of which the CTO directive and this contract itself prohibit. This phase implements the two concrete `RecoveryAction` items the contract names that genuinely need **no** new backend capability — **Copy** and a backend-independent **Retry** — and documents the rest as blocked, consistent with B10's report.

## What was implemented

1. **Copy, on every error note, unconditionally.** `appendUnavailableNote()` now always renders a "Copy" action (copies the exact error text — useful for support/bug reports). Purely client-side, needs no server round-trip, satisfies the contract's stated minimum ("supports Copy received text... or Retry").
2. **Retry, opt-in via an explicit `retryText` parameter.** Rather than attempting the contract's harder problem — reconciling an uncertain OLD request's fate against a server-authoritative status endpoint this codebase doesn't have — Retry is scoped to something that needs no new backend capability at all: resubmitting the **same user message as a genuinely new request**, indistinguishable from the user re-typing and re-sending the same words. This makes no claim about what happened to the failed request. Wired into every call site in `sendMessage()`'s own failure handling where resending is the sensible recovery action: the response not arriving OK, no content after a `done` event, an explicit SSE `error` event, the stream ending unexpectedly, and a network error — **not** wired into the model-unavailable note (retrying immediately can't fix unavailability) or `stopGeneration()`'s own note (that's a user-chosen stop, not a failure to recover from).
3. **`/api/stream`'s session-expiry truthfulness gap closed, for consistency.** The contract: *"A token expiring on the client must not be silently treated as backend execution failure."* `/api/stream` turned out to share the exact `get_current_user_optional` backend gap already documented in `ORNEUR_SESSION_EXPIRY_401_AUDIT.md` (confirmed by reading `orca/serve/api.py` directly — it is a seventh affected endpoint, not previously listed). Added the same `if (resp.status === 401) { _handleSessionExpired(); return; }` guard used at the other six call sites, for the same defense-in-depth reason: correct today if the backend's behavior is ever fixed, and distinguishes a genuine session-expiry from an undifferentiated "could not be completed" message right now.
4. **Neutral visual treatment**, per the contract's explicit instruction ("no borrowed blue/gold/coral UI accent or decorative alerts") — the Copy/Retry buttons use the same neutral border/muted-text tokens as the rest of the composer's secondary controls, not the app's coral/accent color.

## Verified live, in a real browser

Rendered an error note with both actions present; confirmed neutral (non-accent) styling in both themes via the existing token system. Clicked "Retry" on a simulated network-error note with `retryText: 'hello world test'`: confirmed it correctly selected the real composer, repopulated the message input, and called the real `sendMessage()` — the message appeared as a new user turn and a fresh generation began, verified via the composer's button correctly entering Stop mode (B10's control) for the new request.

## Tests

```
node --test tests/frontend/test_streaming_completion_truth.mjs   # 9 tests (was 7) -- 2 new, covering Copy-always / Retry-opt-in
node --test tests/frontend/*.mjs                                    # 102/102 passing (was 101)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

## What remains genuinely blocked, and why

Everything requiring server-confirmed terminal status or retry eligibility — the `RecoveryDetailsTrigger`/`GuidedRecoverySurface` contextual inspector, re-authenticate-and-resume flows, attachment-failure recovery (B16 itself remains `NOT STARTED`, so there is no attachment lifecycle to recover from), and the full retry/reconciliation race matrix in `B12_ERROR_STATE_AND_RETRY_MATRIX.md` — needs the same backend contract already specified for B10 (a stable generation ID, a server-authenticated status/cancel endpoint). Not attempted here, disclosed rather than hidden.

## Honest verdict

**`ENGINEERING PARTIAL — DOCUMENTED BLOCKERS`** for B12 specifically. The two backend-independent `RecoveryAction` items the contract names are now real and live-verified; the session-expiry truthfulness requirement is honored consistently across a seventh endpoint found by inspection, not assumed fixed. The contract's larger server-confirmed reconciliation surface remains blocked on the same backend work already flagged for B10, documented here rather than worked around.
