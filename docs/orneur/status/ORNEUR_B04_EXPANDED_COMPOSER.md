# B04 — Expanded Composer: Implementation Report

**Branch:** `claude/b04-b09-implementation-2026-10-23`
**Source:** `APPROVED_SOURCE_ARCHIVES/ORNEUR_B04_FINAL_LOCK_AND_HANDOFF.zip` (SHA-256 `ad5e1304c096029df337c8d8aee2ecef79d6a3c62ad46a08bf9879dd093fffad`) — verified against `SHA256_MANIFEST.txt` and the archive's own `verify_assets.py` (26/26 files, zero failures) before any code was written.

## What B04 is

Per `docs/B04_IMPLEMENTATION_CONTRACT.md` (included in the source archive): a composer state machine — normal composer → **FOCUSED_EXPANDED** (taller inline editor with a header bar) → **DRAFT_WORKSPACE** (a dedicated modal editor) — for preparing long prompts, with the same unsent draft shared across both expanded views.

## Design decision: reparent the real composer, never clone it

The archive's static HTML prototype (`prototypes/B04_Combined_*.html`) uses two separate `<textarea>` elements and a small JS snippet that copies `.value` between them on open/close. That satisfies a *static design preview*, but the implementation contract's "Editing fidelity" section requires caret position, selection, undo/redo history, IME composition state, and scroll position to survive every transition — a value-copy loses all of that.

