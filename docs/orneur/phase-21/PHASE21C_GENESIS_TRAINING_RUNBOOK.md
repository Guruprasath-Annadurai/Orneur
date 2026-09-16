# PHASE 21C — Genesis 1 Training Runbook (PLANNING ONLY -- DO NOT EXECUTE)

This document specifies the exact intended order of operations for the
first canonical Genesis training run. **None of these steps have been
executed.** Phase 21C requires a separate, explicit owner authorization
naming the compute resource:

    AUTHORIZED — BEGIN PHASE 21C GENESIS TRAINING ON <RESOURCE>

Phase 21B's own approval does not authorize any step below.

## Preflight (before touching any resource)

1. Re-verify `git status`/branch/SHA against the approved Phase 21C
   starting point.
2. Re-verify `orca.registry.model_spec.MODEL_SPECS["genesis"]` matches
   this runbook's assumptions (base model, revision, license status
   unchanged since Phase 21B).
3. Re-run `pytest tests/test_training_provenance.py
   tests/test_genesis_v2_dataset_builder.py
   tests/test_genesis_not_trained_guard.py -q` -- all must pass before
   proceeding.
4. Confirm the owner-named resource in the authorization string matches
   the resource about to be used -- refuse to proceed on any mismatch.

## Step A -- Acquire and pin the verified base

```bash
# Downloads the exact pinned revision, never "main"/"latest":
python -c "
from huggingface_hub import snapshot_download
from orca.registry.model_spec import require_pinned_revision
base_rev, tok_rev = require_pinned_revision('genesis')
snapshot_download('unsloth/Qwen2.5-3B-Instruct', revision=base_rev)
"
```

Record the exact local cache path and re-verify the downloaded
`config.json` matches `docs/orneur/phase-21/GENESIS_BASE_MODEL_QUALIFICATION.md`'s
recorded architecture fields (hidden_size=2048, num_hidden_layers=36,
etc.) before proceeding -- a mismatch means the pinned revision resolved
to something unexpected and training must not continue.

## Step B -- Hash and record the base

```bash
# Hash every downloaded weight shard; record alongside the run manifest.
sha256sum <cache_path>/*.safetensors
```

## Step C -- Baseline (pre-training) evaluation

```bash
orneur train eval --ollama <base-model-serving-alias> --ci   # or equivalent direct-inference baseline
python -m orca.train.genesis_eval --model <base-model-serving-alias>
```

Record baseline scores under the SAME held-out suite that will later
score the trained checkpoint (spec section 27's baseline-vs-post-training
comparison requirement) -- run the expanded evaluation suite (§9's
blocking gap in the build-preparation doc) once it exists, not just
`genesis_eval.py` alone.

## Step D -- Dataset digest verification

```bash
python -c "
from orca.registry.dataset_manifest import DatasetManifest
from pathlib import Path
for dataset_id, version, train, eval_ in [
    ('orneur-genesis-combined-safety-calibration', 'v1',
     Path('notebooks/data/orca_nano_combined_train_v1.jsonl'),
     Path('notebooks/data/orca_nano_combined_eval_v1.jsonl')),
    ('orneur-genesis-v2', 'v1',
     Path('notebooks/data/orneur_genesis_v2_train.jsonl'),
     Path('notebooks/data/orneur_genesis_v2_eval.jsonl')),
]:
    m = DatasetManifest.load(dataset_id, version)
    ok, msg = m.verify_against_files(train, eval_)
    print(dataset_id, version, ok, msg)
    assert ok, f'{dataset_id}-{version} failed digest verification: {msg}'
"
```

Refuse to proceed if any dataset's on-disk content no longer matches its
recorded manifest digest.

## Step E -- Combine and expand the training corpus

Not yet built -- Phase 21C's own first real step should be assembling a
training-ready corpus (combining v1 + v2 + whatever expansion has
happened by then) and freezing/approving it via
`DatasetManifest.approve()` + `.freeze()` (both already implemented,
neither has been exercised for Genesis yet). **Do not train on an
unapproved, unfrozen manifest.**

## Step F -- Tiny training smoke (real base model, tiny data subset)

```bash
python -c "
from orca.train.config import TrainingConfig
from orca.train.finetune import train
cfg = TrainingConfig.preset('nano')
cfg.num_epochs = 1
cfg.train_file = '<tiny 5-10 record subset>'
cfg.output_dir = '<scratch dir, not the real output path>'
train(cfg, dataset_manifest_ids=['orneur-genesis-v2-v1'])
"
```

Confirms the full pipeline (load -> LoRA attach -> train -> save ->
merge) runs end to end on the REAL base model before committing to the
full run. Verify: loss decreases over the tiny subset (a basic overfit
sanity check), a `TrainingRunManifest` was created and marked complete,
a `CheckpointRecord` was registered at `EXPERIMENTAL`.

## Step G -- Full QLoRA run

```bash
python -c "
from orca.train.config import TrainingConfig
from orca.train.finetune import train
cfg = TrainingConfig.preset('nano')
train(cfg, dataset_manifest_ids=['orneur-genesis-combined-safety-calibration-v1', 'orneur-genesis-v2-v1'])
"
```

## Step H -- Checkpoint recording (automatic via Step G's `train()` call)

Verify the resulting `CheckpointRecord` and `TrainingRunManifest` are
complete and internally consistent (`run_id` cross-reference, dataset
hashes match Step D's verification).

## Step I -- Inference smoke (on the new checkpoint)

Deterministic single-prompt generation completes without error, before
any evaluation run.

## Step J -- Held-out evaluation

Run the full expanded evaluation suite (coding, debugging, product-
building, safety/authority, fabricated-completion resistance -- once
built) against the new checkpoint, using the SAME held-out suite as
Step C's baseline. Compute per-capability deltas, not just an aggregate
average (spec section 27).

## Step K -- Adversarial/safety evaluation

Genesis-specific prompt-injection, authority-confusion, tool-overreach,
execution-grant-hallucination, and secret-request test cases (spec
section 24) -- separate from, and never a substitute for, ORNEUR's
deterministic governance layers.

## Step L -- Regression comparison

Baseline (Step C) vs. trained checkpoint (Step J/K), explicit delta
report -- capability gain, any safety/calibration regression, coding
change.

## Step M -- Model card generation

Only after Steps I-L produce real evidence -- `docs/MODEL_CARDS.md`'s
existing generation machinery, extended to Genesis once a checkpoint
genuinely exists to card.

## Step N -- Lifecycle review

`ModelRegistry.promote()` against the real evaluation report -- refuses
automatically if thresholds aren't met (existing, unmodified logic).
Only a passing promotion changes Genesis's router-visible lifecycle;
training completion alone never does.

---

**No step in this runbook has been executed as part of Phase 21B.**
