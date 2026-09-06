# Aeternum (Ultra) Training Plan — Kaggle

Honest premise: this is the biggest remaining lift in Orca's model lineup.
Genesis (nano) and Novus (core) each went through distillation → format →
fine-tune → eval → red-team → model card, and each step hit real bugs along
the way. Aeternum starts from zero — no distilled data, no fine-tune, no
adapter. This plan applies every lesson learned from the nano/core runs (and
from the core safety-DPO run done earlier this session) up front, instead of
re-discovering them one failed Kaggle run at a time.

## 0. The honest constraint that shapes everything below

Kaggle's free tier gives ~30 GPU-hours/week, and the actual accelerators
available are a **T4** (16GB VRAM) or a **P100** (16GB VRAM, and as just
proven on a live run, incompatible with current PyTorch/Unsloth releases —
always force `machine_shape: "NvidiaTeslaT4"` in kernel-metadata.json, never
leave it to Kaggle's default).

A genuinely "flagship," 70B-class model does not fit on this hardware, even
in 4-bit QLoRA (~35GB+ needed just for weights). Two honest paths:

- **Recommended for now**: pick a **13-14B class base model**
  (`Qwen2.5-14B-Instruct` is the concrete candidate — fits 4-bit QLoRA on a
  16GB T4 with room for LoRA adapters and activations). This is genuinely
  bigger than Genesis (7B) and Novus (8B), which is what "flagship" needs to
  mean here — not a specific parameter count, but the largest model this
  free hardware can actually train well.
- **If a true 70B-class model is wanted**: that needs paid compute (Kaggle's
  paid tiers, Lambda, RunPod, or Colab Pro+ with an A100). That's a real
  budget decision for you to make, not something to quietly assume.

This plan proceeds on the recommended path (14B class) unless told otherwise.

## 1. Lessons learned, applied from the start (not re-discovered)

Every one of these was a real failure on a live run this session, for nano,
core, or core's DPO pass. Baking them into the Aeternum notebooks from cell
one avoids paying for the same mistake a fourth time:

- **Pin `transformers<5`** in every install cell. Transformers 5.x's internal
  weight-conversion refactor breaks `save_pretrained_merged` /
  `save_pretrained_gguf` for Llama/Qwen architectures with a
  `NotImplementedError` deep in `revert_weight_conversion`.
- **Force `"machine_shape": "NvidiaTeslaT4"`** in kernel-metadata.json.
  Leaving GPU selection to default risked a P100, whose sm_60 compute
  capability current PyTorch wheels no longer ship kernels for.
- **Strip `model.config.quantization_config` before merge/GGUF export.**
  After merging 4-bit → 16-bit, Unsloth leaves a stale `quantization_config`
  tag that llama.cpp's converter refuses with `NotImplementedError: Quant
  method is not yet supported: 'bitsandbytes'`, even though the merged
  weights are genuinely fp16 by that point. Delete the attribute (and
  re-check the written `config.json`) right before calling
  `save_pretrained_gguf`.
- **Save the adapter to `/kaggle/working/` immediately after training**,
  before attempting merge/export — the adapter is small, fast to save, and
  is the actual valuable artifact if the export step breaks (which it did,
  three times, on the core DPO run — training itself succeeded every time).
- **Do heavy merge/export work in `/tmp`, not `/kaggle/working`** —
  `/kaggle/working` has a hard 19.5GB quota that a merged 16-bit weights file
  plus an intermediate GGUF will exceed.
- **No mid-training checkpointing** (`save_strategy="no"`) — a known Kaggle-side
  pickling bug hits that path; the post-training adapter save is the safety net.
- **Attach a prior kernel's own output as a `kernel_source`** instead of
  manually downloading/re-uploading adapter files between notebooks — Kaggle
  exposes another of your own committed notebooks' `/kaggle/working/` output
  directly under `/kaggle/input/` when referenced this way.

## 2. Phases

### Phase A — Distillation data generation (no GPU needed)

Reuse `orca/train/distill.py`'s existing teacher-call infrastructure
(`_teacher_generate`, Nvidia Nemotron backend already configured via
`NVIDIA_API_KEY`) rather than writing new plumbing. New work:

- Define an Aeternum-specific prompt/domain set emphasizing **cross-domain
  synthesis** — this is Aeternum's actual differentiator per
  `orca/train/aeternum_eval.py` (already built, 18 prompts across 6
  domain-pairs) and per `orca/personas.py`'s Aeternum framing. The
  distillation prompts should be broader and more cross-domain than
  Genesis/Novus's single-domain sets, not just "harder" versions of the same
  questions.
- Real cost note: teacher calls cost real money (Nvidia API). Budget for a
  few hundred prompts, not thousands, for a first pass — same scale as
  nano/core's initial distillation runs.
- Output: raw distilled JSONL, same format nano/core used
  (`orca/data/seeds.py`-style conversation records).

### Phase B — Curate + format training data (no GPU needed)

- Filter for quality (reuse whatever filtering nano/core's pipeline already
  does — check `orca/train/` for the existing filter script pattern before
  writing a new one).
- Format into the llama3/chat-template JSONL the SFT notebook expects,
  matching the exact pattern `orca_nano_llama3_train_v3_safety.jsonl` and
  core's equivalent used.

### Phase C — Baseline eval (no GPU needed)

- Run `orca/train/aeternum_eval.py` against the **base, unfine-tuned**
  Qwen2.5-14B-Instruct (via Ollama, pulled locally or via a lightweight
  Kaggle CPU run) *before* any fine-tuning — nano did this
  ("Nano pre-fine-tune baseline eval," already completed) and it's the only
  way to honestly claim fine-tuning improved anything, rather than asserting
  it without a real before/after comparison.

### Phase D — SFT fine-tune notebook (GPU, the first real Kaggle spend)

- New notebook, structured like `orca_core_finetune_kaggle_v2.ipynb` but
  with base_model = `unsloth/Qwen2.5-14B-Instruct`, all six lessons from
  Section 1 applied from the first draft.
- Expect this to be the most expensive single step — a 14B model takes
  longer per step than nano's 7B or core's 8B. Budget accordingly against
  the weekly quota; this alone could be several hours.
- Real expectation-setting: the first SFT run may not be the last. Nano
  needed multiple versions (v1 through v7) before landing on a good
  checkpoint. Don't budget the whole week's quota on the assumption v1 works.

### Phase E — Post-fine-tune eval + red-team (no GPU needed — runs against Ollama)

- `orca train eval --ollama orca-ultra --ci` (generic accuracy)
- `orca train aeternum_eval --model orca-ultra` (the cross-domain synthesis
  set — the eval that actually matters for Aeternum's specific claim)
- `orca train redteam --model orca-ultra --ci` with `--bias-trials 3` (matching
  the trials-averaging discipline already applied to nano/core, given how much
  single-trial noise this session found in exactly this kind of measurement)

### Phase F — Model card + persona-claim gate (no GPU needed)

- `orca train card ultra` — this automatically applies
  `PERSONA_CLAIM_THRESHOLDS["ultra"]` (80% accuracy, 95% jailbreak block
  rate — the highest bar of the three tiers, appropriately, given Aeternum's
  "flagship" self-description). Expect this **not** to pass on the first
  attempt — nano and core both needed real iteration to clear their bars,
  and ultra's bar is stricter than either.

### Phase G — Safety DPO pass (GPU, small/cheap — same pattern as core's)

- Once a baseline Aeternum checkpoint exists and has a redteam report,
  regenerate `generate_probe_grounded_safety_pairs(weak_model="orca-ultra",
  trials=3)` and run the same small, cheap DPO continuation used for core —
  this step alone costs almost no GPU quota, per what was just proven on the
  core run.

## 3. Honest sequencing recommendation

Do **not** attempt Phases D through G in one sitting or one week. Realistic
pacing against a 30hr/week quota:

- **Week 1**: Phases A-C (no GPU cost at all — data generation, curation,
  baseline eval). This can start immediately regardless of GPU quota state.
- **Week 2**: Phase D (the SFT fine-tune) — budget most of the week's quota
  here, expect 1-3 failed/iterated attempts based on nano/core's own history.
- **Week 3**: Phases E-G once a working checkpoint exists.

## 4. What "done" honestly looks like

A model card for `orca-ultra` exists, `persona_claim_approved` may well be
`False` on the first pass (that's fine — it was for core too, until its
DPO pass), and the landing page's "Aeternum: in development" framing gets
updated to reflect real, current, verifiable numbers — not flipped to
"available" just because a checkpoint exists.
