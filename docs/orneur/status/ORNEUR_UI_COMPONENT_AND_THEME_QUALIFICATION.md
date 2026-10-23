# ORNEUR UI Component and Theme Qualification

**Branch:** `claude/ui-implementation-programme-2026-10-23`
**Date:** 2026-10-23

## Official theme tokens — verified against the live `:root`/`body.dark` CSS in `orca/serve/web/conversation.html`

| Directive-cited anchor | Claimed value | Actual in code | Match |
|---|---|---|---|
| Obsidian canvas | `#080808` | `body.dark{--bg:#080808}` | ✅ exact |
| Meridian canvas | `#F6F3EE` | `:root{--bg:#F6F3EE}` | ✅ exact |
| Slate Indigo | `#3A4B6B` | `:root{--accent:#3A4B6B}` (unchanged by this session's A-P1-02 contrast fix, confirmed) | ✅ exact |
| Solar Coral | `#FF6B57` | `:root{--coral:#FF6B57}` (also unchanged) | ✅ exact |
| Pale Stone | `#E8E4DE` | **Not found anywhere in the current stylesheet.** The closest existing token is `--border:#E4DED6` (light theme) — a different value, not a match. | ❌ **unresolved discrepancy, flagged rather than assumed** |

The Pale Stone discrepancy is reported exactly as found, not silently reconciled: either (a) Pale Stone is a planned token not yet wired into any implemented screen, or (b) it was meant to replace `--border` or another existing light-theme value and the implementation is stale. This needs a one-line founder/design clarification, not an engineering guess — see `ORNEUR_UI_IMPLEMENTATION_AUDIT_HANDOFF.md`.

No neon accents, gradients, unrelated purple styling, decorative geometry, or futuristic-dashboard treatment were found anywhere in the current stylesheet — confirmed by reading the full `<style>` block, not sampled.

## Shared component inventory (what actually exists today, reusable or not)

| Component | Status | Notes |
|---|---|---|
| Sidebar / navigation | Partial | "New conversation" + recent-conversations list + account row exist and are reusable; Search/Projects/Library/Settings rows do not exist (see fidelity report). |
| Conversation composer | Implemented, reusable | `<template id="composer-template">` + `mountComposer()` is already a real shared-component pattern (used for both the empty-state and active-conversation composer slots) — a sound foundation for B04's "Expanded Composer" variant, not yet built. |
| Model selector | Implemented, reusable, hardened this session | Real `<button>`-pattern dropdown (A-P1-03), `aria-expanded`/`aria-haspopup`, keyboard-operable. |
| Menus and popovers | Only the model selector exists as a popover; no generic popover primitive. | A future B04–B16 build would need to decide whether to generalize this or keep one-off popovers — not decided here (would be a "technically justified, separately reviewable" architecture choice per the directive, not made unilaterally in this pass). |
| Dialogs and sheets | One real dialog exists: the auth overlay, hardened this session (`role="dialog"`, focus trap, focus restoration — A-P1-03). No sheet/drawer primitive beyond the mobile sidebar drawer. |
| Notifications and errors | `appendUnavailableNote()` / `markMessageInterrupted()` / `.autherr` exist and are reusable; no toast/notification-center primitive. |
| Loading and streaming states | Implemented and hardened this session: `appendThinking()`, `appendStreamingMessage()`, `finalizeStreamingMessage()`, explicit terminal-state tracking (P1-01, A-P1-01). |
| Code blocks | Implemented and hardened this session: fenced/inline code protected from inline-Markdown reinterpretation (A-P2-01). |
| Evidence presentation | **Does not exist.** Backend `source_summary`/`sources` fields are present in `/api/stream`'s `done` event but entirely unused by the frontend. |
| Authentication controls | Implemented, hardened this session (A-P1-03): real dialog semantics, keyboard trap, `role="alert"` errors. |
| Mobile navigation | Implemented: hamburger button, veil overlay, slide-in drawer, `prefers-reduced-motion` override (A-P2-02). |
| Shared typography/spacing/tokens | A real token system exists (`:root`/`body.dark` CSS custom properties) — the Pale Stone gap above is the only verified discrepancy in it. |

## What this document does not do

No consolidation/refactor was performed in this pass — only inventory and verification. Consolidating the above into a formally shared component library (per Assignment C) is real, multi-screen-touching engineering work that depends on B04–B16 actually being built first (there's nothing to "share" between B01–B03 and screens that don't exist yet); doing it prematurely would risk exactly the "unnecessary framework rewrite" the directive warns against.
