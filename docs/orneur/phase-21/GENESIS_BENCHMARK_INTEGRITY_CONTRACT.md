# Genesis Benchmark Integrity Contract

The fail-closed rules Genesis's evaluation pipeline enforces, closing
the gaps an independent audit found in Phase 21B.4.8's initial
generation/scoring split. This document describes the CONTRACT; the
enforcing code lives in `orca/eval/generation_artifact.py`,
`orca/eval/runner.py`, and `orca/eval/baseline.py`.

## 1. Cross-machine generation artifact

`GenerationRecord.raw_response_ref` (Phase 21B.4.8) was an ephemeral
path with no claim to being readable from anywhere but the machine
that created it. `GenerationArtifactManifest`
(`orca/eval/generation_artifact.py`) is the durable replacement:

- Every raw response is persisted via `persist_raw_response()` into
  ORCA_HOME's canonical, content-addressed evaluation-artifact tree
  (`GENERATION_ARTIFACT_DIR`), keyed by SHA-256 of the exact UTF-8
  response text.
- `GenerationArtifactManifest` binds run_id, candidate identity (exact
  revision, tokenizer revision, upstream model, artifact repo), suite
  identity (suite_id/version, content digest, scoring-contract digest),
  generation configuration digest, system-instruction digest, the
  FULL expected task_id list (from the verified suite, not from
  whatever records happen to exist), every record (with its SHA-256
  and byte length), software commit SHA, backend, hardware metadata,
  and a creation timestamp.
- `to_json()`/`from_json()` provide deterministic, schema-versioned
  (`genesis-generation-v1`) serialization with a `bundle_digest()`
  integrity hash over the canonical JSON -- proven by a live round-trip
  test (serialize, deserialize from a fresh object, verify identical
  digest and records).
- `read_and_verify_raw_response()` re-verifies a response's SHA-256
  against the manifest's recorded hash before scoring ever sees the
  text -- corruption, truncation, or substitution in transit is
  detected and raises `GenerationArtifactIntegrityError`, never
  silently scored anyway.

## 2. Denominator integrity

**The rule**: what counts as "expected" for a given evaluation run is
determined ONLY by the live-verified suite task set. It is never
determined by `scored_task_ids`, by whichever `GenerationRecord`s
happen to be present, or by any other caller-supplied subset.

Two enforcement points implement this:

- `orca.eval.generation_artifact.verify_against_suite()` -- runs
  BEFORE scoring, in `run_scoring_phase_from_artifact()`. Reconciles
  the manifest's records against the suite's own task list: every
  suite task must have exactly one record (missing = integrity error,
  duplicate = integrity error), no record may reference an unknown
  task_id, and each record's category/scoring_type must match what the
  suite itself defines for that task_id.
- `orca.eval.baseline._validate_result_completeness()` -- runs before
  any baseline can be finalized. Derives its expected set from `tasks`
  (the live-verified suite passed into `record_baseline_and_freeze_suite()`),
  not from `scored_task_ids`. Detects missing tasks, duplicate
  task_id entries, and unknown task_id entries.

**Missing transport data is NOT a generation failure.** A generation
failure (`generation_failures` entry) means the model/backend was
asked and explicitly failed to answer -- a known, legitimate outcome
that correctly accounts for a task. A task with NO entry anywhere is
an integrity error: ORNEUR does not know what happened to it, and
treating that as equivalent to "the model failed" would misrepresent
what actually occurred. `GenerationArtifactIntegrityError` (transport-
level) and `IncompleteResultError` (baseline-level) are kept
distinct from `generation_failures` for exactly this reason.

## 3. Judge-task accounting

`llm_judge` categories (currently 2, 6, 8, 13) are still REQUIRED to
appear in `per_task_results` with `passed: None` and the
`UNSCORED_REQUIRES_JUDGE` marker (matching
`orca.eval.runner.run_scoring_phase()`'s existing contract) -- they are
exempt from requiring a deterministic pass/fail, never exempt from
being accounted for at all. A baseline can never be finalized with a
silently-vanished judge task.

## 4. What this contract does NOT do

It does not run any judge (Phase 21B.4.8.1 defines only the judge
protocol contract -- see `GENESIS_JUDGE_PROTOCOL_SPEC.md` -- and
explicitly does not execute one). It does not itself decide which
generation/scoring split topology (same-machine vs. cross-machine) a
future real evaluation uses -- both `run_scoring_phase()` (same-
machine, records-based) and `run_scoring_phase_from_artifact()`
(cross-machine-safe, manifest-based with full reconciliation) remain
available; callers running generation and scoring on separate machines
should use the artifact-manifest path specifically to get the
integrity guarantees this document describes.
