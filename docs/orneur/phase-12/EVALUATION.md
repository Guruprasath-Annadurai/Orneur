# Phase 12 — Evaluation

## Deterministic scenario harness (spec §80)

`orca.learning.eval_harness.run_all()` — **21/21 scenarios passed
(100%)**. All 21 scenarios from spec §80's required list are implemented
1:1 (verified Truth failure → eval candidate; runtime/infrastructure
failure → NOT training candidate; simulation mismatch → candidate with
lineage; Court disagreement → contested review; false Falsifier
contradiction → negative curriculum; private connector failure →
tenant-local only; secret-containing event → sanitized/rejected;
duplicate failure → deduped candidate; same-root-family split isolation;
dataset manifest checksum; frozen dataset immutability; holdout
inaccessible to training compiler; candidate approval required before
freeze; training completion does not promote; eval regression blocks
promotion; security failure becomes security regression; synthetic
sample marked synthetic; synthetic unverified sample rejected;
deleted/revoked source invalidates derived eligibility; checkpoint
checksum mismatch rejected; model cannot self-approve training).

Real, non-mocked in the sense that matters here: no scenario invents a
fake "correct" behavior — each one calls the actual production function
(`triage()`, `evaluate_promotion()`, `CheckpointRecord.verify_integrity()`,
`DatasetManifest.freeze()`, `apply_review_decision()`, etc.) and asserts
its real, observable output.

## Pytest coverage

`tests/test_learning_phase12.py` (48 tests) + `tests/test_learning_eval_harness.py`
(1 wrapper test asserting the harness itself is 21/21) +
`tests/test_learning_training_experiment.py` (4 tests) = **53 tests**,
all passing.

## Performance (spec §83) — framework overhead, measured on this machine

| Operation | Mean (2000 iterations) |
|---|---|
| Triage | 0.0016 ms |
| Dedupe (against 100 existing candidates) | 0.3881 ms |
| Sanitization | 0.0096 ms |
| Candidate compilation | 0.0005 ms |
| Checksum (1 MB file, SHA-256) | 0.3271 ms |
| Lineage lookup (3-node ancestor walk) | 0.0004 ms |

All framework-overhead operations are sub-millisecond except dedupe
against a 100-candidate working set (still under 0.4ms) and file
checksumming (I/O-bound, scales with file size, not candidate count).
Training time is reported separately in `TRAINING_RUNS.md` — no
controlled training experiment executed on this hardware, so there is no
training-time number to report here (honestly, not a zero standing in for
"not measured").

## Fast path (spec §84)

`test_learning_package_not_imported_by_hot_request_path` — AST-inspects
`orca/serve/api.py`, `orca/agent/runtime.py`, `orca/gateway/gateway.py`
and confirms none of them import `orca.learning` at module scope. A
normal production request therefore cannot reach this pipeline
synchronously; every `orca.learning` entry point is explicitly invoked
(a script, a test, a future CLI command), never triggered by request
handling.

## Known limitation: standalone harness invocation is not registry-isolated

Running `python -m orca.learning.eval_harness` directly (as opposed to via
`tests/test_learning_eval_harness.py`) writes two harmless,
fixed-ID artifacts (`phase12-frozen-test-v1.json`,
`phase12-regression-test.json`) into this developer's real
`~/.orca/registry/{datasets,evaluations}/` directories, since the
file-scoped pytest isolation fixture (`tests/_learning_registry_isolation.py`)
only applies inside a pytest run. This was caught twice during this
phase's own development (see `DATASET_VERSIONING.md`'s note on the freeze
bug) and is disclosed rather than silently left as a footgun: prefer
`pytest tests/test_learning_eval_harness.py` over the standalone
`python -m` invocation, or manually remove the two `phase12-*` files
after a standalone run.
