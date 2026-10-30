# LANDMARK-02 — master engineering report

**Engineering state: `VERIFIED_ENGINEERING — READY_FOR_INDEPENDENT_RETEST`** (not independently qualified; nothing merged, deployed or provisioned; PR #139 stays draft).

Lineage: PR #134 → #135 → #136 `9cb864c9…` (unmodified, under Antigravity qualification) → this branch. Final code-bearing SHA `70b2960a410301b02afb2a098554d4a71467a04b`, CI run 40998377463 green (10/10, first attempt; earlier failures and causes in `L02_EXACT_HEAD_CI.md`). See `L02_EXACT_HEAD_CI.md`.

| Wave | Result | Report |
|---|---|---|
| L02-01 data lifecycle & deletion (incl. 01e temporary chat, 01f live failure qualification) | VERIFIED_ENGINEERING | `L02_DATA_LIFECYCLE_AND_DELETION.md` |
| L02-02 documents/RAG (02e judge trust boundary, 02f tool authority, 02g recovery, upload parsing security) | VERIFIED_ENGINEERING | `L02_DOCUMENT_RAG_CORRECTNESS.md` |
| L02-03 network recovery / outcome truth | VERIFIED_ENGINEERING | `L02_RECOVERY_AND_ERROR_CONTRACT.md` |
| L02-04 account security | VERIFIED_ENGINEERING (no real mail delivery) | `L02_ACCOUNT_SECURITY_REPORT.md` |
| L02-05 resource reconciliation | VERIFIED_ENGINEERING (synthetic) | `L02_RESOURCE_RECONCILIATION.md` |
| L02-06 operational readiness | VERIFIED_ENGINEERING (one workstation, no capacity claim) | `L02_OPERATIONAL_READINESS.md` |
| L02-07 customer journeys (real Chromium) | VERIFIED_ENGINEERING — 3 personas × fixture/real, all steps passed | `L02_CUSTOMER_JOURNEY_EVIDENCE.md` |
| L02-08 model identity & capability truth | VERIFIED_ENGINEERING | `L02_MODEL_IDENTITY_AND_CAPABILITY_TRUTH.md` |

## Tests (this branch)
New deterministic L02 files: 246 passed, 0 skipped (13 files). Live/browser (workstation, final code): deletion 6, recovery 8, operations 8, account 2, upload parsers (real libs) 7, document real-Ollama 3, customer journeys 6 runs; LANDMARK-01 regressions: streaming 17, real Ollama 2, cancel race 1, browser 26, concurrency 11; frontend Node 102. CI (final code head): 9332 passed, 0 failed, 399 skipped, 6 xfailed. Failed runs along the way and their causes: `L02_EXACT_HEAD_CI.md`.

## Material findings fixed in this pass (beyond the reports)
Postgres init broken by a `;` in a SQL comment (caught by CI); CDP pipe read used `select()` and failed for descriptors ≥ 1024 (caught by CI, fixed with `poll()`); two workers cold-starting on one empty data directory could crash one with `database is locked` at the WAL switch (caught by CI once the harness printed the server log; fixed with a retry); the new data-backup CLI group shadowed the documented `orca backup` command (found while writing the runbook, now pinned by a test); 4/24 concurrent streams failed as `backend_error`; Kernel stream path had no admission cap; readiness hung 5 s with Redis frozen; fd leak; stale idempotency row blocked retry after a killed worker.

## Honest limits
Prompt injection into the answering model is mitigated structurally only. Real-Ollama and real-parser evidence is workstation-only. All performance numbers are single-workstation measurements, not capacity claims. No real mail was sent. The model is third-party `llama3.2:1b`; no native weights exist; GENESIS is INTERFACE_ONLY, NOVUS/AETERNUM NOT_AVAILABLE. See `L02_BLOCKER_REGISTER.md` (P0 0, P1 1 = independent qualification) and `L02_ANTIGRAVITY_HANDOFF.md`.

## Pretraining programme
No pretraining artefact, branch, corpus or authorisation was touched. Broad feature work stops here; the branch is ready for independent retest, after which a separately CTO-approved pretraining assignment can proceed.

## CI event history
Two Journeys-job failures were caused by the multi-worker cold-start lock (the first one diagnosed only after the harness began printing the server log; the first attempt's cause is therefore an inference). Details: `L02_EXACT_HEAD_CI.md`.
