# Phase B — B10/B12 Real Generation Tracking & Cancellation

**Integration branch:** `claude/b01-b16-backend-integration-2026-10-24` (isolated worktree at `/tmp/orneur_integration_work`, not pushed to any protected branch), based on PR #98 `22d9ec4c` merged with this branch's own frontend baseline `66af5f0`. One real, intentional merge conflict in `orca/serve/api.py` (background knowledge-graph extraction: this branch's GC-safety fix combined with PR #95-98's temporary-chat skip — both kept, neither discarded).

## What was implemented

- **Real generation identity**: `sendMessage()` resets `_activeGenerationId`/`_activeGenerationCancellable` at the start of every attempt (including a user-initiated Retry, which is its own fresh attempt per B12's existing philosophy); `processLine()` gets a new `case 'generation'` that captures `generation_id` and `cancellable` from the new SSE event, which arrives right after `session` — confirmed live via a real stream capture, not assumed from docs.
- **`Idempotency-Key` header**: a fresh `crypto.randomUUID()` per attempt. Its job is narrower than "is this a retry" — it protects against a lower-level duplicate delivery of the *same* attempt (a double-click before `updateSendEnabled()` disables Send, or a network-level resend of the identical POST), never across distinct attempts; reusing a key across attempts would incorrectly 409 `generation_not_reusable` once the first reaches a terminal state, per the contract.
- **Real `stopGeneration()`**: now `async`. When a cancellable `generation_id` is known, it calls `POST /api/generations/{id}/cancel`, then **confirms via a real `GET`** before ever using the word "confirmed" in the UI — `cancel_accepted: true` is explicitly not treated as proof of a stop, matching the contract's own repeated warning. Four distinct, honestly-worded outcomes: `cancelled` ("confirmed cancellation"), `completed` ("finished generating... before the stop request took effect"), `failed` ("the run itself failed"), and anything else (`running`, `interrupted_unknown`, or the GET itself failing) — "has not yet confirmed... may complete independently of this device." When no generation id was ever issued (the frontier passthrough path, which the contract states never emits one) or the backend marked the run not cancellable (a replayed answer), the **exact original, unchanged honest local-abort message** is used — never inventing server-confirmed cancellation for either case.
- **Confirmed and fixed an unrelated, pre-existing bug found via this work**: `processLine()`'s `error` event handler read `ev.message`, but `PublicError.as_sse()` (`orca/serve/errors.py`) always emits the field as `ev.text`. Every real backend error was silently falling through to the generic fallback string, discarding the server's own specific message — confirmed live (a real `model_access_denied` refusal rendered as the generic fallback before the fix). This predates Phase B and was not introduced by it.

## Live verification, not just unit tests

Ran the actual merged backend (port 7346) and drove the real `sendMessage()`/`stopGeneration()` through the real composer DOM, not synthetic calls:

1. Sent a real message with `model_variant: 'nano'`; confirmed the `generation` SSE event fires with a real `generation_id`, `cancellable: true`, immediately after `session`.
2. Called the real Stop control mid-generation (before any chunk arrived). Server state immediately after: `{"state":"running","cancel_requested":true,"terminal":false}` — my code correctly rendered the honest "has not yet confirmed" message, matching the server's true state exactly at that instant.
3. **A genuinely new finding, not documented anywhere**: waited 11 seconds and re-checked the same generation. It never reached `state: "cancelled"`. It settled into `{"state":"interrupted_unknown","terminal":true,"retry_eligible":true}`. Reading the server's own `_stop_if_needed()` (checked both `cancel_requested` and `request.is_disconnected()`) explains why: once the client's `AbortController` disconnects, nothing continues driving the server's async generator forward to the point where it would next check that flag and call `generations.finish(..., "cancelled", ...)` — the generation record is orphaned at `running` and later observed as `interrupted_unknown` once its heartbeat goes stale, exactly as `GET /api/generations/{id}`'s own documented behavior says it would. **In practice, a fast cancel-before-any-chunk on this implementation essentially never resolves to a stored `cancelled` state** — it resolves to `interrupted_unknown`, which my code already treats as "not confirmed," never as success. This is disclosed here as a real backend behavior worth Cursor's attention (not a frontend defect — the frontend's handling of it is already correct), not silently worked around.
4. Confirmed via `node --check` and `python3 -c "import orca.serve.api"` that the merged branch boots cleanly; confirmed 167/167 JS tests and 13/13 Python tests pass on the merged branch.

## What was explicitly not done (named, not silently skipped)

- **Retry-after-cancel/failure using the real idempotency semantics**: B12's existing Retry button still re-populates the input and calls `sendMessage()` fresh (a new key, a new attempt) — this already matches the contract (`generation_not_reusable` only applies to literal key reuse, which this UI never does). No separate work was needed here, but it was not independently re-verified live against a `failed`/`cancelled` prior attempt in this pass.
- **Polling `GET /api/generations/{id}` while a generation is merely slow** (not stopped) — out of this phase's scope; the contract does not ask for a live progress poll, only post-cancel confirmation.
- **B14's `X-Run-Id` header** — not wired in this phase (Phase E's scope); `_activeGenerationId` tracking is a prerequisite for it and is now in place.

## Tests

```
node --test tests/frontend/*.mjs   # 167/167 passing (was 161; net +6 after replacing 2 stale structural tests with 8 new ones)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

`test_b10_stop_generation.mjs` rewritten: the old structural guard asserting no `is_disconnected()` check exists is now **inverted** into a guard confirming the real infrastructure exists and is used (the exact condition the original test's own comment anticipated and warned about). New behavioral tests cover: cancel-then-confirm ordering, the real `cancelled` success path, `cancel_accepted` alone never being presented as confirmed, a generation that completed before the cancel landed, and the unchanged non-cancellable/no-generation-id fallback.

## Honest verdict for Phase B

**IMPLEMENTED AND INTEGRATION-TESTED.** Not independently qualified, not production authorized (per the addendum's required three-state distinction). Real generation tracking, real server-authenticated cancellation with real confirmation (never inventing a "Stopped" state from `cancel_accepted` alone), and real Idempotency-Key handling are in place and live-verified against the actual merged backend, including a genuine, previously-undocumented behavior (cancel-before-any-chunk settles to `interrupted_unknown`, not `cancelled`) that the frontend already handles correctly without needing a workaround.
