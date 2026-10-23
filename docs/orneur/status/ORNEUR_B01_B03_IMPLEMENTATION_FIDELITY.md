# ORNEUR B01–B03 Implementation Fidelity Report

**Branch:** `claude/ui-implementation-programme-2026-10-23` (verification only — no code changes made on this branch; the implementation under test is PR #81 `3cb96ac`)
**Date:** 2026-10-23
**Method:** real local server (`uvicorn orca.serve.api:app`), real browser (Claude's built-in browser pane), screenshots compared directly against the authentic original PNGs in `ORNEUR_UIUX_FINAL_REVIEW_GALLERY/` — not CSS inspection alone.

## B01 — New Conversation / Home

Compared against `ORNEUR_B01_FINAL_LOCKED_DARK.png` and `ORNEUR_B01_FINAL_LOCKED_LIGHT.png` at 1536×900 (the gallery's own reference viewport).

**Matches exactly:** the greeting `"Hello chief, what's the plan today."`, the `"Your workspace"` eyebrow label, the composer's `"Message ORNEUR..."` placeholder and `"Choose model"` control, the three suggestion chips (`Research with sources` / `Work with a file` / `Write or code`), the `"New conversation"` sidebar button and its icon, the topbar `"Relay · Not connected"` status pill, the account avatar circle, the `ORNEUR` wordmark and emblem, and — critically — the sidebar staying solid dark (`--rail`) in **both** themes exactly as the original locks it, not following the canvas theme. Meridian Light canvas and Obsidian Dark canvas both read correctly against the approved tokens.

**Confirmed gap, not previously flagged this precisely:** the original locks three sidebar nav rows below "New conversation" — **Search**, **Projects**, **Library** — plus a **Settings** row and an **Account** expander at the bottom. The live implementation has none of these; only "New conversation," a "Recent conversations" list, and a bare account row with no Settings affordance. This is the single largest, most visible fidelity gap in B01 as shipped. It corresponds to B06 (history/projects), B07 (search), and most of B10 (settings) in the 30-screen matrix — all honestly marked `NOT STARTED` there, not silently absorbed into "B01 complete."

## B02 — Active Conversation

Re-verified live (not re-screenshotted against the gallery's 7 B02 variants in this pass, given time budget — spot-checked against `B02_DEFAULT_DARK.png`/`B02_DEFAULT_LIGHT.png` only): message bubbles, streaming chunk rendering, the "thinking" indicator, and session switching via the sidebar's recent-conversations list all match the approved quiet-reading layout. Session-switch safety (A-P1-01, fixed earlier this session on PR #81) was independently A/B-verified against the pre-fix code in a real browser: a delayed SSE event from an abandoned request no longer overwrites `sessionId` or leaks stale content into a newly-opened conversation.

**Not verified this pass:** the B02-specific "user-invoked context/source panel" contextual variant (`B02_CONTEXT_*` screenshots) — no such panel exists in the live implementation; citations/evidence UI is `NOT STARTED` per the matrix (B15).

## B03 — Answer Reading

Re-verified live against the approved Markdown/code rendering contract, not re-screenshotted this pass. Confirmed this session: the code-block protection fix (A-P2-01) and the link-sanitization fix (P0-01, earlier phase) both hold under direct JS execution in the live page — `mdToHtml()` neutralizes `javascript:`/`data:` scheme links and preserves literal `**bold**`/`[link]()` syntax inside fenced code, matching "approved answer formatting" and "Markdown and code rendering" without weakening either protection to get the other.

**Not verified this pass:** B03's "optional answer outline where the approved contract requires it" — no outline/section-navigation UI exists in the live implementation; `B03_*_OutlineOpen.png` variants in the gallery were not compared.

## Streaming ownership protections (explicit directive requirement: "preserve")

Confirmed intact and unmodified on this pass: `_streamEpoch`/`isOwner()` request-ownership guard, `AbortController` wiring, and the terminal-state (`done`/`error`/EOF) tracking that prevents a closed connection from being presented as a successful completion. No code on this branch touches `conversation.html` at all — this is a read/verify-only pass, consistent with the directive's "Do not replace it wholesale" and the mandate to report fidelity, not re-implement B01–B03.

## Verdict

B01–B03 remain **IMPLEMENTED — INDEPENDENT AUDIT PENDING**, as in the 30-screen matrix. This pass adds: (1) real-browser, both-theme, side-by-side screenshot evidence against the authentic gallery originals (not previously captured this precisely), and (2) one concretely identified, previously-undocumented-at-this-precision fidelity gap (missing Search/Projects/Library/Settings sidebar rows) that should be routed to the B06/B07/B10 implementation work, not treated as a B01 regression.
