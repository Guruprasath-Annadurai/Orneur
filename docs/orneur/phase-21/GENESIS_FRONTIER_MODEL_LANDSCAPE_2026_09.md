# Genesis Frontier Model Landscape — September 2026

Research conducted live this phase (2026-09-18/19) via web search against
primary/near-primary sources (vendor announcements, official docs,
Hugging Face repos) and Modal's own live, authenticated rate card
(`modal billing rates`), which itself surfaced two models (Qwen3.8,
GLM-5.3) not caught by the initial search pass — a concrete reminder
that even "current" research needs cross-checking against more than
one source. **None of this is independently benchmarked by ORNEUR.**
Every "Independent evidence" field below is explicitly marked as
vendor/press-aggregated, not ORNEUR-verified, per spec section 5's
requirement to distinguish the two.

**Phase 21B.4.8.1 correction pass**: an independent audit of the
original (Phase 21B.4.8) sweep found it missed relevant primary
sources (Qwen3.8-Flash-Next, Mistral Small 4) and mischaracterized two
license situations. Those corrections are folded into the relevant
entries below rather than kept as a separate errata section, with each
correction flagged inline.

## Candidates investigated

### DeepSeek V4.1-Flash
- Organization: DeepSeek
- Release date: 2026-09-10
- Exact repository: `deepseek-ai/DeepSeek-V4-Flash` (Hugging Face)
- Current immutable revision: NOT RESOLVED this phase (no HF API call made — see note at end)
- License: MIT
- Commercial-use posture: permissive (MIT)
- Total parameters: ~763B (552B backbone + 196B "Engram" conditional-memory parameters, per vendor description)
- Active parameters: 8B (input path) / 16B (output path) — a novel Causal Encoder-Decoder architecture, not a conventional single-active-parameter-count MoE
- Architecture: Causal Encoder-Decoder, new to this DeepSeek generation
- Context: up to 1M tokens (vendor claim)
- Multimodal: yes — native image+text understanding
- Reasoning mode: single reasoning-effort dial (replaces prior discrete "think" modes)
- Tool use / Coding / Agentic: not independently assessed this phase
- Native inference formats: not confirmed this phase (presumed bf16/fp8 given MoE scale)
- Quantized official checkpoints: not confirmed this phase
- Fine-tuning / distillation feasibility: not assessed — architecture is novel (Causal Encoder-Decoder), so standard MoE fine-tuning tooling may not transfer directly; flagged as an open question, not assumed either way
- Estimated inference hardware: see Compute Matrix doc — ~763B total weight storage dominates regardless of 8-16B activation
- Independent evidence: NONE gathered this phase — vendor description only

### GLM-5.2 / GLM-5.3 / GLM-5.3-Flash (Zhipu AI / Z.ai)
- Organization: Zhipu AI (Z.ai)
- GLM-5.2: released 2026-06-13/16 (sources vary by a few days), 753B total / ~40B active, MIT license, 1M context / 131K max output, two reasoning-effort levels (High/Max)
- GLM-5.3: released 2026-08-14 (API) / weights public 2026-08-25, **same 743B base as GLM-5.2, upgraded via scaled post-training only** — released under a custom, non-MIT "GLM-5.3 License" (a real licensing regression vs. GLM-5.2, worth flagging explicitly)
- GLM-5.3-Flash: released 2026-08-26, 320B total / 18B active, first natively multimodal (text/image/video) model in the GLM-5 line, **MIT licensed**
- Architecture: sparse MoE throughout the line
- Coding focus: GLM-5.2/5.3 are explicitly marketed as coding/long-horizon-agentic-focused
- Independent evidence: NONE gathered this phase — vendor/press-aggregated only
- Licensing note for Genesis purposes: GLM-5.2 (MIT) and GLM-5.3-Flash (MIT) are commercially clean; GLM-5.3 flagship is NOT (custom license, terms not read in full this phase)

