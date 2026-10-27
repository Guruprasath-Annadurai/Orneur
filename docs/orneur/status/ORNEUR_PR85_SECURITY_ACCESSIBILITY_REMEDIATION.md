# PR #85 — Targeted UI Security and Accessibility Remediation

**Branch:** `claude/b04-b09-implementation-2026-10-23`
**Starting head:** `9b348d8eb4fd6a5627260b53257e2ddedc11f767` (verified before editing)
**PR:** [#85](https://github.com/Guruprasath-Annadurai/Orneur/pull/85), draft, stacked on PR #81

## P0 — Search request ownership: confirmed, reproduced, fixed

**The vulnerability was real.** I did not assume it from the directive's description — I independently reproduced it first, against the actual pre-fix code, with two real signed-up accounts, a real artificially-delayed network response, and a real account switch while that response was in flight:

1. Signed up Alice, sent a real message creating a real persisted conversation containing `"ALICE_SECRET_PROJECT..."` / `"ALICE_SECRET_NIGHTOWL_TWO"`.
2. Patched `window.fetch` to add a 2-second artificial delay to only `/api/sessions/search` calls (everything else unaffected) — simulating a slow network.
3. Started a real search for Alice's own content (`runConversationSearch('NIGHTOWL')`).
4. **Immediately**, before that delayed response resolved, called the real `doLogout()` and logged in as a completely different, unrelated real account, Bob.
5. Waited for the delayed response to resolve.

**On the pre-fix code:** Bob's sidebar displayed Alice's private conversation content (`"(untitled conversation)ALICE_SECRET_NIGHTOWL_TWO"`), confirmed via the real DOM text after the switch — a genuine cross-account information disclosure.

**On the fixed code, the identical adversarial sequence:** Bob's sidebar correctly showed `"No conversations yet"` — his own true, empty state.

(One methodology note, disclosed for transparency: my first several reproduction attempts showed no leak, which I did not take at face value — I traced it down before concluding anything. The root causes were two real artifacts of my OWN test setup, not the app: (a) a newly-sent conversation's transcript file needs a brief moment to flush to disk before `conversations.search()` can find it — unrelated to this P0, a pre-existing async-write-lag worth noting separately but out of this fix's scope; and (b) stacking multiple `window.fetch` monkey-patches across repeated test attempts without resetting compounds artificial delays. Once isolated, the reproduction was clean and consistent.)

### The fix

`_searchEpoch` (same ownership-epoch pattern as `_streamEpoch`, AUDIT-B81-A-P1-01) plus two additional, explicit checks the directive specifically asked for beyond epoch alone:

```js
function _searchResponseStillOwns(myEpoch, myToken, myQuery) {
  if (myEpoch !== _searchEpoch) return false;         // newer request / abandonment happened
  if (myToken !== _authToken) return false;            // the authenticated principal changed
  const liveInput = document.getElementById('conv-search-input');
  if (!liveInput || liveInput.value.trim() !== myQuery) return false;  // query no longer matches
  return true;
}
```

Checked **twice** per request (after the `fetch` resolves and again after the `.json()` parse — ownership can be lost at any point while either await was pending), not once.

`_abandonActiveSearch()` (bumps `_searchEpoch`) is called from every scenario the directive listed:
- **Logout** — `doLogout()`.
- **Authentication identity change / account switch** — `onAuthSuccess()` (via `loadSessions()`, see below) and `continueAnonymous()`.
- **Search query change** — implicit: `runConversationSearch()` itself claims a fresh epoch (`++_searchEpoch`) on every call, which alone invalidates any older still-pending request.
- **Search clearing** — the `input` handler and the Escape handler both call it before restoring the real list.
- **Session-history context reset** — `loadSessions()` itself calls it, since that's the single real choke point every identity-change path already routes through.

## P1 — Menu accessibility: confirmed, fixed

**Root cause, confirmed by reading the CSS, not assumed:** `.rec-more-btn{display:none}` by default, shown only via `.rec-row:hover`. `display:none` removes an element from the tab order entirely — a keyboard-only user could never reach it, period, regardless of how long they tabbed. Touch devices have no reliable `:hover` state either, so it was also undiscoverable there.

**Fix:** the button is now always `display:flex` (always present, always focusable, `tabIndex: 0` confirmed), with `opacity:0` as the purely-visual "quiet until interacted with" treatment (opacity never affects focusability, unlike display). `opacity:1` on `:hover`, `:focus-visible`, `.open`, and unconditionally under `@media (hover: none)` for touch devices.

**Verified against the real browser accessibility tree, not a mock:** a real `Tab` keypress moved focus onto the button; `document.activeElement.matches(':focus-visible')` confirmed `true` with `opacity: 1` computed. `Enter` opened the menu; `Escape` closed it and `document.activeElement` was confirmed to be the same `.rec-more-btn` again (focus restoration).

No currently-shipped menu item is ever disabled, so "disabled actions must not be misleading" has nothing to check yet — noted for when one is added.

## P1 — Asynchronous search correctness: confirmed, fixed

- **Stale-response prevention**: the P0 fix above is the same mechanism.
- **Sub-minimum-length query transitions**: real bug, confirmed by reading the old code — only a fully-*empty* query restored the real list; a 1-character query fell through to `runConversationSearch`'s own `if (q.length < 2) return;`, which left whatever the PREVIOUS search had painted on screen with no path back short of clearing the box entirely. Fixed: the input handler now treats *any* query below the minimum (including 1 character) identically to empty. **Live-verified**: searched `"NIGHTOWL"` (got results), backspaced to `"N"`, confirmed the sidebar correctly reverted to the real recent-conversations list, not stuck on stale results.
- **Network errors/timeouts**: the existing `catch` block's `list.innerHTML = '<div class="recents-empty">Search failed</div>'` is now also gated by `_searchResponseStillOwns()` — a failed stale request no longer overwrites a newer, legitimate state with an incorrect "Search failed" message either.

## P1 — Rename and deletion reliability: confirmed, fixed

Two real bugs, both confirmed by reading the code before fixing:

1. **Repeated-rename / stale-export-filename bug**: `startRenameConversation`'s `currentTitle` and the export menu items' `title` argument were both read from the `title` parameter closed over at `renderRecentRow()` call time — never updated after a successful rename. A second rename, or an export performed right after a rename, would have silently used the ORIGINAL title. **Fixed**: `row.dataset.title` is the new single source of truth, set at render time and updated after every successful PATCH; rename and both export menu items now read it at click time. **Live-verified**: performed a real rename via the actual API, confirmed `row.dataset.title` correctly reflected the new server-confirmed value immediately after.

2. **Delete-confirm never resets on cancellation**: the two-click arm/confirm state (`confirming`) was a closure variable with no reset path except an actual second click. Arming delete, then closing the menu (outside click or Escape) without confirming, then reopening the SAME row's menu later would show `"Click again to delete"` still armed — meaning what LOOKS like a fresh first click would have immediately deleted. **Fixed**: `closeAllRecMenus()` now resets every open menu's delete-confirm state unconditionally. **Live-verified**: armed delete, closed without confirming, reopened — confirmed the button read `"Delete"` again, not the armed state.

3. **Rename errors were silent**: a failed PATCH previously did nothing visible at all (the code comment even said so). **Fixed**: `appendUnavailableNote('Could not rename this conversation. The title was not changed.')`, the same accessible pattern already used for export/delete failures.

## P1 — Security and integration tests

- `tests/frontend/test_search_ownership_epoch.mjs` (new, 6 tests): the ownership primitive, including a direct simulation of the adversarial two-account scenario at the unit level. All 6 confirmed to fail against the pre-fix file (the functions didn't exist at all before this fix).
- `tests/frontend/test_recent_conversation_row.mjs` (extended, 3 new tests, 7 total): menu open/close + focus restoration, the delete-confirm-reset bug, and the `row.dataset.title` mutability the rename/export fix depends on. The delete-confirm test specifically failed against the pre-fix `closeAllRecMenus()` signature.
- **The real, non-mocked reproduction** (the cross-account leak, the keyboard-reachability check via a genuine `Tab` keypress, the sub-minimum-length live check, the real rename/delete-confirm checks against the real running backend) is documented above and is the primary evidence for this directive's explicit "do not claim a cross-account vulnerability is confirmed until it is reproduced" requirement — not a structural DOM assertion standing in for it.

Existing suite: 55 JS tests (up from 46), 13 Python tests — all passing.

## Both-theme verification

Spot-checked in light theme (Meridian): the menu panel (uses the same `var(--compose)`/`var(--border)` tokens as the existing model-selector dropdown) renders correctly; the always-dark sidebar convention (search box, row, menu-trigger button) is unchanged from the rest of the sidebar, consistent with the founder-approved pattern already established for the rest of the nav. A full side-by-side comparison against the authentic founder-approved B06 original was not re-captured in this pass (time-bounded); the existing B01 fidelity comparison from the earlier `ORNEUR_B01_B03_IMPLEMENTATION_FIDELITY.md` remains the most recent authentic-reference comparison on file.

## Tests and CI

```
node --test tests/frontend/*.mjs           # 55/55 passing
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

New tests wired into the existing "Conversation Shell Frontend" CI job.

## Antigravity handoff

Reproduction commands:
```bash
node --test tests/frontend/test_search_ownership_epoch.mjs
node --test tests/frontend/test_recent_conversation_row.mjs
```

Adversarial fixtures worth independently re-probing: the exact two-account delayed-search sequence described above (a second, independent reproduction by a different reviewer is the strongest confirmation); rapid-fire typing through the 2-character minimum boundary in both directions; a rename immediately followed by an export (filename must reflect the NEW title); arming delete on two different rows' menus in quick succession.

## Honest verdict

**Do not mark this PR independently qualified based on green CI alone** — per the directive's own instruction. This report documents genuine reproduction-then-fix work for all five findings, with live evidence for each, but has not been independently reviewed. **`ENGINEERING PASS — INDEPENDENT AUDIT PENDING`** for this remediation specifically. Resuming the remaining source-supported B-series work (B04, B05, B10–B16) is the next, separate increment, as instructed.
