# B11 Requalification — Cancel-during-save, 500-after-commit, ambiguous-reopen

Per the CTO's "ORNEUR — CTO Engineering Continuation Directive," step 2: *"Examine Cancel during an in-flight or uncertain save, closing/reopening after ambiguous outcomes, idempotency keys after retry, and server-error responses that may follow a committed write. Ensure that no uncertain result is falsely described as a definitive failure and that retry behavior cannot silently create duplicates."*

All four named scenarios were investigated against the real backend source (not assumed). Idempotency-keys-after-retry was already sound from the prior correctness-hardening pass and needed no change. The other three had real, confirmed gaps, now fixed.

## New finding: a 500 can only mean a post-commit crash

Reading `edit_session_message()` in `orca/serve/api.py` directly: it calls `message_versions.edit()` (which durably commits the new version under a real per-message lock in `orca/serve/message_versions.py`), and then, only if `view.get("created")`, calls `_replace_visible_copy()` — with **no enclosing try/except of its own** (only one inner call, `sess.persist_to_redis()`, is guarded). An exception anywhere else in that function (e.g. iterating `agent._history` or `sess.memory.short._messages`) surfaces as an unhandled 500 to the client **after the edit has already been durably committed**.

Cross-confirmed via `_message_version_error()`'s complete status-code mapping: every genuine pre-commit validation failure (empty/too-long content, `message_not_found`, a real `idempotency_mismatch`, `regeneration_in_progress`, version history full) maps exclusively to 400/404/409/422. A 500 from this endpoint is never a pre-commit rejection — it can only be a post-commit crash.

The prior code treated **every** non-ok HTTP status identically as a definitive rejection (clearing the pending idempotency key, showing "could not be saved"). That was wrong for 500: it risked telling the user an edit failed when it may have already landed.

## Fixes (`orca/serve/web/conversation.html`, inside `appendUserMessage()`)

1. **500 (or any unexpected ≥500/0 status) is now treated as ambiguous**, exactly like a thrown network error: it falls through to the same one-shot automatic same-key retry, and if still unresolved after that, shows the same honest "Could not confirm..." copy — never "could not be saved." A genuine 400/404/409/422 is unaffected and still shown as a real, definitive rejection with the server's own error text.

2. **Cancel is now genuinely disabled while a save is in flight.** Previously nothing stopped a user from clicking Cancel mid-request (clearing the pending key, closing the panel) while the fetch promise was still running; if it later resolved as a real success, `applyEditSuccess()` would still fire and mutate the displayed bubble — a real violation of Cancel's "no mutation" guarantee. `cancelBtn.disabled` is now set alongside `saveBtn.disabled` at the start of the save attempt, re-enabled in the same `finally` block regardless of outcome, and the click handler itself also checks `if (cancelBtn.disabled) return;` as defense-in-depth (not relying solely on the browser honoring the attribute).

3. **Reopening the edit panel after an unresolved (ambiguous) attempt now shows that pending draft**, with an explanatory note, instead of silently reverting to the last confirmed text. The toggle-close branch of `editBtn`'s own handler never went through `closeEdit()`/Cancel's key-clearing logic, so a pending key could still be tracked internally while the textarea showed stale confirmed text on reopen — safe from a duplicate-creation standpoint (content-keyed reuse still works regardless), but not honest about the ambiguity. On open, if `_pendingEditKey` is set, the textarea now shows `_pendingEditContent` and the error banner explains an earlier attempt is unresolved.

## Tests

```
node --check <extracted inline script>   # syntax OK
node --test tests/frontend/*.mjs          # 222/222 passing (was 217; +5 new)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

Five new tests added to `test_b11_inline_edit.mjs`:
- a 500 is treated as uncertain (automatic retry, same key, honest copy, panel stays open)
- two 500s followed by a later manual same-key retry that succeeds is reported as the real success, never as having already failed
- a genuine 409 (`idempotency_mismatch`) is still a real, definitive failure — confirms the 500 special-case didn't swallow genuine rejections
- Cancel is genuinely disabled during an in-flight save; a click while disabled is a no-op; an in-flight success the user tried to cancel still applies once it resolves (since Cancel never got the chance to intervene — the entire point of disabling it)
- reopening after an uncertain outcome shows the pending draft and explanatory note, not the stale confirmed text

## Live verification (not just unit tests)

Exercised the real UI against the live integration backend (port 7346): sent a real message, opened the real Edit panel, and — since `fetch` is the only seam between the client and server for this endpoint — monkey-patched `window.fetch` to return a real `500` response for `.../edits` calls only (every other call, including the real `/api/stream` exchange that preceded it, went through the real backend unmodified). Confirmed directly against live DOM state:
- Two 500 responses both carried the identical `Idempotency-Key` header.
- `Cancel` was disabled the instant Save was clicked (checked synchronously before any response arrived).
- After both 500s, the error banner read the exact honest "Could not confirm..." copy, the panel stayed open, and `Cancel` was re-enabled.
- Closing and reopening the panel surfaced the pending draft and the "never got a confirmed result" note instead of the stale confirmed text.
- Restoring the real success path and clicking Save again produced a genuine close + confirmed-text update, confirming no regression to the ordinary success flow.

## Honest verdict

**FIXED AND VERIFIED** for the three real gaps found (Cancel-during-save, 500-as-uncertain, reopen-shows-pending-draft). Idempotency-keys-after-retry required no change — already authoritative via the backend's own `_find_key()` lookup. All changes are additive to the existing retry/ambiguity machinery; no existing passing test was altered to make this pass (217/217 prior tests are byte-for-byte unchanged and still green).

This does not fix the underlying server-side gap (`_replace_visible_copy()` still has no enclosing try/except in `orca/serve/api.py`) — that is Cursor's backend code, out of scope for a frontend-only consolidation branch, and is recorded here as a residual risk for the independent review: **a 500 from this endpoint should ideally never happen post-commit; the frontend now handles it honestly when it does, but the backend crash itself is still a real defect worth fixing upstream.**
