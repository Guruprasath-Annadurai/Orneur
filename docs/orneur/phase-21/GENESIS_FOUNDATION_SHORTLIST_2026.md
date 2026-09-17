# Genesis Foundation Shortlist 2026

**Phase 21B.3.** This document starts fresh from live upstream sources
(September 2026) rather than reusing Phase 21B.1's `GENESIS_BASE_CANDIDATE_STUDY.md`
recommendation. It does NOT change `orca/registry/model_spec.py::MODEL_SPECS["genesis"]`
-- the canonical base remains `unsloth/Qwen2.5-3B-Instruct` until the owner
issues an explicit `APPROVED -- SET GENESIS 1 BASE TO <MODEL>` approval.

## Methodology and evidence discipline

Every factual claim below is labeled:

- **VERIFIED FACT** -- confirmed live against a primary upstream source
  (the HuggingFace Hub API, a raw model-card README, or an official
  license file/repo) during this phase, with the exact URL cited.
- **UPSTREAM CLAIM** -- stated by the model's own publisher (a benchmark
  table in their model card, a blog post) but not independently
  reproduced here.
- **THIRD-PARTY CLAIM** -- reported by a secondary source (a blog,
  aggregator site) and not cross-checked against a primary source.
- **INFERENCE** -- a conclusion this document draws from the above, not
  a claim made by any source.

No model weights were downloaded. Only small metadata (HF API responses,
model-card READMEs, license text) was fetched. Exact revision SHAs below
were read live from `https://huggingface.co/api/models/<repo>` on
2026-09-17.

## Candidates table (VERIFIED FACT unless noted)

| Model | Params | License | Revision SHA (2026-09-17) | Context | Ecosystem |
|---|---|---|---|---|---|
| `Qwen/Qwen2.5-3B-Instruct` (current canonical) | 3.09B | `qwen-research` (non-commercial, `license: other`) | -- | 32,768 | Unsloth-supported |
| `Qwen/Qwen2.5-7B-Instruct` | 7.61B | `apache-2.0` | `a09a35458c702b33eeacc393d103063234e8bc28` | 131,072 | Unsloth-supported |
| `Qwen/Qwen2.5-14B-Instruct` | ~14B | `apache-2.0` | `cf98f3b3bbb457ad9e2bb7baf9a0125b6b88caa8` | 131,072 | Unsloth-supported |
| `Qwen/Qwen3-4B-Instruct-2507` | ~4B | `apache-2.0` | `cdbee75f17c01a7cc42f958dc650907174af0554` | 32,768 native / 131,072 (YaRN) | Unsloth-supported |
| `Qwen/Qwen3-8B` (`unsloth/Qwen3-8B` mirror) | 8.2B | `apache-2.0` | `946bc9ac74a6c1f8cf012497c503a119b2fcf2eb` (unsloth mirror) | 32,768 native / 131,072 (YaRN) | Unsloth-supported |
| `Qwen/Qwen3-14B` | ~14B | `apache-2.0` | `b8755c0b498d7b538068383748d6dc20397b4d1f` (unsloth mirror) | 32,768 native / 131,072 (YaRN) | Unsloth-supported |
| `Qwen/Qwen3-30B-A3B-Instruct-2507` (MoE) | 30B total / ~3B active | `apache-2.0` | `0d7cf23991f47feeb3a57ecb4c9cee8ea4a17bfe` | 32,768 native / 131,072 (YaRN) | Unsloth-supported (per Unsloth docs) |
| `meta-llama/Llama-3.1-8B-Instruct` (current canonical Novus base) | 8B | `llama3.1` (custom, 700M-MAU commercial gate) | `0e9e39f249a16976918f6564b8830bc894c89659` | 128,000 | Unsloth-supported |
| `meta-llama/Llama-4-Scout-17B-16E-Instruct` (MoE) | 17B active / 16 experts | `llama4` (custom, 700M-MAU commercial gate) | `92f3b1597a195b523d8d9e5700e57e4fbb8f20d3` | up to 10M (UPSTREAM CLAIM, third-party summaries) | Emerging |
| `mistralai/Mistral-Nemo-Instruct-2407` | 12B | `apache-2.0` | `04d8a90549d23fc6bd7f642064003592df51e9b3` (`unsloth/Mistral-Nemo-Instruct-2407`: `e9976040f42d8a5590ed58cefe973061b3f973b5`) | 128,000 | Unsloth-supported |
| `microsoft/Phi-4` | 14B | `mit` | `2db69c1c3e91a05d2c64a3185acfbaf36f744e25` (`unsloth/Phi-4`: `c6220bde10fff762dbd72c3331894aa4cade249d`) | 16,384 (UPSTREAM CLAIM) | Unsloth-supported |
| `microsoft/Phi-4-mini-instruct` | ~3.8B | `mit` | `cfbefacb99257ffa30c83adab238a50856ac3083` | 128,000 (UPSTREAM CLAIM) | Emerging |
| `google/gemma-3-12b-it` | 12B | `gemma` (custom, see caution below) | `96b6f1eccf38110c56df3a15bffe176da04bfd80` | 128,000 (UPSTREAM CLAIM) | Unsloth-supported |
| `ibm-granite/granite-3.1-8b-instruct` | 8B | `apache-2.0` | `4009206d5fc95d2e65a7b7633e159d6e97e25d35` | 128,000 (UPSTREAM CLAIM) | Emerging |
| `deepseek-ai/DeepSeek-R1-Distill-Qwen-7B` | 7B | `mit` | `916b56a44061fd5cd7d6a8fb632557ed4f724f60` | 131,072 (UPSTREAM CLAIM) | Unsloth-supported |

