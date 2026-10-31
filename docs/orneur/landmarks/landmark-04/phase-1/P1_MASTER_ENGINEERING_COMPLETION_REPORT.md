# LANDMARK-04 Phase 1 — Master Engineering Completion Report

**Verdict: `LANDMARK-04 PHASE 1 — PARTIALLY VERIFIED, EXTERNAL BLOCKERS REMAIN`** (Outcome B)

Why B and not A: working code and verified journeys exist and no known P0/P1 application defect is unresolved, but two mandatory real-world items cannot be evidenced here — **real email delivery** (`BLOCKED_EXTERNAL`) and **MFA recovery** (`NOT_IMPLEMENTED`, needs a decision) — and accessibility is verified only at the automated level. Independent qualification has not happened. No public-launch authorisation is claimed.

## Identifiers
| | |
|---|---|
| Starting `main` | `0a4c5180555a3102a4e0d61f56e0f8539975f4ee` (tree `106487db24a66672c7ca3e660a1d1e0792281238`); verified, had not advanced |
| Branch | `claude/landmark-04-phase1-real-app` |
| Final code SHA / tree | `02572dd6ef72bfc07dd4847b7cff3977766ee96e` / `40bdf43ce56c07e99cd8f8a7d0115d796814f4ee` |
| Draft PR | https://github.com/Guruprasath-Annadurai/Orneur/pull/151 (draft, not merged) |

## Independently observed facts (re-runnable) vs engineering judgement
**Facts:** the red/green results, the CI conclusions, the measurements and the screenshots in this package. **Judgements:** the severity labels, the "no defect found" readings for areas probed only with the listed attacks, and the Outcome B call.

## Components implemented
1. Approved-page account lifecycle: contextual forgot-password, reset-link handling, MFA challenge, unverified-address resend.
2. Account settings dialog: change password, two-step verification on/off, delete account (confirmation + fresh authentication), replacing a dead control.
3. Server: fresh-authentication rules for sign-in MFA, 2FA disable, change-password and account deletion (single-use codes, per-account lockout); fresh session returned after a password change.
4. UI security: CSP, `frame-ancestors`/`X-Frame-Options`, `no-store` on auth responses.
5. Official logo restored on `/conversation` (installed founder files, nothing redrawn); tight markdown lists.
6. Bounded post-turn background extraction.
7. Test infrastructure: 5 real-browser journey files + 1 live quota file, 5 deterministic test files, evidence scripts; CI workflow runs the new journeys.

## Existing components preserved (not rebuilt)
Kernel/SSE streaming, Stop/cancellation, session recovery, deletion ledger, tenant isolation, quota reservation, model capability truth, vector subsystem, backup/restore, API-key step-up, stream redactor and Kernel memory ingestion. Their suites were re-run green.

## Defects
Found and repaired: 13 (P1: 6, P2: 5, P3: 2) — table in `P1_GAP_AND_DEFECT_REGISTER.md`. No P0 found.
Probed with no defect: XSS rendering, cross-tenant access, quota overspend, failed-turn charging, cancellation leaks.

## Red-before-green proof
Deterministic: 12 of 13 new security/headers tests fail on pristine `main`, 13/13 pass on the branch (`evidence/red_on_baseline_0a4c518.txt`, `green_on_branch.txt`); asset-reference tests (2) and extraction-bound (1) were red before their fixes; browser steps A8 and B1 failed on `main` (B1 names the broken file). The XSS test is red under mutation (15 injected elements) and green on the product.

## Test totals
| Class | Result |
|---|---|
| Deterministic CI (exact head) | 9749 passed · 425 skipped (identical to `main`) · 6 xfailed · 0 failed |
| New deterministic tests | 19 (3 MFA login, 5 sensitive ops, 5 headers, 5 asset references, 1 extraction bound) |
| Live API (new) | 4 quota/routing/cancellation (Q1–Q4) |
| Real provider | 12 sequential + 4 concurrent real-model answers, identity probe, plus 22 existing real-Ollama API tests re-run on `main` |
| Browser (new, real Chromium) | 5 files / 42 named steps (X1–X6+X8, A1–A9, U1–U7, M1–M6 + N1/N2/T1/B1/H1/H2/Z, C1–C6) — all green |
| Browser/live regression (existing, after changes) | 39 + 15 + 25 + 3 passed, plus L03/MASTER-04 groups in CI |
| Frontend unit (node) | 7 files, 0 failures |

## Performance
See `P1_PERFORMANCE_AND_RELIABILITY.md` (one workstation, 1B model; TTFT p50 0.43 s / p95 1.72 s, 12/12 progressive, 4/4 concurrent, hang-up 0.5 s, page load 32 ms p50, +9 ms from +22 KB). No capacity claim.

## Accessibility
Automated checks only: accessible names on all visible controls, visible focus indicator, ≥24 px targets, reduced motion, no horizontal scroll at 390/820/1280, dialog focus management. **No screen-reader, contrast or zoom verification.**

## Exact-head CI
Code head `02572dd`: success on all 10 jobs (push run 41217652876). History and the one preserved failure/flake: `P1_EXACT_SHA_CI_REPORT.md`.

## Remaining issues
P0: 0. P1: 0 known. P2: P1-X-01 (email, BLOCKED_EXTERNAL), -02 (MFA recovery), -03 (CSP `unsafe-inline`), -04 (unmetered background call), -08 (accessibility depth). P3: -05, -06, -07, -09.

## External dependencies
Authorised mail service; (optionally) external provider with budget policy; staging environment; accessibility reviewers; founder decisions on MFA recovery and metering.

## Readiness status
Engineering complete for the verified scope: yes, with the exceptions above. Staging candidate ready: **not asserted**. Independently qualified: **no**. Public release ready: **no**.

## Final engineering recommendation
**GO** for independent qualification of this candidate on its SHA; **NO-GO** for any public release, and no staging claim, until the external blockers and the P2 items are closed.

## Governance
`FORMAL_PRETRAINING_ACCEPTANCE = 0/95`, `TRAINING_AUTHORIZATION = NOT_AUTHORIZED`, `GENESIS = INTERFACE_ONLY`, `NOVUS = NOT_AVAILABLE`, `AETERNUM = NOT_AVAILABLE` — untouched. No merge, deployment, tag, spend, training or credential action.

## Antigravity instructions
`P1_ANTIGRAVITY_INDEPENDENT_HANDOFF.md`.
