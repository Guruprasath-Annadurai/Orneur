# Phase 12.1 — Learning Pipeline Final Qualification — Closure

**Repository**: orca | **Branch**: session-update-2026-08-25

## What Phase 12.1 closed

Two qualification gaps left open by Phase 12's own closure report:

1. **Baseline lineage gap** — the interval `5b58b91..cc732b0` (two
   commits) was not accounted for in Phase 12's closure. Fully audited in
   [`BASELINE_LINEAGE_AUDIT.md`](BASELINE_LINEAGE_AUDIT.md): both commits
   are branding-only (README/CLI display strings, a new `orneur` console-
   script alias), made in this same session for an unrelated, explicit
   user request, with zero production security/runtime/model/training
   behavior changed. Neither is UNEXPECTED. Phase 12's reported starting
   SHA (`cc732b0`) was correct as a repository-HEAD snapshot; it simply
   didn't explain the gap, which this audit now does. A real, pre-existing
   test-coverage gap was found and closed alongside this audit:
   `orca/cli.py` had zero tests before Phase 12.1 — `tests/test_cli_branding.py`
   (3 tests) now covers the Typer app name and `--version` output.

2. **Standalone registry-write safety** — `orca.learning.eval_harness` and
   `orca.learning.training_experiment` both wrote real files under the
   real `~/.orca/registry/` when invoked outside pytest. Fixed properly,
   not merely re-disclosed: `orca/learning/registry_isolation.py`'s
   `isolated_registry()` context manager makes ephemeral, self-cleaning
   temporary storage the DEFAULT for both the CLI and the plain Python
   API, with explicit, validated, reported-before-writing persistence as
   an opt-in. Full design in
   [`REGISTRY_ISOLATION.md`](REGISTRY_ISOLATION.md).

## Test results (fresh, this closure)

| Suite | Result |
|---|---|
| Full application suite (deterministic) | 1391 passed, 0 failed, 40 deselected |
| Authoritative security suite (79 files) | 733 passed, 0 failed, 1 deselected |
| Live suite (`-m live_ollama_smoke`) | See final Phase 12.1 report for this run's result |
| Phase 12 eval harness | 21/21 (100%), unchanged |
| Phase 11 eval harness | 23/23 (100%), independently re-confirmed |
| Phase 11.1 eval harness | 21/21 (100%), independently re-confirmed |
| New registry-isolation tests | 13/13 (`tests/test_learning_registry_isolation.py`) |
| New CLI branding tests | 3/3 (`tests/test_cli_branding.py`) |

## Real registry diff test (spec §17)

Snapshot of `~/.orca/registry/{datasets,training_runs,checkpoints,evaluations}/`
taken immediately before and after a default (`run_all()`,
`prepare_training_experiment()` with no explicit destination) invocation
of both entry points, with NO pytest fixture patching those directories —
**zero diff**, confirmed directly in
`test_default_run_all_does_not_touch_real_orca_registry` and
`test_default_prepare_training_experiment_does_not_touch_real_orca_registry`.

## Accidental artifact cleanup (spec §16)

Two artifacts were confirmed to have leaked into the real registry during
Phase 12's own development, before this fix existed:

| Path | Reason created | Cleanup result |
|---|---|---|
| `~/.orca/registry/datasets/phase12-frozen-test-v1.json` | Manual `python -c` testing and standalone `python -m orca.learning.eval_harness` runs during Phase 12 development | Removed |
| `~/.orca/registry/evaluations/phase12-regression-test.json` | Same as above | Removed |

No legitimate pre-existing registry record (e.g. `orca-nano-v7.json`,
`orca-core-combined.json`, `orca-novus-combined-safety-calibration-v2.json`)
was touched or removed — confirmed by directory listing before and after
cleanup.

## Model lifecycle (unchanged, reconfirmed)

- **Genesis**: legacy `orca-nano-v7` unchanged; canonical future 3B
  checkpoint remains absent. No registry-safety code in this phase
  creates or touches any Genesis checkpoint record.
- **Novus**: `EXPERIMENTAL` / `NOT_PROMOTABLE`, unchanged.
- **Aeternum**: absent, unchanged. No fake checkpoint created.

## Known limitations (disclosed, not blocking)

1. `orca.learning.pipeline` has no CLI/dataset-compiler/regression-suite/
   candidate-review-tooling entry points yet — nothing new to isolate
   there, but also nothing built yet (unchanged from Phase 12).
2. `REGISTRY_COLLISION_OVERWRITE` and `REGISTRY_PATH_CONTROL_BY_MODEL_DATA`
   are verified as structural guarantees (AST inspection, exception-raising
   guards) rather than runtime-incremented counters — consistent with how
   several Phase 12 counters already work, disclosed for consistency.
3. `orca/gateway/frontier_runtime.py`'s analogous `RequestCancelledError`
   site (disclosed in Phase 11.2) remains unverified — unrelated to this
   phase's scope, carried forward as a known gap.

## Remaining Phase-12 blockers

None.

**READY TO ADVANCE TO PHASE 13: YES**
