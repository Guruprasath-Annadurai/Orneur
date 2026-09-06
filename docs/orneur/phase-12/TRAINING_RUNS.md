# Phase 12 — Training Runs

## Contract (spec §27)

`orca.registry.training_run.TrainingRunManifest` (Phase 1, unmodified):
`run_id`, `model_id`, `base_model`, `dataset_manifest_ids`,
`training_config`, `hyperparameters`, `seed`, `precision`,
`hardware_info`, `git_sha`, `start_time`/`end_time`,
`checkpoint_outputs`, `failure_state`, `resume_parent_*`.

## Backend (spec §28)

`orca/train/finetune.py` — real Unsloth-based QLoRA fine-tuning code from
Phase 1, audited and reused as-is. Phase 12 does not replace it or build
a second training path.

## Modes (spec §29)

`TrainingMode`: `SFT | LORA_QLORA | PREFERENCE_OPTIMIZATION | DISTILLATION`.
Only `LORA_QLORA` has a real, existing backend
(`orca/train/finetune.py`) in this repository as of Phase 12. `SFT` is a
strict subset of the same backend's capability (QLoRA fine-tuning IS a
form of SFT here). `PREFERENCE_OPTIMIZATION` has real code in
`orca/train/dpo_pairs.py`/`losses.py` from earlier phases but was not
exercised by this phase's own experiment. `DISTILLATION` has real code in
`orca/train/distill.py`, also not exercised this phase. **No RLHF
implementation exists anywhere in this repository** — the mode enum does
not include it, matching spec §29's explicit "do not claim RLHF/DPO/etc
unless implementation genuinely exists" (DPO's existing `dpo_pairs.py`
module IS real and is covered under `PREFERENCE_OPTIMIZATION`; it was
audited, not re-verified end-to-end this phase).

## Controlled training experiment (spec §30, §81) — hardware audit result

`orca.learning.training_experiment.audit_hardware()` checked this actual
machine:

```
cuda_available=False
mps_available=True
unsloth_installed=False
bitsandbytes_installed=False
```

This is a MacBook Air (Apple Silicon, ARM64, Darwin 25.6.0) with no
discrete/CUDA GPU. Unsloth's QLoRA path requires `bitsandbytes` 4-bit
quantization, which is CUDA-only — **MPS cannot run it even if unsloth
and bitsandbytes were both installed.** `audit_hardware().can_run_qlora()`
returns `False` on this machine, checked directly and honestly, not
assumed.

`orca.learning.training_experiment.prepare_training_experiment()` was run
for real against this exact environment. It:

1. Built and saved a real `TrainingRunManifest` (real git SHA, real
   hardware string, real config) — this manifest IS the validated
   "TRAINING_READY run" spec §81 asks for when hardware doesn't permit
   execution.
2. Detected the hardware gate and returned
   `TrainingExperimentStatus.TRAINING_READY` with an explicit,
   evidence-based reason string — **no training was executed, no
   checkpoint was fabricated.**

This is the honest stop point required by spec §30 ("Do not overwrite
production Genesis... the objective is to prove the pipeline... not to
claim major capability gains") and spec §81 ("If hardware does NOT permit:
stop honestly at a validated TRAINING_READY run and report why. Do not
fake trained artifacts.").

## Budget & cancellation (spec §72-74)

`TrainingBudget`/`TrainingCostReport.exceeds()` — explicit numeric caps
(GPU-seconds, examples, wall-clock, storage) checked deterministically;
no unbounded run is possible through this contract.
`TrainingFailureCategory`: `DATA_ERROR | OOM | CHECKPOINT_ERROR |
EVAL_FAILURE | SECURITY_FAILURE | CANCELLED | INFRASTRUCTURE_FAILURE` — a
bounded set, never a generic "failed" string.
`orca.learning.training_experiment.cancel_training()` marks the manifest
`CANCELLED` via `mark_failed()`, explicitly documents the partial
checkpoint as incomplete/not-promotable, and never touches
`ModelRegistry`.
