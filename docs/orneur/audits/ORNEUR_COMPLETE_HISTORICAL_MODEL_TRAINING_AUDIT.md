# ORNEUR — Complete Historical Model Training Audit

Status date: 2026-10-16. Read-only evidence reconciliation, documentation
only. Repository HEAD referenced: `origin/main` at
`20a8546f5a1ece7e5af655c0f30ca7e305f71b1a`. This document lives on its own
documentation-only branch and draft PR, separate from and without touching
PR #58's engineering work.

**Compliance statement**: no retraining, no GPU provisioning, no spend, no
model-weight modification, no renaming of historical weights or checkpoints,
no fabricated lineage, no deletion of evidence, and no change to any
governance record occurred in producing this document.

## Why this document exists

A prior general claim in this program's recent sessions -- that GENESIS,
NOVUS, and AETERNUM are "untrained" -- was **incomplete**. It was accurate
for the *current, native-architecture* GENESIS/NOVUS/AETERNUM programme
(`orca/genesis/model/transformer.py` and friends, Sprint 1/Sprint 2/Audit
#016/#017 work), which genuinely has never been trained. It was **not**
accurate as a statement about this project's full history: an **earlier,
separate lineage** -- built by LoRA/QLoRA fine-tuning and DPO on top of
third-party pretrained models (Qwen2.5, Llama-3.1), under the ORCA-era names
`nano`/`core`/`ultra`, later mapped onto the `genesis`/`novus`/`aeternum`
family labels -- really was trained, really produced real checkpoints, and
some of those checkpoints are still present and loadable on this machine
today. This document reconciles both lineages honestly, distinguishes them
explicitly, and corrects every place a prior statement blurred them together.

## Method

Every document named in the originating directive was read in full from the
actual committed repository content (`origin/main`), not from memory or
summary. Beyond that, this audit independently verified the documents'
claims against **live, primary evidence** on this machine, not just trusted
the prose:

- Started the local Ollama server and ran `ollama list` / `ollama show`
  against every legacy checkpoint tag the documents name, to confirm present-
  day installation and re-confirm architecture/parameter-count metadata
  directly from the GGUF header (not from config files).
- Ran one minimal real inference call (`"Say OK."`, 5 tokens) against
  `orca-nano-v7` to directly confirm it loads and generates today, without
  any training step.
- Read the actual local registry state at `~/.orca/registry/` (checkpoints,
  datasets, evaluations) -- the real, persisted `CheckpointRecord` /
  `DatasetManifest` / evaluation-report JSON files this project's own code
  produces, not just the markdown narrating them.
- Independently recomputed the SHA-256 of one checkpoint's actual on-disk
  Ollama blob (`orca-nano-v7`) from raw bytes and confirmed it matches both
  Ollama's own manifest digest and the registry's recorded
  `artifact_checksum` exactly -- a real, from-first-principles hash
  verification, not a copied-and-trusted value.
- Cross-checked the specific numbers cited in `NOVUS_PROMOTION_DECISION.md`
  (72.8% / 70.0% / 12.5% / 37.5%) against the actual saved evaluation JSON
  files (`redteam_orca-core-combined-v2.json`,
  `novus-combined-v2-full-eval.json`) -- found to match exactly.
- Checked `~/.orca/registry/training_runs/` (the formal `TrainingRunManifest`
  directory) directly: **empty**, confirming the documents' own statement
  that this legacy training predates formal run-manifest tracking
  (`run_id: "legacy-pre-orneur"` on every legacy `CheckpointRecord`).
- Searched the entire registry for any `aeternum`/`ultra` checkpoint record:
  **none found anywhere**, confirming no Aeternum/Ultra checkpoint has ever
  existed, historically or currently.

No external account (Kaggle, Hugging Face, Colab) was accessed -- those
platforms' own artifacts are cited exactly as the source documents describe
them (kernel names, dataset IDs), explicitly marked where this audit could
not independently re-verify them, per the directive's own instruction not to
assume unavailable external access.

## Evidence provenance taxonomy

Every factual claim in this document is tagged with one of four provenance
labels, so a reader never has to guess how strongly a given line is
supported. This taxonomy is applied consistently in the table and findings
below.

- **`[ORIGINAL OBSERVATION]`** -- gathered directly by this audit, on this
  machine, on 2026-10-16: a live `ollama list`/`ollama show` call, the
  independently-recomputed SHA-256 of a raw blob, the one real inference
  call against `orca-nano-v7`, or a direct read of a currently-existing
  local file (registry JSON, evaluation JSON) performed in this pass.
- **`[ARCHIVED EVIDENCE]`** -- a specific, cited claim from one of the six
  named historical documents or a registry/evaluation file, where this
  audit read the underlying file directly but the event itself (a training
  run, an evaluation pass) happened in the past and was not re-executed or
  re-verified independently beyond reading the record.
- **`[UNAVAILABLE ARTIFACT]`** -- a checkpoint, dataset, or run that the
  historical record describes as having existed, but that this audit
  confirmed is NOT currently present/loadable on this machine (e.g.
  `orca-core`, `orca-core-dpo`), or whose current status this audit could
  not determine at all.
- **`[UNVERIFIED CLAIM]`** -- a statement this audit could not independently
  check at all (e.g. whether a named Kaggle kernel is still live), reported
  exactly as the source document states it, with no independent
  confirmation either way.

## The critical identity distinction

**There are two, entirely separate things in this project's history that
have both been called "Genesis", "Novus", or "Aeternum" at different times:**

1. **The ORCA-era fine-tuned lineage** (this document's main subject):
   LoRA/QLoRA SFT + DPO fine-tuning of third-party pretrained models
   (Qwen2.5-7B-Instruct for the `nano`/legacy-`genesis` tier, Llama-3.1-8B-
   Instruct for `core`/`novus`), run on Kaggle/Colab GPUs, producing real
   GGUF checkpoints, several of which are installed in Ollama **today**. The
   model registry's `legacy_ollama_names` field and `legacy_note` strings
   (`orca/registry/model_spec.py`) exist specifically to keep this lineage
   visibly distinct from the family's *canonical future target*.
2. **The current native-architecture GENESIS programme**
   (`orca/genesis/model/transformer.py`, `orca/genesis/tokenizer/`,
   `orca/genesis/training/`): an original ORNEUR Transformer architecture
   (GQA, RoPE, RMSNorm, SwiGLU), with its own tokenizer training framework
   and training primitives -- **genuinely never trained**, not even once,
   not even a single optimizer step. Every model object this programme's
   own test suite constructs is freshly, randomly initialized. This is
   NOVUS and AETERNUM's *only* existence so far -- there is no ORCA-era
   NOVUS/AETERNUM fine-tune-lineage equivalent for AETERNUM at all (see
   below), and NOVUS's native-architecture work has not begun.

**These must never be conflated.** A Qwen2.5-7B-Instruct LoRA adapter fine-
tuned via SFT+DPO is not evidence that ORNEUR has natively pretrained
anything from random initialization. Conversely, "GENESIS's native
Transformer has never been trained" does not mean "ORNEUR has never trained
any model called Genesis" -- it has, under the ORCA-era lineage, and that
history is real and must not be erased.

## Complete historical model/checkpoint table

Each row's **Evidence** cell ends with this row's provenance tag(s) from
the taxonomy above, so the table itself carries the distinction, not just
the prose around it.

| Model family & checkpoint | Base model & lineage | Training method | Date / environment | Dataset & volume | Parameter updates verified | Artifact location & hash | Currently accessible | Inference verified | Evaluation results & limitations | Lifecycle status | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Genesis (legacy)** `orca-nano` | `unsloth/Qwen2.5-7B-Instruct` (forensically confirmed 7.6B params, embed 3584 via GGUF header -- NOT the 3B config value some files claimed) | SFT (multiple rounds, Unsloth+TRL, Kaggle/Colab notebooks `orca_nano_finetune_kaggle_v2/v3/v4_safety.ipynb` + Colab v1-v4) | Predates formal run-manifest tracking (`run_id="legacy-pre-orneur"`); Kaggle/Colab, single-GPU (T4-class) | `nano_safety_dpo_20260719.jsonl` (38 examples) + related safety-refusal sets; no checksums existed at training time | **YES** (real LoRA fine-tuning occurred; `ollama show` confirms a real, distinct checkpoint exists, not a base-model passthrough) | `ollama://orca-nano`, `sha256:671e7777da70c808de5d0060d1e9df3b8f496e15fa6b39c86371abd70cb0d560` (registry-recorded; not independently re-hashed in this pass -- `orca-nano-v7`'s was, see next row) | **YES** -- confirmed via `ollama list` on this machine, today (2026-10-16) | Not directly re-run this pass (see `orca-nano-v7` row for the directly-tested sibling checkpoint) | No standalone eval report found separate from the v7 line | `RETIRED` (per `docs/orneur/phase-1/GENESIS_NOVUS_AETERNUM_STATUS.md`) | `MODEL_TRAINING_STATUS.md`, `GENESIS_MODEL_IDENTITY.md`, `~/.orca/registry/checkpoints/orca-nano.json` -- `[ARCHIVED EVIDENCE]` (training history) + `[ORIGINAL OBSERVATION]` (today's `ollama list` presence) |
| **Genesis (legacy)** `orca-nano-v4` | Same as `orca-nano` | Same lineage, later SFT round | Same era | Same lineage | **YES** | Same digest as `orca-nano` per `ollama list` (confirmed identical artifact, re-tag only) -- `sha256:671e77...` | **YES** -- confirmed via `ollama list` today | Not independently re-tested (identical bytes to `orca-nano`) | Same as `orca-nano` | `RETIRED` | Same sources -- `[ARCHIVED EVIDENCE]` + `[ORIGINAL OBSERVATION]` |
| **Genesis (legacy)** `orca-nano-v7` | `unsloth/Qwen2.5-7B-Instruct`, forensically confirmed (7.6B params, qwen2, embed 3584, Q4_K_M) | SFT, final nano round, then a safety+honesty DPO round (`orca_nano_dpo_kaggle_v1.ipynb`) on top | Predates run-manifest tracking; Kaggle, single-GPU | `nano-v7_probe_grounded_safety_dpo_20260724.jsonl` + prior SFT data | **YES** | `ollama://orca-nano-v7`; registry-recorded `sha256:5ce043a5425064eb264c8054ff9c49c335764b6664d639c71a8788a4dd5e2391` -- **independently re-hashed in this audit from the raw Ollama blob bytes (`shasum -a 256`); matches exactly, both the registry record and Ollama's own manifest digest** | **YES** -- confirmed via `ollama list` + `ollama show` today, 7.6B/qwen2/embed-3584 metadata re-confirmed live | **YES -- directly tested this audit**: a real, minimal (`num_predict=5`) generation call via the Ollama API returned a genuine, non-empty completion (`" Then show the step-by"`) in ~14s, confirming real loadable inference with zero training involved | `redteam_orca-nano.json` / `redteam_orca-nano-v7.json` exist in `~/.orca/training/redteam/` (not line-by-line re-parsed in this pass; existence and dates confirmed: `redteam_orca-nano-v7.json`, 2026-07-22) | `RETIRED` | `MODEL_TRAINING_STATUS.md`, `GENESIS_MODEL_IDENTITY.md`, `~/.orca/registry/checkpoints/orca-nano-v7.json`, direct `ollama show`/`shasum`/`curl` evidence gathered in this audit -- `[ARCHIVED EVIDENCE]` (training history) + `[ORIGINAL OBSERVATION]` (hash recomputation, live inference, live architecture metadata -- the most strongly independently-verified row in this table) |
| **Genesis (canonical future target)** -- no checkpoint | `unsloth/Qwen2.5-3B-Instruct` (pinned revision `7548fff1f997f57b2e9e8ab1ec7be96949b00ed0`, per `orca/registry/model_spec.py`) | **NONE -- not yet attempted** | N/A | `orca-genesis-combined-safety-calibration-v1` (37 records) exists, built, checksummed -- but its own manifest states "not yet used for training"; a second, later dataset `orneur-genesis-v2-v1` (19 hand-authored records, Phase 21B) also exists and is explicitly documented as "far too small... must be combined... before a real training run" | **NO** -- no training run has ever targeted this base model | N/A -- no artifact exists | N/A | N/A | N/A -- nothing to evaluate | No candidate exists at any lifecycle stage | `GENESIS_NOVUS_AETERNUM_STATUS.md`; `~/.orca/registry/datasets/orca-genesis-combined-safety-calibration-v1.json`, `~/.orca/registry/datasets/orneur-genesis-v2-v1.json` (both read directly in this audit) -- `[ARCHIVED EVIDENCE]` + `[ORIGINAL OBSERVATION]` (dataset files read directly; no checkpoint exists to observe) |
| **Genesis (current native programme)** -- no checkpoint | None (original ORNEUR architecture, not a fine-tune of any base model) | **NONE -- no training loop even exists yet** (Workstream C, GENESIS Foundation Sprint 2, pending) | N/A | N/A | **NO** -- every model object is freshly, randomly initialized | N/A | N/A | N/A | N/A | Architecture/tokenizer/training-primitives exist and are tested (Sprint 1); `NOT_AUTHORIZED` for training | This session's own Sprint 1/2 + Audit #016/#017 work; `orca/genesis/` -- `[ORIGINAL OBSERVATION]` (this programme's own code and tests, read directly) |
| **Novus (legacy)** `orca-core` | `unsloth/Meta-Llama-3.1-8B-Instruct`, unambiguous | Plain SFT (`orca_core_finetune_kaggle_v2.ipynb`), pre-DPO foundation | Predates run-manifest tracking; Kaggle | Not separately itemized in the source docs | **YES** (adapter portion independently recovered and verified this phase per the registry note: `sha256:094de7b23a0ce1b343b560c4c0354e408c48c2e1d74c84e03fbd4d65694ed5e4` for the LoRA adapter, `r=64`/`lora_alpha=128` matching the project's own core-tier config -- real corroborating lineage evidence) | `ollama://orca-core`; `artifact_checksum: "UNPROVEN_GGUF_RECOVERY_INCOMPLETE"` | **NO -- explicitly recorded as MISSING.** The merged/quantized GGUF download stalled at 0 bytes for 55+ minutes during a recovery attempt and was never completed; left honestly `MISSING` rather than assumed recoverable | **NO** -- cannot load a missing artifact | `redteam_orca-core.json` exists (dated 2026-08-26) but pertains to whichever checkpoint was installed at that time, not independently re-attributed in this pass | Checkpoint `MISSING` (unrecoverable as of last attempt) | `~/.orca/registry/checkpoints/orca-core.json` (read directly in this audit) -- `[ARCHIVED EVIDENCE]` + `[UNAVAILABLE ARTIFACT]` (confirmed absent/unrecoverable) |
| **Novus (legacy)** `orca-core-dpo` | `unsloth/Meta-Llama-3.1-8B-Instruct` | DPO (safety/honesty), on top of `orca-core`'s SFT foundation | Predates run-manifest tracking; Kaggle | `core_probe_grounded_safety_dpo_20260724.jsonl` (3 examples) | **YES** | `ollama://orca-core-dpo`; `sha256:3075a9bb064a63e4ea0d48be2378d6dc4fb08883724c58cee5489022b6d10873` -- recovered and verified via its Kaggle merge-export kernel (file size + GGUF header match the expected Llama-3.1-8B signature) | **NO, not locally loadable** -- recorded `availability: "REMOTE"`; not re-imported to local Ollama due to disk constraints. **Confirmed absent from this machine's current `ollama list`** (not in the live listing obtained in this audit) | **NO** (not locally present to test) | 20.0% jailbreak block rate (baseline, per `MODEL_TRAINING_STATUS.md`'s comparison table) | `EXPERIMENTAL`/superseded | `MODEL_TRAINING_STATUS.md`, `~/.orca/registry/checkpoints/orca-core-dpo.json` -- `[ARCHIVED EVIDENCE]` + `[ORIGINAL OBSERVATION]` (today's `ollama list` confirms absence) + `[UNAVAILABLE ARTIFACT]` |
| **Novus (legacy)** `orca-core-calibration` | Same base | SFT (calibration-fix round, sequential after DPO) | Predates run-manifest tracking | Unspecified in source docs | **YES**, but this specific run **caused catastrophic forgetting** (jailbreak collapsed from 20.0% to 0.0%) | Not independently located as a separate registry record in this pass (no `orca-core-calibration.json` file found in `~/.orca/registry/checkpoints/`) | **UNVERIFIED** -- no current registry record or Ollama tag confirmed for this exact intermediate checkpoint | **UNVERIFIED** | 0.0% jailbreak, 33.3% calibration (per `MODEL_TRAINING_STATUS.md`'s comparison table; a `redteam_orca-core-calibration.json` file exists at `~/.orca/training/redteam/`, dated 2026-08-28, not individually re-parsed in this audit) | Superseded (the failed sequential-fix attempt) | `MODEL_TRAINING_STATUS.md` -- `[ARCHIVED EVIDENCE]` + `[UNAVAILABLE ARTIFACT]` (no current checkpoint record located) |
| **Novus (legacy)** `orca-core-combined` | Same base | SFT, joint safety+calibration, fix attempt 2 (1:2 safety:calibration ratio, 10x oversample) | Predates run-manifest tracking; Kaggle | Unspecified exact dataset ID in source docs for this exact checkpoint | **YES** | `ollama://orca-core-combined`; `sha256:f9e41d9092d2a2443fb8f4e40a0b9d8a09c909617c37581e56e2f1dac60ecc95` | **YES** -- confirmed via `ollama list` on this machine, today | Not directly re-tested in this audit (budget focused on `orca-nano-v7` and `orca-core-combined-v2`) | 70.0%/90.0% jailbreak, 12.5% bias, **0.0% calibration** (the specific regression this lineage's "fix attempt 3" exists to resolve) | `EXPERIMENTAL`, superseded by `-v2` | `MODEL_TRAINING_STATUS.md`, `~/.orca/registry/checkpoints/orca-core-combined.json` -- `[ARCHIVED EVIDENCE]` + `[ORIGINAL OBSERVATION]` (presence confirmed today) |
| **Novus (legacy)** `orca-core-combined-v2` | `unsloth/Meta-Llama-3.1-8B-Instruct` (forensically re-confirmed 8.0B/llama/embed-4096 via live `ollama show` in this audit) | SFT, joint safety+calibration, fix attempt 3 (1:5 ratio, 4x oversample), Kaggle kernel `orca-core-combined-sft-kernel-v1` version 5 | Predates formal run-manifest tracking (`run_id: "orca-core-combined-sft-kernel-v1-v5"` recorded, but no `TrainingRunManifest` file exists in `~/.orca/registry/training_runs/`, which is empty) | `orca-novus-combined-safety-calibration-v2` -- **72 records** (3 safety examples, 4x oversampled to 12; 60 calibration examples), checksummed (`train_checksum`/`eval_checksum` present in `~/.orca/registry/datasets/orca-novus-combined-safety-calibration-v2.json`) | **YES** | `ollama://orca-core-combined-v2`; registry-recorded `sha256:c519cba17b689b752807006da39713ba25caadcbb5d4c0380b3d519862308725` (4,920,738,816 bytes, Q4_K_M) -- **not independently re-hashed in this specific pass (budget spent re-hashing `orca-nano-v7` instead), but the registry's own availability_note states it was "Verified present in local Ollama store via `ollama list`"**, and this audit independently re-confirmed its presence and 8.0B/llama architecture live | **YES** -- confirmed via `ollama list` + `ollama show` on this machine, today | Not directly re-tested in this audit (budget spent on `orca-nano-v7`); the source documents themselves record a real, directly-executed inference-based evaluation pass (see next columns) | **Directly cross-verified against the real saved JSON reports in this audit** (not just the markdown prose): `redteam_orca-core-combined-v2.json` confirms jailbreak 70.0%/90.0%, bias 12.5%, calibration **100.0%** (6/6 corrected, each response individually legible and substantive per the saved detail records); `novus-combined-v2-full-eval.json` confirms `eval_accuracy=72.8`, `domain_eval=37.5`, `pass_fail_status="NOT_PROMOTABLE"`. **Limitation, stated honestly in the source docs and not contradicted by this audit**: these are internal keyword/LLM-judge/lexical-heuristic evaluations against this project's own golden-prompt and probe sets -- not a credible external/frontier benchmark (no MMLU, no HLE, no independently-administered test) | `EXPERIMENTAL` -- `ModelRegistry.promote()` was attempted and correctly raised `PromotionDenied`; no production entry exists | `NOVUS_FRESH_EVALUATION.md`, `NOVUS_PROMOTION_DECISION.md`, `~/.orca/registry/checkpoints/orca-core-combined-v2.json`, `~/.orca/registry/evaluations/novus-combined-v2-full-eval.json`, `~/.orca/training/redteam/redteam_orca-core-combined-v2.json` -- all four read and cross-checked directly in this audit -- `[ARCHIVED EVIDENCE]` (training history) + `[ORIGINAL OBSERVATION]` (today's architecture re-confirmation + direct JSON cross-check of the specific cited numbers) |
| **Novus (canonical future target / current native programme)** -- no checkpoint | `unsloth/Meta-Llama-3.1-8B-Instruct` is the legacy fine-tune target; the *current native-architecture* NOVUS has no base model at all (would be original ORNEUR architecture, like GENESIS) | **NONE for the native-architecture track** -- NOVUS's native-Transformer work has not begun in this programme at all (unlike GENESIS, which has Sprint 1/2 architecture code) | N/A | N/A | **NO** | N/A | N/A | N/A | N/A | Legacy fine-tune lineage: `EXPERIMENTAL`, `NOT_PROMOTABLE`. Native-architecture lineage: does not yet exist as code | `GENESIS_NOVUS_AETERNUM_STATUS.md` -- `[ARCHIVED EVIDENCE]` + `[ORIGINAL OBSERVATION]` (confirmed via a direct search of `orca/genesis/` and `orca/novus/`-equivalent paths that no native-architecture NOVUS code exists) |
| **Aeternum (legacy, ORCA-era "ultra")** -- no checkpoint, ever | Originally declared `unsloth/Meta-Llama-3.1-70B-Instruct` in Phase 0/1 docs; **the CURRENT `orca/registry/model_spec.py` MODEL_SPECS["aeternum"] entry has since changed this to `base_model=None`, `base_model_status="UNSELECTED_PROVISIONAL"`, `parameter_class="~14B"`** -- a real, deliberate, owner-reviewed correction (commit `fef1be0`, 2026-09-12), not a drift; see the dedicated "AETERNUM target reconciliation" section below | **NONE, at any point in this project's history** | N/A | N/A | **NO** | N/A | N/A | N/A | N/A | No candidate exists at any lifecycle stage (`ModelRegistry.lookup_production("aeternum")` and `lookup_latest_candidate("aeternum")` both return `None`, per the source doc; this audit additionally confirmed **zero Aeternum/ultra checkpoint records exist anywhere in the current local registry directory** by direct search) | `GENESIS_NOVUS_AETERNUM_STATUS.md`; `orca/registry/model_spec.py` (read directly in this audit); `~/.orca/registry/checkpoints/` directory listing -- `[ARCHIVED EVIDENCE]` (Phase 1 status) + `[ORIGINAL OBSERVATION]` (this audit's own live registry search and live `model_spec.py` read, which is what surfaced the target-definition discrepancy -- see the dedicated reconciliation section below) |

## Finding 1 — What ORNEUR has genuinely trained or fine-tuned historically

Real, parameter-updating training genuinely occurred, historically, under
the ORCA-era project name, for two of the three family labels:

- **"Genesis" (legacy `nano` tier)**: multiple real SFT rounds plus a
  safety/honesty DPO round, fine-tuning `Qwen2.5-7B-Instruct` via LoRA on
  Kaggle/Colab GPUs. This produced the `orca-nano` / `orca-nano-v4` /
  `orca-nano-v7` checkpoints.
- **"Novus" (legacy `core` tier)**: a longer, honestly-tracked multi-attempt
  history -- plain SFT, then DPO, then three successive attempts to jointly
  fix a safety/calibration trade-off via combined SFT with varying
  safety-oversample ratios -- fine-tuning `Meta-Llama-3.1-8B-Instruct` via
  LoRA/QLoRA on Kaggle GPUs. This produced `orca-core`, `orca-core-dpo`,
  `orca-core-calibration`, `orca-core-combined`, and
  `orca-core-combined-v2`.
- **"Aeternum" (legacy `ultra` tier)**: **no training of any kind ever
  occurred.** No checkpoint, no dataset, no training run -- this family
  has never had any trained artifact, under either the legacy fine-tune
  lineage or the current native-architecture programme.

None of this historical training was native pretraining from random
initialization. Every trained artifact above is a fine-tune (SFT, DPO, or
both) layered on top of an externally-pretrained third-party base model
(Qwen2.5 or Llama-3.1). This is explicitly the correct and important
distinction: these are real ORNEUR training *events*, producing real
ORNEUR-specific checkpoints, but they are not evidence of ORNEUR having
pretrained a model's weights from scratch.

## Finding 2 — What trained artifacts verifiably exist today

Confirmed present, loadable, and architecturally verified **on this machine,
today (2026-10-16)**, by this audit's own direct commands (not by trusting
the source documents):

- `orca-nano` (= `orca-nano-v4`, identical digest) -- Qwen2.5-7B-class,
  present in `ollama list`.
- `orca-nano-v7` -- Qwen2.5-7B-class, present in `ollama list`; architecture
  independently re-confirmed via `ollama show` (7.6B params, qwen2, embed
  3584); its on-disk blob's SHA-256 independently recomputed from raw bytes
  and confirmed to match the registry's recorded checksum exactly; a real,
  minimal inference call against it succeeded, returning genuine generated
  text.
- `orca-core-combined` -- Llama-3.1-8B-class, present in `ollama list`.
- `orca-core-combined-v2` -- Llama-3.1-8B-class, present in `ollama list`;
  architecture independently re-confirmed via `ollama show` (8.0B params,
  llama, embed 4096); its evaluation numbers independently cross-checked
  against the actual saved JSON report files and found to match exactly.

Confirmed **absent or unrecoverable**, despite having been real, trained
checkpoints historically:

- `orca-core` -- the registry's own record states the merged/quantized GGUF
  recovery attempt stalled and was never completed; this audit confirms it
  is **not** in this machine's current `ollama list`. Its artifact checksum
  is explicitly recorded as `"UNPROVEN_GGUF_RECOVERY_INCOMPLETE"`.
- `orca-core-dpo` -- recorded as `REMOTE` (recovered and hash-verified from
  its Kaggle kernel, but not re-imported locally due to disk constraints);
  this audit confirms it is **not** in this machine's current `ollama list`.
- `orca-core-calibration` -- no current registry checkpoint record or
  Ollama tag could be located for this exact intermediate checkpoint in
  this pass; its existence is attested only by the narrative history and a
  dated redteam report, not by a currently-loadable artifact. **UNVERIFIED**
  whether this specific checkpoint's weights still exist anywhere.

No checkpoint for the *canonical future* Genesis target (Qwen2.5-3B-class)
or for Novus/Aeternum's native-architecture programme exists at all, past or
present -- there is nothing to verify because nothing was ever trained
there.

## Finding 3 — What ORNEUR has never pretrained natively from scratch

**Every single checkpoint in this entire history -- without exception --
is a fine-tune of a third-party, externally pretrained base model.** ORNEUR
has never performed native pretraining from random initialization for
GENESIS, NOVUS, or AETERNUM, under either naming lineage, at any point
documented in this repository's history. The current native-architecture
GENESIS programme (`orca/genesis/`) has built real, tested architecture,
tokenizer, and training-primitive code, but has never executed a single
optimizer step against it. NOVUS and AETERNUM have no native-architecture
code at all yet. This conclusion matches, and is not contradicted by,
everything this session's own prior work (Sprint 1, Sprint 2, Audit
#016/#017) has independently established about the *current* programme --
this audit's contribution is confirming that the *historical* record, once
fully read, tells the same "never pretrained from scratch" story for the
legacy lineage too, just for a different reason (it was always fine-tuning,
never intended to be pretraining).

## AETERNUM target reconciliation — Llama-3.1-70B (historical) vs. ~14B (current, provisional)

This audit was asked to reconcile these without silently selecting a model
on anyone's behalf. On fuller investigation (`git log -p` over
`orca/registry/model_spec.py`, beyond what the six named documents alone
cover), **this is not an unexplained drift -- it is a deliberate, owner-
reviewed correction, fully documented in the commit that made it**:

- **`[ARCHIVED EVIDENCE]`** Phase 0/1 (`MODEL_TRAINING_STATUS.md`,
  `GENESIS_NOVUS_AETERNUM_STATUS.md`, both dated 2026-08-29): Aeternum's
  `ModelSpec.base_model` was `"unsloth/Meta-Llama-3.1-70B-Instruct"`,
  `parameter_class="70B"`.
- **`[ORIGINAL OBSERVATION]`** commit `fef1be0f8595459c0a4d7dae33851609a3505e2b`
  ("Phase 16 closure: correct Aeternum architecture per owner review", dated
  2026-09-12, found by this audit's own `git log` search, not cited in any
  of the six source documents): explicitly states *"Aeternum's base model
  was incorrectly carrying the legacy Llama-3.1-70B plan as if it were
  canonical"* and corrects it to `base_model=None`,
  `base_model_status="UNSELECTED_PROVISIONAL"`,
  `provisional_parameter_hypothesis="~14B"` (a non-binding research
  starting point, not a size lock). The current code's own
  `legacy_note` field states this explicitly at runtime: *"The historical
  Llama-3.1-70B plan is LEGACY/STALE architecture, not the current owner
  architecture, and must not be treated as the canonical Aeternum training
  target."* A new fail-closed accessor, `require_base_model()`, was added
  in the same commit specifically so future training code raises an error
  rather than silently resolving to the stale 70B default. The commit
  message states this was done "per owner review" and backed by 6 new
  TDD-first tests (e.g. `test_aeternum_base_model_is_unselected_not_legacy_70b`,
  `test_require_base_model_fails_closed_for_aeternum`).
- **Reconciliation, stated plainly**: the 70B figure was a real, historical
  planning value that an explicit, reviewed, tested commit later determined
  had been wrongly treated as canonical, and deliberately un-selected it
  (not replaced it with a different final answer). **~14B is documented, in
  the current code's own field name and docstring, as a provisional
  research hypothesis, not a selected target** -- this audit does not treat
  it as one either, and no training-relevant decision should read ~14B as
  "the new canonical size." The two historical Phase 0/1 documents named in
  the originating directive are not wrong about what the code said *at the
  time they were written* (2026-08-29, before the Phase 16 commit on
  2026-09-12) -- they are simply superseded by a later, intentional change
  that this audit is the first document to connect back to them explicitly.

## Finding 4 — Which previous project status statements need correction

- **Any blanket statement of the form "GENESIS/NOVUS/AETERNUM have never
  been trained" is incomplete and must be corrected** to specify *which*
  lineage: the current native-architecture programme has never been
  trained (true, unchanged); the ORCA-era fine-tune lineage for Genesis and
  Novus specifically *has* been trained, repeatedly, with real checkpoints,
  some still present today. This document is that correction. No prior
  document is being rewritten or deleted -- the correction is additive,
  via this new document, exactly as instructed.
- **This session's own prior work** (GENESIS Foundation Sprint 1/Sprint 2,
  Audit #016/#017 remediation reports) never claimed otherwise about the
  *legacy* lineage -- those documents were scoped entirely to the current
  native-architecture programme and did not assert anything about ORCA-era
  training history one way or the other. No retraction of those documents'
  own claims is required; this document adds the missing historical context
  they never covered.
- **The Aeternum base-model target changed** between the Phase 0/1
  documents (`Meta-Llama-3.1-70B-Instruct`) and the current
  `orca/registry/model_spec.py` (`UNSELECTED_PROVISIONAL`, `~14B`
  non-binding hypothesis) -- see the dedicated "AETERNUM target
  reconciliation" section above. This is a real, deliberate, owner-reviewed
  correction (commit `fef1be0`, 2026-09-12), not an unexplained drift; the
  Phase 0/1 documents are simply dated before that correction and were
  accurate when written. A future reader of the Phase 0/1 documents alone,
  without this document, would still be misled about Aeternum's current
  target -- those documents could be improved with a forward pointer to
  this reconciliation, which this read-only audit is not making on its own
  initiative beyond recommending it here.
- **No statement in the six source documents themselves was found to be
  false against the primary evidence this audit could check** (Ollama
  listings, GGUF headers, blob hashes, registry JSON, evaluation JSON) --
  every specific, checkable claim in them held up. The correction needed is
  one of *completeness and framing* at the level of how this project's
  training history is summarized in later, broader statements, not of
  factual accuracy within these six documents themselves.

## Remaining verification gaps (explicitly unresolved by this audit)

- `orca-core-calibration`'s exact checkpoint artifact: not located as a
  currently-loadable or registry-recorded artifact in this pass --
  **UNVERIFIED** whether it still exists anywhere.
- `orca-core`'s and `orca-core-dpo`'s weights: confirmed **not** present on
  this specific machine; their recorded Kaggle recovery sources were not
  re-accessed in this audit (no external account access performed, per the
  directive's own instruction).
- `orca-core`/`orca-core-dpo`/`orca-core-combined`'s artifact checksums were
  not independently re-hashed from raw bytes in this pass (only
  `orca-nano-v7`'s was, as a representative spot-check); they are reported
  here as registry-recorded values, not independently re-verified ones.
- The Aeternum base-model-target change (Phase 1 → current spec) has no
  located decision record explaining it within this audit's scope.
- Whether any Kaggle-hosted kernel or dataset referenced in these documents
  (e.g. `orca-core-combined-sft-kernel-v1`, `orca-core-dpo-merge-export-v1`)
  is still live/accessible on Kaggle itself was not checked -- this audit
  was conducted entirely against local repository and filesystem evidence.
