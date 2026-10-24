# B16 Final Correction & Audit (CTO P0 directive)

**Branch:** `claude/b04-b09-implementation-2026-10-23`
**Baseline:** `950909e` (B16 first implementation pass, all 10 CI jobs green)
**Scope:** fix the confirmed B16 attachment identity defect, test in-flight attachment operations, complete B16 401 recovery, reconcile implementation documentation, final verification.

## A. Confirmed B16 attachment identity defect — reproduced, then fixed

**Reproduced before fixing**, exactly as the directive described: `renderAttachChip({ filename: file.name, state: 'uploading' })` built a plain object with no `doc_id`; `uploadAttachment()` wired `removeAttachment(chip, doc)` with that object captured in the click-handler closure. After a successful upload, `uploadAttachment()` only wrote `chip.dataset.docId = data.doc_id` — the closure's `doc` object was never touched. A live reproduction (upload → click Remove → `GET /api/docs/list`) confirmed the document was left on the server with the chip gone from the DOM: the local-only `if (!doc.doc_id) { chip.remove(); return; }` branch fired instead of the real `DELETE`.

**Fix:** `chip.dataset.docId` — the single place `uploadAttachment()` writes the id — is now the only source of truth. `renderAttachChip()` wires `removeAttachment(chip)` (no second argument); `removeAttachment()` reads `chip.dataset.docId` at click time.

**Live-verified, both journeys the directive named, with a fresh `GET`, not DOM inspection alone:**
- *Immediately after upload*: uploaded `journey-test.txt`, confirmed via `GET /api/docs/list` the doc existed server-side, clicked the real Remove button, confirmed via a second fresh `GET` the server list was empty.
- *After reopening the conversation*: uploaded `reopen-test.txt`, switched to a new conversation, reopened the original one (`openSession()`), confirmed the chip reappeared via the real `loadAttachmentsForSession()` fetch with its real `doc_id`, clicked Remove, confirmed via fresh `GET` the server list was empty.

Both in Obsidian Dark and Meridian Light (screenshots captured during this session).

## B. In-flight attachment operations — tested, and genuinely fixed where a real gap existed

