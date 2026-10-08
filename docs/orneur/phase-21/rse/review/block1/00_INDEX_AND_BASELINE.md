# RSE Block 1 (IMP-2, IMP-3, IMP-4) — independent audit package

`NON_NORMATIVE_AUDIT_EVIDENCE` · prepared 2026-10-09 by the independent reviewer (Claude) · **no implementation has been examined, accepted or pre-accepted.**

## A. Canonical baseline verified (not assumed)

| Check | Result |
|---|---|
| Canonical `main` | `464b602f3f259b56f139c3304828baa660e6b860` (local = origin) |
| Canonical-main CI | run `37821363822`, event `push`, branch `main`, head SHA exactly the above, success |
| Governing architecture | RSE-ARCH-1.2 + Clarification 1 + Freeze Amendment + Manifest V3 (digest `7b19e6ca…e703`, 32 entries verified) |
| IMP-1 | merged (PR #7), accepted and canonicalized; carry-forward N-1 and N-2 open |
| IMP-2 / IMP-3 / IMP-4 candidates | **none found**: no branch or PR other than the merged IMP-1 branch and the open characterization PR #6 |
| Docker Synthetic Integration Lab | **no files found** in any branch or PR |
| Authorization locks | unchanged (`NO_PROVISIONING`, `NO_HARDWARE_PURCHASE`, `NO_REAL_SECRET_CREATION`, no corpus/Qualification/model/GPU/training); `IMP_5_NOT_AUTHORIZED` |

Work was done read-only from a separate review workspace on the working branch (`session-update-2026-08-25`); `main`, Cursor's branches and the Docker branch were not touched.

## Contents

| File | Output |
|---|---|
| `01_REQUIREMENT_EVIDENCE_MATRICES.md` | B, C, D — IMP-2/3/4 requirement-to-evidence matrices with exact normative sources |
| `02_ADVERSARIAL_TEST_SPECIFICATIONS.md` | E — executable test specifications (T2-01…, T3-01…, T4-01…) and the adapter contract |
| `03_CRYPTOGRAPHIC_CONFORMANCE_FINDINGS.md` | F — RFC 9180 / Ed25519 / library assessment |
| `04_N1_N2_CLOSURE_AND_DOCKER_REVIEW.md` | G (N-1, N-2 closure criteria and regression tests), H (Docker lab review preparation) |
| `05_RISK_REGISTER.md` | I — CRITICAL/HIGH/MEDIUM/LOW/INFORMATIONAL, proven separated from hypothetical |
| `06_AUDIT_PROCEDURE_ACCEPTANCE_AND_OPEN_QUESTIONS.md` | J exact-SHA procedure, K acceptance criteria, L open architecture questions, M pending evidence |
| `audit_gate_checks.sh` | mechanical exact-SHA gate (dry-run against the accepted IMP-1 range: all PASS; it is necessary, never sufficient) |
| `vectors/` | (vector file SHA-256 `5795d0b6643694f12ea015e80a9acfac10ab9e74e64f94fdc2374fb20d7a3c43`) independent RFC 9180 reference (reproduces Appendix A.2.1), OCR1 v2 reference, 3 positive and 31 negative known-answer cases, run script |

## What was established, and what was not

Established independently this session:
- An independent HPKE reference reproduces **all** values of RFC 9180 Appendix A.2.1; OCR1 v2 vectors derived from the frozen text are deterministic and every negative is rejected at the phase the text implies.
- **The in-repo HPKE API cannot implement the frozen OCR1 v2** (single-shot: no AAD, no reusable context, no caller IKM, cannot be validated against Appendix A). This is raised as OAQ-5.
- The frozen text leaves several protocol constants for IMP-3/IMP-4 undefined (ledger tree profile and leaf formats; `OCK1`/`OCH1` signature domains; the "non-state-changing" record list; sandbox bounds; journal format). They are raised as OAQ-2…OAQ-9 so they are classified *before* implementation, not after.
- Legacy-code defects (promotion without T/W/D grant; ledger tail/rollback/fork blind spot; unauthenticated sender; parse-before-auth) remain **proven** by Cursor's characterization tests (PR #6, 9/9 executed here) and are outside this block but must not be relied upon.

Not established: anything about the quality or security of IMP-2/3/4 — they do not exist yet. Every matrix row is `PENDING_IMPLEMENTATION_EVIDENCE` unless the accepted IMP-1 already covers it.

## N. Final preparation verdict

`RSE_BLOCK_1_INDEPENDENT_AUDIT_PACKAGE_READY` — the preparation is complete and usable. This is **not** acceptance of IMP-2, IMP-3 or IMP-4. At the code-review gate a new audit of Cursor's exact delivered SHA will be performed.

`IMP_5_NOT_AUTHORIZED` · `NO_PROVISIONING_AUTHORIZED` · `NO_HARDWARE_PURCHASE_AUTHORIZED` · `NO_REAL_SECRET_CREATION` · `NO_CORPUS_GENERATION_AUTHORIZED` · `NO_QUALIFICATION_AUTHORIZED` · `NO_MODEL_SELECTION_AUTHORIZED` · `NO_GPU_AUTHORIZED` · `NO_TRAINING_AUTHORIZED`
