# B14 — Multi-Conversation Navigation: Partial Implementation Report

**Branch:** `claude/b04-b09-implementation-2026-10-23`
**Source:** `APPROVED_SOURCE_ARCHIVES/ORNEUR_B14_FINAL_LOCK_AND_HANDOFF.zip` (SHA-256 `810f1a472db61360261c678404e40a50c0c3fc79471bef8dc9a740e468e88c14`) — verified via the archive's own `verification/verify_handoff.py`: 40 packaged + 31 approved source files passing, before any code was written.

## The contract names two features; this phase builds one fully and discloses the other as out of scope

`docs/B14_IMPLEMENTATION_CONTRACT.md` describes **Quick Switch** (a recent-conversations picker) and **Workspace Tabs** (multiple concurrently-open conversations). Reading the approved prototype (`references/prototypes/B14_Unified_Dark.html`) directly: Workspace Tabs is explicitly optional even in the locked design itself (*"Illustrative conversations only. No session sync, account access or model execution"*), and the contract's own section 4 flags real per-tab stream subscription/correlation as a hard, separate backend problem (*"A streaming generation may continue server-side when user navigates away... Design and test how streams are subscribed/unsubscribed, resumed, and correlated to a run/request ID"* — no such run-ID correlation exists in this backend). Building Workspace Tabs honestly would require the same kind of backend work already disclosed as blocked for B10/B12. **Not attempted in this pass.**

Quick Switch, by contrast, needed no new backend capability — it is a new way to *reach* the already-existing, already-hardened `openSession()`, not a new switching mechanism. Implemented in full.

## What was implemented

### 1. Per-conversation draft isolation (a real bug, confirmed and fixed)

The contract: *"Never use a singleton shared input state that shows draft from chat A when chat B opens."* Reproduced live before any fix: switching conversations via `openSession()` left the composer's unsent text completely untouched — typing a draft, opening a different real conversation, and checking `#msg-input` showed the stale text still present, now silently misattributed to the newly-opened conversation.

Fixed with `_draftsByConversation` (a `Map` keyed by conversation id, with a dedicated `__new__` key for the "new conversation" composer slot) and two helpers: `_saveCurrentDraft()` (called before `sessionId` changes, saving the *departing* conversation's text) and `_restoreDraftFor(id)` (called after, restoring the *target*'s own saved text or empty). Wired into `openSession()` and `newConversation()`. Live-verified end to end: typed a draft for "new conversation," opened a real conversation (empty, correctly), typed a different draft there, returned to "new conversation" (first draft correctly restored), reopened the real conversation (its own draft correctly restored).

**Honest scope, stated plainly, per the contract's own instruction** (*"Do not claim server persistence when only local in-memory draft exists"*): this is in-memory only, scoped to the current tab. It does not survive a reload, a different device, or a different browser tab — no server-side draft endpoint exists in this backend (confirmed by reading `orca/serve/api.py`; none found). Cleared entirely on every genuine identity transition (`doLogout()`/session-expiry, `onAuthSuccess()`, `continueAnonymous()`) — a draft keyed only by conversation id must never survive an account switch on the same device, and a structural test asserts all three call sites clear it.

### 2. Quick Switch

A header button opens an accessible dialog (`role="dialog" aria-modal="true"`, the same focus-trap/Escape/backdrop/restore pattern already established for B04's workspace and B13's details panel) listing the caller's real recent conversations via the same `GET /api/sessions` the sidebar already uses — **never** the approved archive's own illustrative example titles ("Infrastructure strategy," etc.), which a structural test explicitly guards against reintroducing. Each row shows the real title (escaped via `esc()` before rendering — the contract's own named threat, "rendered conversation title injection," closed the same way every other untrusted string in this file already is) and marks the currently-open conversation. Selecting a row calls the real `openSession(sid, title)` — meaning every ownership-epoch and draft-isolation guarantee already built into this codebase applies automatically, since this is a new entry point into existing, already-hardened code, not new switching logic.

Keyboard: Up/Down roving focus across the close button and all rows, Enter activates the focused row, Escape closes and restores focus to the triggering button, Tab wraps at the first/last focusable element — the same accessible-dialog discipline used throughout this session.

## Verified live, in a real browser, both themes

Opened Quick Switch: real conversation ("First Rename," Alice's actual data) listed, first row auto-focused. Clicked it: panel closed, the real conversation's real messages loaded via `openSession()`. Confirmed the "Current" label correctly marks the already-open conversation when reopening the panel. Confirmed Meridian light theme renders correctly. Confirmed Escape closes the panel and returns focus to the trigger button (`document.activeElement` check, not just visual inspection).

## Tests

```
node --test tests/frontend/test_b14_quick_switch_and_drafts.mjs   # 9 tests, new
node --test tests/frontend/*.mjs                                     # 127/127 passing (was 118)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

Structural guards: draft-clearing wired into all three identity-transition functions; `openSession()`'s save-then-restore ordering is correct (save before `sessionId` changes, restore after); Quick Switch never hardcodes the archive's example titles and always escapes real titles; Quick Switch reuses the real `openSession()`. Behavioral tests exercise the real `_saveCurrentDraft()`/`_restoreDraftFor()` round-trip across three conversation slots (including the empty-input-clears-the-entry case, relevant after a real send) and confirm both are safe no-ops with no composer mounted.

## What was deliberately not built, and why

- **Workspace Tabs** — explicitly optional/illustrative-only even in the approved design; real support needs backend run-ID correlation for concurrent stream subscriptions that does not exist (the same class of gap already disclosed for B10's Stop and B12's recovery surface).
- **Cross-tab/cross-device draft sync** — the contract itself distinguishes this from the honestly-scoped in-memory case; no backend draft-persistence endpoint exists to build it against.
- **The full 320px/390px/tablet/desktop screenshot-diff sweep** against all three approved screenshot states (`QuickSwitchClosed`/`QuickSwitchOpen`/`WorkspaceTabsEnabled`) was not run as a dedicated pass; desktop and the mobile bottom-sheet-equivalent layout (the same responsive panel positioning already used for B13) were checked live, both themes.

## Honest verdict

**`ENGINEERING PARTIAL — DOCUMENTED BLOCKERS`** for B14 — Quick Switch and per-conversation draft isolation are both real, live-verified, and fix a genuine bug this codebase had (silent draft misattribution across conversations); Workspace Tabs remains disclosed as out of scope, blocked on the same backend stream-correlation work already named for B10/B12, not fabricated or silently skipped.
