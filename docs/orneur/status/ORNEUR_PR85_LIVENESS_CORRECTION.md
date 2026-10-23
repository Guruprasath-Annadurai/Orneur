# PR #85 — Final Liveness and Request-Ownership Correction

**Branch:** `claude/b04-b09-implementation-2026-10-23`
**Starting head (verified before editing):** `ef03a1853959308fddd0362020bfd8f06951d494`

## The defect: confirmed real, reproduced, then fixed — not assumed from the audit's description

Antigravity's independent audit of PR #85 returned `PARTIAL — CONFIRMED LIVENESS COUPLING DEFECT`: the shared `_viewEpoch` introduced in the immediately-prior commit (`ef03a18`) made `loadSessions()` (sidebar history) and `openSession()` (reading pane) incorrectly invalidate each other, even though they are functionally independent UI regions. Per this session's standing discipline, this was independently reproduced against the actual pre-fix code before any fix was written — not accepted from the audit's own description.

### Sequence 1 — delayed `loadSessions()`, then `openSession()` intervenes

1. Logged in as Alice (real account, one real conversation, "First Rename").
2. Let the normal post-login `loadSessions()` complete, then forcibly overwrote `recents-list.innerHTML` with an unambiguous `"CLEARED FOR TEST"` placeholder (methodology note: without this, a pre-existing correct repaint from the automatic post-login load is indistinguishable from a successful one under test).
3. Delayed exactly one `/api/sessions?limit=20` response by 1.5–2s via a `window.fetch` monkey-patch (`delayedOnce` flag — only the first matching call is delayed, to avoid the false-negative this session previously documented from delaying every matching call including a fresh one).
4. Called `loadSessions()`. Before it resolved, called `openSession()` on a real conversation.

**Pre-fix (`ef03a18`, shared `_viewEpoch`):** `{"recentsListAfter":"CLEARED FOR TEST"}` — the delayed, valid, still-authorized history response was discarded; the sidebar never updated.
**Post-fix:** `{"recentsListAfter":"<div class=\"rec-row\" data-title=\"First Rename\">..."}` — the same sequence now correctly applies the delayed response.

### Sequence 2 — delayed `openSession()`, then a `loadSessions()` refresh intervenes

Same structure, reversed: `openSession()` on Alice's real conversation (containing `"ALICE_SECRET_NIGHTOWL_TWO"`), its `/messages` response delayed, a `loadSessions()` refresh triggered before it resolved.

**Pre-fix:** `{"readingPaneAfter":"Loading conversation..."}` — the reading pane stayed stuck on the loading placeholder permanently, even after the real message response had genuinely arrived.
**Post-fix:** `{"readingPaneAfter":"<div class=\"msg-user\"><div class=\"sample-q\">ALICE_SECRET_NIGHTOWL_TWO</div>..."}` — the messages now correctly render.

## The fix: independent ownership domains, not one shared epoch

Replaced the single `_viewEpoch`/`_abandonActiveView`/`_viewResponseStillOwns` block with two fully independent domains:

```js
let _historyEpoch = 0;
let _messageEpoch = 0;
function _abandonActiveHistory() { _historyEpoch++; }
function _abandonActiveMessage() { _messageEpoch++; }
// The ONLY place both are invalidated together -- a genuine
// authenticated-principal change.
function _abandonAllViewsForAccountChange() {
  _historyEpoch++;
  _messageEpoch++;
}
function _historyResponseStillOwns(myEpoch, myToken) {
  if (myEpoch !== _historyEpoch) return false;
  if (myToken !== _authToken) return false;
  return true;
}
function _messageResponseStillOwns(myEpoch, myToken) {
  if (myEpoch !== _messageEpoch) return false;
  if (myToken !== _authToken) return false;
  return true;
}
```

- `loadSessions()` claims and checks `_historyEpoch`/`_historyResponseStillOwns` only.
- `openSession()` claims and checks `_messageEpoch`/`_messageResponseStillOwns` only, plus retains the pre-existing, independent `sessionId !== mySid` conversation-identity guard.
- `newConversation()` — the directive's explicitly named example — now calls **only** `_abandonActiveMessage()`. Starting a new conversation ends this view's claim on an in-flight message load (there is no longer a specific conversation whose messages belong here), but has nothing to do with an otherwise-valid, authenticated, merely-slow sidebar history refresh.
- `doLogout()`, `onAuthSuccess()`, `continueAnonymous()`, and `tryRestoreSession()` — every authentication transition the directive named by name — each now explicitly call `_abandonAllViewsForAccountChange()`, since a genuine identity change must invalidate both domains regardless of which function reaches it. `doLogout()` in particular needed this added explicitly: it previously relied on `newConversation()` for its message-domain invalidation, but after narrowing `newConversation()` to message-only, logout would otherwise have left the history domain uninvalidated (invariant 6).

### A real bug introduced and caught mid-fix