### Mistral Large 3
- Organization: Mistral AI
- Release date: 2025-12 (per search results; note this is BEFORE this phase's Sept 2026 research window, included because it remains current/relevant)
- Exact repository: not resolved this phase
- License: Apache 2.0 (both base and instruct variants)
- Total parameters: 675B
- Active parameters: 41B
- Architecture: sparse MoE
- Context: 256K
- Multimodal: yes (vendor describes it as a "frontier open-weight multimodal model")
- Training hardware note (vendor-disclosed): trained from scratch on 3,000 NVIDIA H200 GPUs — useful signal for the scale of infrastructure a comparable post-training effort would need, not directly relevant to inference
- Independent evidence: NONE gathered this phase

### MiniMax M3
- Organization: MiniMax
- Release date: 2026-06-01
- Exact repository: `MiniMaxAI/MiniMax-M3` (Hugging Face)
- License: **CUSTOM LICENSE — REQUIRES TERMS REVIEW.** Phase 21B.4.8.1 correction: the official Hugging Face repository metadata identifies `License: minimax-community`. The earlier MIT claim found in one secondary source is NOT authoritative and is dropped — MIT is not listed as an equally valid alternative. No commercial-posture decision may be made until the actual `minimax-community` license terms are read and reviewed.
- Total parameters: 428B
- Active parameters: ~23B
- Architecture: MoE with "MiniMax Sparse Attention" (MSA) — grouped-query attention variant claimed to cut per-token compute at 1M context to ~1/20 of the prior generation
- Context: 1M tokens
- Multimodal: native image and video input (vendor claim)
- Coding/agentic: vendor claims 80.5% SWE-bench Verified, "matches Claude Sonnet 4.6 on real-world agentic benchmarks" — **unverified vendor claim, not independently checked**
- Independent evidence: NONE gathered this phase
- Of the "true frontier" (100B+ total) tier researched, this is the SMALLEST by total parameters (428B), making it the most plausible frontier-tier candidate to eventually touch with limited compute — still requires ~3x80GB GPUs at INT4 for weight storage alone (see Compute Matrix doc)

### Qwen3.8 family (Alibaba)

**Phase 21B.4.8.1 identity correction**: `Qwen/Qwen3.8-2.4T-A95B` (the
open-weight Hugging Face artifact, what ORNEUR could actually download
and run) and `qwen3.8-max` (Alibaba's managed API/product name for the
same underlying model family) are distinguished explicitly below.
Any feature or behavior claimed only for the managed API product is
NOT assumed to be a property of the open-weight checkpoint unless the
open-weight model card itself states it.

- **Qwen3.8-Max / `Qwen/Qwen3.8-2.4T-A95B`** (open-weight artifact):
  previewed 2026-07-19, launched 2026-08-03, open weights released
  2026-08-12/13 — the first Max-scale Qwen model to have weights
  released at all. 2.4T total parameters, 95B active, hybrid
  attention, 92 layers, 512 experts (10 routed + 1 shared per token).
  License: custom `qwen3.8-max` license, NOT Apache 2.0 — imposes
  additional authorization thresholds for hyperscale commercial/MaaS
  use (a real licensing regression vs. earlier Qwen generations).
- **Qwen3.8-27B**: dense (not MoE), multimodal, 27B parameters,
  Apache 2.0 license — by far the smallest, most permissively-
  licensed, most immediately deployable model surfaced in this entire
  research pass. Fits on a single 80GB GPU at bf16 (~54GB weights)
  with room for KV cache and activations.
- **Qwen3.8-Flash-Next** (`Qwen/Qwen3.8-Flash-Next`, added Phase
  21B.4.8.1 per audit): released 2026-08-26, an experimental preview
  of the architecture underpinning the future Qwen4 line. Core sparse
  MoE: 125B total / 6B active (512 experts, 10 routed + 1 shared),
  PLUS a 51B-parameter n-gram embedding component and a 4B-parameter
  MTP (multi-token-prediction) layer — Hugging Face's own aggregate
  model-size metadata reports figures up to ~177-180B when all
  components are counted together, which must not be confused with
  the 125B/6B core architectural MoE figure. License: `qwen-community-1.0`
  — free to use/deploy commercially, but products exceeding 100M MAU
  or $20M monthly revenue must display model-name attribution, and
  Model-as-a-Service/AI-Work-Assistant businesses face additional
  restrictions (materially more permissive than `qwen3.8-max`'s
  license, but still not unrestricted Apache 2.0). Compatible with HF
  Transformers, vLLM, SGLang per its own model card.
- Independent evidence: NONE gathered this phase for any Qwen3.8 family member
- Correction to the phase's own earlier-generation assumption: Qwen3-235B is clearly no longer Alibaba's flagship; the family has moved through 3.5 (Feb 2026, 397B, Apache 2.0) → 3.6 (Apr 2026, includes a 35B MoE open-weight variant, Apache 2.0) → 3.8 (Aug 2026, 2.4T flagship + 27B dense sibling + Flash-Next preview, mixed licensing)

### Mistral Small 4 (added Phase 21B.4.8.1 per audit)
- Organization: Mistral AI
- Release date: 2026-03-16
- Exact repository: `mistralai/Mistral-Small-4-119B-2603` (Hugging Face; an NVFP4-quantized sibling `mistralai/Mistral-Small-4-119B-2603-NVFP4` also exists)
- License: Apache 2.0
- Total parameters: 119B
- Active parameters: 6B
- Architecture: sparse MoE
- Context: 256K
- Multimodal: yes — accepts text and image input, text output
- Reasoning/instruct modes: unifies capabilities Mistral previously shipped as separate models (Magistral for reasoning, Pixtral for multimodal, Devstral for agentic coding) into one model, per vendor description
- Coding/agentic: includes function-calling support (vendor description); no independent benchmark gathered
- Independent evidence: NONE gathered this phase
- Significance for Genesis: alongside Qwen3.8-27B, this is one of the two cleanest-licensed, most concretely deployable candidates found across both research passes — smaller weight-storage footprint than the 400B+ "true frontier" tier while still MoE-architected and multimodal. Must be considered in the deployable Genesis candidate pool (spec section 13's explicit requirement).

### Kimi K3 (Moonshot AI)
- Organization: Moonshot AI
- Release date: 2026-07-16 (announced) / 2026-07-27 (weights released)
- Total parameters: 2.8T — described as "the largest open weights model ever" at release
- Active parameters: 104B
- Context: 1,048,576 tokens (1M)
- Multimodal: native
- License: **custom, revenue-threshold-gated** — any company with >$20M annual revenue must negotiate a separate contract before offering Kimi K3 to external customers as a service; any company with >$20M monthly revenue or >100M MAU must display attribution. This is a materially more restrictive posture than a standard permissive license and must be weighed carefully for any eventual commercial ORNEUR use, even indirect (e.g. as a teacher model whose outputs train a deployed product).
- Independent evidence: on release, reported to debut #3 on the Artificial Analysis leaderboard (behind Claude Fable 5 and GPT-5.6 Sol) and to outperform on Arena.ai's front-end web-dev benchmark — **third-party leaderboard result, not ORNEUR-verified, and leaderboard methodology/scope not independently reviewed this phase**

### Newly surfaced via Modal's own live rate card (not caught by initial search)
Modal's Shared Endpoints product (`modal billing rates`, live-queried this phase) hosts several of the above models plus two not independently researched in depth this phase, flagged for completeness: `nvidia/GLM-5.2-NVFP4` (an NVFP4-quantized GLM-5.2 variant, hosted by Modal itself) and `thinkingmachines/Inkling-NVFP4` ("Thinking Machines" — a lab not otherwise investigated this phase; "Inkling" model not researched beyond its existence on Modal's rate card).

## Note on revision pinning

No exact immutable HF commit SHA was resolved for any candidate this
phase — this was explicitly a landscape/architecture-planning phase,
not a pre-execution candidate-lock phase. Per this project's own
established discipline (Phase 21B.4/21B.4.1 CandidateConfig
validation), no future real evaluation may proceed without live
re-resolution of exact revisions at execution time, never reused from
this document.
