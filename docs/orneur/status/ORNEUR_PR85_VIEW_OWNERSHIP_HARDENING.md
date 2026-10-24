# PR #85 — Final Cross-Account Async Ownership Hardening

**Branch:** `claude/b04-b09-implementation-2026-10-23`
**Starting head:** `14a8238551d9b461a3e3b7bcacfc0d90891fcaaa` (verified before editing)

## Both findings: confirmed real, reproduced, then fixed — not assumed

Per the directive, neither was treated as confirmed until independently reproduced against the actual pre-fix code, with two real signed-up accounts and real artificially-delayed network responses (not mocks).

### `loadSessions()` — confirmed, reproduced

1. Logged in as Alice (owns one real conversation).
2. Delayed exactly one `/api/sessions?limit=20` response by 2s (subsequent calls, including Bob's own, go through immediately — isolating the stale-response effect from being masked by a near-simultaneous correct repaint, a methodology pitfall from the earlier P0 search fix worth re-disclosing here too).
3. Called `loadSessions()` as Alice.
4. Immediately logged out and logged in as Bob (who owns zero conversations).
5. Confirmed Bob's own `loadSessions()` call resolved first, correctly showing `"No conversations yet"`.
6. Waited for Alice's delayed response to land.

**Pre-fix:** Bob's sidebar flipped to show Alice's real conversation ("First Rename") — her private data, under Bob's logged-in session.
**Post-fix:** Bob's sidebar stayed `"No conversations yet"` through the identical sequence.

### `openSession()` — confirmed, reproduced

Same structure: Alice calls `openSession()` on her own real conversation (containing `"ALICE_SECRET_NIGHTOWL_TWO"`), its `/messages` response delayed 2s, immediately switched to Bob before it resolves.

**Pre-fix:** Bob's reading pane displayed Alice's private message content and the model's response to it.
**Post-fix:** Bob's reading pane stayed empty through the identical sequence.

## The fix: one consistent account-view ownership contract

A single shared `_viewEpoch` (deliberately separate from `_streamEpoch` and `_searchEpoch`, which the directive asked to preserve unmodified) covers both `loadSessions()` and `openSession()`, since both must be invalidated by exactly the same events:

```js
let _viewEpoch = 0;
function _abandonActiveView() { _viewEpoch++; }
function _viewResponseStillOwns(myEpoch, myToken) {
  if (myEpoch !== _viewEpoch) return false;
  if (myToken !== _authToken) return false;
  return true;
}
```

- **Captured before each operation**: epoch (`++_viewEpoch`), authenticated principal (`_authToken`), and — in `openSession()` specifically — the "relevant conversation identity" the directive asked for (`sid`, re-checked against the live `sessionId` global, as a second, independent guard beyond epoch alone).
- **Revalidated after every await**: both `loadSessions()` and `openSession()` check ownership after the `fetch()` resolves AND again after `.json()` parses, in both the success and the `catch` paths.
- **Invalidated on**: logout (`doLogout()` → `newConversation()` → `_abandonActiveView()`), account switch (same path, plus `continueAnonymous()`), navigation to a new/different conversation (each `openSession()` call self-claims a fresh epoch, and `newConversation()` explicitly abandons), and session reset (`loadSessions()` self-claims a fresh epoch on every call, covering the SSE `session`-event-triggered reload, search-restore, and auth-restore paths uniformly).
- **Existing search and streaming ownership preserved, unmodified**: `_searchEpoch`/`_streamEpoch` and their own abandon functions are untouched by this change.

## Rename, delete, export callbacks — inspected per the directive's explicit instruction

All three were checked for the same stale-account effect and hardened:
- **Rename**: the authenticated principal is captured before the `PATCH`; a changed principal by the time it resolves means the result is never applied to the (possibly now-detached, possibly now-belonging-to-a-different-account's-view) row.
- **Export**: same guard — a completed export under the wrong account would otherwise still trigger a real file download of the PREVIOUS account's content while the screen shows a different one.
- **Delete**: same guard — prevents a stale completion handler from calling `row.remove()`/`newConversation()` against what may now be a different account's DOM state.

These are a lighter check (principal only, not a full epoch claim) since they're secondary actions on an explicitly-clicked row, not primary view loads — claiming/bumping the shared `_viewEpoch` on every rename/export/delete would have incorrectly invalidated unrelated in-flight `loadSessions()`/`openSession()` calls.

## Tests

`tests/frontend/test_view_ownership_epoch.mjs` (new, 7 tests) — the ownership primitive, including deterministic simulations of every scenario the directive listed: Alice-to-Bob, rapid conversation switching, logout during fetch, network failure, and recovery. All 7 confirmed to fail against the pre-this-fix file (the functions didn't exist).

```
node --test tests/frontend/*.mjs           # 62/62 passing (was 55)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

New test wired into the existing "Conversation Shell Frontend" CI job.

## Remaining limitations, disclosed honestly

- The "rapid conversation switching" and "network failure/recovery" scenarios were verified deterministically at the unit-primitive level (see tests above), not re-reproduced live in a real browser with two real in-flight network requests racing each other — the two scenarios that MOST warranted a full live reproduction (the actual cross-account leaks) were; the remaining ones follow from the identical, already-proven primitive.
- A real live second-conversation-send for Alice (to test rapid X→Y switching end-to-end) was attempted but hit this environment's known backend "using tools" planning-path latency (documented in this session's earlier PR #81 work) rather than completing in a reasonable time; abandoned in favor of the deterministic unit reproduction above rather than spending further time on an unrelated, already-disclosed backend latency issue.

## Antigravity handoff

```bash
node --test tests/frontend/test_view_ownership_epoch.mjs
node --test tests/frontend/test_search_ownership_epoch.mjs
node --test tests/frontend/test_recent_conversation_row.mjs
```

Adversarial fixtures worth independently re-probing: the exact two-account delayed-`loadSessions()`/delayed-`openSession()` sequences above (strongest when reproduced independently); opening conversation X then Y in rapid succession with X's response artificially delayed past Y's; renaming a conversation immediately before logging out.

## Honest verdict

**`ENGINEERING PASS — INDEPENDENT AUDIT PENDING`** for this hardening specifically. Not claimed independently qualified on CI alone. PR #79, PR #81, and Cursor branches untouched.
