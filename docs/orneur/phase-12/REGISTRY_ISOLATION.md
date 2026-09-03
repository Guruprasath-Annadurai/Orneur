# Phase 12.1 — Registry Isolation

## The problem

`orca.learning.eval_harness` (via `DatasetManifest.save()`/
`EvaluationReport.save()`) and `orca.learning.training_experiment`
(via `TrainingRunManifest.save()`) both write real files through
`orca/registry/`'s module-level directory constants
(`DATASET_MANIFEST_DIR`, `TRAINING_RUN_DIR`, `CHECKPOINT_DIR`,
`EVALUATION_REGISTRY_DIR`), which default to subdirectories of the real
`ORCA_HOME` (`~/.orca/registry/...`). A bare `python -m
orca.learning.eval_harness` — no pytest, no fixture, no special
environment variable — would therefore write two fixed-ID artifacts into
the developer's actual registry. This was caught, disclosed, and
initially accepted as a "known limitation" in Phase 12's own
`EVALUATION.md`; Phase 12.1 rejects that as insufficient and fixes it.

## Why this must not depend on pytest fixtures

`tests/_learning_registry_isolation.py`'s `isolate_registry_dirs()` (used
by `tests/test_learning_phase12.py`, `test_learning_eval_harness.py`,
`test_learning_training_experiment.py`) only runs inside a pytest
session — it is invisible to a developer running the module directly, to
a future CLI wrapper, or to any other Python process that imports
`orca.learning` and calls its functions programmatically. Safety that
only exists inside pytest is not safety; it is a coincidence of how the
code happens to usually be invoked.

## The fix: `orca/learning/registry_isolation.py`

A single, dependency-free context manager,
`isolated_registry(destination: Path | None = None)`:

- **`destination=None` (the default)** — creates a fresh
  `tempfile.TemporaryDirectory`, points all four registry directory
  module-attributes at subdirectories of it, yields, then restores the
  original module attributes AND deletes the temp directory — in a
  `finally` block, so this happens even if the code inside the `with`
  block raises (spec §11). **This is the safe default for both
  `orca.learning.eval_harness.run_all()` and
  `orca.learning.training_experiment.prepare_training_experiment()`.**
- **`destination=<a Path>` (explicit opt-in)** — validates the path via
  `validate_persist_destination()` (resolves symlinks, rejects anything
  falling inside a hard denylist reusing `orca.godmode.file_elevation`'s
  exact discipline: `/etc`, `/root`, `~/.ssh`, `~/.aws`, `~/.gnupg`,
  `~/.orca/auth.db`, `~/.orca/godmode`), creates it if needed, points the
  four registry directories at subdirectories of it, and — critically —
  **never deletes it afterward.** Both call sites print the exact
  resolved destination before writing (spec §8).

## Call sites

- **`orca.learning.eval_harness.run_all(persist: Path | None = None)`** —
  the CLI (`python -m orca.learning.eval_harness [--persist DIR]`) and
  the plain function call share this one parameter; there is no separate
  "CLI-only" safety path (spec §13: "safety should not exist only in CLI
  argument parsing").
- **`orca.learning.training_experiment.prepare_training_experiment(...,
  registry_home: Path | None = None)`** — same pattern. Distinguished
  explicitly from a real production training workflow (see
  `TRAINING_RUNS.md`): this function is governance PREPARATION (spec
  §15), and defaults to ephemeral exactly like the eval harness. A real
  production training launch that genuinely needs its
  `TrainingRunManifest` to persist in the developer's real registry would
  pass `registry_home=Path.home() / ".orca" / "registry"` explicitly —
  no code in this repository does that today.

## Fixed-ID artifacts are now safe by construction (spec §9)

`scenario_frozen_dataset_immutability` and
`scenario_eval_regression_blocks_promotion` still use fixed IDs
(`phase12-frozen-test`, `phase12-regression-test`) — this is now safe
regardless of the ID value, because those IDs can only ever collide with
themselves inside a freshly created, isolated directory (ephemeral or
explicitly supplied), never with anything in the real
`~/.orca/registry/`. The fixed IDs remain deterministic, which is exactly
what a reproducible test scenario wants (spec §9: "for deterministic
tests: deterministic IDs may exist inside isolated temporary storage").

## Collision protection at an explicit destination

If a caller reuses the same explicit `destination` across multiple runs
and a PREVIOUSLY FROZEN dataset manifest already exists there,
`DatasetManifest.save()`'s own freeze-immutability check (see
`DATASET_VERSIONING.md`) still applies and raises `DatasetFrozenError` --
tested directly in
`test_fixed_id_collision_does_not_silently_overwrite_frozen_artifact_at_explicit_destination`.

## Security (spec §21)

- **Path traversal / symlink escape**: `validate_persist_destination`
  resolves the path (symlinks followed) before checking the denylist —
  a traversal string or a symlink pointing at a denied location is
  caught after resolution, not before. Tested directly.
- **Registry destination cannot be controlled by model/candidate/failure
  content**: structural guarantee, not a runtime filter. The ONE call
  site of `isolated_registry()` in production code
  (`training_experiment.py`) passes only `None` or its own explicit
  `registry_home` parameter — verified by AST inspection in
  `test_candidate_or_failure_content_never_used_as_registry_destination`.
  No function anywhere in `orca/learning/` reads a `FailureEvent` or
  `CurriculumCandidate` field to build a `Path`.
- **Prompt content requesting persistence**: a candidate's own text
  asking to "persist this to production" is inert — `sanitize.py`/
  `security.py`'s existing poisoning-pattern scanning treats it as
  suspicious data for human review, and (per the structural guarantee
  above) there is no code path that would honor it even if scanning
  missed it.

## What is verified

- Default `run_all()` and `prepare_training_experiment()` leave the real
  `~/.orca/registry/{datasets,training_runs,checkpoints,evaluations}/`
  byte-for-byte unchanged (snapshot-diff tests, no fixture involved).
- A crash mid-harness leaves the real registry unchanged (an injected
  `RuntimeError` mid-scenario-list, real registry snapshotted before and
  after).
- `isolated_registry()`'s module-attribute patch is always restored, even
  when the wrapped code raises.
- Explicit `--persist`/`registry_home` writes ONLY to the supplied
  destination, reports it before writing, and is unaffected if the real
  registry directories don't exist yet.
- Programmatic invocation (`run_all()`/`prepare_training_experiment()`
  called directly, no CLI parsing involved) is exactly as safe as the CLI.