All revision SHAs above are VERIFIED FACT, read live from the HuggingFace
Hub Models API (`GET /api/models/<repo>` -> `.sha`) on 2026-09-17, except
where marked otherwise. `lastModified` timestamps were also captured but
are omitted from the table for brevity; they are available in the raw
research transcript for this session.

**MATERIAL RE-CONFIRMATION**: re-checking the current canonical base live
(not from memory) reproduces Phase 21B.1's finding exactly --
`Qwen/Qwen2.5-3B-Instruct`'s HF model-card YAML frontmatter still reads
`license: other` / `license_name: qwen-research`
(https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/raw/main/README.md,
fetched live 2026-09-17). This is a non-commercial research license.
Nothing about this has changed since Phase 21B.1; the canonical base
remains commercially unsuitable as-is.

**MAJOR NEW FINDING since Phase 21B.1**: Qwen's newer Qwen3 family ships
under Apache-2.0 at every size checked (4B/8B/14B/30B-A3B), unlike
Qwen2.5's split (3B = research-only, 7B/14B = Apache-2.0). Qwen3-8B in
particular resolves the exact license defect that disqualifies the
current 3B canonical base, while staying in the same model family/
tokenizer lineage Unsloth/PEFT already demonstrably supports for this
project (Qwen2.5 training path already exists in `orca/train/finetune.py`).

## License detail (hard gate, per spec section 6)

### `qwen-research` (current canonical Genesis base)
VERIFIED FACT, quoted from the HF license link
(https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/main/LICENSE, as
already recorded in `GENESIS_BASE_MODEL_QUALIFICATION.md`): restricted to
non-commercial research/evaluation use; commercial use requires a
separate license from Alibaba Cloud. **Verdict: RESTRICTED. Unsuitable
for commercial Genesis 1 without a separate Alibaba Cloud commercial
license (not evaluated here -- flagged for formal legal review, not a
model-delegated legal interpretation).**