This codebase already has the right mechanism for this, in production, today: `mountComposer(slotId)` reparents a single persistent `composerEl` between `#composer-empty-slot` and `#composer-active-slot` (B01/B02's own existing architecture). B04 extends the exact same pattern with a third destination, `#draft-workspace-slot`. The textarea, model picker, and send button are never cloned — only moved — so there is no synchronization step and therefore no class of bug where the FOCUSED_EXPANDED and DRAFT_WORKSPACE views' content could diverge. This also means the model picker and send button inside the workspace are the **real, already-wired** controls (populated from `loadModels()`, enabled/disabled by the real `updateSendEnabled()`), not a parallel disabled mock — satisfying the contract's "Runtime model eligibility... must come from verified backend state. No mock model names" requirement for free.

## A real bug caught by live verification, not just reading the code

The CSS was initially written as `.composer.focused-expanded{...}` and `.workspace-body .composer{...}`, assuming `composerEl` itself carries the pre-existing `.composer` class. It doesn't — that class lives on the fixed slot elements (`#composer-empty-slot`/`#composer-active-slot`) in the static markup; `composerEl` has always been a bare, unstyled wrapper `<div>`. Live-tested in a real browser: clicking "Expand" visually did nothing (the class was being added correctly, but no CSS rule matched it), and opening the draft workspace rendered the textarea with the browser's default **white** background in dark theme (the `.workspace-body .composer textarea{...}` rule never matched once reparented outside any `.composer`-classed ancestor).

**Fixed**: `composerEl.id = 'live-composer'` assigned once at creation; every new CSS rule rewritten to target `#live-composer` directly, independent of whichever parent it currently has. Reproduced and confirmed fixed live (both themes). A structural regression test (`test_b04_expanded_composer.mjs`) now asserts neither broken selector pattern can be reintroduced.

## What was verified live, in a real browser, both themes

- **FOCUSED_EXPANDED**: clicking "Expand composer" shows the header bar ("Expanded prompt · Unsent draft", "Open draft workspace" + "Collapse" actions), textarea grows, draft text and caret position preserved exactly (typed text, checked `selectionStart` before/after).
- **DRAFT_WORKSPACE**: "Open draft workspace" opens the modal with the exact same draft text already present (the same element, not a copy); `role="dialog" aria-modal="true"`; `#app-root` gets `inert` while open; focus moves into the textarea.
- **Escape** closes the workspace, returns to FOCUSED_EXPANDED (not all the way to normal, per the contract's state diagram), draft preserved, `inert` removed, focus restored to the textarea.
- **Tab focus trap**: focused the last control (`send-btn`), pressed Tab, confirmed wraparound to the first (`close-workspace-btn`) — the same pattern already established for the auth overlay, applied here via a dedicated `_workspaceFocusableEls()`.
- **Collapse** (from FOCUSED_EXPANDED) returns to the normal composer state, draft preserved, focus lands on the expand button.
- **Both themes**: Obsidian dark and Meridian light both render correctly using the existing `--bg`/`--compose`/`--border`/`--ink` tokens (which already match the contract's locked `#080808`/`#191919`/`#303030` values — no new hardcoded colors introduced).
- **Mobile (375px)**: the workspace goes edge-to-edge fullscreen, the header's "Return to conversation" label swaps to "Back", no horizontal overflow. FOCUSED_EXPANDED's header bar wraps gracefully at this width.
- **Account-switch safety**: `newConversation()` (which `doLogout()`, `onAuthSuccess()`, and `continueAnonymous()` all route through) now calls `collapseComposer()` first, which itself closes an open draft workspace before collapsing — so an account transition can never leave a derelict modal, or another account's draft, visible.

## What was deliberately not built, and why

- **Attachments**: the attachment tray shows a static, honest `0 files · None uploaded` status row, matching the contract's explicit default spec, with no interactive "add attachment" affordance — there is no real file-upload backend endpoint in this application (B16, Context & Attachments, remains `NOT STARTED`), and the contract explicitly prohibits advertising a file as uploaded without real backend-confirmed metadata.
- **Collapse from the composer back to a true "no draft" state**: the FOCUSED_EXPANDED prototype's own secondary icon button is a *disabled* placeholder in the source archive ("Collapse composer is not available in this concept"); B04's actual, functional collapse (back to the normal single-line composer) is a real, separate affordance this implementation added (`#collapse-composer-btn`), since the contract's state diagram explicitly allows it ("user collapses → normal composer [if collapse is separately implemented]").

## Tests

```
node --test tests/frontend/test_b04_expanded_composer.mjs   # 12 tests, new
node --test tests/frontend/*.mjs                              # 87/87 passing (was 75)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

Three structural regression guards specifically lock in the fixed `.composer`/`#live-composer` bug (asserting the id assignment exists, asserting the broken selector patterns are absent, asserting the workspace textarea rule carries its base — not just size — styling). The remaining nine tests exercise the real `expandComposer()`, `collapseComposer()`, `openDraftWorkspace()`, `closeDraftWorkspace()`, `_workspaceFocusableEls()`, and `newConversation()`'s new guard, against a minimal fake DOM (classList/parentElement/appendChild/querySelector) sufficient to verify reparenting, idempotency, inert-toggling, and focus restoration without needing a full browser harness for the unit layer.

## Honest limitations

- IME composition and full undo/redo-stack preservation were not independently exercised keystroke-by-keystroke in this pass (the reparenting design guarantees this structurally, since the element is never cloned or its value ever reassigned during a transition — but a dedicated IME/undo-stack live test was not separately run).
- 200%/400% zoom and a full cross-browser pass (contract section 8) were not run in this increment; the 375px mobile check and both-theme desktop checks above were.
- The small `#expand-btn` inside the workspace toolbar remains reachable via Tab while already inside the workspace (clicking it again is a harmless idempotent no-op, since `expandComposer()` just re-adds an already-present class) — not pruned from the workspace's focusable set in this pass; a minor redundancy, not a defect.

## Honest verdict

**`ENGINEERING PASS — INDEPENDENT REQUALIFICATION PENDING`** for B04 specifically. Source-verified, a real defect caught and fixed via live verification (not merely unit tests), both themes and mobile checked, 87/87 JS and 13/13 Python tests passing. B01–B03 and B06–B09 unchanged by this work. Does not touch PR #79, PR #81, or Cursor's Foundation-X branches.
