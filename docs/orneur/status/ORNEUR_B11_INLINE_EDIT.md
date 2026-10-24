# B11 — Editing & Versions: Honest Disabled-State Implementation

**Branch:** `claude/b04-b09-implementation-2026-10-23`
**Source:** `APPROVED_SOURCE_ARCHIVES/ORNEUR_B11_FINAL_LOCK_AND_HANDOFF.zip` (SHA-256 `a6f6d0350bc3f889fdcb572447857e69f73bda59b28000a1befaa8f0e38c2401`) — verified against `manifests/SHA256_MANIFEST.json`'s per-file `sha256`/`size_bytes` records: 21/21 files passing, before any code was written.

## Why this is a disabled-state implementation, matching B13's precedent

`docs/B11_IMPLEMENTATION_CONTRACT.md` requires a message-edit state machine (`viewing → editing_draft → submitting_edit → edit_acknowledged/edit_error`) bound to server-side precondition/ETag checks, immutable version lineage, and a full regenerate pipeline (idempotency keys, branch/version tracking, server-confirmed cancellation reusing B10). None of this exists: grepped `orca/serve/api.py` and `orca/serve/conversations.py` for `edit_message`/`message_version`/`version_id`/`regenerate`/`lineage` — zero hits. The only message-related endpoint is the read-only `GET /api/session/{id}/messages`. The contract's own explicit instruction for exactly this: *"If any required contract is absent, leave dependent UI disabled/fail-closed, document the gap."*

## The locked design is itself already honest — reused, not reworded

Same pattern as B13: the approved prototype (`prototypes/B11_A_Dark.html`) is explicitly labeled `B11 DESIGN PREVIEW · NO QUALIFIED MODEL OR LIVE REGENERATION`, its own edit panel already says `"Local preview · not submitted"` and `"The original stays in history. Sending the edit requires an available model."`, and it states outright: *"The production UI must preserve original prompts and responses. It must not imply a regeneration succeeded without backend confirmation."* This phase reused that exact copy verbatim.

## What was implemented: Inline Edit only

The contract names two surfaces: **Inline Edit** (default) and optional **Response Versions** (compare/regenerate). Only Inline Edit was built:

- An "Edit" button appears below every user message (`appendUserMessage()`), opening an inline panel with a textarea pre-filled with **the exact original text** — reset on every open, so an abandoned draft from a prior open/cancel never silently reappears.
- **Cancel** closes the panel with zero mutation and restores focus to the Edit button, per the contract's own `Cancel` semantics ("restores the original displayed message; no mutation").
- **"Save edit" carries a real `disabled` attribute** (not a fake clickable control that silently no-ops), with its `title` naming the exact gap: *"Editing requires a real message-edit endpoint, which does not exist in this backend yet."* A structural test asserts no code path in `appendUserMessage()` ever calls `fetch()`, issues a `PATCH`, or claims an `edit_acknowledged` state.

**Response Versions/Regenerate/Compare was not built.** There is no second response version anywhere in this backend to compare against or regenerate from — building even a disabled affordance for it would have nothing real to anchor to, unlike Inline Edit's disabled Save (which anchors to a genuinely absent but well-specified endpoint). Disclosed as out of scope, not silently skipped.

## A real bug avoided by applying this session's own established lesson

The edit panel's visibility CSS was written directly as `.edit-msg-panel.open{display:block}` with the base rule left at `display:none` — the `.open`-class toggle pattern already proven necessary (and the lack of it already caught live, twice, for B05's Details panel and B15's Sources panel this same session). A structural regression test explicitly asserts the base rule never regains a forcing `display` value, so this known bug class can't silently reappear here too.

## Verified live, in a real browser, both themes

Opened a real conversation, clicked "Edit" on the real user message: the textarea appeared pre-filled with the exact original text and auto-focused, the honest note displayed, "Save edit" confirmed genuinely `disabled` (via direct DOM inspection, not just visual styling) with the correct `title`. Clicked Cancel: panel closed, focus correctly returned to the Edit button (`document.activeElement` check). Confirmed Meridian light theme renders correctly.

## Tests

```
node --test tests/frontend/test_b11_inline_edit.mjs   # 6 tests, new
node --test tests/frontend/*.mjs                          # 133/133 passing (was 127)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

Structural guards: the disabled attribute is real; no edit-submission code path exists anywhere; the textarea always resets to the true original; the `[hidden]`/`display` specificity bug class can't recur here; the disabled explanation names the real, specific gap. One behavioral test exercises the real `appendUserMessage()` end to end against a minimal fake DOM (Edit opens the panel with the correct pre-filled text; closed by default).

## What remains genuinely blocked

The full message-edit state machine, server-side precondition/ETag enforcement, immutable version lineage, and the entire Response Versions/Regenerate/Compare surface (idempotency-keyed regeneration, branch tracking, server-confirmed cancellation reusing B10's own still-blocked cancellation work) — none of this exists today, none of it was fabricated here.

## Honest verdict

**`ENGINEERING PARTIAL — DOCUMENTED BLOCKERS`** for B11 — the contract's own sanctioned response to an entirely absent backend (a genuinely disabled, honestly-explained entry point, using the locked design's own already-honest copy) is implemented and live-verified, including a real caught-in-advance CSS bug avoided by applying this session's own prior lesson. The actual edit/regenerate capability remains entirely unbuilt and is reported as a genuine, disclosed blocker.
