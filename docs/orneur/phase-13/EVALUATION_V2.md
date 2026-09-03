# Phase 13.1 — Red-Team Evaluation V2

Independent per-campaign metrics (spec §48). "Attacks attempted" counts
distinct test functions in this phase's 8 new files; "blocked safely"
counts those whose assertions passed on the FIRST correct run (after
fixing test-authoring bugs, not security bugs — see `FINDINGS.md`'s false
positive note); "real findings" and "inconclusive" as defined below.

| Campaign | Attempted | Blocked safely | Real findings | False positives | Inconclusive |
|---|---|---|---|---|---|
| RAG/evidence | 10 | 9 | 1 (fixed) | 1 (RAG-06, reclassified) | 0 |
| Memory | 7 | 7 | 0 | 0 | 0 |
| Fuzzing (property-based, 4 families) | 11 | 11 | 0 | 0 | 0 |
| Resource exhaustion / structured-input | 12 | 11 | 1 (fixed) | 0 | 0 |
| TOCTOU / concurrency | 4 | 3 | 1 (documented, not fixed) | 0 | 0 |
| Cross-layer (4 new chains) | 4 | 4 | 0 | 0 | 0 |
| Live model behavior | 3 | 3* | 0 | 0 | 0 |
| Audit/log injection + error leak | 4 | 4 | 0 | 0 | 0 |
| **Total (this phase)** | **55** | **52** | **2 fixed + 1 documented** | **1** | **0** |

\* Live model results depend on the actual full live-suite run's outcome
recorded in `PHASE_13_FINAL_CLOSURE.md` — the deterministic tool-set
boundary these tests check is the real oracle, not model compliance
itself (spec §47).

## Combined with Phase 13's original campaign

| Suite | Result |
|---|---|
| Phase 13 (original) new attacks | 6 |
| Phase 13.1 (this closure) new attacks | 55 |
| **Total new red-team attacks across Phase 13 + 13.1** | **61** |
| Existing security tests reused (unmodified, reconfirmed) | 733 → 790 (post this phase's own 9 new files added to inventory) |

## Full regression (spec §50)

| Suite | Result |
|---|---|
| Full deterministic application suite | 1448 passed, 0 failed, 1 xfailed (documented Finding 3), 43 deselected |
| Authoritative security suite (89 files) | 790 passed, 0 failed, 1 xfailed, 4 deselected |
| Live suite (`-m live_ollama_smoke`) | **43 passed, 0 failed** (726.77s) |