### Apache License 2.0 (Qwen3 family, Qwen2.5-7B/14B, Mistral-Nemo, IBM Granite)
VERIFIED FACT (license tag `apache-2.0` read from each repo's HF API/
README). Apache-2.0 is a standard OSI-approved permissive license:
permits commercial use, modification, distribution, sublicensing, and
private use; requires preservation of copyright/license notices and a
statement of changes on redistribution; grants an express patent license
from contributors; no revenue or MAU gate. **Verdict: PERMITTED for
commercial use, including as a fine-tuning base, subject to standard
Apache-2.0 notice-preservation obligations on redistribution of the
original weights/code.** This is a legal-text characterization of a
well-known standard license, not a claim requiring case-specific
interpretation -- still worth a pro forma confirmation from counsel
before public commercial release, per this phase's own instruction not
to delegate exact legal interpretation to the model.

### MIT License (Phi-4, Phi-4-mini, DeepSeek-R1-Distill-Qwen-7B)
VERIFIED FACT (license tag `mit`). MIT is maximally permissive: commercial
use, modification, distribution, sublicensing all permitted; only
obligation is preserving the copyright/license notice. **Verdict:
PERMITTED for commercial use.** Note DeepSeek-R1-Distill-Qwen-7B is
itself a distillation of a DeepSeek reasoning model onto a Qwen base --
its MIT license covers DeepSeek's own contribution, but it inherits
Qwen's architecture; no indication this creates a licensing conflict
(the base Qwen weights it was distilled from were themselves separately
licensed by Alibaba), but this lineage is flagged as a point a formal
review should double check rather than a verified-clean determination.

### `llama3.1` / `llama4` (Meta community licenses)
VERIFIED FACT for `llama4`, quoted verbatim from the primary GitHub-hosted
license file (https://github.com/meta-llama/llama-models/blob/main/models/llama4/LICENSE,
fetched live 2026-09-17): grants "a non-exclusive, worldwide,
non-transferable and royalty-free limited license... to use, reproduce,
distribute, copy, create derivative works of, and make modifications to
the Llama Materials," but Section 2 ("Additional Commercial Terms")
states: *"If, on the Llama 4 version release date, the monthly active
users of the products or services made available by or for Licensee...
is greater than 700 million monthly active users in the preceding
calendar month, you must request a license from Meta."* Below that
threshold, commercial use (including derivative fine-tunes) is permitted
without a separate license. `llama3.1` (the license on the currently
Novus-canonical `Llama-3.1-8B-Instruct`) is UPSTREAM CLAIM/THIRD-PARTY
CLAIM to carry a materially similar structure -- not independently
re-fetched and quoted this closure (out of this narrow phase's primary
candidate set; Llama family is Novus's existing base, not a Genesis
finalist here). **Verdict for Llama 4: PERMITTED for any ORNEUR-scale
commercial use for the foreseeable future** (700M MAU is a very high bar
for an early-stage product) **but carries an ongoing obligation to
monitor MAU and re-license if that threshold is ever crossed** --
different in kind from Apache-2.0/MIT, which carry no such
usage-triggered re-licensing obligation.

### Gemma custom license (Gemma-3)
NOT independently fetched and quoted this closure -- flagged as
**UNVERIFIED THIS CLOSURE**. Historically (THIRD-PARTY CLAIM, not
re-confirmed here), the Gemma license includes usage-restriction
provisions beyond a standard OSI license (an acceptable-use policy
incorporated by reference) that have led some commentators to describe
Gemma as not meeting the OSI Open Source Definition despite permitting
broad commercial use. Given Qwen3 and Mistral-Nemo already provide
clean, VERIFIED Apache-2.0 options in the same capability classes, Gemma
is not advanced to the finalist list this closure -- not because it is
known to be unsuitable, but because a cleaner-verified alternative
exists and this phase's time budget did not extend to a full Gemma
license text review.

## Finalist recommendation

### Primary finalist: `Qwen/Qwen3-8B` (mirrored as `unsloth/Qwen3-8B`)

