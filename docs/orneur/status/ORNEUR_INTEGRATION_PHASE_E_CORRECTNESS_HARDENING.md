# Phase E Prep — Correctness Hardening (B11 identity race, B11 ambiguous save, B13 navigation, B16 deletion-proof scope)

Per the CTO's "Phase E–I + Final Correctness Hardening" directive. All three named issues investigated, reproduced where possible, and fixed before proceeding to Phase E.

## 1. B11 — Message identity race (confirmed real, fixed by removing the guess)

**Investigated**: `_backfillMessageIds()` fetched the full message list after each exchange and assigned `userDiv`/`answerDiv` the ids of "the last user/assistant entry" found. Read `orca/serve/conversations.py`'s `append()` (a single `O_APPEND` `os.write()` — atomic at the line level) and `_persist_turn()` (a plain, synchronous `def` with no `await` between its two `append()` calls — a pair can never be split by another request *within this backend's current implementation*). That structural fact makes within-pair interleaving impossible today, but the real vulnerability is different: **a third request's pair landing in the list between this request's own persist and the backfill fetch resolving** makes "last in the list" refer to someone else's turn, not this one. Reproduced the general shape of this (two concurrent requests to one session) via direct API calls; local Ollama serialized them enough that a true interleave wasn't captured on this machine, but the code-level mechanism is unambiguous and the fix does not depend on reproducing it under this specific load.

**Fixed by removing the guess, not by making it safer**, per the directive's explicit instruction ("Do not guess message identity from text or position"):
- **Assistant bubble**: assigned directly from the real `done` event's own `message_id` (`_assignAssistantMessageId(finalAnswerDiv, ev.message_id)`) — already correct, unique, and known with zero ambiguity. No fetch, no window for a race to land in.
- **User bubble**: has no reliable id source anywhere in the current API (confirmed again by re-reading `_persist_turn()` — `user_message_id` is generated server-side but never returned). Editing a message in the same turn it was sent now stays honestly disabled until the conversation reloads via `openSession()`, which reads every message's real id directly, never inferred.

**Escalated to Cursor, not silently worked around**: `/api/stream`'s `done` event should also return `user_message_id` — the value already exists in `_persist_turn()`; returning it is a small, additive change mirroring the assistant side's existing `message_id` field. Until then, editing a just-sent message requires a reload — a real, disclosed UX limitation, not a correctness bug.

