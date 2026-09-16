# Genesis 1 — Base Foundation Candidate Study

Phase 21B.1. Verified live against authoritative Hugging Face sources
(API `sha`/`lastModified`/`tags`/`cardData`, live `config.json`, live
`README.md`) on **2026-09-16/17**, not recalled from memory. This
document researches and recommends; it does **not** change
`orca/registry/model_spec.py::MODEL_SPECS["genesis"].base_model`.

## Method and honesty notes

- Every field below is either **VERIFIED** (retrieved live this
  session, cited), **UPSTREAM CLAIM** (the model's own card asserts it,
  not independently reproduced), or **NOT_VERIFIED** (could not be
  checked in this closure's scope).
- No model weights were downloaded for any candidate.
- Meta's `meta-llama/*` repositories are **gated** on Hugging Face
  (require an accepted license agreement tied to an authenticated HF
  account) -- this session has no HF auth token, so `config.json` for
  `meta-llama/Llama-3.2-3B-Instruct` returned `HTTP 401 Unauthorized`
  and could not be independently verified. This is itself a real,
  material practical-friction finding for any Llama-family candidate:
  base-model acquisition requires a gated-access agreement, not just a
  `git clone`.
- Third-party/independent benchmark claims were **not** collected in
  this closure (out of scope, time-boxed) -- capability comparisons
  below rely on each model's own card, explicitly labeled UPSTREAM CLAIM,
  never presented as independently verified.

## Candidates

### 1. Qwen2.5-3B-Instruct (current selection, unchanged)

- Upstream: Alibaba Cloud (Qwen), via `unsloth/Qwen2.5-3B-Instruct`
- Revision: `7548fff1f997f57b2e9e8ab1ec7be96949b00ed0` (already pinned)
- Parameters: 3.09B (2.77B non-embedding) -- VERIFIED (upstream card)
- Architecture: Qwen2, 36 layers, hidden 2048, GQA 16Q/2KV, vocab 151936 -- VERIFIED (`config.json`)
- Context: 32,768 native -- VERIFIED (upstream card)
- **License: `qwen-research` -- non-commercial only** -- VERIFIED (LICENSE file text; see `GENESIS_BASE_MODEL_QUALIFICATION.md`)
- Commercial use: **RESTRICTED**
- Training rights: derivative works permitted (non-commercial), with attribution notice
- Tokenizer: same repo/revision
- Coding/reasoning/tool-use evidence: UPSTREAM CLAIM only (not independently reproduced)
- VRAM (QLoRA, rank 32): ~10GB (existing preset)
- QLoRA/Unsloth compatibility: VERIFIED (existing training pipeline already targets this exact repo)
- Limitations: non-commercial license is a hard blocker for a commercial ORNEUR release on this exact artifact

### 2. Qwen2.5-7B-Instruct

- Upstream: Alibaba Cloud (Qwen), `Qwen/Qwen2.5-7B-Instruct`
- Revision: `a09a35458c702b33eeacc393d103063234e8bc28` -- VERIFIED (HF API `sha`)
- Parameters: ~7.61B nominal -- VERIFIED (`config.json`: hidden_size 3584, 28 layers)
- Architecture: Qwen2, GQA 28Q/4KV, vocab 152064, native context 32,768 -- VERIFIED (`config.json`)
- **License: `apache-2.0`** -- VERIFIED (HF API `tags`: `license:apache-2.0`, `cardData.license`)
- Commercial use: **PERMITTED** (Apache-2.0 imposes only standard attribution/notice requirements, no non-commercial restriction)
- Tokenizer: same repo/revision, same tokenizer family as the current 3B selection (migration-friction-minimizing: same chat template, same special tokens, same ChatML convention)
- Coding/reasoning/tool-use evidence: UPSTREAM CLAIM ("significantly more knowledge... improved capabilities in coding and mathematics")
- VRAM (QLoRA, rank 32-64): ~16-20GB estimated by analogy to the existing `core`/Novus preset (8B Llama, `vram_gb=16`) -- NOT_VERIFIED for this exact model, reasonable estimate only
- QLoRA/Unsloth compatibility: VERIFIED indirectly -- same `Qwen2ForCausalLM` architecture class already used by the existing `nano` preset's training path (`unsloth.FastLanguageModel` supports the Qwen2 architecture family)
- Limitations: ~2.5x the VRAM of the 3B target; would require re-tuning the existing `nano` LoRA/batch-size preset, not a drop-in

### 3. Meta Llama-3.1-8B-Instruct

- Upstream: Meta, `meta-llama/Llama-3.1-8B-Instruct`
- Revision: `0e9e39f249a16976918f6564b8830bc894c89659` -- VERIFIED (HF API `sha`)
- License: `license:llama3.1` (Meta's own Llama 3.1 Community License, not a standard OSI license) -- VERIFIED (HF API tags)
- Commercial use: **CONDITIONALLY PERMITTED** -- Meta's Llama license permits commercial use but includes attribution requirements and an acceptable-use policy; **this session did not fetch and review the full license text** (would require the same live-retrieval rigor as the Qwen license was given) -- **NOT_VERIFIED** in full, flagged rather than assumed
- Architecture/parameters: NOT independently verified this closure -- Meta's `meta-llama/*` repos are gated (HTTP 401 without an authenticated, license-accepted HF account); this is the SAME base model already canonically selected for **Novus** (`MODEL_SPECS["novus"].base_model`), so its architecture is presumably already known to the team from that selection, but this document does not re-derive it from memory
- Note: selecting this exact model for Genesis would mean Genesis and Novus share an identical base architecture, differing only in fine-tuning -- a real design question (does that undermine the "distinct cognitive specialization" doctrine, or is shared-base-different-adaptation an acceptable Model Society pattern?) that this document surfaces but does not resolve

### 4. Mistral-7B-Instruct-v0.3

- Upstream: Mistral AI, `mistralai/Mistral-7B-Instruct-v0.3`
- Revision: `c170c708c41dac9275d15a8fff4eca08d52bab71` -- VERIFIED
- Parameters: ~7.25B -- VERIFIED (`config.json`: hidden_size 4096, 32 layers, vocab 32768)
- Architecture: Mistral, GQA 32Q/8KV, native context 32,768 -- VERIFIED
- **License: `apache-2.0`** -- VERIFIED
- Commercial use: **PERMITTED**
- Notable: extended tokenizer (v3, vocab 32768) with **native function-calling support** -- VERIFIED (upstream card explicitly states this), directly relevant to Genesis's tool-use-planning requirement
- QLoRA/Unsloth compatibility: Mistral architecture is Unsloth-supported (same class of support as Llama/Qwen)
- Limitations: different tokenizer/chat-template family from the current Qwen-based pipeline -- would require adapting `orca/data/formatter.py`'s ChatML assumption (Mistral's own template differs) and re-verifying the existing training pipeline against a new architecture family, more migration work than staying within the Qwen family

### 5. Mistral-Nemo-Instruct-2407 (~12B)

- Upstream: Mistral AI + NVIDIA, `mistralai/Mistral-Nemo-Instruct-2407`
- Revision: `04d8a90549d23fc6bd7f642064003592df51e9b3` -- VERIFIED
- Parameters: ~12B (hidden_size 5120, 40 layers) -- VERIFIED (`config.json`)
- **License: `apache-2.0`** -- VERIFIED
- Commercial use: **PERMITTED**
- Context: **131,072 tokens native** -- VERIFIED (`config.json::max_position_embeddings`), by far the largest of any candidate here, directly relevant to Genesis's multi-file/long-context reasoning needs
- Coding/reasoning evidence: UPSTREAM CLAIM ("significantly outperforms existing models smaller or similar in size" -- vague, not independently reproduced)
- QLoRA VRAM: larger than 7B-class, meaningfully more than the current 3B preset
- Limitations: same tokenizer-family migration cost as Mistral-7B; largest VRAM footprint of the mid-tier candidates

### 6. Qwen2.5-14B-Instruct

- Upstream: Alibaba Cloud (Qwen), `Qwen/Qwen2.5-14B-Instruct`
- Revision: `cf98f3b3bbb457ad9e2bb7baf9a0125b6b88caa8` -- VERIFIED
- Parameters: ~14.7B (hidden_size 5120, 48 layers) -- VERIFIED
- **License: `apache-2.0`** -- VERIFIED
- Commercial use: **PERMITTED**
- Architecture: Qwen2, same family/tokenizer/chat-template as the current 3B selection and candidate 2 (Qwen2.5-7B) -- lowest migration friction of any candidate above 3B
- Context: 32,768 native
- QLoRA VRAM: meaningfully larger than 7B (roughly double parameter count)
- Limitations: largest VRAM/compute footprint of the Qwen-family candidates; overlaps size-wise with Aeternum's own current `~14B` provisional hypothesis (`MODEL_SPECS["aeternum"].provisional_parameter_hypothesis`) -- selecting this for Genesis would need explicit reconciliation with that overlap, since the doctrine (&sect;2.6) requires distinct cognitive specialization, not merely distinct sizes

### 7. microsoft/phi-4 (~14.7B)

- Upstream: Microsoft Research, `microsoft/phi-4`
- Revision: `2db69c1c3e91a05d2c64a3185acfbaf36f744e25` -- VERIFIED
- Parameters: ~14.7B (hidden_size 5120, 40 layers) -- VERIFIED
- **License: `mit`** -- VERIFIED (HF API tags: `license:mit`)
- Commercial use: **PERMITTED** (MIT is maximally permissive)
- Architecture: Phi3-family (`Phi3ForCausalLM`), a distinct architecture from both Qwen2 and Llama -- VERIFIED
- Notable: upstream card explicitly emphasizes math/code training data mix -- UPSTREAM CLAIM, directly aligned with Genesis's Builder/Executor identity if reproducible
- Context: 16,384 native -- VERIFIED, smaller than the Qwen-14B/Mistral-Nemo alternatives
- Limitations: architecture family not currently used anywhere in ORNEUR's existing training pipeline (new integration/compatibility work); MIT license is the most permissive of all candidates here, a real point in its favor

## Comparison summary

| Candidate | Params | License | Commercial | Context | Architecture family already in ORNEUR? |
|---|---|---|---|---|---|
| Qwen2.5-3B-Instruct (current) | 3.09B | qwen-research | **RESTRICTED** | 32K | Yes |
| Qwen2.5-7B-Instruct | 7.61B | apache-2.0 | Permitted | 32K | Yes |
| Llama-3.1-8B-Instruct | ~8B (not re-verified) | llama3.1 community (NOT fully reviewed) | Conditional | 128K (upstream claim) | Yes (Novus) |
| Mistral-7B-Instruct-v0.3 | 7.25B | apache-2.0 | Permitted | 32K | No |
| Mistral-Nemo-Instruct-2407 | ~12B | apache-2.0 | Permitted | **131K** | No |
| Qwen2.5-14B-Instruct | ~14.7B | apache-2.0 | Permitted | 32K | Yes |
| microsoft/phi-4 | ~14.7B | **mit** | Permitted | 16K | No |

## RECOMMENDED GENESIS 1 FOUNDATION CANDIDATE

**Qwen2.5-7B-Instruct.**

Reasons: (1) Apache-2.0 -- fully resolves the current commercial-license
blocker without any qualification caveats; (2) same architecture family,
tokenizer, and chat template as the currently-selected 3B model, so the
existing training pipeline (`orca/train/finetune.py`, Unsloth
compatibility, ChatML formatting) requires no architectural rework, only
hyperparameter re-tuning (LoRA rank/batch size for the larger VRAM
footprint); (3) meaningfully more capability headroom than 3B while
remaining single-consumer-GPU feasible for QLoRA, unlike the 12-14B tier;
(4) doesn't create the same-base-as-Novus identity-overlap question that
selecting Llama-3.1-8B would (Novus already owns that exact base), nor
the same-size-class-as-Aeternum's-provisional-hypothesis question that
Qwen2.5-14B would.

**Runner-up: Mistral-7B-Instruct-v0.3** -- also Apache-2.0, also
commercially clean, and notably has native function-calling support
directly relevant to Genesis's tool-use-planning requirement. Held back
from the primary recommendation only because it requires adapting the
existing ChatML-based data-formatting pipeline to a different chat
template family -- real but modest additional migration work compared
to staying within the Qwen family.

**Commercially usable: YES** (both the recommendation and its runner-up).

**Unresolved risks**:
- No independent benchmark verification was performed for either
  candidate's actual reasoning/coding/tool-use quality -- capability
  claims above are upstream-card assertions, not reproduced results.
  Phase 21C's own baseline-evaluation step (runbook Step C) is where
  this would first get real, ORNEUR-specific evidence.
- VRAM/training-time estimates for the 7B tier are reasonable estimates
  by analogy to Novus's existing 8B preset, not independently measured
  for this specific 7B model.
- Llama-3.1-8B's full license text was not reviewed in this closure
  (gated repo, and out of the time this closure could allocate) --
  if the team wants Llama-3.1-8B seriously considered despite the
  same-base-as-Novus question, that license needs the same full-text
  review this document gave the Qwen research license.

**CANONICAL BASE WAS NOT CHANGED.** `orca/registry/model_spec.py::
MODEL_SPECS["genesis"].base_model` remains `unsloth/Qwen2.5-3B-Instruct`.

## Required owner approval phrase for any change

    APPROVED — SET GENESIS 1 BASE TO <MODEL>

No such approval has been given or inferred in this closure.
