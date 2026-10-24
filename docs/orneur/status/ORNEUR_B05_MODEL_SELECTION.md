# B05 — Native Model Selection: Partial Implementation Report

**Branch:** `claude/b04-b09-implementation-2026-10-23`
**Source:** `APPROVED_SOURCE_ARCHIVES/ORNEUR_B05_FINAL_LOCK_AND_HANDOFF.zip` (SHA-256 `44fd0d85685c94eff219e73b57745bf1df407fc1ecce56dc9e519dbded637dfc`) — verified against `SHA256SUMS.txt` (17/17 files) before any code was written.

## Starting point: B05 was already substantially covered, not absent

Unlike B04, this codebase already had a real, backend-driven model picker (`loadModels()`/`renderModelOptions()`/`selectModel()`, built in earlier phases of this project): three native entries (Genesis/Novus/Aeternum) sourced from a real `GET /api/models`, honest lifecycle/disclosure/fallback labeling, no fabricated availability, a real `<button>`-based (not clickable-`<div>`) list. The prior matrix's "NOT STARTED" classification reflected that B05's own *dedicated* contract had never been read and compared — not that nothing relevant existed. This phase read `docs/B05_IMPLEMENTATION_CONTRACT.md` and closed the gaps it found against the *existing* picker, rather than rebuilding it.

## What was genuinely missing, found by comparing the contract against the real code

1. **Model selection survived an account switch.** `selectedModelVariant` was set by `selectModel()` and never reset anywhere else. The contract: *"On account/tenant switch or logout: clear selected model and cached private entitlements."*
2. **Unavailable rows were keyboard-unreachable.** `opt.disabled = true` removed the entire button from the Tab order — the contract: *"Buttons for Details must remain accessible even if selection is disabled... Never disable the entire row when it would hide reason/details from keyboard users."* A keyboard-only or screen-reader user could not discover *why* a model was greyed out.
3. **No Details disclosure existed at all** — the contract's required anatomy item 3 ("Details disclose only verified attributes... Hide empty/unverified metrics rather than displaying invented numbers").

## What was implemented

- **`resetModelSelection()`**: clears `selectedModelVariant`, restores the model button to its default "Choose model" label/state, hides the disclosure note, and re-evaluates send-eligibility. Wired into `_clearAuthStateAndShowSignIn()` (covers both `doLogout()` and `_handleSessionExpired()`), `onAuthSuccess()`, and `continueAnonymous()` — the same four identity-transition entry points this session's prior authentication audit already established, not re-derived from scratch.
- **Keyboard reachability fix**: unavailable rows now use `aria-disabled="true"` instead of the native `disabled` attribute, keeping `tabIndex` at its default so Tab still reaches them; every row (available or not) carries `aria-describedby` linking to its visible reason text.
- **Details disclosure**: a per-row "Details" toggle button, reachable regardless of availability, showing only fields `GET /api/models` actually returns for that tier — `model`, `lifecycle`, computed availability, `vision_capable` (when present), the actually-serving model when a fallback is active, and the disclosure label. No modalities, regions, limits, or pricing are shown, since the backend does not provide them — omitted rather than invented, per the contract.

## A real bug caught by live verification, not just reading the code

The Details panel's CSS was first written as `.model-details{display:flex;...}` with visibility meant to be controlled by the element's `hidden` property. Live-tested: every panel rendered **open by default** — `display:flex` on the class selector out-specifies the browser's own `[hidden]{display:none}` user-agent rule, so setting `.hidden = true` had no visible effect. Fixed by making `.open` (mirroring this file's existing `.modelmenu-panel.open` convention) the authoritative visibility toggle, with `.model-details{display:none}` as the real default. Reproduced and confirmed fixed live. A structural regression test guards against this pattern recurring.

## What was verified live, in a real browser

- Opening the picker shows Genesis/Novus/Aeternum with honest EXPERIMENTAL/fallback disclosure text, unchanged from the pre-existing behavior.
- Clicking "Details" on a row shows exactly the real backend fields (`Model: orca-nano`, `Lifecycle: EXPERIMENTAL`, `Availability: Ready`, `Vision input: Not supported`, `Disclosure: ...`) — confirmed these are not editable/fabricated by reading them directly off `_models` in the live page.
- Simulated an unavailable tier (`publicly_served: false`) and confirmed the row gets `aria-disabled="true"` with `tabIndex: 0` (no native `disabled` attribute) and a correctly-linked `aria-describedby` reason — real keyboard reachability, not merely visual greying.
- Selected a model, then called the real `doLogout()`: confirmed `selectedModelVariant` returned to `null` and the button label returned to "Choose model" with the availability dot cleared.

## What was deliberately not built in this pass, and why

- **A dedicated mobile bottom sheet** (contract anatomy item 4). The existing `.modelmenu-panel` is a responsive absolute-positioned dropdown, not a true bottom sheet with safe-area insets and a distinct mobile layout. Given this phase's priority was closing the two concrete truthfulness/accessibility gaps above (a genuine correctness bug and a genuine keyboard-accessibility bug) plus the Details disclosure named explicitly in the required anatomy, a full mobile-sheet rebuild was not attempted and is reported honestly as outstanding rather than rushed.
- **Listbox/roving-tabindex arrow-key navigation.** The contract allows "listbox, menu or dialog" as alternatives and asks for *one* consistent pattern; the existing `role="menu"` with real, independently-Tabbable buttons is a defensible existing choice and was not changed in this pass — arrow-key roving-tabindex navigation within the list was not added.
- **200%/400% zoom and the full 320–1536px width sweep** (contract section 8) were not run as a dedicated pass in this increment.

## Tests

```
node --test tests/frontend/test_b05_model_picker.mjs   # 6 tests, new
node --test tests/frontend/*.mjs                          # 93/93 passing (was 87)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

Four structural regression guards (no native `disabled` attribute reintroduced, the `.model-details` display/`[hidden]` specificity bug can't recur, no fabricated fields beyond what the backend returns, `resetModelSelection()` wired into all four identity-transition entry points) plus two behavioral tests against the real `resetModelSelection()`/`updateSendEnabled()` functions with a minimal fake DOM.

## Honest verdict

**`ENGINEERING PARTIAL — DOCUMENTED BLOCKERS`** for B05 specifically — this closes two real, live-reproduced bugs (the account-switch model-selection leak and the keyboard-unreachable disabled rows) and adds the contract's required Details disclosure using only verified backend fields, but the dedicated mobile bottom sheet and the full accessibility/zoom test matrix (contract section 8) remain outstanding and are disclosed above, not silently treated as complete.
