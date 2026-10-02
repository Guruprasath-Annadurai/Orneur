# Genesis V2 — LOCAL vs EXACT-SHA CI test-count provenance

Audit-closure note for commit `57262eba4181a427498e6247f55b429f12929df7` (CI run `36886633374`, job "Deterministic Unit Tests").

| Source | passed | skipped | deselected | collected (passed+skipped) |
|---|---|---|---|---|
| **LOCAL** (macOS, `.venv`, torch 2.13.0 + transformers 5.14.1 installed) | 6026 | 318 | 43 | 6344 |
| **EXACT-SHA CI** (ubuntu, `pip install -e ".[dev,mcp,nvidia,postgres]"`, no torch/transformers) | 6015 | 306 | 43 | 6321 |

Not a regression. Cause (verified by diffing per-test node ids from `pytest --collect-only` locally against the node ids in the CI job log; 0 ids appear only in CI):

- `tests/test_train_losses.py` (9 tests) and `tests/test_transformers_adapter.py` (16 tests) begin with a module-level `pytest.importorskip("torch"/"transformers")`. Locally torch and transformers are installed, so all 25 tests are collected and run. In the deterministic CI job neither is installed (by design — `.github/workflows/test.yml` runs torch tests in the separate "Training Math Unit Tests (Torch)" job), so each module is a single module-level skip: 2 skips, 0 individual tests.
- Net collection difference: 25 − 2 = **23** (6344 − 6321), exactly matching the observed gap.
- The 43 deselected (`-m "not live_ollama_smoke"`) are identical in both environments.
- The ~11 extra local passes / ~12 extra local skips are the 25 locally-collected torch/transformers tests (some pass, some skip on local conditions) net of the 2 CI module-level skips; the split is environment-dependent and does not alter the 23 collection delta.
- Parsing note: 3 of the 6321 CI results do not appear as one-line node ids in the job log (1 test whose output interleaves with its status line, plus the 2 module-level skips); they are still counted in the CI summary line.

Always label counts LOCAL or EXACT-SHA CI; they are not interchangeable. The authoritative gate is exact-SHA CI.
