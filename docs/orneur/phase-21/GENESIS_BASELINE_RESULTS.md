# Genesis Foundation Baseline Results

## NO REAL MODEL WAS EXECUTED IN PHASE 21B.4

**BLOCKED ON OWNER-CONTROLLED COMPUTE RESOURCE -- NO MODEL BASELINE
EXECUTED.**

This document exists (per spec §14) specifically to state that fact
clearly rather than leave the gap silently unaddressed. No section
below contains, implies, or approximates a real model score.

## Resource gate check (verified live this closure)

```
$ nvidia-smi
command not found

$ system_profiler SPDisplaysDataType
Apple M4 (integrated GPU, no CUDA)

$ env | grep -iE "modal|kaggle|colab|hf_token|huggingface|cuda|gpu"
(no matches)

$ which modal kaggle
modal not found
kaggle not found

$ uname -a
Darwin ... arm64
```

This local development environment has no CUDA-capable GPU and no
configured credentials for Kaggle, Google Colab, Modal, Race
Engineering, or any other cloud compute provider named in
`PHASE21B4_FOUNDATION_BASELINE_SHOOTOUT.md`. Per Phase 21B.4 spec §8,
this means real model inference cannot and did not happen in this
closure.

## What WAS built and validated this closure

- The full baseline<->freeze transaction
  (`orca.eval.baseline.record_baseline_and_freeze_suite()`), exercised
  against 14 real test scenarios (see `PHASE21B4_FOUNDATION_BASELINE_IMPLEMENTATION.md`).
- A provider-neutral evaluation runner (`orca.eval.runner.run_suite()`),
  exercised ONLY against `DryRunAdapter` -- an explicitly-labeled,
  non-real placeholder adapter used solely to validate the runner's own
  plumbing (denominator integrity, digest wiring, failure capture). Its
  fixed placeholder response predictably fails most deterministic
  tasks -- this is a harness-validation artifact, not a model score of
  any kind, and is not reported as one anywhere in this document.
- A hardened, subprocess-isolated code-execution sandbox for the
  coding/debugging categories, replacing a sandbox proven exploitable
  via live reproduction this closure.

None of the above constitutes, approximates, or should be read as
evidence toward a foundation-model capability comparison. `genesis-eval-v1`
remains UNFROZEN (no real baseline has been recorded against it -- see
`orca.registry.evaluation_suite_manifest.EvaluationSuiteManifest`; no
persisted `genesis-eval-v1` manifest exists in this repository's
committed state, since freezing only happens transactionally alongside
a real recorded result).

## Per-category results

Not applicable. No candidate was evaluated. No category has a score.
Fabricating placeholder numbers here, even clearly labeled as
placeholders, was judged more likely to be mistaken for real data on a
future skim than simply stating their absence -- so none are included.

## When this document will be updated

Only after an owner explicitly authorizes and provisions a real
compute resource, a real `ModelAdapter` is implemented for that
resource's backend, and `orca.eval.runner.run_suite()` +
`orca.eval.baseline.record_baseline_and_freeze_suite()` are invoked
against a real candidate. See `PHASE21B4_FOUNDATION_BASELINE_IMPLEMENTATION.md`
section 7 for the exact reproduction steps.
