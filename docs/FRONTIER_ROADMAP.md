<!--
This document exists to answer one direct question honestly: what would it
ACTUALLY take for Genesis/Novus/Aeternum to become legitimately frontier-class
models, not what training run makes that claim SOUND true. Every number in
here is a real, grounded estimate from public information about how GPT-4,
Llama 3.1 405B, DeepSeek-V3, Gemini, and Claude were actually built — not
guesses tuned to make the plan look achievable. Where a number is disputed
or uncertain in public reporting, that's stated explicitly.
-->

# Orca Frontier Roadmap — What It Actually Takes

## 0. What "frontier-class" means, precisely

A frontier-class model (GPT-4/4o/5, Claude Opus, Gemini Ultra/2.5 Pro,
Llama 3.1 405B, DeepSeek-V3/R1) is not "a good chatbot." It's a specific,
measurable bar:

- **Scale**: 100B-2T+ parameters (dense or mixture-of-experts)
- **Pretraining data**: 10-15+ trillion tokens, deduplicated and
  quality-filtered — itself a multi-year engineering effort, not a dataset
  you download
- **Benchmark bar**: >85-90% on hard reasoning/knowledge benchmarks (GPQA,
  MMLU-Pro, competition math, real-world coding agents), genuinely novel
  problem-solving, long-context reliability (100K-1M+ tokens), often
  multimodal (vision, sometimes audio/video)
- **Post-training**: extensive RLHF/RLAIF across hundreds of thousands to
  millions of human/AI preference judgments, dedicated red-team and safety
  evaluation teams, iterative alignment research — not a few hundred DPO
  pairs

## 1. What it actually costs — real numbers, not estimates tuned to be encouraging

| Resource | What frontier labs actually spend/use |
|---|---|
| Compute (single training run) | Llama 3.1 405B: ~16,000 H100 GPUs for ~54 days. At market cloud rates that's **$60-100M+ for one run**; owning that hardware is **$400-600M+ in capex**. |
| Compute (disputed low end) | DeepSeek-V3's widely-cited "~$5.5M" figure covers only the final training run's GPU-hours — it explicitly excludes data curation, failed experiments, research salaries, and infrastructure buildout. Even DeepSeek's own broader R&D spend is credibly estimated far higher. Treat "$5.5M" as a real but incomplete number, not "the cost of a frontier model." |
| Data | 10-15+ trillion tokens of deduplicated, filtered text/code/math, often supplemented by licensed data (books, news archives) and large synthetic-data pipelines. Building the filtering/dedup/quality-classification infrastructure alone is a multi-year effort for a dedicated data team. |
| Team | 50-300+ researchers and engineers at OpenAI/Anthropic/Google DeepMind/Meta AI, with years of accumulated distributed-training tooling (Megatron, DeepSpeed, JAX/TPU pods, custom schedulers) that took those orgs years to build. |
| Time | 6-18+ months per generation, for teams that already have all of the above in place. |

**Orca today**: a single 7B open-weight base model (Qwen2.5-7B /
Llama-3.1-8B), QLoRA fine-tuning (rank 16-64) on ~2,000-2,700 examples,
free-tier single-GPU Kaggle sessions (one T4, hours not months), one
operator. The gap to frontier is roughly **4-6 orders of magnitude in
compute, 6-7 orders of magnitude in training data, and zero dedicated
research team.** No amount of additional QLoRA fine-tuning runs on free-tier
GPUs closes that gap — it's a difference in kind, not a shortfall that more
iteration fixes.

## 2. A real, phased plan — what each phase honestly requires and honestly delivers

This is the actual path a well-resourced, growing AI lab follows. Skipping
phases doesn't work; each one is a prerequisite for the next, both
technically (data pipelines, training infra, eval harnesses built in one
phase are reused in the next) and financially (each phase's results are
what justifies raising the capital for the next one).

### Phase 0 — where Orca is today
QLoRA fine-tuning of small open base models on free/cheap compute.
**Honest ceiling**: a competent, narrow, efficient small-model assistant.
Not frontier, and claiming otherwise is false. Legitimate positioning:
efficiency, privacy (local/on-prem deployable), cost, and transparency —
real, defensible differentiators that don't require frontier-scale
capability.

### Phase 1 — full fine-tuning + continued pretraining on a strong mid-size open base
**What it requires:**
- A multi-GPU cluster: 8-64 A100/H100-class GPUs, rented (AWS/GCP/Lambda/
  CoreWeave/RunPod) — realistically **$50K-$500K** for a serious continued-
  pretraining + full-parameter fine-tuning run on a 70B-class model
  (Llama 3.1 70B, Qwen2.5-72B, Mixtral 8x22B, DeepSeek-V2-Lite as base)
- A much larger curated dataset: hundreds of billions of tokens for
  continued pretraining, millions of SFT examples (not thousands), hundreds
  of thousands of preference pairs for real RLHF/DPO
- RLHF/RLAIF infrastructure: using a strong external model (GPT-4-class,
  via API, respecting its ToS) as a judge/reward signal is a legitimate,
  widely-used technique at this budget tier — full from-scratch human RLHF
  panels are a Phase 2+ investment
- A small dedicated team, not one operator: at minimum a data engineer, a
  training/infra engineer, and someone doing evaluation/safety full-time
- 2-4 months of sustained work with that team and budget in place