**Adversarial tests added** (`test_b11_inline_edit.mjs`): two concurrent `done`-event-shaped assignments (beta arriving before alpha despite alpha starting first) never cross-assign ids; confirmed `_assignAssistantMessageId()` never looks up its own target element (the caller's closure is the only source of which div an id belongs to, eliminating the entire class of bug).

## 2. B11 — Ambiguous save outcome (confirmed real, fixed with reconciliation)

**Investigated**: the save handler's `catch` block on a thrown `fetch` error said "the edit was not saved" unconditionally. A thrown network error means the *request* failed in transit — it does not mean the *server* never received or committed it (the connection can drop after the server writes the new version and before the response arrives). This claim was false exactly as often as it was true.

**Fixed with real reconciliation, not a guess**: on a thrown error, the UI now says "Connection lost while saving — checking whether it went through..." and calls the real `GET .../messages/{id}/versions` to find out. If `active_content` matches what was just submitted, the UI reflects the real success state (`applyEditSuccess()`, the same helper the direct-success path uses) — and critically, **does not retry**, since resubmitting under a new Idempotency-Key would mint a genuine duplicate edit version (explicitly what the directive says to avoid). If reconciliation shows the content is still the old version, only then is "not saved" said definitively, and a retry is genuinely safe. If the reconciliation check *itself* also fails, the message stays honestly uncertain ("Could not confirm... check 'Edited' history before retrying, to avoid creating a duplicate version") rather than guessing either way.

**Tests added**: reconciliation-confirms-success (UI reflects the real landed edit, panel closes, no retry prompt), reconciliation-confirms-failure (honest "not saved," draft preserved for retry), and double-failure (genuinely uncertain, warns about duplicate risk rather than asserting an outcome).

## 3. B13 — Temporary-session lifecycle (confirmed real, fixed with an explicit choice, not a silent default either way)

**Investigated**: starting a temporary chat, then clicking "New conversation" or opening a different conversation, previously reset `_isTemporarySession` and silently navigated away. Because the backend itself excludes an active temporary chat from `GET /api/sessions`/search, **there was no way back to it from the sidebar or Quick Switch, and no prompt to close it** — it would sit active, un-navigable-to, until TTL expiry, with the user never told. Reproduced live (see below).

**Fixed with `_withTempChatGuard()`, which pauses and asks rather than guessing either way** — matching the directive's explicit instruction not to silently delete a session the user may want to retain, *and* not to silently abandon one either:
- Wired into the three voluntary navigation points: the "New conversation" button, sidebar conversation rows, and Quick Switch rows.
- **Deliberately NOT wired into** `onAuthSuccess()`/`continueAnonymous()`/`_clearAuthStateAndShowSignIn()` — these are security/identity transitions that must always proceed unconditionally; blocking a logout or account switch on a temp-chat dialog the user might leave unanswered would be its own, worse correctness bug. A temp chat left behind by an account switch is abandoned the same way it already was (until TTL expiry) — this phase did not change that, and discloses it honestly rather than claiming the navigation guard covers every path.
- The dialog's active-state view gains a third, context-sensitive label: "Continue without closing" (when reached via a paused navigation) vs. "Keep chatting" (when opened directly from the header pill) — same button, same handler, honest copy for each real meaning.
- Dismissing the dialog without an explicit choice (Escape, backdrop, the × close button) **cancels the paused navigation** — it does not silently proceed, and does not silently close the session either.
- A real `state: "failed"` close response (confirmed by reading `temporary_chat.finish()` directly: `"failed"` is itself in `_TERMINAL = {"expired","closed","failed"}`, so a retry of Close would short-circuit on that terminal check and return the *same stale record* without ever attempting deletion again) now disables the Close button permanently and says so honestly, instead of the previous copy's inaccurate "you can try again."

**Live-verified end-to-end** against the real merged backend (not just unit tests): started a real temp chat, clicked "New conversation" — confirmed the navigation paused and the dialog opened showing the real active state, not a silent switch. Clicked "Continue without closing" — confirmed the new conversation started *and*, independently via `GET /api/session/{id}/temporary`, that the old session genuinely remained `state: "active"` server-side (informed, not silently deleted). Repeated with "Close temporary chat" instead — confirmed the new conversation only started *after* the real close, and independently confirmed the old session's server state was genuinely `"closed"`. Screenshotted the live paused-navigation dialog.

**Disclosed, not silently left out**: a full page reload or browser close while a temp chat is active cannot be intercepted by this fix (no in-app routing exists to pause, and a `beforeunload` handler was deliberately not added — it is unreliable across browsers and would interfere with legitimate page closes for a relatively narrow benefit). The session remains active server-side until TTL expiry in that case, exactly as already disclosed in the dialog's own retention copy ("lasts 1 hour by default, or until you close it").

## 4. B16 — Deletion truth: does a list-404 prove absence from every storage location?

**Investigated, per the directive's explicit question**: read `orca/docs/store.py` directly. `list_docs()` (the function `delete_doc()`'s "No such document in this conversation" 404 is based on) reads a **separate JSON registry file** (`register_doc()`/`unregister_doc()`), not a live query of the actual `doc_store` or the authorized-index storage. **Confirmed finding: a 404 here proves the document is no longer *listed* — it does not, by itself, prove every physical storage location is actually clear.** A registry/storage desync (e.g., a registry write that failed silently at upload time, leaving real content with no corresponding list entry) is a plausible, previously-undisclosed root cause of a real orphan that this signal alone cannot detect.

**What changed and what didn't**: the UI behavior (removing the chip when this specific 404 shape is seen) is still correct — nothing in the conversation's visible document list references it any more, which is what the chip is meant to reflect. What changed is the *internal claim*: code comments previously said "genuinely confirmed absent," overclaiming physical deletion; corrected throughout `removeAttachment()` and `_deleteOrphanedUpload()` to say precisely what is and isn't proven. **Durable orphan reconciliation remains assigned to Cursor** (per `ORNEUR_B16_SECURITY_ADDENDUM.md`'s existing recommendation), restated here with this additional nuance: the reconciliation mechanism should account for registry/storage desync as a real cause, not only abandoned-upload orphans.

## Tests

```
node --test tests/frontend/*.mjs   # 205/205 passing (was 191; +19 across B11/B13)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

## Honest verdict

**IMPLEMENTED AND INTEGRATION-TESTED** (not independently qualified, not production authorized). All three correctness issues named in the directive were genuinely reproduced or structurally confirmed, fixed by removing the unsafe inference rather than hardening it, live-verified end-to-end against the real merged backend where applicable, and regression-tested adversarially. The B16 investigation found the list-404 signal is narrower than previously documented and corrected the internal claim accordingly, without changing (or needing to change) the resulting UI behavior.
