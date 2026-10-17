# ORNEUR GENESIS/NOVUS Legacy Training Recovery Inventory

Status date: 2026-10-17. Parallel read-only assignment under the
Native-Authorization-Convergence directive: "investigate the actual
historical GENESIS and NOVUS checkpoints... without modifying model
weights."

**No model weights, checkpoints, or training artifacts were modified,
moved, or deleted by this investigation.** This report is a reading of
what already exists, not new work performed on it. One piece of
incidental debris this session's own testing accidentally created on
the local host (two empty `.claimed` marker files under
`~/.orca/genesis/training/native_pretraining_authorizations/`, written
by this session's own `GenesisTrainingRun` test runs that ran outside
pytest's isolation fixtures) was removed as session cleanup — it was
not a training artifact of any kind, just leftover state from this
session's own code under test.

## CRITICAL naming distinction — read this first

**The "GENESIS" this report investigates is NOT the same system as the
"GENESIS" this session's own Workstreams A–F (`orca/genesis/`) have
been building all session.** They share a name and nothing else:

| | Legacy "Genesis" (this report) | This session's "GENESIS Foundation Sprint" (Workstreams A–F) |
|---|---|---|
| What it is | A LoRA/QLoRA fine-tune of an existing base model | A from-scratch NATIVE pretraining effort (own tokenizer, own architecture) |
| Base model | `unsloth/Qwen2.5-7B-Instruct` (nano tier) | None — native pretraining has no base model |
| Code location | `orca/train/*`, Kaggle/Colab notebooks | `orca/genesis/*` (this repo's new modules) |
| Status | Multiple real SFT/DPO rounds completed, Ollama-quantized | `NOT_AUTHORIZED` — no training has ever run |

"NOVUS" has the same relationship to "core": legacy NOVUS = the
`unsloth/Meta-Llama-3.1-8B-Instruct` LoRA fine-tune lineage investigated
below; it has no relationship to this session's native-pretraining work
either. **Nothing in this report implies any connection between the two
"GENESIS" names beyond the shared label** — conflating them would be a
serious error.

## Sources read

- `~/.orca/registry/checkpoints/*.json` — a pre-existing, already-honest
  checkpoint recovery registry (7 entries, dated 2026-08-29/30, i.e.
  from an earlier session, not fabricated for this report).
- `docs/orneur/phase-0/MODEL_TRAINING_STATUS.md` (this repo) — a
  pre-existing, already-rigorous investigation (explicitly labeled
  "Nothing here is invented; anything not directly verifiable is
  labeled UNVERIFIED"), re-read and spot-checked against the registry
  above for consistency (confirmed consistent: `orca-core-combined`'s
  "fix attempt 2, the 0%-calibration checkpoint" matches the registry's
  `orca-core-combined.json`; `orca-core-combined-v2` matches "attempt 3
  ... pending GGUF/Ollama import").
- `~/.orca/training/{eval,redteam,dpo,formatted}/*` — real eval/redteam
  JSON reports and formatted training datasets, enumerated directly
  (filenames and presence only; contents not reproduced here beyond
  what the sources above already summarize).
- Filesystem search across `~/` for GGUF/safetensors/adapter/
  optimizer/scheduler/trainer-state artifacts.

## Inventory

### Legacy "Genesis" (nano tier — Qwen2.5)

| Item | Status |
|---|---|
| Base model | `unsloth/Qwen2.5-7B-Instruct` **or** `Qwen2.5-3B-Instruct` — **unresolved contradiction between `orca/train/variants.py`'s `VARIANTS` dict (7B) and its own docstring (3B), and `orca/train/config.py`'s `preset("nano")` (3B)**. Not resolved by this investigation; flagged as a precondition for trusting any nano training config. |
| LoRA/QLoRA adapters | Multiple rounds exist only as informally-versioned Kaggle/Colab notebook outputs (`orca_nano_finetune_kaggle_v2/v3/v4_safety.ipynb`, Colab v1–v4), then a DPO round (`orca_nano_dpo_kaggle_v1.ipynb`). **No adapter-naming registry in code** — history tracked only via notebook filenames. |
| Optimizer/scheduler state | `optimizer_state_available: false`, `scheduler_state_available: false` for every nano checkpoint in the registry — **none recoverable; exact training resumption is not possible for any of them.** |
| Kaggle/Colab artifacts | Notebooks named above exist per `MODEL_TRAINING_STATUS.md`; not independently re-verified as still present/runnable by this read-only pass. |
| Tokenizer | Base-model default (Qwen2.5's own tokenizer) — no custom tokenizer training found for nano. |
| Datasets | `nano_safety_dpo_20260719.jsonl` (38 examples), `nano-v7_probe_grounded_safety_dpo_20260724.jsonl` (1 example), `nano_distilled_20260829.jsonl` (31 calibration examples) — all confirmed present under `~/.orca/training/dpo/`. **No checksums or versioning on any of them.** |
| Evaluation reports | Confirmed present: `genesis_eval_orca-nano{,-v3,-v4,-v5,-v6,-v7,-finetuned-latest}.json`, `redteam_orca-nano{,-v6,-v7}.json`, plus `persona_eval_nano_*.json`. |
| Available checkpoints (Ollama-local, GGUF) | `orca-nano`, `orca-nano-v4`, `orca-nano-v7` — all `validation_state: UNVALIDATED`, `availability: LOCAL` (verified present via `ollama list` per the registry's own note). |
| Missing | The joint safety+calibration combined-SFT training run for nano (dataset built, per `MODEL_TRAINING_STATUS.md`, but **training run not yet executed** as of that document) — this remains the single largest concrete next step for legacy nano, independent of anything in this session. |

### Legacy "Novus" (core tier — Llama-3.1-8B)

| Item | Status |
|---|---|
| Base model | `unsloth/Meta-Llama-3.1-8B-Instruct` — consistent across all config sources, no ambiguity. |
| LoRA/QLoRA adapters | `orca-core-combined-adapter-v2` (latest, "attempt 3" in `MODEL_TRAINING_STATUS.md`'s terminology) is the newest LoRA weight set, **pending its own evaluation** as of that document. An EARLIER adapter (matching `orca-core`'s QLoRA kernel, `guruprasathannadurai/orca-core-qlora-v2`) was **independently re-downloaded and verified this registry's own prior session**: `sha256:094de7b23a0ce1b343b560c4c0354e408c48c2e1d74c84e03fbd4d65694ed5e4`, `r=64`/`lora_alpha=128` — confirmed to match `orca/train/variants.py`'s core-tier `lora_rank=64` exactly (real corroborating lineage evidence, not assumed). |
| Optimizer/scheduler state | `optimizer_state_available: false`, `scheduler_state_available: false` for every core checkpoint in the registry — **none recoverable.** |
| Kaggle/Colab artifacts | `orca_core_finetune_kaggle_v2.ipynb` (pre-DPO SFT foundation); `orca-core-combined-sft-kernel-v1` version 5 (the "fix attempt 3" training kernel, completed per the registry); a merge-export kernel `guruprasathannadurai/orca-core-dpo-merge-export-v1` (status COMPLETE, used to recover `orca-core-dpo`'s GGUF). |
| Tokenizer | Base-model default (Llama-3.1 tokenizer); one explicitly-documented infra bug fixed along the way — a stale `tokenizer_config.json` was being loaded from the adapter directory instead of the base model name, corrected. |
| Datasets | `core_probe_grounded_safety_dpo_20260724.jsonl` (3 examples — a notably thin safety base), `core-dpo_probe_grounded_safety_dpo_20260826.jsonl`, `core_distilled_20260826.jsonl` (60 calibration examples); `orca_core_llama3_{train,train_v2,eval,eval_v2}.jsonl` under `~/.orca/training/formatted/`. **No checksums or versioning.** |
| Evaluation reports | Confirmed present: `eval_orca-core{,-combined-v2}.json`, `novus_eval_orca-core-{v1,v2}.json`, `novus_eval_judged_orca-core.json`, `novus_eval_orca-core-combined-v2.json`, `redteam_orca-core{,-v1,-v2,-dpo,-calibration,-combined,-combined-v2}.json`, plus a `history/` subdirectory of timestamped prior eval runs. **The pending eval for "attempt 3" (`orca-core-combined-v2`) had not returned as of `MODEL_TRAINING_STATUS.md` being written** — not independently re-checked for completion by this pass; treat as still pending unless a fresher report is found. |
| Available checkpoints | `orca-core-combined` (LOCAL, Ollama-verified), `orca-core-combined-v2` (LOCAL, Ollama-verified), `orca-core-dpo` (REMOTE — recovered from Kaggle, GGUF header verified against the expected Llama-3.1-8B signature, but **not re-imported to local Ollama**, so not currently loadable as-is), `orca-core` (**MISSING** — the GGUF merge/export stalled at 0 bytes after 55+ minutes and was never completed; only its LoRA adapter was recovered and verified, the merged/quantized artifact itself was not, and this was left honestly `MISSING` rather than retried indefinitely or assumed recoverable). |
| Missing | `orca-core`'s merged GGUF (adapter recovered, merge never completed); the pending "attempt 3" eval/redteam result; any optimizer/scheduler state for ANY core checkpoint (none ever captured). |

### Legacy "Aeternum" (ultra tier — Llama-3.1-70B)

No confirmed fine-tuned checkpoint exists at all — directly confirmed
by this codebase's own test suite
(`test_persona_claim_gate.py::test_persona_system_ultra_with_zero_training_data_is_demoted_not_crashed`).
No training data, no training run, no evaluation, no checkpoint.
**AETERNUM remains deferred per the directive — nothing here changes
that.**

## Exact resumption vs. a new fine-tuning continuation — explicit distinction

**None of the recoverable artifacts above constitute a complete,
resumable training checkpoint in the sense of "continue the exact same
optimizer trajectory from the exact step it stopped at."** Every single
checkpoint in the registry has `optimizer_state_available: false` and
`scheduler_state_available: false` — there is no recoverable optimizer
momentum/variance state, no scheduler step count, and (per the
registry's own `step_or_epoch: "unknown (legacy, predates run-manifest
tracking)"`) not even a reliably known step count to resume from.

**What IS available, for the checkpoints with recovered/verified LoRA
adapters** (`orca-core`'s adapter specifically, with a verified
checksum and corroborating rank/alpha lineage) **is a starting point for
a genuinely NEW fine-tuning continuation**: loading the adapter weights
as initialization and training further with a fresh optimizer state —
not a bit-for-bit resumption of the original run. This is an
important, honest distinction: a caller asking to "resume NOVUS
training" cannot get exact resumption from anything recovered here;
they can get a new training run that starts from an existing adapter's
weights.

**A quantized Ollama GGUF copy (the `LOCAL`/`REMOTE` artifacts above)
is explicitly NOT treated as a resumable training checkpoint at all** —
per the directive's own instruction. GGUF is a merged, quantized
INFERENCE format; it contains no LoRA-rank structure, no optimizer
state, and in several cases (per `MODEL_TRAINING_STATUS.md`) was
produced through a MERGE of the base model with an adapter, which is
not even reversible back into "the adapter alone" without the adapter
file existing separately (which, for `orca-core-dpo`'s case, it does
not appear to, since only the merged GGUF was recovered).

## Genuine next-experiment readiness matrix

| Tier | Resumable (exact)? | New-continuation-ready? | Blocking gap |
|---|---|---|---|
| Legacy Genesis (nano) | No (no optimizer/scheduler state for any checkpoint) | Partially — `orca-nano-v7`'s GGUF is LOCAL and Ollama-verified, but **no separately-recoverable LoRA adapter file** is confirmed for it specifically (only the merged GGUF); would need re-extraction from its own Kaggle/Colab kernel to get adapter-level continuation | Base-model-size ambiguity (7B vs 3B) must be resolved FIRST — training against the wrong size entirely invalidates the run |
| Legacy Novus (core) | No (no optimizer/scheduler state for any checkpoint) | **Yes, for `orca-core` specifically** — a real, checksum-verified LoRA adapter (`r=64`/`lora_alpha=128`, matching `variants.py` exactly) was recovered; a new continuation run could load it today | `orca-core`'s own merged GGUF remains missing (immaterial for a NEW continuation, which only needs the adapter); the "attempt 3" eval result should be obtained before deciding whether to continue from the OLDER adapter or wait for attempt 3's own adapter to be separately recovered |
| Legacy Aeternum (ultra) | N/A — nothing exists | No | Everything — training data, a training run, and a base checkpoint all remain to be created from scratch; explicitly deferred |
| This session's native-pretraining GENESIS (Workstreams A–F) | N/A — no training has ever occurred, by design (`NOT_AUTHORIZED`) | N/A | Founder authorization (real signing key, real acceptance-ledger rows) — entirely orthogonal to anything in this table |

## Unresolved problems

- Nano's base-model-size contradiction (7B vs 3B) is unresolved and
  blocks trusting ANY nano training config as-is.
- No checksums or versioning exist for ANY training dataset file across
  either legacy tier — a real, standing data-integrity gap this report
  does not attempt to close (it is a legacy-era gap, not something this
  session's Workstream A hardening retroactively fixes for these
  pre-existing files).
- `orca-core-dpo`'s GGUF has a freshly-recorded checksum with **no
  prior value to compare against** — it establishes a baseline, not a
  confirmed-unchanged comparison; if this artifact is later found to
  differ from that recorded hash, that would indicate tampering or
  corruption, but there is currently nothing to compare the ORIGINAL
  Kaggle-produced bytes against independently.
- `orca-core`'s own merged GGUF remains genuinely unrecovered (download
  stalled); not retried as part of this read-only investigation, per
  the "no training, no resource consumption" constraint and because
  retrying a multi-GB download was out of scope for a read-only pass.
- This investigation did not re-verify Kaggle kernel availability/
  accessibility live (would require network access and Kaggle
  credentials this read-only pass does not exercise) — kernel
  references above are taken from the pre-existing registry's own
  prior verification, not re-confirmed today.

## Verdict

Read-only investigation complete. No training occurred. No model
weights were modified. Native pretraining (this session's actual
Workstream A–F GENESIS effort) remains completely unrelated to, and
unaffected by, anything in this legacy inventory. Any decision to
resume or continue legacy Genesis/Novus/Aeternum training requires
founder approval, per the directive's own execution constraints, and
is a separate decision from anything in the native-pretraining
authorization chain built this session.
