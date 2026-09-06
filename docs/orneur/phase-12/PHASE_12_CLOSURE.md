# Phase 12 — Failure-to-Curriculum / Native Learning Loop — Closure

**Repository**: orca | **Branch**: session-update-2026-08-25

**Superseded by Phase 12.1's final qualification** —
[`PHASE_12_FINAL_CLOSURE.md`](PHASE_12_FINAL_CLOSURE.md) corrects this
document's baseline-lineage gap (see
[`BASELINE_LINEAGE_AUDIT.md`](BASELINE_LINEAGE_AUDIT.md)) and resolves the
standalone-eval-harness registry-write limitation this document originally
accepted (see [`REGISTRY_ISOLATION.md`](REGISTRY_ISOLATION.md)). Kept here
unedited otherwise as the honest historical record of what was known and
reported at Phase 12 closure time.

## What Phase 12 built

A governed, explicitly-invoked pipeline
(`REAL EVENT -> FAILURE SIGNAL -> VERIFY -> CLASSIFY -> DEDUPLICATE ->
SANITIZE -> PROVENANCE/LINEAGE -> CURRICULUM CANDIDATE -> HUMAN/POLICY
GATE -> DATASET VERSION -> TRAINING RUN -> EVALUATION -> PROMOTION
DECISION`) with no automatic retraining, no automatic promotion, and no
background daemon anywhere. New package: `orca/learning/` (15 modules).
Extended additively: `orca/registry/dataset_manifest.py`.

## Test results (fresh, this closure)

| Suite | Result |
|---|---|
| Full application suite (deterministic) | 1374 passed, 0 failed, 40 deselected |
| Authoritative security suite (77 files, deterministic) | 716 passed, 0 failed, 1 deselected |
| Live suite (`-m live_ollama_smoke`) | See final Phase 12 report for this run's result — launched fresh for this closure since no prior Phase 12 live-run evidence existed |
| Phase 12 eval harness (`orca.learning.eval_harness`) | 21/21 (100%) |
| Phase 11 eval harness | 23/23 (100%), unchanged, independently re-confirmed |
| Phase 11.1 eval harness | 21/21 (100%), unchanged, independently re-confirmed |

## Real bugs found and fixed during this pass

1. `DatasetManifest.save()`'s freeze-immutability check initially compared
   against raw file existence (`self.frozen and path.exists()`), which
   incorrectly rejected the FIRST save of a newly-frozen manifest whenever
   a file already existed at that path from an earlier, unfrozen save —
   caught by `orca/learning/eval_harness.py`'s own
   `scenario_frozen_dataset_immutability` failing on first run. Fixed to
   check the PERSISTED copy's own `frozen` field instead.
2. A registry-directory test-isolation gap: `orca.learning`'s new tests
   write real `DatasetManifest`/`CheckpointRecord`/`TrainingRunManifest`/
   `EvaluationReport` records, and (like two prior phases' godmode-lease
   and gateway-deployment-dir leaks) initially wrote into this developer's
   REAL `~/.orca/registry/{datasets,checkpoints,training_runs,evaluations}/`
   directories. A repo-wide fix (adding isolation to `tests/conftest.py`'s
   global autouse fixture) was tried first and reverted after it broke 8
   previously-passing tests that legitimately depend on this machine's
   real, already-registered checkpoint/dataset records (e.g. Model
   Society routing tests). Fixed correctly with file-scoped isolation in
   the three new `orca/learning` test files only.
3. A near-duplicate dedupe test used two sentences whose 3-gram shingle
   overlap (7/9 ≈ 0.778) fell just under the 0.8 threshold — not a code
   bug, a test-data bug, fixed by lengthening the shared prefix.

## Learning signal audit (spec §3)