- **Why Genesis-specific**: Qwen3's own model card explicitly claims
  "expertise in agent capabilities, enabling precise integration with
  external tools in both thinking and unthinking modes" (UPSTREAM CLAIM,
  https://huggingface.co/Qwen/Qwen3-8B/raw/main/README.md) -- directly
  relevant to Genesis's Builder/Executor identity (tool planning,
  staged execution), not merely a coding-benchmark model. The
  thinking/non-thinking mode switch is architecturally relevant to
  Genesis's epistemic-behavior and verification-vs-implementation
  evaluation categories (§18 categories 10, 12).
- **Capability upside**: UPSTREAM CLAIM of improved reasoning/coding/
  commonsense logic over Qwen2.5-Instruct and the QwQ reasoning line;
  100+ language multilingual support (UPSTREAM CLAIM).
  8.2B params -- meaningfully more capacity than the current 3B canonical
  base at a similar deployment/QLoRA cost class.
- **Weakness**: benchmark superiority claims are UPSTREAM CLAIM only,
  not independently reproduced by this phase (no model evaluation was
  run -- see Phase 21B.4 runbook). Same-vendor concentration risk if
  paired with a Qwen-family Novus/Aeternum choice (diversity is a
  Model-Society consideration, not evaluated here).
- **Compute cost class**: QLoRA-feasible on a single 24GB-class consumer
  GPU (INFERENCE, extrapolated from the 3B Qwen2.5 QLoRA profile already
  documented in `PHASE21C_GENESIS_TRAINING_RUNBOOK.md` and Unsloth's
  documented "70% less VRAM" claim for the Qwen3 family -- UPSTREAM
  CLAIM, https://unsloth.ai/blog/qwen3).
- **Inference cost class**: dense 8.2B model -- straightforward
  single-GPU or CPU-offload inference, no MoE routing complexity.
- **Commercial-license posture**: PERMITTED (Apache-2.0, VERIFIED FACT,
  see above).
- **Architecture risk**: dense transformer, same family/tokenizer
  lineage as the current Qwen2.5-based training path already implemented
  in this repo -- LOW migration risk to the existing
  `_load_base_model_and_tokenizer()` / Unsloth loading code.
- **Adaptation risk**: LOW -- Unsloth officially documents Qwen3 QLoRA
  fine-tuning support (VERIFIED via WebSearch of Unsloth's own docs,
  https://unsloth.ai/blog/qwen3 and https://unsloth.ai/docs/models/tutorials/qwen3-how-to-run-and-fine-tune).
- **Ecosystem maturity**: HIGH -- same publisher/tokenizer family
  already integrated; `transformers` support confirmed (README requires
  `transformers>=4.51.0`, VERIFIED FACT from the model card).

### Second finalist: `mistralai/Mistral-Nemo-Instruct-2407` (12B)

- **Why Genesis-specific**: broad general-purpose model (not
  coding-specialized), trained jointly by Mistral AI and NVIDIA
  (UPSTREAM CLAIM), explicitly marketed as a "drop-in replacement of
  Mistral 7B" with substantially more capacity -- fits Genesis's
  "broad executable intelligence, not narrow coding" identity.
- **Capability upside**: 128K native context (VERIFIED FACT from model
  card), strong multilingual coverage across 9 languages with published
  per-language MMLU scores (UPSTREAM CLAIM,
  https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407/raw/main/README.md).
- **Weakness**: different tokenizer/architecture family than the
  project's existing Qwen2.5 training path -- would require validating
  the ChatML-equivalent chat template and tokenizer behavior from
  scratch (Mistral uses its own "tekken" tokenizer per the model card).
- **Compute cost class**: 12B is a step up from Qwen3-8B; QLoRA
  feasibility is credible (INFERENCE, based on Unsloth's general 4-bit
  QLoRA support claims) but not verified with a project-specific VRAM
  measurement this closure.
- **Inference cost class**: moderate -- dense 12B, larger than Qwen3-8B.
- **Commercial-license posture**: PERMITTED (Apache-2.0, VERIFIED FACT).
- **Architecture risk**: MEDIUM -- different vendor/tokenizer lineage
  than the currently-implemented training path; provides useful
  vendor diversity but at real integration cost.
- **Adaptation risk**: MEDIUM -- Unsloth lists Mistral-Nemo support
  (`unsloth/Mistral-Nemo-Instruct-2407` exists as a verified HF repo,
  VERIFIED FACT), but this project has no prior Mistral-family training
  code to build on.
- **Ecosystem maturity**: MEDIUM-HIGH -- major-vendor model, broad
  community adoption (THIRD-PARTY CLAIM, popularity not independently
  measured), but new to this codebase.

### Optional third finalist: `microsoft/Phi-4` (14B) / `microsoft/Phi-4-mini-instruct` (~3.8B)

- **Why Genesis-specific**: most permissive license of any candidate
  (MIT, VERIFIED FACT) -- zero ongoing obligations beyond notice
  preservation, the cleanest possible legal posture for a commercial
  product. Phi-4-mini offers an efficiency-class option in the same
  family if a smaller footprint is later prioritized.
  Phi-4 offers strong claimed reasoning/math performance
  (UPSTREAM CLAIM, not independently benchmarked here).
- **Capability upside**: MIT license removes essentially all commercial
  friction; Microsoft actively maintains the repo (model card last
  modified 2026-07-14, VERIFIED FACT via HF API -- among the most
  recently updated candidates checked).
- **Weakness**: Phi models have historically been trained with a strong
  emphasis on curated/synthetic "textbook-quality" data (THIRD-PARTY
  CLAIM, not independently confirmed for this exact revision) --
  a real open question for Genesis's "broad, not narrow" mandate is
  whether that training emphasis produces a model that under-performs
  on messy, real-world-style tasks relative to its benchmark scores.
  This is exactly the kind of question the Phase 21B.4 baseline
  shootout exists to answer empirically rather than resolve by
  assumption here.
- **Compute cost class**: Phi-4 (14B) is the largest of the three
  finalists; Phi-4-mini (~3.8B) is the smallest candidate in this
  document overall.
- **Inference cost class**: Phi-4 moderate; Phi-4-mini very low.
- **Commercial-license posture**: PERMITTED (MIT, VERIFIED FACT) --
  the cleanest of all candidates evaluated.
- **Architecture risk**: MEDIUM -- new vendor/tokenizer family to this
  codebase, same integration-cost category as Mistral-Nemo.
  Phi-4's native context (16,384, UPSTREAM CLAIM) is notably smaller
  than the other finalists' 128K-class windows.
- **Adaptation risk**: LOW-MEDIUM -- `unsloth/Phi-4` exists as a
  verified HF repo (VERIFIED FACT), so Unsloth support is credible, but
  (like Mistral-Nemo) this project has no prior Phi-family training code.
- **Ecosystem maturity**: MEDIUM -- major-vendor model, actively
  maintained, but a third distinct tokenizer/chat-template family to
  validate from scratch if chosen.

## What this document does NOT do

- It does not download or run any of these models.
- It does not change `MODEL_SPECS["genesis"].base_model`,
  `base_model_revision`, `tokenizer_revision`, `license_name`, or
  `license_commercial_use` -- those remain the Phase 21B state
  (`unsloth/Qwen2.5-3B-Instruct`, `qwen-research`, `RESTRICTED`) until an
  explicit owner approval phrase changes them.
- It does not resolve the Gemma license question, or independently
  re-verify the `llama3.1` license text (out of this narrow closure's
  time budget) -- both are flagged as open items for a future pass if
  either candidate becomes actively considered.
- It does not constitute formal legal advice; every RESTRICTED/PERMITTED
  verdict above is this document's plain-language reading of the quoted
  primary-source text, not a substitute for counsel review before any
  public commercial release.

## Next step (not executed by this document)

See `docs/orneur/phase-21/PHASE21B4_FOUNDATION_BASELINE_SHOOTOUT.md` for
the (unexecuted) runbook that would empirically compare these finalists
against `genesis-eval-v1` before any Genesis training decision.
