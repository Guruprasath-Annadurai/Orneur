# Wave 1 — Native Intelligence Reality Audit and Capability Baseline

Status date: 2026-10-15. Starting main: `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a`
(re-verified by direct fetch, matches directive). Read-only investigation —
no training, no GPU, no spend, no model changes.

## Mission 1 — Starting state

- Main re-verified: `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a`, matches directive exactly.
- Wave 0 evidence durability gap found and fixed: the Wave 0 report had been pushed to a branch but **no PR was opened** — not durable/reviewable via GitHub as required. Fixed: [PR #52](https://github.com/Guruprasath-Annadurai/Orneur/pull/52).
- RISK-01 (ChromaDB cross-process anomaly) and RISK-02 (multi-tenant agent tool execution) preserved unchanged — not touched by this investigation.
- No other agent's active branch was modified; this work is on its own new branch.

## Mission 2 — Native-model engineering inventory

Classified by direct inspection of real code, not documentation. File paths and line counts are exact.

| Subsystem | Classification | Evidence |
|---|---|---|
| Model architecture (from-scratch, original weights) | **ABSENT** | No `nn.Module` transformer definition, no attention/MLP block implementation anywhere in `orca/`. Confirmed by direct grep across the whole tree — zero matches. |
| Tokenization | **ABSENT** | No tokenizer training or implementation code found anywhere (`find orca -iname "*tokeniz*"` — zero results). |
| Fine-tuning pipeline (QLoRA, on an external base model) | **IMPLEMENTED_UNQUALIFIED** | `orca/train/finetune.py` (344 lines) — a real QLoRA pipeline via Unsloth/transformers/peft/bitsandbytes, loading an **existing pretrained base model** (`FastLanguageModel.from_pretrained`), not training a novel architecture. Never independently run against a real GPU as part of this audit trail. |
| Distillation data generation | **IMPLEMENTED_UNQUALIFIED** | `orca/train/distill.py` (303 lines) — real pipeline generating synthetic training data from an external teacher model (local Ollama or Nvidia-hosted Nemotron). Its own docstring states plainly: "This module builds the DATA GENERATION pipeline. It does not, by itself, make the model smarter." |
| Training objectives / loss functions | **VERIFIED_IMPLEMENTED (as isolated math)** | `orca/train/losses.py` — real, numerically-tested token-weighted loss code (`tests/test_train_losses.py`, genuine tensor assertions against torch's own reference `cross_entropy`). Its own docstring: "What this module's own correctness CANNOT establish: whether weighting these specific spans actually improves the target behavior... requires an actual training run on GPU." Correct as isolated math; not evidence of a trained model. |
| Optimizers / LR schedules | **SPECIFICATION_ONLY / IMPLEMENTED_UNQUALIFIED** | Present inside `finetune.py`'s QLoRA config surface (standard HF/Unsloth training-args passthrough); no original scheduler research or novel optimizer work found. |
| Distributed-training infrastructure | **ABSENT** | `torch.distributed`/`DistributedDataParallel`/FSDP/deepspeed grepped across the whole tree — only appears inside `orca/train/dryrun/sentinel.py` and `dryrun/inventory.py`, i.e. as *detection/guard* code for the training-authorization sentinel, not as real multi-GPU training infrastructure. |
| Numerical stability / precision | **IMPLEMENTED_UNQUALIFIED** | Mixed-precision/quantization config exists via Unsloth's 4-bit loading path in `finetune.py`; no original numerical-stability research beyond what the dependency provides. |
| Checkpoint saving and recovery | **IMPLEMENTED_UNQUALIFIED (infrastructure), ABSENT (real checkpoints)** | `orca/registry/provenance.py` (real functions: `create_run_snapshot`, `verify_run_snapshot`, `start_training_run`, `complete_training_run`, `fail_training_run`, deterministic run IDs, dataset-binding verification, source-lineage verification). This is genuine, tested governance/audit-trail infrastructure around training runs. No `.safetensors`/`.ckpt`/`pytorch_model.bin` artifact exists anywhere in the repository (confirmed by direct search) — no real checkpoint has ever been produced. |
| Evaluation and benchmark infrastructure | **IMPLEMENTED_UNQUALIFIED, substantial and honestly self-reported** | `orca/eval/genesis_suite.py` (690 lines): own docstring states 90 of a ~220-task target are built (~41%), explicitly refusing to pad with low-quality filler tasks (project's own stated discipline). `orca/eval/genesis_harness.py` (309 lines): a real CPU-side scoring/aggregation harness that explicitly **makes no inference itself** — "the generation backend is an injected callable and the default raises `NoInferenceBackend`." This means the evaluation plumbing exists and is tested, but has never been run end-to-end against a real candidate model as part of this audit trail. |
| Model artifact custody | **SPECIFICATION_ONLY** | Custody/signing concepts referenced in `docs/orneur/status/HARDWARE_AND_CUSTODY_OPTIONS.md` and the acceptance register; no real artifact exists to custody yet (see checkpoints, above). |
| Inference loading and serving | **VERIFIED_IMPLEMENTED (for external/provider models), ABSENT (for a native model)** | `orca/gateway/` (gateway.py, wiring.py, contracts.py — extensively tested this session, PR #40/#48/#49) correctly routes, streams, and serves requests to **external provider models**. There is no native ORNEUR checkpoint for it to serve; `AutoModelForCausalLM.from_pretrained`/`FastLanguageModel.from_pretrained` calls in `orca/train/eval.py` and `cloud.py` load third-party base models for evaluation/fine-tuning context, not a native artifact. |
| Training authorization and acceptance registers | **VERIFIED_IMPLEMENTED** | `orca/train/authorization.py` (678 lines), the training-authorization gate (extensively tested across this entire program, PR #24 and its descendants), and the acceptance engine (`scripts/acceptance/acceptance_engine.py`, `docs/orneur/acceptance/`). Acceptance ledger confirmed, directly, to contain **0 entries** right now (`acceptance_ledger.json` is an empty list) — the 0/95 state is real, not asserted from memory. |

**Summary**: ORNEUR has extensive, well-tested, honestly-documented *training-adjacent infrastructure* — authorization gates, dry-run rehearsal, provenance/custody plumbing, a growing evaluation suite, loss-function research, and a real QLoRA fine-tuning pipeline for EXTERNAL base models. It has **no native model architecture, no tokenizer, no distributed-training capability, and no checkpoint of any kind** — original native pretraining (GENESIS's actual mission) has not been started in any technical sense yet, only prepared for.

## Mission 3 — Twelve-capability reality matrix

| Capability | Status | Source of the capability today |
|---|---|---|
| C1 Language intelligence | Functional (product), **not ORNEUR-native** | External provider model, routed via `ModelGateway` |
| C2 Reasoning intelligence | Functional (product), **not ORNEUR-native** | External provider model |
| C3 Knowledge intelligence | Partial, **ORNEUR-built infrastructure + external model** | Retrieval/citation plumbing (`orca/docs/`) is original; the reasoning over retrieved content is the external model's |
| C4 Multimodal intelligence | **Not implemented** / provider-dependent | No ORNEUR-native vision/audio pipeline found this audit; provider-dependent if/when wired |
| C5 Creative intelligence | Functional (product), **not ORNEUR-native** | External provider model |
| C6 Computational intelligence | Functional (product), **not ORNEUR-native**, tool execution is native | Code/math generation: external model. Tool execution/sandboxing: original (`orca/eval/genesis_v2/sandbox.py`, container hardening this session's own PR #48/#49 work) |
| C7 Planning intelligence | **Not implemented as a dedicated capability** | No planner/task-decomposition subsystem found independent of prompting the external model directly |
| C8 Agentic intelligence | **Partial, original infrastructure** | Tool authorization (`test_g020_agent_tool_authority.py`, extensively tested) is real and ORNEUR-native; no multi-agent orchestrator exists yet (Part V of the master directive, not started) |
| C9 Adaptive intelligence | **Partial, original infrastructure** | Model routing/gateway tiering (`orca/gateway/wiring.py`) is real and ORNEUR-native; no learned/measured personalization found |
| C10 Memory and continuity intelligence | **Substantial, original, ORNEUR-native** | This session's own extensively-tested work: `orca/brain/memory.py`'s deletion assurance, durable ledgers, tenant isolation, privacy-safe retrieval. This is the strongest, most independently-verified native capability found in this audit. |
| C11 Verification intelligence | **Partial, original infrastructure** | Training/acceptance verification plumbing is real and extensively tested; no general contradiction-detection/uncertainty-calibration subsystem for ordinary chat found |
| C12 Improvement intelligence | **Specification/early infrastructure only** | Dry-run training-prep resilience and evaluation suites exist; no evaluated-experiment feedback loop that actually changes a shipped model exists (correctly, since no native model exists to improve) |

**Honest summary**: ORNEUR's user-facing language/reasoning/creative/computational capability is **entirely supplied by external provider models today**, correctly routed through original ORNEUR infrastructure (gateway, auth, memory, tool authorization). The capabilities that ARE genuinely ORNEUR-native and independently verified are infrastructure capabilities (C8 tool authorization, C9 routing, C10 memory — this session's own work), not the intelligence itself. No capability here should be credited to a native ORNEUR model, because none exists yet.

## Mission 4 — GENESIS pretraining gap assessment

Acceptance register state, verified directly (not from memory): `docs/orneur/acceptance/acceptance_ledger.json` contains **0 entries**. `R65` (the pre-training rule-mapping requirement) is explicitly `NOT_VERIFIABLE` per the register's own text: *"No pre-training percentage is published. R65 is NOT_VERIFIABLE and stands for an unmapped set... When a founder-approved source of the 65 rules exists, R65 is replaced by one child row per rule... Until then the child rules are absent on purpose."* `G1` and `AUTH-1` are also `NOT_VERIFIABLE`. `FINAL-1` (94 pre-training IDs excluding itself) is `NOT_STARTED`, blocked on `R65`/`G1`/`AUTH-1`. `FINAL-2` requires `FINAL-1`; `EXEC-1` requires `FINAL-2` — the whole chain is gated behind R65's unresolved rule-source.

### Dependency-ordered prerequisite matrix

| Category | Status | What's missing |
|---|---|---|
| **Scientific prerequisites** | SPECIFICATION_ONLY | No architecture decision made (Mission 5 below proposes one); no tokenizer design finalized; no from-scratch training-loop implementation exists to validate against. |
| **Dataset/legal prerequisites** | IMPLEMENTED_UNQUALIFIED | Real provenance/usage-rights/teacher-terms gates exist and are tested (`orca/dataquality/`, this session's own PR #42 review). No actual pretraining-scale corpus has been assembled or legally cleared end-to-end. |
| **Training-engine prerequisites** | ABSENT (for pretraining) | Fine-tuning engine exists (Mission 2); no from-scratch pretraining loop, no distributed-training capability. |
| **Evaluation prerequisites** | IMPLEMENTED_UNQUALIFIED | 90/~220 Genesis eval tasks built and honestly tracked; harness cannot run without a real model plugged in (by design — `NoInferenceBackend` default). |
| **Security and governance prerequisites** | VERIFIED_IMPLEMENTED | Training-authorization gate, acceptance engine, dry-run sentinel — all extensively tested across this program. This is the most mature prerequisite category. |
| **Compute and budget prerequisites** | SPECIFICATION_ONLY | `docs/orneur/status/HARDWARE_AND_CUSTODY_OPTIONS.md` discusses options; no committed budget, no provisioned hardware (explicitly out of scope for this and every prior directive in this program). |

**The explicit, current blocker**: `R65`'s rule source does not exist. Per the register's own fail-closed design, this blocks `FINAL-1` → `FINAL-2` → `EXEC-1`, i.e. formal training authorization cannot advance at all until a founder-approved source for the 65 rules is provided. This is not an engineering gap I can close — it requires a founder decision/input, named precisely rather than left vague.

## Mission 5 — GENESIS V1 technical baseline proposal (research recommendation only, not implemented)

Given the complete absence of any native architecture or tokenizer (Mission 2), and consistent with the directive's own preference for a reproducible baseline over premature complexity:

- **Architecture**: dense decoder-only Transformer (standard pre-norm, RoPE positional embeddings, SwiGLU MLP, grouped-query attention) — avoid MoE, novel attention variants, or multimodal fusion for V1. This is the most-replicated, least-risky architecture family (LLaMA/Mistral-style), chosen specifically to minimize novel-failure-mode risk for a first from-scratch run, not for architectural novelty.
- **Scale**: propose starting at **1–3B parameters** for the first fully-reproduced checkpoint, not a frontier scale. Rationale: validates the entire pipeline (tokenizer, data loader, training loop, checkpoint/eval harness, the existing authorization gate) end-to-end at a cost and time scale survivable even if the first several attempts fail, before committing to a larger run.
- **Tokenizer**: a from-scratch SentencePiece/BPE tokenizer (32k-64k vocabulary), trained on a corpus with **explicit, measured Indian-language representation** (not an afterthought appended to an English-majority corpus) — vocabulary coverage and fertility should be measured per-language before training, not assumed.
- **Context length**: propose starting at 4k-8k tokens for V1 (not a long-context claim), with context extension treated as a separate, later, independently-evaluated research question.
- **Data mixture**: cannot be specified further without the dataset/legal-prerequisite work (Mission 4) actually completing; proposing a mixture before provenance/usage-rights clearance is itself a gap this baseline should not paper over.
- **Checkpoint strategy**: should reuse the existing, already-tested provenance/custody infrastructure (`orca/registry/provenance.py`) from day one of any real run, not build parallel plumbing.
- **Compute and cost assumptions (quantified, not implemented)**: a 1-3B dense model trained on roughly 300-600B tokens (a widely-used, literature-grounded token-to-parameter ratio for this scale, not an ORNEUR-specific claim) on a single 8xH100 node would plausibly take on the order of 1-3 weeks of wall-clock compute at typical achievable throughput for this architecture family — this is an order-of-magnitude planning estimate for the founder's own budget decision, not a committed number, and explicitly **not an authorization to provision or spend**.

This is a proposal for founder/scientific review, not a committed plan, and does not itself advance any acceptance-register count.

## Mandatory readiness assessment

| Area | Readiness |
|---|---|
| Platform foundation | STRONG_ENGINEERING_BETA_CANDIDATE-equivalent for the *platform* (auth, memory, gateway, tool authorization — extensively tested this program) |
| Native model architecture | **NOT_VERIFIED** (absent) |
| Training engine | **NOT_VERIFIED** for pretraining (absent); IMPLEMENTED_UNQUALIFIED for fine-tuning/distillation |
| Dataset readiness | **NOT_VERIFIED** at pretraining scale; provenance/legal gates exist and are tested at the tooling level |
| Evaluation integrity | IMPLEMENTED_UNQUALIFIED — real, honestly-tracked (90/~220 tasks), never run end-to-end against a candidate model |
| Compute readiness | **NOT_VERIFIED** (no hardware provisioned, by design) |
| Formal training authorization | **NOT_VERIFIED / blocked** — acceptance ledger 0 entries, R65 unresolved, explicit founder-input dependency named above |

No category here is scored 9.5/10 or `GOD_MODE_VERIFIED`-eligible; several are explicitly `NOT_VERIFIED` because the underlying work does not exist yet, not because it was overlooked.

## Final verdict

**`WAVE_1_READY_FOR_INDEPENDENT_AUDIT`**

This is a read-only reality audit: no training, no GPU provisioning, no spend, no acceptance-count advancement, no protected-dataset modification occurred. The one actionable, named gap this audit surfaces that isn't purely an engineering task: `R65`'s rule source requires a founder-approved input before formal training-authorization can advance at all — everything else in this document is either already real and tested (platform/governance infrastructure) or a proposal for review (Mission 5), not an implementation claim.
