# Pretraining Closure — Technical Baseline (Phase 0)

**Programme:** ORNEUR Pretraining Completion  
**Owner:** Cursor (engineering evidence)  
**Training authorization:** **NO-GO**  
**Formal acceptance:** **0 / 95** (authoritative register/ledger unchanged)

## Starting repository state

| Ref | SHA / value |
|---|---|
| `origin/main` | `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a` |
| FOUNDATION-02 PR | [#138](https://github.com/Guruprasath-Annadurai/Orneur/pull/138) (OPEN, mergeable) |
| Independently tested code SHA | `4d9fcda896e9ac12581f67fd65aaf3bc23aad7e4` |
| Documentation tip (CI record) | `b2a307158e8b171b04ec75b7786e7acfdc8dce87` |
| Exact-head CI on code SHA | run `40860060023` |
| Corrective branch | `cursor/foundation-02-phase1-evidence-closure-8108` |

Machine-readable twin: `PHASE_0_TECHNICAL_BASELINE.json`.

## Recovery decision

Recover FOUNDATION-02 from PR #138. Do not restart the foundation. Do not rewrite stable architecture. Preserve `4d9fcda…` as the prior qualified code lineage SHA while applying Phase 1 evidence-tool corrections on a new tip.

## Engineering matrix at recon (not formal acceptance)

| Disposition | Count |
|---|---:|
| `VERIFIED_ENGINEERING` | 9 |
| `IMPLEMENTED_UNVERIFIED` | 19 |
| `BLOCKED` | 16 |
| `NOT_IMPLEMENTED` | 51 |

Verified IDs at recon: G4, G5, C01, C02, DATA-1, DATA-2, TRAIN-1, TRAIN-2, AUTH-1.

## Phase 1 defects found in evidence tooling

1. Hard-coded `/workspace/.venv` interpreter and `/home/ubuntu/...` PYTHONPATH.
2. Exit-0 / xfail-only suites treated as verification OK.
3. No requirement for `passed >= 1`; skipped/xfailed not distinguished from passes.
4. Committed probe argv non-portable; probe `candidate_sha` lagged tip.
5. Audit-tail truncation residual remains a documented P2; strict xfail ≠ PASS.

## Work routes

- **Evidence honesty:** `orca/pretrain_foundation/probe_honesty.py` + `scripts/foundation02/build_requirement_matrix.py`.
- **Adversarial proof:** `tests/test_foundation02_probe_honesty.py`.
- **Founder / hardware / G1 / R65 / corpus / GPU:** remain BLOCKED; see `ENGINEERING_BLOCKER_REGISTER.json`.
- **Later phases (2–9):** prepared only after Phase 1 honesty exit; Phase 10 prohibited until Phase 9 founder authorization.

## Explicit non-claims

- No training executed or authorized.
- No formal acceptance writes.
- No second acceptance register.
- No Cursor self-certification as independent Antigravity qualification.
