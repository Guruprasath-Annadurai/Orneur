# Genesis Teacher/Student Strategy

Per spec section 7, this document establishes two categories. **No
model is selected, promoted, or declared a winner here.** This is
planning, not a decision.

## A. Frontier Reference / Teacher Pool

Candidates whose measured (vendor-claimed, not yet ORNEUR-verified)
capability is frontier-grade, regardless of how impractical they are
to operate directly:

- **DeepSeek V4.1-Flash** (763B total, novel Causal Encoder-Decoder
  architecture, native multimodal) — potential reasoning/multimodal
  teacher, architecture is unusual enough that its suitability as a
  conventional distillation teacher is an open question
- **GLM-5.2 / GLM-5.3** (743-753B total) — potential coding/long-
  horizon-agentic teacher; GLM-5.2's MIT license is materially cleaner
  for this purpose than GLM-5.3's custom license
- **Mistral Large 3** (675B total, Apache 2.0) — cleanly licensed,
  general-purpose frontier reference
- **MiniMax M3** (428B total) — potential agentic-coding teacher,
  license status unresolved (see landscape doc) and must be confirmed
  before any real use
- **Qwen3.8-Max** (2.4T total) — largest, but custom-licensed with
  commercial-use thresholds; usable as a benchmark reference more
  readily than as a teacher whose outputs feed a commercial product
- **Kimi K3** (2.8T total) — largest model surfaced, but its revenue-
  threshold-gated license is the most restrictive of any candidate
  researched; usable as an external benchmark reference (e.g. via
  Modal's hosted endpoint, per-token, at owner-approved spend) far more
  readily than as a training-data teacher for a model ORNEUR might
  eventually monetize

Purpose of this pool: benchmark references, synthetic-data generation,
critique/verification, reasoning-trace generation, and — for the MIT/
Apache-licensed members specifically — potential distillation teachers,
pending a real license review before any actual training use.

## B. Deployable Genesis Foundation Candidate Pool

Models with a realistic path to post-training, controlled deployment,
and eventual 10K-user serving, evaluated on evidence rather than
capped at a specific parameter count:

- **Qwen3.8-27B (dense, Apache 2.0)** — by a wide margin the most
  immediately deployable candidate surfaced this phase: single-GPU at
  bf16, permissively licensed, multimodal, from the same lineage as a
  model (Qwen3.8-Max) with credible frontier-tier claims at larger
  scale. The central open question is whether the 27B dense sibling
  inherits meaningful capability from the 2.4T flagship's training
  effort, or whether it is a materially weaker standalone model — this
  requires real evaluation, not assumption.
- **Qwen3-8B / Mistral-Nemo-Instruct-2407 / Phi-4** — per spec section
  19, reclassified as CONTROL / SMALL-BASELINE CANDIDATES. Their prior
  infrastructure work (Phase 21B.4-21B.4.1's adapter, sandbox, CLI, and
  digest-verified suite work) remains fully valid and reusable; they no
  longer define Genesis's frontier target, but remain useful as cheap,
  well-understood reference points for validating the evaluation
  pipeline itself before spending real GPU-hours on a frontier
  candidate.
- **GLM-5.3-Flash (320B total, MIT)** — the smallest MIT-licensed
  member of the GLM line with native multimodality; at 2× 80GB GPUs
  (INT4) it sits between the small Qwen dense model and the true
  frontier giants, worth a closer look as a mid-scale option once
  compute permits.

Open questions common to every candidate in this pool: none have been
evaluated against `genesis-eval-v1` or any ORNEUR-controlled benchmark;
all capability claims above are vendor/press-sourced.

## No assumption that distillation preserves frontier intelligence

Per spec section 9, if a smaller deployable Genesis student is
eventually proposed (e.g. a Qwen3.8-27B-based or similarly-scaled
model), it must have a CREDIBLE route to frontier-quality behavior —
strong teacher selection, real dataset construction, reasoning
distillation, verification, post-training, tool/retrieval integration,
and test-time reasoning support — and that result must later be proven
empirically against ORNEUR's own evaluation suite, not assumed from
the student's parameter count or its teacher's reputation. No training
of any kind was started or planned in detail this phase; Phase 21C
remains locked.

## Training strategy options, per candidate class (research only, spec section 8)

- **True frontier giants (100B+ total)**: full fine-tuning is almost
  certainly infeasible given the same multi-GPU weight-storage
  requirement as inference, likely worse (optimizer states, gradients).
  LoRA/QLoRA against a frozen giant is more plausible but still
  requires the base weights resident somewhere. More realistic: use
  these as teachers ONLY (synthetic data generation, critique,
  verification) rather than attempting to directly post-train them.
- **Qwen3.8-27B-class dense models**: full fine-tuning, LoRA, QLoRA,
  continued pretraining, RL post-training, and preference optimization
  are all realistic at this scale on modest multi-GPU or even
  single-GPU (for LoRA/QLoRA) setups.
- **Teacher/student combination**: the most credible path to
  "frontier-quality-behavior at deployable scale" given the compute
  reality documented in `GENESIS_FRONTIER_COMPUTE_MATRIX.md` — use an
  MIT/Apache-licensed frontier teacher (GLM-5.2, Mistral Large 3, or a
  vendor-hosted endpoint for a more restrictively-licensed one, subject
  to license review) to generate reasoning traces, critiques, or
  synthetic tasks, and post-train a deployable-scale student against
  that signal, then verify empirically.

No training strategy is selected here. This is the research spec
section 8 required before any future owner authorization to actually
train.
