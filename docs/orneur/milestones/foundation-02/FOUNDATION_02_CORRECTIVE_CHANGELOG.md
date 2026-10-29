# FOUNDATION-02 Corrective Changelog

| Change | Kind | Evidence |
|---|---|---|
| Recover foundation-p0 + gap/readiness | recovery | prior commits on branch |
| Initial evidence package | F02-01..13 | `b384348` |
| Harden serving contract capability states | F02-10 corrective | `serving_contract.py` + adversarial tests |
| Matrix v2 probe-backed VERIFIED_ENGINEERING | F02-01 corrective | `build_requirement_matrix.py` + probes JSON |
| Downgrade FINAL-1 to IMPLEMENTED_UNVERIFIED | honesty | matrix |
| Classify audit-tail truncation residual | F02-02 residual | `FOUNDATION_02_AUDIT_TAIL_RESIDUAL.md` |
| Probe honesty: portable python/PYTHONPATH; reject zero-collected/skip-only/xfail-only; distinguish xfailed; SHA/digest provenance | F02 evidence-tool | `orca/pretrain_foundation/probe_honesty.py`, matrix/probes schema v3, `tests/test_foundation02_probe_honesty.py` |
| Phase 0 technical baseline + engineering programme slots | pretraining-closure | `docs/orneur/programmes/pretraining-closure/engineering/` |

No protected ledger, trust root, or founder signature was modified.
No changes to Claude PR #136.
Training authorization remains **NO-GO**.
