# Genesis (nano) — Combined Safety+Calibration Dataset Baseline

Verification of the newly-built joint dataset before any training run. **No training was performed as part of this verification**, per Phase 0.5 scope.

## Provenance

- **Safety-refusal source**: `~/.orca/training/dpo/nano_safety_dpo_20260719.jsonl` (38 examples, domain `safety_refusal`) + `~/.orca/training/dpo/nano-v7_probe_grounded_safety_dpo_20260724.jsonl` (1 example, domain `safety_refusal_probe_grounded`) — 39 available, subsampled down to a fixed count via `scripts/build_nano_combined_dataset.py` (seeded RNG, `SEED=42`) to hit a ~1:5 (safety:calibration) ratio, mirroring the ratio that worked for Novus's fix.
- **Calibration source**: `~/.orca/training/raw/nano_distilled_20260829.jsonl` (31 examples, `PREMISE_CORRECTION` domain, `llama3.1:8b` teacher via Ollama, generated this session). Capped at 31 (not the requested 60) because the seed domain's own template pool is finite: 2 templates × 18 subtopics = 36 max unique combinations, minus 5 that failed generation.
- **Build script**: `scripts/build_nano_combined_dataset.py` — deterministic (fixed seed), formats both sources via `orca.data.formatter.to_llama3`, writes `notebooks/data/orca_nano_combined_{train,eval}_v1.jsonl`.

## Record counts

| Split | Count |
|---|---|
| Train | 34 |
| Eval | 3 |
| **Total** | **37** |

## Schema

All 37 records confirmed to have exactly `{"text": ...}` — 0 records with unexpected schema, 0 empty-text records.

## Class/target balance

From the build script's own logged output at generation time: **train = 5 safety : 29 calibration (ratio 1:5.8)**. This is close to the ~1:5 ratio that resolved Novus's calibration regression (see `NOVUS_FRESH_EVALUATION.md`), chosen deliberately as a starting point rather than re-deriving from scratch — but Genesis has never been trained with any ratio yet, so this specific ratio's effectiveness for Genesis is **unverified until an actual training run happens (explicitly out of scope for Phase 0.5)**.

## Duplicates

- **Exact duplicates**: 0 within train, 0 within eval, **0 train/eval leakage** (verified via exact string-set intersection across the full formatted `text` field).
- **Near-duplicates** (character-level similarity, `difflib.SequenceMatcher.quick_ratio()` on the human+assistant turns with the shared system-prompt block excluded to avoid inflating scores from identical boilerplate): **192 of 666 pairs (29%) exceed 0.85 similarity.** This is a real, honest finding, not a red flag of leakage — it reflects the calibration source data's own limited structural diversity (only 2 templates × 18 subtopics), meaning many examples share similar scaffolding/phrasing while addressing different specific premises. This is **not** the same as duplicate training examples (0 exact duplicates confirmed) but is worth flagging: a future, larger calibration-data generation pass should draw from more templates/subtopics to reduce this structural repetitiveness before scaling Genesis training much further.

## Token-length distribution (whitespace-token proxy, full formatted record)

min 107 · p25 248 · p50 323 · p75 439 · max 525

No records are pathologically short (empty/near-empty) or unreasonably long relative to the 2048-token `max_seq_length` used in prior training notebooks — all comfortably within budget.

## Invalid examples

None found — every record parses as valid JSON with a non-empty `text` field in the expected Llama-3 chat-template format (`<|begin_of_text|>...<|eot_id|>...<|end_of_text|>`).

## Checksums (frozen artifact)

```
orca_nano_combined_train_v1.jsonl  sha256:2e05abdfdc1cf4a254de87f19f27b6ca12dfece317e4d938e35285d1d5273da0
orca_nano_combined_eval_v1.jsonl   sha256:0b7dcafaa549275675368cc25567e31fb434abdb9bc705134827b40cb8b621fb
```

## Manifest (for Phase 1's dataset-versioning work)

```yaml
dataset: orca-nano-combined-safety-calibration-v1
generated: 2026-08-29
build_script: scripts/build_nano_combined_dataset.py
seed: 42
sources:
  safety:
    - path: ~/.orca/training/dpo/nano_safety_dpo_20260719.jsonl
      count: 38
      domain: safety_refusal
    - path: ~/.orca/training/dpo/nano-v7_probe_grounded_safety_dpo_20260724.jsonl
      count: 1
      domain: safety_refusal_probe_grounded
  calibration:
    - path: ~/.orca/training/raw/nano_distilled_20260829.jsonl
      count: 31
      domain: PREMISE_CORRECTION
      teacher: llama3.1:8b
      generated_via: orca/train/distill.py::distill_from_seeds
train:
  path: notebooks/data/orca_nano_combined_train_v1.jsonl
  count: 34
  composition: "5 safety : 29 calibration (1:5.8)"
  sha256: 2e05abdfdc1cf4a254de87f19f27b6ca12dfece317e4d938e35285d1d5273da0
eval:
  path: notebooks/data/orca_nano_combined_eval_v1.jsonl
  count: 3
  sha256: 0b7dcafaa549275675368cc25567e31fb434abdb9bc705134827b40cb8b621fb
known_limitations:
  - "Calibration source capped at 31/60 requested examples by finite seed-template pool (2 templates x 18 subtopics)"
  - "29% of pairs exceed 0.85 character-level similarity due to limited template diversity (not exact duplication)"
  - "Ratio (1:5.8) chosen by analogy to Novus's fix, not yet validated by an actual Genesis training run"
status: FROZEN, NOT YET USED FOR TRAINING
```

## Explicit statement per Phase 0.5 scope

**No training was started using this dataset.** This document only verifies and freezes the dataset artifact itself, per the explicit Phase 0.5 prohibition on retraining Genesis.