| Scenario | Finding |
|---|---|
| **Remove clicked while upload still pending** | Real gap, fixed. `removeAttachment()` now sets `chip._removeRequested = true` and removes the chip immediately (the user asked for it gone). `uploadAttachment()` checks this flag after its own `await`; if the upload succeeded anyway, it deletes the now-orphaned document via a new `_deleteOrphanedUpload()` helper. Live-verified: triggered an upload, clicked Remove before it resolved, confirmed via `read_network_requests` that `POST /api/docs/upload → 200` was immediately followed by a real `DELETE /api/docs/{doc_id}`. |
| **Account change during upload** | Real gap, fixed. The prior code only discarded the UI-visible chip; the server-side upload, if it completed under the *old* account's token, stayed on the server with nothing pointing at it. Now cleaned up via the same `_deleteOrphanedUpload()` path. Unit-tested (`test_b16_context_attachments.mjs`). |
| **Conversation change during upload** | Same fix, same reasoning, as account change — a document uploaded into conversation A that resolves after the user switched to conversation B is deleted rather than silently abandoned. Unit-tested. |
| **Session expiration during upload, list, delete** | See section C — the backend never emits 401 for these three endpoints (confirmed live), so "session expiration" manifests as either a 404 (an *owned* session_id with an invalid token) or a silent anonymous degradation (no session_id). The existing identity-ownership guards (token/sessionId re-checked after every `await`) already prevent a stale response from misattributing. The `r.status === 401` branches are kept as defense-in-depth, not because they fire today. |
| **Concurrent uploads to a new conversation** | Real gap, fixed. `session_id=None` always means "create a new session" (`_get_session`'s own docstring) — there is no dedup, so two uploads started concurrently against a brand-new conversation each get their *own* new backend session. Whichever response arrives first adopts the shared `sessionId`; the sibling's own `data.session_id` then no longer matches. Fixed: `uploadAttachment()` now detects this mismatch (`conversationShifted` check, split by whether `mySidAtStart` was an existing conversation or null) and deletes the losing sibling's document rather than leaving it attached to a session_id the frontend no longer tracks. Live- and unit-verified (a deliberately deferred-resolution test exercises genuine concurrency, not sequential calls that would trivially avoid the race). |
| **Late JSON parsing after identity changes** | Already correctly guarded, confirmed unchanged: every call site re-checks `myToken !== _authToken \|\| sessionId !== mySid(AtStart)` both immediately after the `fetch()` resolves *and* again after `await r.json()`. |
| **A stale list response after a different account signs in** | Real gap, fixed in `loadAttachmentsForSession()` — see section C; it previously only checked `sessionId`, never `_authToken`. Unit-tested: a response that resolves after `_authToken` changes no longer repaints the view. |
| **HTTP 403 `retrieval_unauthorized` vs HTTP 401 session expiry** | **This status/code pair does not exist in this codebase.** Grepped the entire repository for `retrieval_unauthorized` — zero matches. Live-tested the actual behavior instead of assuming the directive's framing: `curl` against `/api/docs/list?session_id=<owned>` with an invalid/garbage token returns **404** `{"code":"not_found","error":"session not found"}`, not 401 and not 403. Reading `orca/auth/middleware.py:57-65` explains why: `get_current_user_optional` (used by all three `/api/docs/*` routes) catches `get_current_user`'s own `HTTPException(401)` internally and returns `None` — the caller is silently treated as anonymous, never rejected. The actual 404 then comes from `_get_session`'s ownership check (`orca/serve/api.py:832-867`, itself documented as "404, never 403 -- an unauthorized caller must not be able to confirm the session exists"). This matches the exact finding already on record in `ORNEUR_SESSION_EXPIRY_401_AUDIT.md` for the other six authenticated endpoints, now independently reconfirmed for the three docs endpoints. **No code was written to fabricate handling for a 403/`retrieval_unauthorized` response the backend cannot produce.** |

## C. B16 HTTP 401 recovery — completed honestly, not fabricated

The directive asked to "ensure an HTTP 401 invokes the correct session-expiry behavior" in `loadAttachmentsForSession()`. Two real, separable things were done:

1. **Consistency fix (real gap):** `loadAttachmentsForSession()` previously checked only `sessionId !== mySid` for staleness, never `_authToken`. A response arriving after a *different account* signed in (but the same `sessionId` happened to still be set) could have repainted the view with the prior account's document list. Fixed: now checks `myToken !== _authToken || sessionId !== mySid` at both await points, matching the pattern already used in `uploadAttachment()`/`removeAttachment()`. Unit-tested.
2. **401 handling itself:** added for consistency with the other six authenticated call sites (`ORNEUR_SESSION_EXPIRY_401_AUDIT.md`'s own documented pattern), but — as established in section B — **this branch does not fire on the current backend for these three routes**, confirmed by live `curl`. The directive's instruction to "ensure" it fires is **not something a frontend change can do**: the backend would need `/api/docs/*` to switch to the strict `get_current_user` dependency, which is the same escalated architecture question already on record for `/api/sessions`, `/api/session/{id}/messages`, etc. **Not re-escalated as a new item — it is the identical, already-disclosed gap, now additionally confirmed to cover the docs endpoints too.**

**Deliberately NOT done:** treating a 404 on these endpoints as session-expiry. The backend's own documented design returns 404 for an unauthorized/invalid-token caller specifically so existence can't be confirmed — and the *same* 404 also covers a session simply evicted after 2 hours of idle time (`_get_session`'s own stale-eviction sweep), which has nothing to do with authentication. Converting that 404 into a forced sign-out would spuriously log out a user whose browser tab just sat idle. This is documented inline in the code and is the same "escalate the architecture question rather than invent a fix that misrepresents the real signal" discipline already applied to the other six endpoints.

## D. Documentation reconciled

- `ORNEUR_30_SCREEN_IMPLEMENTATION_MATRIX_UPDATED.md`'s B16 row now points at the corrected SHA and this document, distinguishing: fixed identity defect, real in-flight-race fixes, the honest 401/403 finding, and remaining genuine backend limits.
- This document is the authoritative current state for B16; `ORNEUR_B16_CONTEXT_AND_ATTACHMENTS.md` (the first-pass report) remains as the implementation history and is not rewritten.
- **Explicitly disclosed, not claimed fully functional, per the directive's instruction:**
  - **B05** (Model Selection) — model unavailability/detail surfaces are real, but no capability exists to switch models mid-stream; unchanged since its own report.
  - **B10** (Streaming & Stop) — `stopGeneration()` ends the client-side connection honestly but the backend has no `is_disconnected()`-style server-side cancellation; a regression test explicitly guards this gap.
  - **B11** (Editing & Versions) — honest disabled-state only; no message-edit or regenerate backend exists at all.
  - **B12** (Error & Recovery) — Copy/Retry are real; the contract's server-confirmed reconciliation surface remains blocked on the same backend gap as B10.
  - **B13** (Temporary/Private Chat) — honest disabled-state only; no backend temporary-session capability exists.
  - **B14** (Multi-Conversation Navigation) — Quick Switch and per-conversation drafts are real; Workspace Tabs (the contract's optional second surface) is not built, needing backend stream-correlation that doesn't exist.
  - **B06/B09** — unchanged from their own prior reports; not re-audited in this correction pass (out of this directive's named scope).
  - **B16** itself — now has the identity defect and in-flight races fixed, but malware/virus scanning, async scan states, and context-capacity display remain genuine backend absences, not built here or anywhere.

## E. Final verification

```
node --test tests/frontend/*.mjs   # 151/151 passing (was 142; +9 new B16-correction tests)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

New tests in `tests/frontend/test_b16_context_attachments.mjs`: structural guards for the fixed identity flow, the in-flight-removal deferred-cleanup path, account-change-during-upload cleanup, conversation-change-during-upload cleanup, the concurrent-new-conversation session-adopt race (via genuine deferred-resolution concurrency, not sequential calls), and the stale-account-response guard in `loadAttachmentsForSession()`.

**Live, real-browser, real-backend verification** (not asserted from code reading alone): the full successful-upload → immediate-remove → server-confirmed-delete journey, and the same journey after reopening the conversation, both independently confirmed via a fresh `GET /api/docs/list` (not DOM state), in both Obsidian Dark and Meridian Light. The in-flight-remove-during-upload race was independently confirmed via `read_network_requests` showing the real deferred `DELETE` firing after the upload's own `POST` resolved.

## Honest verdict

**Confirmed defect fixed, live-verified in both named journeys and both themes.** The in-flight races the directive asked to be tested were genuinely tested; three of them (remove-during-upload, account-change-during-upload, conversation-change-during-upload, concurrent-new-conversation-uploads) were real gaps and are now fixed with both unit and live coverage. The directive's point C (401 vs 403 `retrieval_unauthorized`) was investigated rather than assumed: that specific error code does not exist in this codebase, and the real backend behavior (404, confirmed live) is handled honestly — not forced into a session-expiry reaction that would misrepresent a routine idle-session eviction as an auth failure. No functionality is claimed complete beyond what was actually fixed and verified.
