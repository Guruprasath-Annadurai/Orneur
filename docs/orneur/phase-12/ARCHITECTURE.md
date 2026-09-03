# Phase 12 — Architecture

`orca/learning/` implements the governed flow spec §1 requires:

```
REAL EVENT -> FAILURE SIGNAL -> VERIFY -> CLASSIFY -> DEDUPLICATE ->
SANITIZE -> PROVENANCE/LINEAGE -> CURRICULUM CANDIDATE -> HUMAN/POLICY
GATE -> DATASET VERSION -> TRAINING RUN -> EVALUATION -> PROMOTION DECISION
```

## Module map

| Module | Responsibility | Reuses |
|---|---|---|
| `contracts.py` | Every typed dataclass/enum for the pipeline. | — |
| `signals.py` | Adapters: real subsystem output -> `FailureEvent`. | Truth/Simulation/Court/Connector contracts, read-only. |
| `triage.py` | Deterministic `FailureEvent` -> `FailureDisposition`. No model call. | — |
| `sanitize.py` | PII/secret sanitization before candidate admission. | `orca.serve.dlp`, `orca.connectors.security`. |
| `dedupe.py` | Exact + near-duplicate candidate detection. | `orca.godmode.canonical`. |
| `curriculum.py` | Difficulty scoring, balance reporting, `CurriculumCompiler`. | — |
| `provenance.py` | Lineage graph (`LineageGraph`), orphan detection. | — |
| `pipeline.py` | The explicit, callable orchestration sequence. | All of the above. |
| `regression_suite.py` | `FailureRegressionSuite` — failure-to-eval, independent of training. | — |
| `security.py` | Poisoning/exfiltration/injection/supply-chain guards. | `orca.registry.checkpoint`. |
| `training_experiment.py` | Hardware-gated training-run preparation, cancellation. | `orca.registry.training_run`, `orca.train.finetune` (not invoked on this hardware — see `TRAINING_RUNS.md`). |
| `observability.py` | Bounded, low-cardinality counters. | — |
| `audit.py` | The 15 required security/governance counters (spec §90). | — |
| `eval_harness.py` | 21 deterministic scenarios matching spec §80. | — |

## What Phase 12 reuses rather than rebuilds

Phase 1's registry layer (`orca/registry/`) already provided most of
spec §21-34's dataset/training-run/checkpoint/evaluation/promotion
machinery before Phase 12 began:

- `DatasetManifest` (checksummed, versioned) — Phase 12 extends it
  additively with approval state, freeze/immutability enforcement,
  split-group safety, and candidate/failure lineage fields.
- `TrainingRunManifest` — used as-is by `training_experiment.py`.
- `CheckpointRecord` (checksum-verified, `ArtifactAvailability`-gated) —
  used as-is; `security.py::verify_checkpoint_supply_chain` wraps it.
- `EvaluationReport` / `evaluate_promotion` — used as-is; already enforces
  "a metric that is UNMEASURED fails the gate."
- `ModelRegistry.promote()` — already REQUIRES a `PROMOTABLE`
  `EvaluationReport` before any `PRODUCTION` transition, and already
  demotes the prior production entry rather than allowing two. This is
  the existing, unmodified enforcement point for spec §31/§55/§68.

Phase 12's own code is the NEW layer above this: turning a real failure
into a governed candidate, then into a versioned dataset sample, with
sanitization, dedup, lineage, and security guards the pre-existing
registry never had a reason to implement on its own.

## Non-negotiable invariants (see `SECURITY.md` for the tests)

1. Training never happens synchronously with a production request
   (`test_learning_package_not_imported_by_hot_request_path`).
2. No model identity can approve, freeze, or promote anything
   (`ModelCannotSelfApprove`, checked in `apply_review_decision` and
   `DatasetManifest.approve`).
3. `TRAINING_COMPLETE ≠ PROMOTABLE ≠ PROMOTED` — three separately gated
   transitions, enforced by three separate, pre-existing registry
   functions Phase 12 does not bypass.
4. A frozen dataset cannot be silently mutated — checked against the
   ON-DISK copy's own frozen flag, not just an in-memory flag.