**What this honestly delivers**: a genuinely strong, real "near-frontier
open-model tier" result — competitive with Llama 3.1 70B-Instruct or
Qwen2.5-72B-Instruct's own published benchmarks. This is a credible,
defensible claim ("built on and improves a leading open 70B-class model")
— not "frontier-class," but a real step up from Phase 0, and the first
phase where "beats its own baseline" becomes a much more solvable problem
(bigger data + bigger model = the regression pattern nano hit at 7B/QLoRA
becomes far less likely to recur).

**Novus (core)'s realistic target**: this phase, if real investment is
made. This is achievable without claiming frontier status.

### Phase 2 — scale to the largest practical open dense/MoE models (100-400B+) with heavy continued pretraining or partial pretraining-from-scratch
**What it requires:**
- **$5-50M+ in compute** — a dedicated cluster (hundreds to low-thousands
  of H100-class GPUs), via cloud contract or owned hardware
- A dedicated research team: **10-50 people** — pretraining researchers,
  data engineers building licensing/crawling/synthetic-data pipelines at
  10+ trillion token scale, RLHF/alignment researchers, distributed-systems
  engineers (FSDP/Megatron/DeepSpeed at multi-node scale), a real
  evaluation team, a real safety/red-team function
- Real funding: this is a **venture capital Series A/B territory decision**
  ($20-100M+) or a hyperscaler compute-credit partnership (a common path:
  trade equity/commitment for AWS/GCP/Azure/CoreWeave compute credits)
- **12-24 months minimum**, even with an experienced team already in place

**What this honestly delivers**: a model that can legitimately compete on
specific published benchmarks with mid-tier frontier models, and a real
shot at being called "frontier-adjacent" if the team executes well.

**Aeternum (ultra)'s realistic target IF this phase is funded.** Today,
Aeternum is a name and an aspiration, not a model — there is no shortcut
from here to there through more free-tier fine-tuning.

### Phase 3 — true frontier parity or leadership
**What it requires:** $100M-$1B+ compute budgets, proprietary large-scale
data acquisition deals, multi-year sustained R&D, genuine architecture/
algorithmic research contributions (not just scaling up existing recipes),
a team of hundreds, and realistically several training generations to
iterate toward parity. This is the OpenAI/Anthropic/Google DeepMind/Meta AI
tier. It is not reachable without either a massive capital raise or being
acquired by/deeply partnered with an organization that already operates at
this scale.

## 3. Forward-looking techniques worth tracking (informed speculation, not certainty)

These lower the bar somewhat over time, but don't eliminate the gap above —
worth researching as Orca scales through the phases, not treated as a
shortcut around them:

- **Data quality over raw quantity**: Microsoft's Phi family showed that
  very carefully curated "textbook-quality" training data lets smaller
  models punch above their parameter count on some benchmarks. This is a
  real, credible way to make Phase 1's budget go further — but it requires
  building real data-quality infrastructure, not just more examples.
- **RL-from-verifiable-rewards for reasoning** (the technique behind
  DeepSeek-R1 and OpenAI's o-series): training a model to reason via
  reinforcement learning against automatically-checkable rewards (math,
  code execution results) rather than only human preference data. This is
  a genuinely different, promising post-training paradigm — but it still
  requires a capable base model and real RL infrastructure to execute.
- **Distillation from frontier teachers via API**: legally generating large
  synthetic instruction/reasoning datasets from GPT-4/Claude-class models
  (respecting their terms of service) is exactly what Orca's own
  distillation pipeline already does at small scale — scaling this
  approach up (more teacher calls, broader domain coverage, quality
  filtering of the synthetic data) is a real lever available at every
  budget tier, including Phase 1.
- **The open-weight frontier is closing the absolute gap**: Llama, Qwen,
  DeepSeek, and Mistral's best open releases are now genuinely
  competitive with closed frontier models on many benchmarks. This means
  "continued pretraining + heavy post-training on an already-strong open
  base" (Phase 1/2 above) is a more viable path to near-frontier capability
  today than it was two years ago — but "frontier" is also a moving target
  that keeps receding as OpenAI/Google/Anthropic ship new generations, so
  this narrows the gap, it doesn't close it for free.

## 4. The honest bottom line and recommendation

Getting from here to frontier-class is not primarily an engineering
problem that more training runs solve — **it's a capital and team problem
first, and an engineering problem second.** The responsible plan, in order:

1. **Execute Phase 0 excellently** — make Genesis the best it can honestly
   be at its actual scale, and market it on real differentiators
   (efficiency, privacy, transparency, cost) rather than raw capability it
   doesn't have. This is achievable now, with the resources that exist now.
2. **If there's genuine ambition for Novus/Aeternum to be real
   frontier-adjacent claims**, the first concrete next step isn't a new
   training script — it's securing the Phase 1 budget (even the low end,
   ~$50K, is beyond free-tier Kaggle) and, ideally, at least one additional
   person to share the workload. That conversation (fundraising, a compute
   grant, a cloud partnership) has to happen before the engineering plan
   for Phase 1 can start for real.
3. **Don't claim a phase before funding and executing it.** Every credible
   AI company's public model cards and technical reports are specific
   about what data/compute/technique produced their results — that
   specificity is what makes the claim credible. The same discipline
   applied to Orca's own model cards (already true today — see
   `docs/MODEL_CARDS.md`) is the right long-term habit to keep, through
   every phase above.
