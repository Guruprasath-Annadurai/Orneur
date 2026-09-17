# Genesis Foundation Baseline Results

## NO REAL MODEL HAS BEEN EXECUTED (THROUGH PHASE 21B.4.1)

**COMPUTE-READY -- REAL GENESIS BASELINE AWAITS OWNER-AUTHORIZED
RESOURCE.**

This document exists (per spec §14) specifically to state that fact
clearly rather than leave the gap silently unaddressed. No section
below contains, implies, or approximates a real model score.

## Resource gate check (re-verified live this closure, Phase 21B.4.1)

```
$ nvidia-smi
command not found

$ system_profiler SPDisplaysDataType
Apple M4 (integrated GPU)

$ python -c "import torch; print(torch.cuda.is_available(), torch.backends.mps.is_available())"
False True

$ env | grep -iE "modal|kaggle|colab|hf_token|huggingface|cuda|gpu"
(no matches)

$ which modal kaggle
modal not found
kaggle not found
```

**Update from Phase 21B.4's finding, stated honestly**: this host has no
CUDA-capable GPU, but DOES have an Apple M4 GPU visible to PyTorch via
the MPS backend -- a materially different fact than the prior blanket
"no GPU" statement. This is a consumer laptop-class integrated GPU, not
the datacenter-class CUDA resource this project's shootout runbook
anticipates, and it has not been explicitly authorized by the owner as
a resource for real Genesis baseline execution. No configured
credentials exist for Kaggle, Google Colab, Modal, or Race Engineering.
Per spec §12's two-gate requirement, even full technical readiness
(which the infrastructure below now achieves) does not by itself
authorize real inference without a separate, explicit owner resource
authorization.

## What WAS built and validated (Phase 21B.4 + 21B.4.1)

- The full baseline<->freeze transaction
  (`orca.eval.baseline.record_baseline_and_freeze_suite()`), now
  concurrency-hardened (a real multi-threaded race test) and
  adversarially re-reviewed this closure (two real bugs found and fixed:
  a result could reference the wrong suite, and a duplicate run_id could
  silently overwrite a finalized result).
- A provider-neutral evaluation runner (`orca.eval.runner.run_suite()`),
  exercised ONLY against `DryRunAdapter` -- an explicitly-labeled,
  non-real placeholder adapter used solely to validate the runner's own
  plumbing. Not a model score of any kind.
- A REAL container-isolated code-execution sandbox
  (`orca.eval.sandbox_docker`), replacing Phase 21B.4's subprocess-only
  sandbox after this closure found it still had real, unclosed gaps
  (DNS resolution and raw-libc access both bypassed its network guard;
  filesystem access remained fully open). Live-verified this closure
  that the container sandbox closes all of these.
- The first real `ModelAdapter` implementation
  (`orca.eval.adapters.transformers_adapter.TransformersModelAdapter`),
  tested entirely against mocked `transformers` calls -- no real model
  weights downloaded anywhere in its test suite.
- An operator-facing execution CLI
  (`python -m orca.eval.run_genesis_baseline`) with a machine-readable
  `--preflight` mode, live-verified on this host to correctly report
  both `READY FOR REAL BASELINE` (for a valid CPU config) and
  `NOT READY` (for an unpinned revision / unavailable CUDA device).

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