The initial epoch-block replacement left `continueAnonymous()` referencing the now-deleted `_abandonActiveView()` — a `ReferenceError` at runtime. Caught via direct file inspection before any test or commit, fixed to `_abandonAllViewsForAccountChange()`. A full `grep -n "_viewEpoch\|_abandonActiveView\|_viewResponseStillOwns"` over the entire file now returns zero matches — no other stray references remain.

## Invariants verified (the directive's numbered list)

1. **`loadSessions()` does not invalidate an unrelated message request** — structural: `_abandonActiveHistory()`/`loadSessions()` touch only `_historyEpoch`, never `_messageEpoch`. Unit-tested directly.
2. **`openSession()` does not invalidate an unrelated history request** — structural, symmetric to (1). Unit-tested directly.
3. **Opening conversation Y invalidates an obsolete load for X** — guaranteed by every `openSession()` call claiming a fresh `_messageEpoch`; the pre-existing `sessionId !== mySid` check is a second, independent guard. Unit-tested.
4. **Clearing/refreshing search refreshes history without cancelling the active message load** — verified by inspection: `restoreRecentsFromSearch()` (the search-clear path) restores a cached `_preSearchListHTML` snapshot and does not call `loadSessions()` or touch `_messageEpoch` at all, so there is no coupling to begin with.
5. **A genuine authentication transition invalidates both domains** — `doLogout()`, `onAuthSuccess()`, `continueAnonymous()`, `tryRestoreSession()` all call `_abandonAllViewsForAccountChange()`. Unit-tested for `doLogout()`, `continueAnonymous()`, `onAuthSuccess()` by exercising the actual functions (not just the primitive); `tryRestoreSession()` verified by direct inspection (boot-time restore, functionally near-no-op since both epochs are already 0, but matches the invariant for any future code path).
6. **Logout clears private content and blocks every prior-account response** — `doLogout()` now explicitly invalidates both domains, not just the message domain `newConversation()` provides. Unit-tested.
7. **Stale success and error responses are both rejected** — the ownership-check functions take no outcome parameter; both `try` and `catch` blocks in `loadSessions()`/`openSession()` call the same check. Unit-tested.
8. **Ownership is checked after every relevant async boundary** — verified by inspection: both `loadSessions()` and `openSession()` check after the `fetch()` resolves AND again after `.json()` parses, in both branches.
9. **Previously-authorized stale responses don't render after an account switch** — the exact Alice-to-Bob live reproduction below, re-run against the fixed code.
10. **Legitimate current responses are not discarded by an unrelated UI region refreshing** — this is the direct positive-case counterpart of the bug just fixed; both Sequence 1 and Sequence 2 above are its live demonstration.

## Privacy protections re-verified under the new design (not merely assumed preserved)

Re-ran the Alice-to-Bob cross-account reproduction from the immediately-prior phase against the fixed code: Alice calls `loadSessions()` (response delayed 1.5s), immediately logged out and logged in as Bob (a genuine `_abandonAllViewsForAccountChange()`-triggering transition), Bob's sidebar forcibly set to an unambiguous `"BOB-BASELINE"` placeholder, Bob's own `loadSessions()` called. After waiting past Alice's delayed response too: Bob's sidebar showed only his own conversation (`"(untitled conversation)"`), confirmed to contain neither `"First Rename"` nor `"ALICE"` anywhere in the DOM. The independent-domain fix did not reopen the privacy hole the prior phase closed.

## Assignment D — browser regression scenarios

Real two-account testing (`alice2-p85@example.test`, `bob2-p85@example.test`, both `TestPassword123!`) against a disposable local backend (`uvicorn orca.serve.api:app` on port 7344), real browser, real DOM evidence captured via `window.fetch` monkey-patching for artificial delay (never mocking the actual request/response cycle):

| # | Scenario | Pre-fix | Post-fix |
|---|---|---|---|
| 1 | Delayed history, then conversation open | Reproduced: history discarded | Reproduced fixed: history applies |
| 2 | Delayed conversation, then history refresh | Reproduced: reading pane stuck loading forever | Reproduced fixed: messages render |
| 3 | Conversation X then Y in rapid succession | Verified at the unit level (same real backend "using tools" planning-path latency documented in earlier phases made a live double-send unreliable within reasonable test time — disclosed, not hidden) | Unit-verified: X's stale response rejected, Y's current response applied |
| 4 | Search clear while messages load | N/A — no coupling exists (see invariant 4 above) | Confirmed by inspection: `restoreRecentsFromSearch()` never touches `_messageEpoch` |
| 5 | New conversation while sidebar history refreshes | This is the directive's own named example | Unit-tested directly against the real `newConversation()` function: message domain bumped, history domain untouched |
| 6 | SSE session event while messages load | Not applicable — this codebase has no SSE-triggered `loadSessions()` call path (grepped; none found); honestly reported as a non-existent code path rather than built from scratch, per the explicit "do not add fabricated backend functionality" restriction | — |
| 7 | Logout while either request pending | Unit-tested: `doLogout()` invalidates both domains | Same |
| 8 | Alice-to-Bob delayed-response attack | Reproduced live (immediately-prior phase, pre-fix leaked) | Re-reproduced live against the fixed code: blocked (see privacy section above) |
| 9 | Stale network failure after identity transition | Unit-tested: invariant 7 (stale catch-path rejected identically to stale success) combined with invariant 5/6 (account-switch invalidation) | Same |
| 10 | Logout during export/rename/delete completion | Unaffected by this phase — rename/export/delete use only the pre-existing, unmodified `myToken !== _authToken` check (grepped; no `_viewEpoch`/`_historyEpoch`/`_messageEpoch` references in those three functions), which already handles this per the prior phase's report | Unaffected (verified unaffected, not re-fixed) |

