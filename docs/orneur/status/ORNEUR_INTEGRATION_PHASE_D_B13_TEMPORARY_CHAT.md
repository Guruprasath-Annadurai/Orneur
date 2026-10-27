# Phase D — B13 Real Temporary Chat

Per the CTO's Phase C-I Continuation Directive, using Cursor PR #95-98's real routes (verified by reading `orca/serve/api.py` directly, then live end-to-end against the actual merged backend).

## What changed

The prior honest disabled-state implementation correctly reflected that no backend existed. Reconnected the same approved dialog shell (not redesigned): `#temp-mode-prestart` is the original "Before you start" content with its copy corrected to match real, now-true behavior instead of "proposed"/"not yet verified" placeholder language; `#temp-mode-active` is new, added only for the state the original design never needed to show (a session that's actually running), reusing the exact same `.temp-mode-rule`/`-sub`/`-footnote`/`-actions` components.

## Implemented

- **Start**: real `POST /api/sessions/temporary` with a fixed 1-hour default TTL (the approved design has no TTL picker control; 3600s is always inside the real 60-86400s valid range). Only a genuine `state: "active"` response is treated as success.
- **Active-session indication**: the header "Temporary" pill gains a `· Active` label and a Solar Coral accent when `_isTemporarySession` is true — a real, server-confirmed state, not a client-side guess.
- **Close**: real `POST .../temporary/close`. Only `state: "closed"` or `state: "expired"` is treated as success; a real `state: "failed"` (a deletion that leaves the transcript, per the contract's own explicit warning) shows an honest failure message and leaves the session marked active so the user can retry — never silently reported as closed.
- **Expired-session behavior**: `sendMessage()` now distinguishes a real `409` `temporary_expired`/`temporary_closed` refusal (returned before any SSE stream starts, confirmed by reading `/api/stream`'s route body — the model is never called for this refusal) from a generic failure, and resets the active indicator since the session is genuinely gone.
- **Distinguishing temporary from normal**: `newConversation()` and `openSession()` both reset `_isTemporarySession` — correct because the backend itself excludes an active temporary chat from `GET /api/sessions`/search, so every `sid` reaching `openSession()` is structurally guaranteed non-temporary.
- **Export blocked honestly**: `exportConversation()` now surfaces the real server error text instead of a generic "Export failed," which naturally and correctly surfaces the real `409 temporary_not_exportable` reason without any special-casing.
- **Honest retention copy, not weakened**: states plainly that the transcript exists on the server until close/expiry (not zero-persistence), names what it does cover (long-term memory, search, export, history) and what it explicitly does not (backups, logs outside this conversation, the process already serving the chat) — matching the handoff doc's own corrections to the prior "proposed"/"not yet verified" placeholder language, now that the behavior is real and verified.

## Live verification, not just unit tests

Ran the actual merged backend end-to-end through the real UI:
1. Opened the dialog, clicked the real (now-enabled) Start button. Confirmed: `_isTemporarySession` became `true`, the real returned `session_id` was adopted, the header pill showed "Temporary · Active".
2. Independently confirmed via `GET /api/session/{id}/temporary` that the server genuinely shows `state: "active"` with the correct `ttl_seconds`/`expires_at`, and via `GET /api/sessions` that it is genuinely absent from the normal conversation list.
3. Clicked the real Close button. Confirmed `_isTemporarySession` reset to `false`, `sessionId` reset to `null` (a fresh `newConversation()`), header pill reverted to "Temporary".
4. Independently confirmed via a fresh `GET /api/session/{id}/temporary` that the server genuinely transitioned through `closing` → `closed` (full `transitions` history returned), not merely that the client believed it.
5. Screenshotted the real "Before you start" panel in Meridian Light — clean, honest copy, correctly enabled Start button, no visual regression from the approved design.

## Tests

```
node --test tests/frontend/*.mjs   # 191/191 passing (was 184; test_b13_temporary_chat.mjs rewritten: 14 tests, was 6)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

`test_b13_temporary_chat.mjs` is entirely rewritten (old premise now false): real start/close success-condition guards, the `failed`-state-is-never-reported-as-closed guard, the honest-copy guard (asserts the real retention language, asserts no zero-persistence claim), the 409 expiry-handling guard in `sendMessage()`, the export-honesty guard, and behavioral tests for both dialog sub-views (prestart vs. active) and the header indicator.

## Honest verdict

**IMPLEMENTED AND INTEGRATION-TESTED** (not independently qualified, not production authorized). Start, active-state indication, close, expiry handling, and honest retention disclosure are real, live-verified against the actual merged backend's genuine state transitions (not just HTTP status codes), and tested.
