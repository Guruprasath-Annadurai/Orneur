# B13 — Temporary / Private Chat: Honest Disabled-State Implementation

**Branch:** `claude/b04-b09-implementation-2026-10-23`
**Source:** `APPROVED_SOURCE_ARCHIVES/ORNEUR_B13_FINAL_LOCK_AND_HANDOFF.zip` (SHA-256 `f0ee3ddc1c44885a8adf3cb88d95cfd9b0a13202bdc8aaeeb78541606a14f9a8`) — verified via the archive's own `verification/verify_handoff.py`: 32 package files + 24 approved source files passing, before any code was written.

## Why this is a disabled-state implementation, not a stop

`docs/B13_IMPLEMENTATION_CONTRACT.md` requires a server-owned typed session capability (owner/tenant binding, a `NOT_ACTIVE → POLICY_CHECK → ACTIVATION_PENDING → ACTIVE → (EXPIRED|CLOSED|FAILED)` state machine, server-enforced TTL/retention across the primary database, search index, caches, memory/RAG stores, exports, attachments, and more) — none of which exists anywhere in this codebase. Grepped `orca/serve/` and `orca/auth/` for any temporary/ephemeral/private-mode session concept: the only hit was an unrelated comment about `ExplainStore` (explainability data, not conversations). The contract's own explicit instruction for exactly this situation: *"If unsupported, show a clearly disabled state with a succinct explanation (not a fake toggle)."* That is what this phase builds — not a stop, because the contract itself sanctions this as the correct, scoped response to an absent backend.

## The locked design is itself already honest — implemented faithfully, not reworded

The approved reference prototype (`references/ORNEUR_B13_Unified_Dark.html`) is not a polished "it works" mockup — it is explicitly labeled `B13 CONCEPT · ILLUSTRATIVE ONLY · NO LIVE PRIVACY OR MODEL SERVICE`, and its own "Start temporary chat" button is already disabled with the title `"Concept review · action disabled until verified implementation."` This phase reused that **exact, real, founder-approved copy** verbatim (the privacy-rule text, the "This preview creates no session" footnote, the disabled action's own label) rather than writing new wording — faithfully implementing an honest design is the correct action here, not a shortcut.

## What was implemented

1. **Discoverability**: a compact "Temporary" control in the existing chat header (`.topright`, next to the Relay status badge) — not a floating dashboard item, matching the contract's placement requirement.
2. **Details dialog**: clicking it opens an accessible dialog (`role="dialog" aria-modal="true"`) with the three real locked privacy-rule sections (Conversation history / Data retention / Access and model readiness) and the honest footnote. Desktop: a contextual side panel. Mobile (≤650px): a bottom sheet. Both reuse the same accessible-dialog pattern already established this session (focus trap, Escape, backdrop-click, focus restoration) rather than a new, unproven mechanism.
3. **The one action stays genuinely disabled**: "Start temporary chat" carries a real `disabled` attribute (not a fake clickable control that silently does nothing) with its title explaining why — a structural test asserts no code path anywhere ever attempts to create or claim a temporary session.
4. **Account-transition safety**: `newConversation()` (routed through by logout/login/account-switch) now closes the temp-mode panel first, matching the same precedent already established for B04's draft workspace — a derelict dialog must not survive an identity transition.

## A real layout bug caught by live verification

At the mobile bottom-sheet width, "Start temporary chat"'s longer text wrapped to a third line and visually overflowed the `.expand-action` class's fixed `34px` height (sized for B04's short labels), spilling into and overlapping the "Back" button beside it. Reproduced live, fixed with a scoped override (`flex:1;height:auto;min-height:40px`) for this panel's buttons specifically, without touching B04's own styling. Confirmed fixed live, both themes.

## Verified live, in a real browser

Clicked "Temporary" in the header: dialog opened with the real locked copy, correct bottom-sheet layout at mobile width. Verified Escape closes it and restores focus to the triggering button (confirmed via `document.activeElement`). Verified Meridian light theme renders correctly with visible focus ring. Confirmed the "Start temporary chat" button has a real `disabled` attribute (not just visual styling) by inspection.

## Tests

```
node --test tests/frontend/test_b13_temporary_chat.mjs   # 7 tests, new
node --test tests/frontend/*.mjs                             # 118/118 passing (was 111)
pytest tests/test_conversation_shell.py tests/test_background_task_tracking.py -q   # 13/13 passing
```

Structural guards: the disabled attribute is real, not simulated; no code path ever attempts session activation; the panel is idempotent and manages focus correctly; `newConversation()` closes it; the button-overflow fix is present.

## What remains genuinely blocked

Everything the contract actually asks for beyond discoverability + honest explanation: the server-owned session capability and its full state machine, server-enforced retention/TTL across every data store the contract enumerates (primary DB, B06 history grouping, B07 search index, B09 exports, B04 drafts, B10 partial streams, B11 versions, B12 retry/transcript replay, memory/RAG stores, attachments, backups, audit logs). None of this exists today, none of it was fabricated here, and building any of it is explicitly out of this phase's scope per the contract's own repeated instruction not to invent backend capability.

## Honest verdict

**`ENGINEERING PARTIAL — DOCUMENTED BLOCKERS`** for B13 — the one piece the contract itself sanctions building without backend support (discoverable, honestly-disabled entry point with a truthful explanation) is implemented, source-faithful, and live-verified, including a real bug caught and fixed through that verification. The actual temporary-session capability remains entirely unbuilt and is reported as a genuine, disclosed blocker, not a stop condition this phase was unable to work around.