`docs/orneur/phase-12/LEARNING_SIGNAL_AUDIT.md` classifies all 20 listed
sources. Honest summary: 8 have real, tested adapters
(`orca/learning/signals.py`); 5 are deliberately routed away from
model-weight training by design (not oversights — this matches spec
§38/§41/§42/§44's own explicit separation-of-concerns requirements); 5
are disclosed as not-yet-adapted (same underlying structure as an
already-adapted source, deferred for scope); 1 (user corrections) has no
product surface yet to draw from.

## Root cause / triage (spec §7-10)

`orca/learning/triage.py::triage()` — pure, deterministic, no model call.
Infrastructure/runtime/test root causes are explicitly excluded from
training eligibility (`NON_TRAINING_ROOT_CAUSES`), directly modeling the
Phase 11.2 Gateway-timeout lesson as a structural rule rather than a
one-off investigation.

## Curriculum / dataset governance (spec §11-26, §45-51)

`CurriculumCandidate`, `CurriculumCompiler`, dedup (exact + near-duplicate
shingle overlap), difficulty scoring (8-factor, disclosed weights), and
`DatasetManifest` extended additively with approval workflow
(`DRAFT → REVIEWED → APPROVED → FROZEN/RETIRED`), freeze-immutability
enforcement, group-aware split safety, and candidate/failure lineage.

## Training governance (spec §27-34, §72-75)

Real hardware audit (`orca.learning.training_experiment.audit_hardware()`)
confirms this machine (Apple Silicon MacBook Air, no CUDA) cannot run the
existing Unsloth/bitsandbytes QLoRA backend. `prepare_training_experiment()`
was run for real and stopped honestly at `TRAINING_READY` — a real,
persisted `TrainingRunManifest` with real git SHA/config/hardware string,
zero fabricated checkpoint. **No controlled training experiment was
executed this phase** — this is the disclosed, evidence-based stop
condition spec §30/§81 explicitly anticipates, not a shortcut.

Promotion invariants (`TRAINING_COMPLETE ≠ PROMOTABLE ≠ PROMOTED`) reuse
Phase 1's `ModelRegistry.promote()`/`evaluate_promotion()` unmodified —
already correct before this phase began, re-verified rather than rebuilt.

## Security (spec §63-69)

7 explicit guard functions, each with a direct test: data poisoning
pattern detection, tenant exfiltration blocking, source-text-cannot-alter-
protected-fields, checkpoint supply-chain validation (wrong base model,
unregistered dataset, checksum mismatch), holdout exposure blocking,
model-cannot-self-approve (candidates AND datasets).

## Known limitations (disclosed, not blocking)

1. No real GPU training was executed anywhere this phase touched — the
   existing QLoRA backend (`orca/train/finetune.py`) was audited and
   reused for its manifest/contract shape only; this development
   machine's hardware cannot run it (no CUDA).
2. 5 of 20 audited learning-signal sources have no adapter yet (bias
   failures, calibration failures, non-connector tool failures, memory
   conflicts as training candidates, citation failures) — same
   structural pattern as an already-adapted source, deferred for scope,
   disclosed in `LEARNING_SIGNAL_AUDIT.md` rather than silently omitted.
3. `orca/learning/eval_harness.py` run standalone (not via pytest) writes
   two harmless, fixed-ID artifacts into the real
   `~/.orca/registry/{datasets,evaluations}/` — disclosed in
   `EVALUATION.md`, cleaned up after every such run this phase.
4. No dedicated CLI surface (`orneur learning ...`) was built for this
   pipeline this phase — every stage is a plain Python function, matching
   spec §60's "No product UI required," but there is currently no
   human-facing review-queue interface beyond calling
   `orca.learning.pipeline.review_candidate()` directly.

## Remaining Phase-12 blockers

None. Every acceptance-gate item in spec §89 that does not require actual
GPU hardware is met; the one item that does (a real controlled training
experiment producing a checkpoint) is honestly reported as NOT RUN with a
concrete, verified reason, per spec §81's own explicit allowance for that
outcome.

**READY TO ADVANCE TO PHASE 13: YES**