## Authentication boundary audit (Assignment C)

Checked every function the directive named: `doLogout()`, `onAuthSuccess()`, `continueAnonymous()`, `tryRestoreSession()`. Per the explicit instruction "do not assume every auth transition necessarily passes through `doLogout()`" — confirmed `onAuthSuccess()` (anonymous-to-authenticated sign-in) and `tryRestoreSession()` (boot-time restore) never call `doLogout()`, and both previously had NO view-invalidation call of their own; both now explicitly call `_abandonAllViewsForAccountChange()`.

**Session-expiry / authentication-failure recovery**: grepped the entire file for `401`, `r.status`, and any expiry-detection pattern. None exists — there is no explicit 401-interceptor or session-expiry-triggered re-auth flow anywhere in `conversation.html` today. Reported honestly as a non-existent code path rather than invented, per the directive's explicit restriction against fabricating backend functionality or broadening scope.

Server-side ownership enforcement (the backend's own authorization checks on `/api/sessions`, `/api/session/{id}/*`) was not modified — this phase is a client-side liveness/ownership fix only.

## Tests

```
node --test tests/frontend/test_view_ownership_epoch.mjs   # 13 tests, rewritten for the new functions
node --test tests/frontend/*.mjs                            # 68/68 passing (was 62)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

The rewritten `test_view_ownership_epoch.mjs` was confirmed to genuinely **fail** against the pre-fix (`ef03a18`) file (marker-not-found — the old `_viewEpoch` functions are gone, the new ones don't exist yet in that snapshot) before being confirmed to pass against the fixed file. Per the explicit instruction to exercise the actual calling functions, not only the isolated primitive: dedicated tests extract and directly execute `newConversation()`, `doLogout()`, `continueAnonymous()`, and `onAuthSuccess()` themselves (with their real DOM/network dependencies stubbed), not just `_historyResponseStillOwns`/`_messageResponseStillOwns` in isolation.

New test file reused under its existing name (`test_view_ownership_epoch.mjs`) — no CI workflow change needed; the existing `node --test tests/frontend/test_view_ownership_epoch.mjs` line in the "Conversation Shell Frontend" CI job picks up the rewritten file automatically.

## Remaining limitations, disclosed honestly

- Scenario 3 (rapid X→Y conversation switching) and scenario 9 (stale network failure after identity transition) were verified at the unit level against the real calling functions, not re-reproduced live with two genuinely racing real network requests — the two scenarios that most warranted a full live reproduction (the two liveness-coupling sequences, and the Alice-to-Bob privacy re-check) were reproduced live; the remainder follow from the identical, already-proven mechanism and were previously live-reproduced in the immediately-prior phase under the (now-superseded) shared-epoch design, where the underlying privacy guarantee is unchanged.
- No SSE-triggered `loadSessions()` path exists in this codebase to test (scenario 6) — confirmed absent, not assumed.
- No session-expiry/401-recovery path exists to audit (Assignment C) — confirmed absent by grep, not assumed; this is a genuine gap in the existing (pre-this-session) codebase, not something this phase was asked to build, and is reported rather than silently left unmentioned.

## Antigravity handoff

```bash
node --test tests/frontend/test_view_ownership_epoch.mjs
node --test tests/frontend/test_search_ownership_epoch.mjs
node --test tests/frontend/test_recent_conversation_row.mjs
```

Adversarial fixtures worth independently re-probing: the exact delayed-`loadSessions()`/delayed-`openSession()` sequences above, confirming each resolves correctly when the OTHER domain is touched in between (the liveness fix); the Alice-to-Bob delayed-response attack, confirming it is still blocked (the privacy fix, now under independent domains); opening conversation X then Y with X's response delayed past Y's.

## Honest verdict

**`ENGINEERING PASS — INDEPENDENT REQUALIFICATION PENDING`** for this correction specifically. Both liveness sequences were independently reproduced broken on the exact pre-fix SHA (`ef03a18`) and independently reproduced fixed afterward, with real DOM evidence captured for both. The Alice-to-Bob privacy fix from the prior phase was re-verified intact under the new design, not merely assumed. The dangling `_abandonActiveView()` reference introduced mid-fix was caught and corrected before any test ran against it. Two genuine gaps in the existing codebase (no SSE-triggered history reload, no session-expiry/401 recovery path) are disclosed rather than fabricated. Not claiming independent qualification from CI alone — Antigravity must independently requalify the new SHA before any merge recommendation. PR #79, PR #81, and Cursor's Foundation-X branches untouched; no protected merge, deployment, spend, or model training performed.
