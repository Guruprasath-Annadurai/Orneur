# Phase 1 Exact-Head CI — Evidence Honesty Closure

**Corrective PR:** [#140](https://github.com/Guruprasath-Annadurai/Orneur/pull/140)  
**Base:** `cursor/foundation-02-pretraining-hardening-1cdf` (FOUNDATION-02 PR #138)  
**Honesty probe tip:** `cd1e557a685b529c57bf4bf2f594b088cbeb5172`  
**Exact-head green tip:** `b3fbda01ea1f4cb23a5fa6da5cd6398a4f3d862a`  
**Test Suite CI:** [40866502460](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40866502460)  
**Training authorization:** **NO-GO**  
**Formal acceptance:** **0 / 95**

## Checks

All **9** PR/push Test Suite jobs on `b3fbda01ea1f4cb23a5fa6da5cd6398a4f3d862a` concluded **success** (0 failures).

| Job | Result |
|---|---|
| Deterministic Unit Tests | pass |
| Training Math Unit Tests (Torch) | pass |
| Genesis V2 Security | pass |
| Genesis V2 Sandbox | pass |
| Production Container Build + Boot Smoke | pass |
| RSE Docker Synthetic Integration Lab | pass |
| RSE dependency lock and vulnerability scan | pass |
| Dependency Vulnerability Scan (informational) | pass |
| SSE Diagnostics | pass |

## Deterministic Unit Tests (exact head)

`9007 passed, 389 skipped, 43 deselected, 7 xfailed` in 771.03s  

Includes:

- All `tests/test_foundation02_probe_honesty.py` adversarial cases **PASSED**
- All `tests/test_foundation02_requirement_matrix.py` honesty-v3 cases **PASSED**
- Documented audit-tail **strict xfail** retained among the 7 xfailed (≠ PASS)

## Training Math (Torch)

`550 passed, 3 deselected` in 260.97s

## Rules

- Skip ≠ PASS; xfail ≠ PASS
- Branch CI ≠ formal acceptance; branch CI ≠ Antigravity G13
- Synthetic ≠ live training
- Training remains **NO-GO**
