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

## Resolved (Phase 12.1): standalone harness invocation is now registry-isolated by default

Phase 12's closure report initially disclosed this as an accepted
limitation. Phase 12.1 rejected that and fixed it properly:
`orca.learning.eval_harness.run_all()` and
`orca.learning.training_experiment.prepare_training_experiment()` now
BOTH run inside `orca.learning.registry_isolation.isolated_registry()`,
which defaults to an ephemeral `TemporaryDirectory` (deleted on exit,
including on exception) and only ever touches a real location when the
caller passes an explicit `persist`/`registry_home` destination — which
is then validated (path-traversal/symlink-escape checked against a hard
denylist reusing `orca.godmode.file_elevation`'s discipline) and reported
before writing. See `REGISTRY_ISOLATION.md` for the full design and
`tests/test_learning_registry_isolation.py` for the snapshot-diff proof
that the real `~/.orca/registry/` is untouched by default, with no pytest
fixture involved in that proof.
