# FOUNDATION Software Closure (Phase 1)

**Disposition:** `ENGINEERING_COMPLETE — AWAITING_INDEPENDENT_REVIEW` (evidence-tool honesty only)  
**Corrective PR:** [#140](https://github.com/Guruprasath-Annadurai/Orneur/pull/140) (bases on FOUNDATION-02 PR #138 branch)  
**Honesty probe tip:** `cd1e557a685b529c57bf4bf2f594b088cbeb5172`  
**Exact-head CI tip:** `b3fbda01ea1f4cb23a5fa6da5cd6398a4f3d862a` — Test Suite [`40866502460`](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40866502460) (9/9 success)  
**Training authorization:** **NO-GO**  
**Formal acceptance change:** none (ledger remains empty)

## Scope

Targeted FOUNDATION-02 evidence-tool corrections on top of PR #138. Not a foundation rewrite.

## Corrections delivered

| # | Requirement | Change |
|---|---|---|
| 1 | Remove machine-specific interpreter / import paths | `resolve_python()` + `build_probe_env()`; portable `pytest_command` argv |
| 2 | Reproducible environment / lock | Matrix/probes record `uv.lock` + `pyproject.toml` sha256 digests |
| 3 | Actual passing tests required for VERIFIED_ENGINEERING | `classify_probe` requires `passed >= 1` |
| 4 | Reject zero-collected / skip-only / xfail-only | Explicit refusal codes |
| 5 | Distinguish passed vs expected failures | Parsed `xfailed` recorded; never counted as PASS |
| 6 | Immutable probe provenance | Probes JSON schema v3 with counts, digests, verdict_reason |
| 7 | Verify artifact digests / source SHAs | `implementation_sha256`; refuse `CANDIDATE_SHA_MISMATCH` |
| 8 | Preserve training authorization refusal | Matrix `training_authorization: NO-GO`; auth record NOT_AUTHORIZED |
| 9 | Audit-tail truncation residual | Remains documented P2; strict xfail preserved; xfail ≠ PASS |
| 10 | Exact-head mandatory CI | Required on corrective tip after push (Antigravity retest) |

## Implementation references

- `orca/pretrain_foundation/probe_honesty.py`
- `scripts/foundation02/build_requirement_matrix.py` (schema → matrix/3, probes/3)
- `tests/test_foundation02_probe_honesty.py` (adversarial)
- `tests/test_foundation02_requirement_matrix.py`

## Adversarial results (must not manufacture PASS)

| Attack | Result |
|---|---|
| xfail-only suite | `XFAIL_ONLY` → not VERIFIED |
| skip-only suite | `SKIP_ONLY` → not VERIFIED |
| zero collected | `ZERO_COLLECTED` / `NO_PASSES` → not VERIFIED |
| exit 0 with failures in summary | `FAILURES_PRESENT` → not VERIFIED |
| missing implementation / tests | refused |
| altered candidate SHA | `CANDIDATE_SHA_MISMATCH` → not VERIFIED |
| unparseable summary | `UNPARSEABLE_SUMMARY` → not VERIFIED |
| dirty `/home/ubuntu` PYTHONPATH | stripped from probe env |

Suite with real passes plus documented residual xfail (G4-style) may still verify engineering-wise; the xfail itself is not a PASS.

## Prior qualified lineage

`prior_qualified_code_sha` = `4d9fcda896e9ac12581f67fd65aaf3bc23aad7e4` (PR #138 exact-head green). Corrective tip supersedes for retest only.

## Next authorized step

Antigravity independent confirmation of reproducible honest verification on the corrective tip. Do not treat this document as formal acceptance.
