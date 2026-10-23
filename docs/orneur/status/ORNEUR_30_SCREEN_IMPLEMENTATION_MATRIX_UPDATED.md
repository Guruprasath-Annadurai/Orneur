# ORNEUR 30-Screen Implementation Matrix — Updated

**Branch:** `claude/b04-b09-implementation-2026-10-23`
**Date:** 2026-10-23
**Supersedes for current-state purposes:** `ORNEUR_30_SCREEN_IMPLEMENTATION_MATRIX.md` (PR #84, `claude/ui-implementation-programme-2026-10-23`) — that matrix is not rewritten in place (it belongs to a different branch/PR and is kept as the historical record of its own moment); this document reflects what has genuinely changed since, verified against the current branch's actual code and tests, not assumed to have carried forward automatically.

Status values: `IMPLEMENTED AND LOCALLY TESTED`, `IMPLEMENTED — INDEPENDENT AUDIT PENDING`, `PARTIALLY IMPLEMENTED`, `BLOCKED — AUTHENTIC DESIGN SOURCE MISSING`, `BLOCKED — BACKEND OR AUTHORITY DEPENDENCY`, `NOT STARTED`.

## What changed since PR #84's matrix

The PR #85 branch (this branch) implemented and locally tested **B06, B07, B08, B09** since that matrix was written (the `ORNEUR_B04_B09_ENGINEERING_REPORT.md` and subsequent liveness/ownership hardening on this same branch). Everything else in the B-series and all of the C-series is **unchanged** from PR #84's matrix — re-verified below, not merely copied forward.

## B-series

| ID | Name | Current implementation | Code location | Tests | Status |
|---|---|---|---|---|---|
| B01 | New Conversation / Home | Implemented | `conversation.html` | `test_conversation_shell.py`, `tests/frontend/*.mjs` | **IMPLEMENTED — INDEPENDENT AUDIT PENDING** |
| B02 | Active Conversation | Implemented | same | same | **IMPLEMENTED — INDEPENDENT AUDIT PENDING** |
| B03 | Answer Reading | Implemented | same | same | **IMPLEMENTED — INDEPENDENT AUDIT PENDING** |
| B04 | Expanded Composer | None | — | — | **NOT STARTED** |
| B05 | Native Model Selection | Partial overlap only (B01/B02's in-line model picker) | — | — | **NOT STARTED** |
| B06 | Conversation History | **Implemented** — real `GET /api/sessions`, rename/delete/export layered in | `conversation.html` | `test_recent_conversation_row.mjs` + this branch's epoch/ownership suite | **IMPLEMENTED AND LOCALLY TESTED** — *changed from NOT STARTED* |
| B07 | Conversation Search | **Implemented** — real `GET /api/sessions/search`, debounced, server-computed snippet | same | `test_search_ownership_epoch.mjs` | **IMPLEMENTED AND LOCALLY TESTED** — *changed from NOT STARTED* |
| B08 | Conversation Management | **Implemented** — rename (`PATCH /api/session/{id}/title`), delete (`DELETE /api/session/{id}`), both real, both server-persisted (verified via reload/re-fetch, not DOM-only) | same | `test_recent_conversation_row.mjs` | **IMPLEMENTED AND LOCALLY TESTED** — *changed from NOT STARTED* |
| B09 | Sharing & Export | **Implemented** — `GET /api/session/{id}/export` for `md` and `json`, real content verified end-to-end | same | covered by browser verification in `ORNEUR_B04_B09_ENGINEERING_REPORT.md` | **IMPLEMENTED AND LOCALLY TESTED** — *changed from NOT STARTED* |
| B10 | Streaming & Stop | Streaming truthfulness (terminal-state tracking, interrupted badge); dedicated "Stop" control not compared against B10's own contract | `conversation.html` | `test_streaming_completion_truth.mjs` | **PARTIALLY IMPLEMENTED** (unchanged) |
| B11 | Editing & Versions | None | — | — | **NOT STARTED** (unchanged) |
| B12 | Error & Recovery | Generic error/unavailable-note states (PR #81); this branch added real 401/session-expiry recovery (`_handleSessionExpired()`, see `ORNEUR_SESSION_EXPIRY_401_AUDIT.md`) layered on top, but B12's own "Calm Inline Recovery" / "Guided Recovery" visual contract still not compared | `conversation.html` | `test_view_ownership_epoch.mjs` (401 tests) | **PARTIALLY IMPLEMENTED** (unchanged classification; real functional addition underneath it) |
| B13 | Temporary / Private Chat | None | — | — | **NOT STARTED** (unchanged) |
| B14 | Multi-Conversation Navigation | None (single active conversation only; history list lets you switch, not view concurrently) | — | — | **NOT STARTED** (unchanged) |
| B15 | Citations & Sources | None (backend `source_summary`/`sources` fields exist, unused by frontend) | — | — | **NOT STARTED** (unchanged) |
| B16 | Context & Attachments | None | — | — | **NOT STARTED** (unchanged) |

## C-series — re-verified against newer design-handoff archives, not assumed unchanged

Four newer design-handoff archives exist in `/Users/ag/Downloads/` (dated 2026-10-22/23, after PR #84's audit): `ORNEUR_APPROVED_UIUX_AVAILABLE_ORIGINALS_PARTIAL_2026-10-22.zip`, `ORNEUR_PRODUCTION_DESIGN_HANDOFF_FINAL_2026-10-23.zip`, `_QUALIFICATION_V2.zip`, `_CLOSEOUT_V3.zip`. Inspected `CLOSEOUT_V3`'s own `01_AUTHENTIC_RECOVERED/C01_C11_ACCESS_BLOCKERS.md` (its own internal audit, not this session's assertion) directly:

> "C01: No authenticated original filename, ZIP, design frame or archive hash located... `APPROVED_REFERENCE_MISSING`."
> "C02–C10: original ZIP bytes are not mounted here. File materialization is rejected as lacking an authorized raw-byte path."
> "C11: ... reattempt to materialize returned: 'This Project file does not have an authorized raw-byte materialization path.' ... C11 recreated preview PNGs are NOT authentic final originals."
> "C12–C14: Original candidate ZIP physically included, unmodified, original SHA verified... Only three milestone sources locally recoverable."

**Conclusion: C01–C11 are still blocked on missing authentic design source** — re-confirmed by a different, more recent audit trail, not merely repeated from PR #84. **C12–C14** still have only the same previously-known founder-reviewed *candidate* ZIP (not a production-final original) — unchanged.

| ID | Name | Status | Why |
|---|---|---|---|
| C01 | Code Workspace | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** | Re-confirmed: no original located anywhere, including the newer archives |
| C02 | Live Mission Execution | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** *and* **BLOCKED — BACKEND OR AUTHORITY DEPENDENCY** | Original ZIP bytes still not materializable; backend (PR #79) under independent audit, not to be altered for a frontend's sake |
| C03 | Projects Workspace | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** | Same |
| C04 | Global Search | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** | Same |
| C05 | Evidence Workspace | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** | Same |
| C06 | Files & Documents | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** | Same |
| C07 | Relay Workspace | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** | Same |
| C08 | Models Workspace | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** | Same |
| C09 | Activity Workspace | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** | Same |
| C10 | Settings & Personalization | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** | Same |
| C11 | Authentication & Account Access | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** for the dedicated screen; `conversation.html`'s own functional auth overlay (Variant A minimal by default) is already shipped and was hardened further this session (focus trap, dialog semantics, now 401-recovery) | The CTO directive's "C11 Variant A default / Variant B conditional" requirement describes the EXISTING shipped auth overlay's own behavior almost exactly — recreating it from scratch without the dedicated original would risk silently inventing a "compatible-looking" redesign the directive explicitly forbids |
| C12 | New User Onboarding | **BLOCKED — BACKEND OR AUTHORITY DEPENDENCY** | Founder-approved candidate ZIP exists (verified SHA, unchanged from PR #84); no real onboarding-completion state exists in the backend to wire a genuine flow to, and the production logo placeholder issue (noted in PR #84) is unresolved |
| C13 | Subscriptions & Billing | **BLOCKED — BACKEND OR AUTHORITY DEPENDENCY** | No real billing/entitlement backend (one strict-auth endpoint, `/api/billing/checkout`, exists and creates a Stripe session, but no entitlement/plan-state backend to render truthfully) |
| C14 | Teams & Enterprise Administration | **BLOCKED — BACKEND OR AUTHORITY DEPENDENCY** | No real org/member/role backend exists |

## C11 — the one place this matrix deliberately pushes back on the directive, honestly

The CTO directive instructs implementing "the founder-approved unified C11 design" with Variant A default / Variant B conditional. Per the above, **C11's own dedicated original design source is not available** (confirmed independently, twice, across two different audit passes using different, newer archives). `conversation.html` already has a real, functional, accessible sign-in/sign-up overlay that IS effectively "Variant A, minimal, default" — contextual messages (expired session, 2FA-required, sign-in/signup failures) already appear only when needed, which is functionally close to "Variant B's contextual guidance appears only when needed." Rebuilding this from scratch without C11's own dedicated source, and calling the result "the founder-approved C11 design," would be exactly the kind of fabricated-reconstruction-presented-as-authentic the directive itself prohibits ("Do not fabricate missing original assets or call an approximate reconstruction an authentic approved design"). **Recorded as a blocker, not silently worked around or silently skipped.**

## Rollup

- **Implemented and locally tested:** 7 (B01–B03 audit-pending, B06–B09 newly so this branch)
- **Partially implemented:** 2 (B10, B12 — B12 gained real functional ground this phase via 401 recovery, classification held at Partial since the dedicated visual contract is still uncompared)
- **Not started:** 9 (B04, B05, B11, B13–B16)
- **Blocked on missing design source:** 11 (C01–C11)
- **Blocked on backend/authority dependency:** 3 (C12–C14), plus C02 doubly-blocked

No screen here is claimed complete merely because its static appearance would resemble the original, and no C-series blocker is claimed resolved without independently re-checking the newest available archives first.
