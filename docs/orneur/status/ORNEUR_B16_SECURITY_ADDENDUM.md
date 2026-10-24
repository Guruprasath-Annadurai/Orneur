# B16 Final Frontend Security & Integration Addendum (CTO P0)

**Branch:** `claude/b04-b09-implementation-2026-10-23`
**Baseline:** `92b6f15` (B16 first correction, all 10 CI jobs green)
**Scope:** stale-401 account-isolation defect, honest orphan-cleanup reporting, correction of backend-branch assumptions, compatibility testing against PR #90.

## A. Stale 401 must not sign out a newer account

**Reproduced first, exactly as directed** (Alice → Bob, Alice's pending request returning 401 after Bob signed in): monkeypatched `fetch` so `uploadAttachment()`'s POST to `/api/docs/upload` hung; started the upload as Alice (capturing `myToken = alice's token` in the closure); signed in as Bob (a real `onAuthSuccess()` call, a genuine account change) while Alice's request was still in flight; released the hung request with a simulated 401. **Result before the fix: Bob was genuinely signed out** — `_authToken`/`_authUser` cleared, even though the 401 belonged entirely to Alice's already-abandoned request.

**Root cause, confirmed by reading the code:** `uploadAttachment()`'s 401 branch computed `accountShifted` correctly but called `_handleSessionExpired()` **unconditionally**, regardless of that flag.

**Fix:** `_handleSessionExpired()` now only runs when `!accountShifted` — a 401 for a request whose principal has since changed is treated as stale and silently discarded (the chip is cleaned up locally; no auth-state mutation).

**Re-verified live after the fix, same exact reproduction:** Bob's token and user remain unchanged after Alice's stale 401 resolves.

**Reviewed every other asynchronous operation for the same issue**, per the directive's explicit instruction. All 10 `_handleSessionExpired()` call sites in `conversation.html` were audited for whether an identity/ownership check runs *before* the 401 branch:

| Call site | Status before this pass |
|---|---|
| `uploadAttachment()` | **Vulnerable — fixed** (this section) |
| `openQuickSwitch()` | **Vulnerable — fixed** (found during this same review; see below) |
| `removeAttachment()` | Already indirectly protected via `sessionId !== mySid` (every real identity transition resets `sessionId` to `null` via `newConversation()`); **explicit `myToken` check added anyway**, for defense-in-depth rather than relying on an indirect guarantee |
| `loadAttachmentsForSession()` | Already correct (fixed in the prior correction pass) |
| `sendMessage()` / `/api/stream` | Already correct — gated by `isOwner()`, which checks `myEpoch === _streamEpoch`, and `_streamEpoch` is documented as "bumped by any identity-changing navigation" |
| `loadSessions()` | Already correct — gated by `_historyResponseStillOwns(myEpoch, myToken)`, which checks `myToken !== _authToken` |
| rename commit, `exportConversation()`, `deleteConversation()` | Already correct — each explicitly checks `myToken !== _authToken` before its 401 branch |
| `runConversationSearch()` | Already correct — gated by `_searchResponseStillOwns(myEpoch, myToken, q)`, which checks `myToken !== _authToken` |
| `openSession()` | Already correct — gated by `_messageResponseStillOwns(myEpoch, myToken)`, which checks `myToken !== _authToken` |

**`openQuickSwitch()` (B14 Quick Switch panel) — a second real, confirmed gap, found during this review, not named in the directive:** had **no identity capture at all** before its `fetch('/api/sessions?limit=8')` call. Fixed the same way: capture `myToken` at request start, check `myToken !== _authToken` immediately after the fetch resolves (before the 401 branch) and again before using the response data.

## B. Orphan cleanup must report the truth

**Confirmed the directive's finding exactly:** `_deleteOrphanedUpload()` fired `fetch(...).catch(() => {})` — never inspected `r.ok`/`r.status`, never distinguished success from failure, and swallowed network errors with no trace.

**Fixed:** now `await`s the response and classifies the outcome honestly:
- `r.ok` → genuinely confirmed deleted.
- `r.status === 404` → already gone (a legitimate non-failure, e.g. a duplicate cleanup attempt) — not reported as an error.
- Anything else (401, 403, 500, or a thrown network error) → a real, unresolved failure, logged via `console.warn` with the `docId` and status/error, since there is no UI surface left to show it on (the chip is already gone by design).

**Tested 401, 403, 404, 500, and a simulated connection failure** (unit tests, `test_b16_context_attachments.mjs`): each status is classified correctly; only 404 and `ok` responses are silent, everything else logs a warning.

**Cancellation** was not separately testable beyond the network-failure case above: if the tab/process ends before the `fetch` settles, there is no JS-observable event to assert against — the request simply never completes, which is a genuine browser-level limit on what this layer can ever detect or report, not a gap this code can close.

**"Never claim server-side deletion merely because cleanup was attempted":** confirmed true of the current and prior implementation — no code path anywhere reports a user-facing "deleted" message for orphan cleanup (it was, and remains, silent by design, since there is no chip left to attach a message to). The directive's concern was about *internal* honesty (not silently assuming success for bookkeeping/logging purposes), which is what this fix addresses.

### Is a reliable backend reconciliation contract needed? **Yes — frontend-only cleanup cannot guarantee deletion.**

This is a genuine, disclosed limitation, not patched around:

- `_deleteOrphanedUpload()` is deliberately fire-and-forget (no caller awaits it — the UI has already moved on and there is nothing left to block on).
- If the DELETE itself fails (401/403/500, a network partition, or the browser tab/process ending before the request completes), **nothing retries it**. There is no client-side persistence (no localStorage-backed retry queue), and even if there were, a tab that never reopens would never flush it.
- The result: a document can be left on the server indefinitely with no remaining client-side reference to it at all once the page is closed.

**Exact backend requirement for Cursor**, in the same spirit as the already-escalated 401 architecture question: the orphan scenarios this addendum fixes client-side (remove-during-upload, account/conversation change during upload, concurrent-new-conversation uploads) are all cases where a document was uploaded but the uploading client can no longer vouch that it's wanted. A reliable fix needs one of:

1. **A server-side idle/unreferenced-document sweep** — if `orca/serve/conversations.py`'s existing `_get_session` idle-session eviction (2h) already tracks per-session liveness, extend it (or add a parallel sweep) to delete documents belonging to a session that was never otherwise used (no messages, no further activity) within a bounded window. This requires no new client contract at all — purely backend-side reconciliation.
2. **Alternatively, an idempotent `pending_cleanup` marker on upload** — accept an optional client-supplied correlation flag (e.g. `?intent=provisional`) on `POST /api/docs/upload`, and a background job that reaps documents still marked provisional after N minutes unless a client explicitly confirms them (a new, currently-nonexistent `POST /api/docs/{doc_id}/confirm` call). This is a larger contract change and is offered as the more robust alternative, not a requirement to build both.

Option 1 is recommended: it requires zero new API surface, reuses infrastructure that already exists for an adjacent purpose (idle-session eviction), and fully closes the gap without any frontend changes beyond what is already shipped in this addendum.

### "Do not silently retain unnecessary old credentials or bypass authentication to complete cleanup"

Reviewed and confirmed already correct, not changed: `_deleteOrphanedUpload(docId, sidForDelete, tokenForAuth)` always uses the **original uploader's own token** (captured as a local closure variable in `uploadAttachment()`, e.g. `myToken`), never the new/current principal's token — this is the uploader cleaning up their own resource with their own genuine credential, not a cross-account bypass. The token is a function parameter, never written to any persistent or global variable, and is eligible for garbage collection immediately after the one `fetch` call completes.

## C. Backend-branch assumptions — corrected

**The directive is right, and the prior correction's claim was branch-scoped, not general — restated precisely here:**

- **On this branch's backend** (`orca/auth/middleware.py` as it exists on `claude/b04-b09-implementation-2026-10-23`), `get_current_user_optional` silently swallows an invalid/expired token into "anonymous," confirmed live via `curl`: an invalid token against an owned `session_id` returns 404, never 401. `retrieval_unauthorized` does not appear anywhere in this branch's source (grepped).
- **On `cursor/p0-security-correction-a8b0` (PR #90, OPEN, not merged)**, both codes genuinely exist:
  - `orca/auth/middleware.py` is rewritten so a *present* Authorization header that is invalid/expired/malformed now raises a real `401` (confirmed by reading the diff: `_credentials_from_authorization_header` + the rewritten `get_current_user_optional`); a *genuinely absent* header still means guest/anonymous.
  - `retrieval_unauthorized` (403) is real, but is scoped specifically to `POST /api/chat`/`POST /api/stream`'s own `run_authorized_retrieval` gate (a revoked AuthorizedIndex document binding for signed-in document-grounded chat) — confirmed by reading `orca/serve/api.py`'s diff in PR #90 and its own docs (`ORNEUR_G9_PRODUCT_AUTHORIZED_RETRIEVAL.md`: *"403 is not session expiry. The frontend must not send the user through sign-in for `retrieval_unauthorized`."*). **It is not used by `/api/docs/upload`, `/api/docs/list`, or `DELETE /api/docs/{doc_id}`** — those three routes' only auth-related change on PR #90 is the corrected 401 behavior above, via the shared `get_current_user_optional`.

**Compatibility tests executed against a separately qualified integration candidate (PR #90), not merged into this branch:**

Checked out `cursor/p0-security-correction-a8b0` into an isolated `git worktree` (never touching this branch's working tree or history), ran its backend standalone on a separate port (7345), and pointed this branch's *already-fixed, unmodified* `conversation.html` frontend code at it (by redirecting only `/api/docs/*` fetch calls, via the real browser, to the candidate backend):

1. **Positive compatibility** — a full real upload → remove → server-confirmed-delete journey against the PR #90 backend, using a real signed-up account: succeeded identically to the current branch's own backend. No frontend changes were needed.
2. **Genuine-401, same principal** — uploaded a document, then corrupted the live `_authToken` for the *same, still-current* user and called `loadAttachmentsForSession()` against the real PR #90 backend: it returned a genuine 401, and the frontend correctly called `_handleSessionExpired()` — `_authToken`/`_authUser` cleared, sign-in overlay opened. (On this branch's own backend, this cannot be observed at all, since the 401 never fires — this is the first time this code path has been exercised against a backend that actually triggers it.)
3. **The Alice → Bob stale-401 reproduction, repeated against REAL responses from the PR #90 backend** (not a simulated 401): two real accounts signed up directly on the candidate backend; Alice's pending request (token corrupted first, guaranteeing a genuine 401 when it resolves) was held open while Bob signed in for real; releasing Alice's request produced a real, server-issued 401. **Bob remained signed in** — the exact same fix from section A holds under real, end-to-end conditions against the actual future backend, not just a mock.

No merge was performed. `git worktree remove` and `git branch -D` cleaned up the candidate checkout after testing; this branch's own history and working tree were never touched by the candidate's code.

## D. Final verification

```
node --test tests/frontend/*.mjs   # 161/161 passing (was 151; +10 new security-addendum tests)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

New tests in `test_b16_context_attachments.mjs`: the stale-401 Alice/Bob defect (reproduced and confirmed fixed, unit-level), `removeAttachment()`'s added identity check, `openQuickSwitch()`'s added identity check (structural, verifying the identity check runs between the fetch resolving and the 401 branch — exactly where the confirmed defect was), and `_deleteOrphanedUpload()`'s honest response classification across 200/404/401/403/500/network-failure.

**Live, real-browser, real-backend verification** (not asserted from code or unit tests alone): the Alice→Bob stale-401 reproduction was run twice — once with a simulated 401 against this branch's own backend (confirming the fix in isolation), and once with a genuinely real 401 from the PR #90 candidate backend end-to-end (confirming the fix holds under real conditions, and confirming forward-compatibility with the corrected backend before it even merges).

Live-verified in both Obsidian Dark and Meridian Light during the prior correction pass (section A/B of `ORNEUR_B16_CORRECTION_AND_AUDIT.md`); this pass's fixes are in the same code paths and did not change any rendering/CSS, so no new theme-specific regression surface was introduced.

## Honest verdict

**All four sections resolved honestly, with live and real-backend verification, not assumed from code reading.** Section A found and fixed two real defects (one named by the directive, one found during the same review — `openQuickSwitch()`). Section B made `_deleteOrphanedUpload()` truthful and documented a genuine, unclosable-from-the-frontend reliability gap with a concrete backend requirement for Cursor, rather than inventing a client-side retry mechanism whose own reliability would be equally unprovable. Section C corrected the prior branch-scoped finding's phrasing and went further than documentation — PR #90 was actually checked out, run, and tested against, confirming both the 401 fix's forward-compatibility and the precise, narrower scope of `retrieval_unauthorized` (chat/stream retrieval, not docs CRUD). No protected branch was merged; no functionality is claimed beyond what was fixed and verified.
