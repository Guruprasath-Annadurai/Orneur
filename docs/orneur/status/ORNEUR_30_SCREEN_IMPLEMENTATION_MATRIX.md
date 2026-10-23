# ORNEUR 30-Screen Implementation Matrix

**Branch:** `claude/ui-implementation-programme-2026-10-23`
**Date:** 2026-10-23

Status values used below are exactly the six defined by the CTO directive: `IMPLEMENTED AND LOCALLY TESTED`, `IMPLEMENTED — INDEPENDENT AUDIT PENDING`, `PARTIALLY IMPLEMENTED`, `BLOCKED — AUTHENTIC DESIGN SOURCE MISSING`, `BLOCKED — BACKEND OR AUTHORITY DEPENDENCY`, `NOT STARTED`.

**Honest summary up front:** this pass implemented nothing new beyond what PR #81 already shipped (B01–B03). It independently verified sources (see `ORNEUR_B_SERIES_SOURCE_VERIFICATION.md`) and re-confirmed B01–B03's fidelity in a real browser (see `ORNEUR_B01_B03_IMPLEMENTATION_FIDELITY.md`). B04–B16 are source-available but **not started** — this is a 13-screen, multi-session body of work and this pass did not attempt to fabricate partial implementations of it. C01–C11 are blocked on missing sources. C12–C14 are blocked on both a production logo decision and missing real backend APIs (billing, team administration).

## B-series

| ID | Name | Original source | Current implementation | Code location | Tests | Status |
|---|---|---|---|---|---|---|
| B01 | New Conversation / Home | Verified (274/274, see source doc) | Implemented | `orca/serve/web/conversation.html` | `tests/test_conversation_shell.py`, `tests/frontend/*.mjs` (42 passing) | **IMPLEMENTED — INDEPENDENT AUDIT PENDING** |
| B02 | Active Conversation | Verified | Implemented | same | same | **IMPLEMENTED — INDEPENDENT AUDIT PENDING** |
| B03 | Answer Reading | Verified | Implemented | same | same | **IMPLEMENTED — INDEPENDENT AUDIT PENDING** |
| B04 | Expanded Composer | Verified (archive present, not opened/compared this pass) | None | — | — | **NOT STARTED** |
| B05 | Native Model Selection | Verified | Partial overlap only — the composer's in-line model picker (B01/B02's own dropdown) is implemented; B05's own dedicated contract not compared | — | — | **NOT STARTED** |
| B06 | Conversation History | Verified | Partial overlap — a basic sidebar conversation list exists (B01/B02 scope); B06's own richer contract (pinning, project org) not compared | — | — | **NOT STARTED** |
| B07 | Conversation Search | Verified | None | — | — | **NOT STARTED** |
| B08 | Conversation Management | Verified | None | — | — | **NOT STARTED** |
| B09 | Sharing & Export | Verified | None | — | — | **NOT STARTED** |
| B10 | Streaming & Stop | Verified | Streaming truthfulness (terminal-state tracking, interrupted badge) implemented as part of PR #81's own remediation; a dedicated "Stop" control per B10's exact contract not compared | `conversation.html` | `test_streaming_completion_truth.mjs` | **PARTIALLY IMPLEMENTED** |
| B11 | Editing & Versions | Verified | None | — | — | **NOT STARTED** |
| B12 | Error & Recovery | Verified | Generic error/unavailable-note states exist (PR #81); B12's own "Calm Inline Recovery" / "Guided Recovery" contract not compared | `conversation.html` | — | **PARTIALLY IMPLEMENTED** |
| B13 | Temporary / Private Chat | Verified | None | — | — | **NOT STARTED** |
| B14 | Multi-Conversation Navigation | Verified | None (single active conversation only) | — | — | **NOT STARTED** |
| B15 | Citations & Sources | Verified | None (no citation UI exists; backend `source_summary`/`sources` fields exist per `orca/serve/api.py` but are unused by the frontend) | — | — | **NOT STARTED** |
| B16 | Context & Attachments | Verified | None | — | — | **NOT STARTED** |

## C-series

| ID | Name | Original source | Current implementation | Status |
|---|---|---|---|---|
| C01 | Code Workspace | **Missing** — `APPROVED_REFERENCE_MISSING` | None | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** |
| C02 | Live Mission Execution | Missing (library metadata only); also under PR #79's own, separate security qualification | Backend exists (PR #79, under independent audit); no frontend screen | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** *and* **BLOCKED — BACKEND OR AUTHORITY DEPENDENCY** (mission authorization must not be altered to satisfy a frontend) |
| C03 | Projects Workspace | Missing | None | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** |
| C04 | Global Search | Missing | None | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** |
| C05 | Evidence Workspace | Missing | None | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** |
| C06 | Files & Documents | Missing | None | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** |
| C07 | Relay Workspace | Missing | None | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** |
| C08 | Models Workspace | Missing | None | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** |
| C09 | Activity Workspace | Missing | None | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** |
| C10 | Settings & Personalization | Missing | None | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** |
| C11 | Authentication & Account Access | Missing (candidate review only, not an approved original) | Partial — `conversation.html`'s own auth overlay exists and was hardened this session (dialog semantics, focus trap) but was not built from C11's own source | **BLOCKED — AUTHENTIC DESIGN SOURCE MISSING** for the dedicated C11 screen; the overlapping functional auth UI inside B01–B03 is already shipped |
| C12 | New User Onboarding | Candidate review ZIP verified (hash `424b72fb...`), founder-approved A/B directions documented | None | **BLOCKED — BACKEND OR AUTHORITY DEPENDENCY** (no real onboarding-completion state exists to wire to; also logo-placeholder production block) |
| C13 | Subscriptions & Billing | Same | None | **BLOCKED — BACKEND OR AUTHORITY DEPENDENCY** (no real billing/entitlement backend exists — fabricating one would violate the "no invented subscription prices/entitlements" rule) |
| C14 | Teams & Enterprise Administration | Same | None | **BLOCKED — BACKEND OR AUTHORITY DEPENDENCY** (no real org/member/role backend exists) |

## Rollup

- **Implemented, independent audit pending:** 3 (B01–B03)
- **Partially implemented:** 2 (B10, B12 — only as an incidental byproduct of PR #81's own remediation scope, not a dedicated B10/B12 build)
- **Not started:** 11 (B04–B09, B11, B13–B16)
- **Blocked on missing design source:** 11 (C01–C11)
- **Blocked on backend/authority dependency:** 3 (C12–C14), plus C02 doubly-blocked

No screen in this matrix is claimed complete merely because its static appearance would resemble the original.
