# Phase C — B11 Real Message Editing and Versions

Per the CTO's Phase C-I Continuation Directive, using Cursor PR #94's real routes (verified live against the actual merged backend, not assumed from docs).

## What changed from the honest disabled-state implementation

The prior B11 implementation (`ENGINEERING PARTIAL — DOCUMENTED BLOCKERS`) correctly reflected that no edit/version backend existed. PR #90-98 adds it. Reconnected the existing, founder-approved Inline Edit UI to the real routes — no visual redesign.

**A real, confirmed gap found before writing any code**: `/api/stream`'s `done` event only echoes the ASSISTANT's `message_id` — read `_persist_turn()` directly and confirmed the user side's id is a separate UUID generated during persistence and never returned to the client. A freshly-sent message therefore cannot be edited at the instant it's sent; `_backfillMessageIds()` (new) re-fetches the real message list once the exchange completes and attaches the real ids to both bubbles. A message loaded via `openSession()` already carries real ids directly from `GET .../messages` (which now adds `message_id`, `version_id`, `version_count`, `edited`) — no backfill needed there.

## Implemented

- **Real edit save**: `POST .../messages/{id}/edits` with a fresh `crypto.randomUUID()` Idempotency-Key per save. Save stays genuinely `disabled` (real HTML attribute, not just a CSS class) until a real `message_id` is known, with an honest, specific reason ("hasn't finished saving yet"), and is disabled again the instant a save request starts (duplicate-submit protection against a second click firing a second request).
- **Correct response synchronization**: the displayed bubble updates to the server's own `active_content`, not merely the typed draft — matters because the server is the authority on the active version.
- **Loading/error states**: "Saving..." while in flight; on failure, the real server error text is shown, the panel stays open, and the user's draft is preserved (never silently discarded).
- **Read-only version history**: a new disclosure (closed by default, matching this file's established `.open`-class pattern) backed by the real `GET .../versions`, showing each version's kind (`original`/`edit`/`regeneration`) and content, with the active one labeled. No prev/next activation control — the backend exposes no such route, and the addendum explicitly forbids inventing one.
- **Honest copy preserved/extended**: editing does not erase long-term memory, and does not regenerate the response below (both explicitly true per the handoff doc and now stated in the UI itself, not just in a design doc).

## Deliberately not built, disclosed per the directive

**Regenerate** (assistant-side "generate a new response version") is not built. The originally-approved B11 design only ever included Inline Edit as its default surface; Response Versions/Regenerate was the explicitly-named optional surface, not built when no backend existed at all. The addendum states: *"Do not extend the approved B11 design without founder approval."* Building a new Regenerate control now — even though the backend supports it — would be exactly that extension. Flagged here as a real, available backend capability intentionally left unconnected pending founder approval of the UI surface, not a silently-skipped item.

## Live verification, not just unit tests

Ran the actual merged backend end-to-end through the real composer/UI:
1. Sent a real message; confirmed `_backfillMessageIds()` attached the real `message_id` to the user bubble (network trace: the exact id matches the one `GET .../messages` independently reports).
2. Opened the real Edit panel, Save was genuinely enabled (real `disabled` attribute cleared).
3. Saved a real edit via the actual Save button; confirmed via the network log the real `POST .../edits` fired with the correct `message_id`, and the displayed bubble updated to the server's own `active_content`.
4. Opened the real "Edited" badge → version-history panel; confirmed it loaded the real `GET .../versions` data and rendered all three real versions (original, edit, edit·active) in correct order with honest labels.
5. Screenshotted both Obsidian Dark and Meridian Light — consistent styling, no regressions, the founder-approved visual identity preserved.

## Tests

```
node --test tests/frontend/*.mjs   # 184/184 passing (was 175; test_b11_inline_edit.mjs rewritten: 15 tests, was 5)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

`test_b11_inline_edit.mjs` is entirely rewritten (the old file's premise — "no backend exists" — is now false) rather than patched: real edit-save flow (success, failure, 401), duplicate-submit protection, honest disabled-until-backfilled state, version-history read-only guard (structurally asserts no activation-style code exists), and the explicit absence of any Regenerate code path.

## Honest verdict

**IMPLEMENTED AND INTEGRATION-TESTED** (not independently qualified, not production authorized). Inline Edit, version history viewing, and correct response synchronization are real, live-verified, and tested. Regenerate is a disclosed, deliberate scope boundary pending founder approval of extending the approved B11 design, not a gap hidden from this report.
