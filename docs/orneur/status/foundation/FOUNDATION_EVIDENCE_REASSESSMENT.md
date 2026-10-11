# Foundation-Model Evidence Reassessment (Workstream D)

Date: 2026-10-11 | Branch: `claude/ws-d-foundation-evidence` | Base: `claude/integration-candidate-1` @ `cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d` | Machine-readable twin: `foundation_evidence.json` | Verifier: `scripts/foundation/verify_evidence.py`

> **NOT A SELECTION. No foundation model is selected, promoted or recommended as final by this document. Selection requires the mandatory frozen capability evaluation (GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26 section 5) and explicit founder authorization.**
> This is a PROVISIONAL, NON-BINDING evidence reassessment. The verdict of `GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26` (`FOUNDATION_DECISION_REQUIRES_CAPABILITY_EVAL`) stands. No training, GPU, model download, inference or provider call occurred; sources were public documentation read through HTTP GET only.

## 0. Evidence classes and how to read this file

Every statement carries one class (full definitions in the JSON):

- **DOCUMENTED_FACT** - cited primary source (publisher repo at exact commit SHA, licence text, technical report) or a labelled third-party page; each has `source_url`, `retrieved_at`, `revision`.
- **INDEPENDENTLY_REPRODUCED** - reproduced by this repository's own persisted evidence (file cited).
- **UNTESTED_HYPOTHESIS** - every estimate, cost figure and rubric judgment. Nothing here was measured.
- **NOT_VERIFIED** - could not be checked in this pass (section 14).

Integrity method: Hugging Face exposes the git blob id of every file (tree API / ETag). Each recorded text (licence, `config.json`, `generation_config.json`, `tokenizer_config.json`) was reconstructed from the tool output and **stored only if its git blob sha1 equals the primary source's oid** (byte-exact proof). Weight-shard LFS sha256 values were cross-checked against the repo's own 2026-09-24 pre-cache manifests (0 mismatches). Details and tool limitations: JSON `retrieval_session`.

## 1. Executive summary and surprises

1. **No drift.** All 15 SHAs re-checked (3 controls, Qwen2.5-3B unsloth + upstream, 10 landscape-admitted dense models) equal the repo's recorded revisions; control weight hashes are identical to the repo manifests.
2. **Mistral-Nemo-Instruct-2407 has no LICENSE file** at the pinned commit (18-file tree). Apache-2.0 rests on the metadata tag and README prose. The package's `K: PASS` is therefore weaker than stated; this document records `REQUIRES_COUNSEL` and refuses `GRANTED`.
3. **The qwen-research licence is stricter than the repo summaries**: clause 4.b requires 'Built with Qwen' / 'Improved using Qwen' when the Materials *or their outputs* are used to train or improve a distributed AI model; 6.d is an indemnity; 8 is PRC law with Hangzhou courts. The current canonical base (unsloth mirror) also ships no LICENSE file of its own.
4. **Qwen3-8B and Phi-4 licence texts are byte-verified** (Apache-2.0 identical to the canonical text with `Copyright 2024 Alibaba Cloud`; MIT with CRLF, 1,105 bytes) - the first time the repo has hashed them.
5. **The three 'finalists' are `BASELINE_ONLY_CONTROL` in the repo's own landscape** (not admitted to the capability eval) and 'never a candidate finalist' in the Stage-0 matrix, yet the decision package uses them as the options. The documents disagree (RC-4).
6. **The control-program 'failures' are largely harness design**, reproducible offline: prompts do not request the format the acceptance demands, `max_tokens` is 1024 for Qwen3 but 64 for Nemo/Phi-4 (Phi-4's JSON smoke was cut off with `finish_reason=length`), and vLLM silently applies each model's `generation_config.json` defaults (section 12).
7. Nemo's template hash independently matches the repo's recorded hash; Qwen3's default template injects `<think>` handling; Qwen2.5's template injects a vendor identity system prompt ('You are Qwen, created by Alibaba Cloud').

## 2. Candidates and depth of verification

| Candidate | Role in repo | Repo @ exact revision (== HEAD on 2026-10-11) | Depth |
|---|---|---|---|
| Qwen3-8B | documented finalist 1 / control (runtime-failed, capability unproven) | `Qwen/Qwen3-8B` @ `b968826d9c46dd6066d109eabc6255188de91218` | DEEP (primary files re-read, hashed) |
| Mistral-Nemo-Instruct-2407 | documented finalist 2 / control (runtime-failed, capability unproven) | `mistralai/Mistral-Nemo-Instruct-2407` @ `04d8a90549d23fc6bd7f642064003592df51e9b3` | DEEP (primary files re-read, hashed) |
| Phi-4 | documented finalist 3 / control (runtime-failed, capability unproven) | `microsoft/phi-4` @ `2db69c1c3e91a05d2c64a3185acfbaf36f744e25` | DEEP (primary files re-read, hashed) |
| Qwen2.5-3B-Instruct (unsloth) | current canonical Genesis base (MODEL_SPECS['genesis']); license gate FAIL for commercial use | `unsloth/Qwen2.5-3B-Instruct` @ `7548fff1f997f57b2e9e8ab1ec7be96949b00ed0` | DEEP (primary files re-read, hashed) |
| SmolLM3-3B | landscape `GENESIS_EVAL_ADMITTED` | `HuggingFaceTB/SmolLM3-3B` @ `a07cc9a04f16550a088caea529712d1d335b0ac1` | IDENTITY_ONLY (sha, params, licence tag) |
| Qwen3.5-4B | landscape `GENESIS_EVAL_ADMITTED` | `Qwen/Qwen3.5-4B` @ `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` | IDENTITY_ONLY (sha, params, licence tag) |
| Qwen3.5-9B | landscape `GENESIS_EVAL_ADMITTED` | `Qwen/Qwen3.5-9B` @ `c202236235762e1c871ad0ccb60c8ee5ba337b9a` | IDENTITY_ONLY (sha, params, licence tag) |
| Olmo-3-7B-Instruct | landscape `GENESIS_EVAL_ADMITTED` | `allenai/Olmo-3-7B-Instruct` @ `6e5971d9eba42665f5bd5a0fcf047f299ce1dccc` | IDENTITY_ONLY (sha, params, licence tag) |
| gemma-4-E4B-it | landscape `GENESIS_EVAL_ADMITTED` | `google/gemma-4-E4B-it` @ `ee0ef6023621cff504d758262d4e04895a5af4a2` | IDENTITY_ONLY (sha, params, licence tag) |
| gemma-4-12B-it | landscape `GENESIS_EVAL_ADMITTED` | `google/gemma-4-12B-it` @ `707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7` | IDENTITY_ONLY (sha, params, licence tag) |
| granite-4.2-3b | landscape `GENESIS_EVAL_ADMITTED` | `ibm-granite/granite-4.2-3b` @ `e459acceac81e5fe67c07d9cfc72329a332e7eb1` | IDENTITY_ONLY (sha, params, licence tag) |
| granite-4.2-8b | landscape `GENESIS_EVAL_ADMITTED` | `ibm-granite/granite-4.2-8b` @ `f8de16cdcdbc6c779ca517604e050d82cc119e44` | IDENTITY_ONLY (sha, params, licence tag) |
| Phi-4-mini-instruct | landscape `GENESIS_EVAL_ADMITTED` | `microsoft/Phi-4-mini-instruct` @ `cfbefacb99257ffa30c83adab238a50856ac3083` | IDENTITY_ONLY (sha, params, licence tag) |
| Ministral-3-14B-Reasoning-2512 | landscape `GENESIS_EVAL_ADMITTED` | `mistralai/Ministral-3-14B-Reasoning-2512` @ `51f9210f3cd20f3452a80d5819d15dc61cc50630` | IDENTITY_ONLY (sha, params, licence tag) |

Upstream of the canonical base: `Qwen/Qwen2.5-3B-Instruct` @ `aa8e72537993ba99e69dfaafa59ed015b17504d1` (weights byte-identical to the unsloth repack). No candidate was `NOT_FOUND_AT_PRIMARY_SOURCE`; the odd-sounding out-of-scope names (Qwen3.8-27B, Mistral-Small-4-119B-2603, GLM-5.3-Flash) exist at the repo's recorded SHAs. **No candidate outside the repo's own documents was added** (Qwen3-14B and Qwen2.5-7B/14B appear only in the 2026-09-17 shortlist and were not re-verified).

## 3. Architecture, parameters, context (DOCUMENTED_FACT from byte-verified `config.json`)

| | Qwen3-8B | Mistral-Nemo | Phi-4 | Qwen2.5-3B (unsloth) |
|---|---|---|---|---|
| Architecture class | Qwen3ForCausalLM | MistralForCausalLM | Phi3ForCausalLM | Qwen2ForCausalLM |
| Parameters (safetensors, BF16) | 8,190,735,360 | 12,247,782,400 | 14,659,507,200 | 3,085,938,688 |
| Layers / hidden | 36 / 4096 | 40 / 5120 | 40 / 5120 | 36 / 2048 |
| Heads / KV heads (GQA) | 32 / 8 (4:1) | 32 / 8 (4:1) | 40 / 10 (4:1) | 16 / 2 (8:1) |
| Head dim | 128 | 128 | 128 (derived) | 128 (derived) |
| MLP intermediate | 12,288 | 14,336 | 17,920 | 11,008 |
| Vocabulary | 151,936 | 131,072 | 100,352 | 151,936 |
| Tied embeddings | False | False | False | True |
| rope_theta | 1,000,000 | 1,000,000.0 | 250,000 | 1,000,000.0 |
| config max_position_embeddings | 40,960 | 131,072 | 16,384 | 32,768 |
| Vendor-stated native context | 32,768 (131,072 with YaRN; card explains 40,960 reservation) | 128k trained (card) | 16K (card), no extension | 32,768 full / 8,192 generation (card intro also says '128K', unsupported by config) |

## 4. Tokenizer and chat template (hashes of the exact template text)

| | Qwen3-8B | Mistral-Nemo | Phi-4 | Qwen2.5-3B (unsloth) |
|---|---|---|---|---|
| Template sha256 | `a55ee1b1660128b7098723e0abcd92caa0788061051c62d51cbe87d9cf1974d8` | `e4676cb56dffea7782fd3e2b577cfaf1e123537e6ef49b3ec7caa6c095c62272` | `fe4120415a3858b873955c92ce3a103a95bc97c2cb00b72e62659aaf0f891ee5` | `cd8e9439f0570856fd70470bf8889ebd8b5d1107207f67a5efb46e342330527f` |
| Template bytes | 4168 | 3945 | 462 | 2507 |
| Format | ChatML `<\|im_start\|>`/`<\|im_end\|>` | `[INST]...[/INST]`, system prepended to last user turn, strict alternation | `<\|im_start\|>role<\|im_sep\|>...<\|im_end\|>` | ChatML + **default system prompt injected** |
| Thinking / mode switch | `enable_thinking` (default on), `/think` `/no_think`; empty `<think>` block when off | none | none | none |
| Tool-call format | `<tool_call>` JSON | `[AVAILABLE_TOOLS]`/`[TOOL_CALLS]`, 9-char ids | none | `<tool_call>` JSON |
| EOS / pad / BOS | `<\|im_end\|>` / `<\|endoftext\|>` / none | ids eos=2, bos=1; **no pad token defined** | `<\|im_end\|>` / `<\|dummy_85\|>` / `<\|endoftext\|>` | `<\|im_end\|>` / `<\|vision_pad\|>` / none |
| Tokenizer files | tokenizer.json (BPE, 151,936) | tokenizer.json **and** tekken.json | tokenizer.json (GPT2Tokenizer) | tokenizer.json |
| Vendor sampling guidance | thinking 0.6/0.95/20 (no greedy); non-thinking 0.7/0.8/20 | temperature 0.3 | none (widget temp 0) | gen. config 0.7/0.8/20, rep. penalty 1.05 |

Nemo's template text was read from the Hugging Face model API at HEAD (== pinned SHA); its sha256 equals the hash the repo recorded from its cached snapshot (RC-12). The repo's root-cause work shows that on transformers 5.16.1 the presence of `tekken.json` makes `AutoTokenizer` return a backend without a chat template (HE-5).

## 5. Licence text identity and commercial findings

| Candidate | Status | Licence text in repo? | sha256 of retrieved text | Git blob sha1 (== HF oid) |
|---|---|---|---|---|
| Qwen3-8B | **GRANTED** (Apache-2.0) | yes | `832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e` | `6634c8cc3133b3848ec74b9f275acaaa1ea618ab` |
| Mistral-Nemo-Instruct-2407 | **REQUIRES_COUNSEL** (Apache-2.0 (declared)) | **no LICENSE file** | none (reference Apache text hash `cfc7749b96f63bd3...` is not a repo file) | n/a |
| Phi-4 | **GRANTED** (MIT) | yes | `c49419617a6070bcb197cfe272f7007fdec3e790dbb529cb995473bd69c0bd51` | `700edcc5f42c4816520bc554926ad7e0d9e613d7` |
| Qwen2.5-3B-Instruct (unsloth) | **RESTRICTED_NONCOMMERCIAL** (qwen-research (Qwen RESEARCH LICENSE AGREEMENT, release 2024-09-19)) | yes (upstream repo; the unsloth mirror has none) | `ef52482bb785733093dc9a2e8edd8e764c77d12d8e9d8f10a80c9b547d32d0f9` | `ed317377ac0abff39f17eec693ce664f4b8152af` |

`GRANTED` means only that the licence text was retrieved, byte-verified and hashed. It is not a selection and not legal advice.

### Commercial-licence findings table

`REQUIRES_COUNSEL` = ambiguous or unresolved by the text.

| Candidate | Topic | Finding | Status | Counsel | Clause |
|---|---|---|---|---|---|
| Qwen3-8B (Apache-2.0) | commercial use | Permitted: the grant covers reproduce, prepare Derivative Works, publicly display/perform, sublicense and distribute the Work and Derivative Works in Source or Object form; no field-of-use, revenue or MAU limit appears in the text. | PERMITTED |  | Apache-2.0 s.2 |
| Qwen3-8B (Apache-2.0) | fine-tuned / derived weights | Permitted. Derivative Works may carry additional or different terms for ORNEUR's own modifications provided the Work's conditions are met. | PERMITTED |  | s.4 final paragraph |
| Qwen3-8B (Apache-2.0) | redistribution obligations | Must (a) give recipients a copy of the License, (b) mark modified files with prominent change notices, (c) retain copyright/patent/trademark/attribution notices in Source form, (d) carry NOTICE contents if a NOTICE file exists - the pinned repo has no NOTICE file. | OBLIGATED |  | s.4(a)-(d) |
| Qwen3-8B (Apache-2.0) | attribution / naming | No 'Built with' style obligation. s.6 grants no trademark licence: the Qwen/Alibaba names may be used only for reasonable and customary description of origin and NOTICE reproduction. | PERMITTED_WITH_LIMIT |  | s.6 |
| Qwen3-8B (Apache-2.0) | ORNEUR 'vendor names stripped from outputs' doctrine | The licence text does not require model OUTPUTS to name the vendor, but s.4(c)/(d) require attribution notices to travel with redistributed Derivative Works. Whether stripping vendor identity from product surfaces is compatible with those duties for hosted-only vs redistributed weights is a legal question. | AMBIGUOUS | **REQUIRES_COUNSEL** | s.4(c)-(d), s.6 |
| Qwen3-8B (Apache-2.0) | patent | Express contributor patent licence; terminates for a licensee that sues alleging the Work infringes a patent. | OBLIGATED |  | s.3 |
| Qwen3-8B (Apache-2.0) | acceptable-use policy | None in the LICENSE or in the model card at the pinned commit. | NONE_FOUND |  |  |
| Qwen3-8B (Apache-2.0) | using outputs to train other models | The licence text is silent on model outputs; no output-use restriction appears in LICENSE or README. Legal effect on distillation from Qwen3 outputs is not resolved by the text. | SILENT | **REQUIRES_COUNSEL** |  |
| Qwen3-8B (Apache-2.0) | weights as licensed subject matter | Apache-2.0 is a copyright/patent licence over a 'Work'; whether trained weights are copyrightable (and therefore what the grant operates on) varies by jurisdiction. Repo shortlist already asks for pro-forma counsel confirmation before public commercial release. | AMBIGUOUS | **REQUIRES_COUNSEL** |  |
| Qwen3-8B (Apache-2.0) | training-data provenance | Qwen3 model card discloses no training-data sources; indemnity-relevant provenance cannot be assessed. | NOT_DISCLOSED | **REQUIRES_COUNSEL** |  |
| Phi-4 (MIT) | commercial use | Permitted: use, copy, modify, merge, publish, distribute, sublicense and/or sell, without restriction, subject to the notice condition. | PERMITTED |  | MIT |
| Phi-4 (MIT) | fine-tuned / derived weights | Permitted (modify, merge, distribute, sublicense). MIT contains no copyleft. | PERMITTED |  |  |
| Phi-4 (MIT) | redistribution obligations | Include the copyright notice ('Copyright (c) Microsoft Corporation') and the permission notice in all copies or substantial portions. | OBLIGATED |  |  |
| Phi-4 (MIT) | attribution / naming | No trademark clause and no 'Built with' obligation in the text; the notice condition is the only attribution duty. | PERMITTED |  |  |
| Phi-4 (MIT) | patent | MIT is silent on patents (no express patent grant or retaliation clause, unlike Apache-2.0). Practical risk assessment belongs to counsel. | SILENT | **REQUIRES_COUNSEL** |  |
| Phi-4 (MIT) | acceptable-use policy | None in LICENSE. Model card 'Out-of-Scope Use Cases' says nothing in the card modifies or restricts the license; it asks developers to evaluate safety/fairness and comply with law. | NONE_FOUND |  |  |
| Phi-4 (MIT) | using outputs to train other models | Licence is silent on outputs; no restriction found in LICENSE or README. | SILENT | **REQUIRES_COUNSEL** |  |
| Phi-4 (MIT) | training-data provenance | data_summary_card.md: synthetic AI-generated data used; commercially licensed datasets used; some private third-party dataset information 'cannot be provided due to unavailability of the underlying data'. Upstream terms of the generator models used for synthetic data are not disclosed (NOT_VERIFIED). | PARTIALLY_DISCLOSED | **REQUIRES_COUNSEL** |  |
| Mistral-Nemo-Instruct-2407 (Apache-2.0 declared) | licence text | No LICENSE or NOTICE file exists in the repository at the pinned commit (tree listing). Apache-2.0 appears only as card metadata (license: apache-2.0) and README prose ('Released under the Apache 2 License'). No licence-text hash can be recorded from the repo, so the status is REQUIRES_COUNSEL, not GRANTED. The canonical Apache-2.0 text from apache.org is stored as a reference only. | UNVERIFIED_TEXT | **REQUIRES_COUNSEL** |  |
| Mistral-Nemo-Instruct-2407 (Apache-2.0 declared) | commercial use / derived weights / redistribution | If Apache-2.0 applies as declared, the same permissions and obligations as the Qwen3-8B rows apply (s.2-s.4). That conditional cannot be confirmed from a licence file in this repo. | CONDITIONAL_ON_DECLARATION | **REQUIRES_COUNSEL** |  |
| Mistral-Nemo-Instruct-2407 (Apache-2.0 declared) | attribution / naming / patent | Unknown beyond the generic Apache-2.0 terms; the model was 'trained jointly by Mistral AI and NVIDIA' (card) - whether NVIDIA contributes any separate notice is not stated. | AMBIGUOUS | **REQUIRES_COUNSEL** |  |
| Mistral-Nemo-Instruct-2407 (Apache-2.0 declared) | acceptable-use policy | None found. README Limitations: 'does not have any moderation mechanisms'; card metadata carries an extra_gated_description (privacy-policy text) although gated=false. | NONE_FOUND |  |  |
| Mistral-Nemo-Instruct-2407 (Apache-2.0 declared) | using outputs to train other models | No statement in the repo files. | SILENT | **REQUIRES_COUNSEL** |  |
| Mistral-Nemo-Instruct-2407 (Apache-2.0 declared) | training-data provenance | Not disclosed in the card ('large proportion of multilingual and code data'). | NOT_DISCLOSED | **REQUIRES_COUNSEL** |  |
| Qwen2.5-3B-Instruct, unsloth mirror (qwen-research) | commercial use | NOT granted. 'Non-Commercial' means research or evaluation purposes only; 2.a limits the grant to NON-COMMERCIAL PURPOSES ONLY; 2.b: commercial use requires requesting a licence from Alibaba Cloud (no terms, price or contact path in the text). | NOT_PERMITTED |  | 2.a-2.b, 1.i |
| Qwen2.5-3B-Instruct, unsloth mirror (qwen-research) | fine-tuned / derived weights | Non-commercial research/evaluation use of derivative works is permitted; commercial release of a derivative is not without a separate licence. | RESTRICTED |  | 2.a |
| Qwen2.5-3B-Instruct, unsloth mirror (qwen-research) | redistribution obligations | Give recipients a copy of the Agreement; mark modified files; retain in a 'Notice' file: 'Qwen is licensed under the Qwen RESEARCH LICENSE AGREEMENT, Copyright (c) Alibaba Cloud. All Rights Reserved.' | OBLIGATED |  | 3.a-3.c |
| Qwen2.5-3B-Instruct, unsloth mirror (qwen-research) | attribution / naming (training with outputs) | If the Materials OR ANY OUTPUTS OR RESULTS THEREFROM are used to create, train, fine-tune or improve an AI model that is distributed or made available, 'Built with Qwen' or 'Improved using Qwen' must be prominently displayed in the product documentation. NOT mentioned in the repo's base qualification or shortlist summaries. Conflicts with a doctrine of stripping vendor names from product surfaces. | OBLIGATED | **REQUIRES_COUNSEL** | 4.b |
| Qwen2.5-3B-Instruct, unsloth mirror (qwen-research) | indemnity / governing law | Licensee must defend, indemnify and hold harmless Alibaba Cloud against third-party claims (6.d); Agreement governed by PRC law with exclusive jurisdiction of the People's Courts in Hangzhou (8). Not summarised in the repo documents. | OBLIGATED | **REQUIRES_COUNSEL** | 6.d, 8 |
| Qwen2.5-3B-Instruct, unsloth mirror (qwen-research) | termination / IP suits | Licences terminate if the licensee sues Alibaba alleging the Materials or outputs infringe (5.c); Alibaba may terminate on breach and the licensee must delete and cease use (7.b). | OBLIGATED |  | 5.c, 7.b |
| Qwen2.5-3B-Instruct, unsloth mirror (qwen-research) | which text governs the unsloth mirror | The unsloth repo has NO LICENSE file (tree listing); its card declares license: other / qwen-research and links to the upstream file. The upstream text is recorded here by hash; the mirror's own legal status relative to upstream is a counsel question. | AMBIGUOUS | **REQUIRES_COUNSEL** |  |

## 6. Memory estimates (ALL UNTESTED_HYPOTHESIS)

Formulas (JSON `estimate_formulas`): BF16 weights `2P`; QLoRA static `(P-E)*0.5159 + 2E` (E = embeddings incl. untied lm_head); LoRA trainable `r*[(h+q)+2(h+kv)+(q+h)+3(h+I)]*layers`; optimizer state 16 B per trainable parameter (fp32 weight+grad+AdamW m,v); activations with gradient checkpointing `L*2*s*h + 34*s*h + s*V*6` bytes (batch 1, flash-attention), without `L*34*s*h + s*V*6`; peak = static + optimizer + activations + 1.5 GB, band 0.8x-1.4x (the package's band). GB = 1e9 bytes.

| | Qwen3-8B | Mistral-Nemo | Phi-4 | Qwen2.5-3B |
|---|---|---|---|---|
| BF16 weights (GB) | 16.4 | 24.5 | 29.3 | 6.2 |
| QLoRA static, NF4 + BF16 embeddings (GB) | 6.1 | 8.3 | 9.1 | 2.1 |
| LoRA r=16 trainable params (M) / optimizer state (GB) | 43.6 / 0.70 | 57.0 / 0.91 | 65.5 / 1.05 | 29.9 / 0.48 |
| LoRA r=64 trainable params (M) / optimizer state (GB) | 174.6 / 2.79 | 228.1 / 3.65 | 262.1 / 4.19 | 119.7 / 1.92 |
| Activations s=2048, ckpt / no ckpt (GB) | 2.8 / 12.1 | 2.8 / 15.9 | 2.4 / 15.5 | 2.3 / 7.0 |
| Activations s=4096, ckpt / no ckpt (GB) | 5.5 / 24.3 | 5.6 / 31.7 | 4.9 / 31.0 | 4.6 / 14.0 |
| QLoRA peak s=2048, ckpt (GB, band) | 11.0 (8.8-15.4) | 13.5 (10.8-18.9) | 14.1 (11.3-19.7) | 6.3 (5.1-8.9) |
| QLoRA peak s=4096, ckpt (GB, band) | 13.8 (11.0-19.3) | 16.3 (13.1-22.9) | 16.5 (13.2-23.1) | 8.7 (6.9-12.1) |
| QLoRA peak s=2048, NO ckpt (GB) | 20.4 | 26.6 | 27.1 | 11.0 |
| QLoRA peak s=4096, NO ckpt (GB) | 32.5 | 42.5 | 42.6 | 18.0 |
| KV cache per token (KiB, BF16) | 144 | 160 | 200 | 36 |
| KV cache per 8k sequence (GB) | 1.21 | 1.34 | 1.68 | 0.30 |
| Serving GPU memory, batch 8 x 8k ctx (GB) / class | 30.6 / 40GB-class | 40.8 / 48GB-class | 49.2 / 80GB-class | 11.2 / 16GB-class |
| 4-bit serving weights, 4.5 bit/param (GB, hypothesis) | 6.4 | 8.8 | 9.7 | 2.2 |

**Delta to the 2026-09-26 package** (both estimates; this pass derives activations explicitly):

| Candidate | QLoRA static pkg -> now | Peak 2k pkg -> now | Peak 4k pkg -> now | BF16 pkg -> now | KV 8k pkg -> now | LoRA r16 (M) pkg -> now |
|---|---|---|---|---|---|---|
| Qwen3-8B | 6.2 -> 6.1 | 12.5 -> 11.0 | 16.7 -> 13.8 | 16.4 -> 16.4 | 1.21 -> 1.21 | 43.6 -> 43.6 |
| Mistral-Nemo-Instruct-2407 | 8.5 -> 8.3 | 14.9 -> 13.5 | 19.0 -> 16.3 | 24.5 -> 24.5 | 1.34 -> 1.34 | 57.0 -> 57.0 |
| Phi-4 | 9.3 -> 9.1 | 15.3 -> 14.1 | 18.8 -> 16.5 | 29.3 -> 29.3 | 1.68 -> 1.68 | 65.5 -> 65.5 |

Reading: KV, BF16 and LoRA parameter counts reproduce the package exactly; static and peak differ by a few percent to ~20% (activation accounting) and stay inside the package's +/-40% band. Without gradient checkpointing the Nemo and Phi-4 peaks already exceed a 24 GB card at s=2048 (26.6 / 27.1 GB) and Qwen3-8B grows from 20.4 GB (s=2048) to 32.5 GB (s=4096); every figure remains an estimate and no run has validated any of them.

## 7. Hardware compatibility, serving engines, quantisation

- **BF16 / Ampere+ (DOCUMENTED_FACT):** BF16 needs compute capability >= 8.0; vLLM rejects BF16 on a Tesla T4 (cc 7.5) - [vllm#1157](https://github.com/vllm-project/vllm/issues/1157). On a T4 the model would run FP16 (numerics NOT tested here) or 4-bit. BF16 weights vs a 16 GB T4: Qwen3-8B 16.4 GB, Nemo 24.5 GB, Phi-4 29.3 GB do not fit; Qwen2.5-3B 6.2 GB fits (ESTIMATE).
- **vLLM (DOCUMENTED_FACT, docs tool-extracted):** `Qwen3ForCausalLM`, `Phi3ForCausalLM`, `Qwen2ForCausalLM` listed with LoRA and PP marks. `MistralForCausalLM`: listed in the repo's 2026-09-26 collection; the LoRA mark was not captured today (NOT_VERIFIED). Repo-observed under vLLM 0.29.0 / transformers 5.16.1: Qwen3 and Phi-4 served on the canonical configuration; Nemo only with `--tokenizer-mode mistral`.
- **Ollama (third-party registry):** `qwen3:8b` Q4_K_M; `mistral-nemo` default tag 7.1 GB (its page claims a '1000K' context, contradicting the vendor's 128k - not adopted); `phi4` 14B 16k. Qwen3's card states Ollama, LM Studio, MLX-LM, llama.cpp and KTransformers support Qwen3.
- **llama.cpp:** only the Qwen3 card statement; Nemo/Phi-4/Qwen2.5-3B NOT_VERIFIED. **Other quantised artifacts:** NOT_VERIFIED.

## 8. Serving-cost hypotheses (UNTESTED_HYPOTHESIS)

Assumptions (stated, not measured): H100 80 GB at the repo's persisted list rate USD 3.95/h (2,844 USD/month always-on, reproducing the package), decode memory-bandwidth-bound at an assumed 3.35 TB/s and 50% efficiency, 16 concurrent sequences, average context 2,048, no prefill or scheduling overhead. Cost per 1M output tokens = rate / (tokens/s x 3600) x 1e6, divided by the fraction of paid hours actually serving.

| | Qwen3-8B | Mistral-Nemo | Phi-4 | Qwen2.5-3B |
|---|---|---|---|---|
| Tokens/s (aggregate) | 1263 | 897 | 744 | 3632 |
| USD / 1M output tokens at 100% utilisation | 0.87 | 1.22 | 1.48 | 0.30 |
| USD / 1M output tokens at 30% utilisation | 2.89 | 4.08 | 4.92 | 1.01 |
| USD / 1M output tokens at 10% utilisation | 8.68 | 12.23 | 14.75 | 3.02 |
| QLoRA tokens/s on 1 H100 (15-25% of 989 TFLOP/s) | 3019-5031 | 2019-3365 | 1687-2811 | 8012-13354 |
| USD / 1M training tokens | 0.22-0.36 | 0.33-0.54 | 0.39-0.65 | 0.08-0.14 |

The dominant uncertainty is utilisation: at low utilisation an always-on GPU costs an order of magnitude more per token than the full-utilisation figure; the package's conclusion (scale-to-zero or 4-bit small-GPU serving regardless of base) is unchanged.

## 9. Published benchmarks and their limitations (vendor-reported; none reproduced)

| Benchmark | Qwen3-8B thinking | Qwen3-8B non-thinking | Qwen2.5-3B-Instruct (Qwen3 report baseline) |
|---|---|---|---|
| MMLU-Redux | 87.5 | 79.5 | 64.4 |
| GPQA-Diamond | 62.0 | 39.3 | 30.3 |
| C-Eval | 83.4 | 77.9 | 68.2 |
| LiveBench 2024-11-25 | 67.1 | 53.5 | 23.8 |
| IFEval strict prompt | 85.0 | 83.0 | 58.2 |
| Arena-Hard | 85.8 | 79.6 | 23.7 |
| MATH-500 | 97.4 | 87.4 | 67.2 |
| AIME'24 | 76.0 | 29.1 | 6.7 |
| AIME'25 | 67.3 | 20.9 | 4.2 |
| BFCL v3 | 68.1 | 60.2 | 50.4 |
| LiveCodeBench v5 | 57.5 | 22.8 | 9.2 |
| Multi-IF | 71.2 | 69.2 | 32.3 |
| INCLUDE | 67.8 | 62.5 | 43.8 |
| MMMLU 14 languages | 74.4 | 66.9 | 51.8 |

Phi-4 (model card, OpenAI simple-evals): MMLU 84.8, GPQA 56.1, MGSM 80.6, MATH 80.4, HumanEval 82.6, SimpleQA 3.0, DROP 75.5. Mistral-Nemo (model card): HellaSwag (0-shot) 83.5%, Winogrande (0-shot) 76.8%, OpenBookQA (0-shot) 60.6%, CommonSenseQA (0-shot) 70.4%, TruthfulQA (0-shot) 50.3%, MMLU (5-shot) 68.0%, TriviaQA (5-shot) 73.8%, NaturalQuestions (5-shot) 31.2%.

Limitations that apply to every number above: (1) VENDOR_REPORTED - the publisher chose benchmarks, prompts, harness and decoding (Qwen3: thinking up to 32,768 output tokens, temp 0.6; non-thinking temp 0.7 with presence penalty 1.5); (2) public benchmarks may be contaminated and the corpora are not inspectable from outside (Phi-4 trains on synthetic 'textbook-like' data and states a June-2024 cutoff; Qwen3 and Nemo disclose no data sources); (3) harness differences make cross-vendor comparison unsound - Phi-4's own card notes simple-evals' strict formatting penalises Llama; Nemo's card gives no harness and does not say whether the numbers are base or instruct; (4) Qwen3 and Qwen2.5 rows were taken through the tool's PDF query extraction; (5) none measures ORNEUR's contract-style exact-output, JSON-schema or refusal/evidence behaviour, which is what the frozen eval must test; (6) the Qwen2.5-3B column is a baseline inside a competing model's report, not a Qwen2.5 card result.

Multilingual: Qwen3 '100+ languages and dialects' (MMMLU-14 74.4/66.9); Nemo en/fr/de/es/it/pt/ru/zh/ja with per-language MMLU 59.0-64.6; Phi-4 'primarily English', multilingual ~8% and 'not intended to support multilingual use'; Qwen2.5-3B '29+ languages'. Safety: Qwen3 and Qwen2.5-3B cards publish no safety evaluation; Nemo states 'no moderation mechanisms'; Phi-4 describes SFT + iterative DPO safety post-training and Microsoft AIRT red-teaming but its card contains no numbers (they are in the technical report, not re-read).

## 10. Known fine-tuning / deployment issues

Repo control program (INDEPENDENTLY_REPRODUCED): Qwen3-8B attempt 5 PASS/FAIL/PASS (served; `2 + 3 = 5`); Nemo attempts 1-2 HTTP 400 template resolution, attempt 3 (native tokenizer mode) FAIL x3 (verbose prose); Phi-4 attempt 1 PASS/FAIL/FAIL (C truncated at 64 tokens). No control is RUNTIME_QUALIFIED; capability is UNPROVEN. These are response-format results, not capability evidence (package s.1).

Public trackers (DOCUMENTED_FACT, excerpts only): [vllm#7739](https://github.com/vllm-project/vllm/issues/7739) Nemo + `--tokenizer-mode mistral` HTTP 400 (fixed in 2024 vLLM); HF [Nemo discussion 14](https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407/discussions/14) (system role in template) and [61](https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407/discussions/61) (alternation error after tool use); [unsloth#2771](https://github.com/unslothai/unsloth/issues/2771) completion-only training with Qwen3; [Unsloth Phi-4 write-up](https://unsloth.ai/blog/phi4) pad/eos bug history; NVIDIA Automodel tracker lists Phi-4 PEFT fused-QKV splitting.

## 11. Provisional ranking (NON-BINDING, NOT A SELECTION)

> NOT A SELECTION. No foundation model is selected, promoted or recommended as final by this document. Selection requires the mandatory frozen capability evaluation (GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26 section 5) and explicit founder authorization. The ordering below covers at most 24 of 100 weighted points, none of them capability points; the pre-registered selection rule (lead >= 5 weighted points AND a paired-bootstrap 95% interval excluding 0 on the eval axes) cannot be applied and is NOT applied.

Gates (pre-registered A, B, K):

| Candidate | A architecture | B memory | K licence |
|---|---|---|---|
| Qwen3-8B | PASS | PASS_ON_PAPER | **PASS** - Apache-2.0 text retrieved and hashed (GRANTED); advisory counsel items remain (see license findings) |
| Mistral-Nemo-Instruct-2407 | PASS | PASS_ON_PAPER | **CONDITIONAL_REQUIRES_COUNSEL** - Apache-2.0 declared but no license file in the repo at the pinned commit; no text hash |
| Phi-4 | PASS | PASS_ON_PAPER | **PASS** - MIT text retrieved and hashed (GRANTED); no express patent grant (counsel advisory) |
| Qwen2.5-3B-Instruct (unsloth) | PASS | PASS_ON_PAPER | **FAIL** - qwen-research: commercial use not granted (RESTRICTED_NONCOMMERCIAL) |

Criteria (weights from the package; 100 total over F-R):

| ID | Criterion | Weight | State | Qwen3-8B | Nemo | Phi-4 |
|---|---|---|---|---|---|---|
| F | Instruction-following | 12 | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED |
| G | Structured output | 12 | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED |
| H | Reasoning potential | 12 | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED |
| I | Coding potential | 12 | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED |
| J | Context-window characteristics | 4 | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED |
| D | Tokenizer/chat-template stability | 4 | SCORED_FROM_DOCUMENTED_EVIDENCE | 3 | 1 | 4 |
| E | Runtime compatibility | 4 | SCORED_FROM_DOCUMENTED_EVIDENCE | 4 | 2 | 4 |
| L | Ecosystem/tooling maturity | 4 | SCORED_FROM_DOCUMENTED_EVIDENCE | 3 | 2 | 3 |
| M | Training-stability evidence | 4 | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED |
| N | Quantization compatibility | 4 | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED |
| O | Inference cost | 6 | SCORED_FROM_DOCUMENTED_EVIDENCE | 6.0 | 4.01 | 3.35 |
| P | Expected training cost | 6 | SCORED_FROM_DOCUMENTED_EVIDENCE | 6.0 | 4.01 | 3.35 |
| Q | Differentiated ORNEUR behaviour | 8 | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED |
| R | Migration path to ORNEUR-owned families | 8 | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED |

| Documented-subset total (max 24 of 100) | Qwen3-8B 22.0 | Mistral-Nemo-Instruct-2407 13.02 | Phi-4 17.7 |
|---|---|

Rubrics: **D** - 4 = template resolves on the canonical HF path in repo evidence with no mode switch or injected defaults; 3 = resolves but contains a mode switch/state needing a deliberate SFT-template decision; 2 = resolves only with a documented workaround; 1 = canonical-path resolution FAILED on the pinned stack (native mode needed); 0 = unresolvable. Candidates without repo runtime evidence are NOT_EVALUATED. **E** - 4 = loaded and served on the canonical configuration under the pinned vLLM in repo evidence; 2 = served only after a non-canonical candidate configuration; 0 = did not serve. Exact-output smoke results are deliberately ignored (they are criteria F/G material). **L** - 4 = vLLM docs list the architecture with a LoRA mark and no pitfall is documented; 3 = listed with LoRA and one documented fine-tuning/export pitfall; 2 = listed but non-default modes needed in repo evidence plus public tracker history; NOT_EVALUATED without evidence. **O** - 6 x (smallest BF16 weight footprint among gate-eligible candidates) / (candidate BF16 weight footprint). ESTIMATE-derived: the criterion's 'at the frozen quality bar' clause cannot be applied. **P** - 6 x (smallest parameter count among gate-eligible candidates) / (candidate parameter count), because QLoRA FLOPs per token scale with 6 x params. ESTIMATE-derived.

Qwen2.5-3B-Instruct is **excluded from weighted scoring** (gate K FAIL: non-commercial licence). The ten IDENTITY_ONLY landscape models are not scored. Capability criteria F, G, H, I and also J, M, N, Q, R are **NOT_EVALUATED**: they need the frozen evaluation and pilot (package s.5). The subset totals are not a lead under the pre-registered rule (>= 5 weighted points AND a paired-bootstrap CI excluding 0) and must not be read as a recommendation.

## 12. Reproducible harness errors in the control program (diagnose / propose only; nothing re-run)

| ID | Finding | Evidence | Proposed fix (NOT applied) | Offline? | Needs owner authorization / re-pin |
|---|---|---|---|---|---|
| HE-1 | **Smoke prompts B and C do not instruct the output format that the acceptance expects** - B sends the bare user message '2 + 3' and requires content to equal exactly '5'; C sends 'Return valid JSON:\n{"status":"ready"}' and requires the whole content to parse as that object. Qwen3-8B answered '2 + 3 = 5' (correct); Phi-4 answered '2 + 3 equals 5.' and, for C, 'The JSON you provided is already valid. Here it is again for clarity: ...'; Nemo answered with a worked calculation and fenced JSON. | INDEPENDENTLY_REPRODUCED: repo:orca/eval/locked_smoke_protocol.py ; docs/orneur/phase-21/evidence/GENESIS_CONTROL_PHI4_RUNTIME_QUALIFICATION_2026-09-24.json | Author a v2 locked protocol with explicit output-format instructions ('Reply with only the digit', 'Output only a JSON object') and re-pin; replay the persisted raw outputs through a semantic acceptance function (reevaluate-smokes mode exists) to report what each model would score under a tolerant policy, as a separate non-qualifying column. | yes | yes |
| HE-2 | **Output-token budget differs per control and is outside the locked-protocol fingerprint** - smoke_max_tokens is 1024 for Qwen3-8B but 64 for Mistral-Nemo and Phi-4 (scripts/phase21b_4_20_control_runtime_qualification.py lines 79/87/94). Phi-4 smoke C ended with finish_reason='length' after exactly 64 completion tokens while Nemo's C (51 tokens) and Qwen's finished with 'stop'. | INDEPENDENTLY_REPRODUCED: repo:scripts/phase21b_4_20_control_runtime_qualification.py ; docs/orneur/phase-21/evidence/GENESIS_CONTROL_PHI4_RUNTIME_QUALIFICATION_2026-09-24.json | Pin one max_tokens in the protocol; classify finish_reason='length' as INCONCLUSIVE_TRUNCATED (not MODEL_RUNTIME failure); add an offline unit test over the persisted raw responses. | yes | yes |
| HE-3 | **Runtime qualification and behavioural contract are conflated in one acceptance gate** - RUNTIME_QUALIFIED requires every smoke to be exactly satisfied (compute_smoke_acceptance), so a server that loaded the pinned identity, answered HTTP 200 x3 with finish_reason=stop and clean cleanup is recorded runtime FAILED. | INDEPENDENTLY_REPRODUCED: repo:orca/eval/control_runtime_qualification.py ; docs/orneur/phase-21/GENESIS_CONTROL_RUNTIME_QUALIFICATION_MATRIX_2026-09-24.md | Report two independent columns - SERVING_OK (identity, BF16, HTTP 200, non-empty, finish_reason=stop, cleanup) and CONTRACT_COMPLIANCE (exact/semantic) - without changing the existing frozen records; derive them offline from persisted raw outputs. | yes | yes |
| HE-4 | **Smoke A is streamed, B and C are not** - Locked protocol sets stream=true only for A. A passed for Qwen3 and Phi-4 and failed for Nemo with different transports than B/C. | INDEPENDENTLY_REPRODUCED: repo:orca/eval/locked_smoke_protocol.py | Add a CPU test that feeds the recorded raw A response through the SSE assembler and compares with a non-streaming replay in a mock; or run all smokes in both modes under a future authorization. | yes | yes |
| HE-5 | **Mistral-Nemo: HF chat-template resolution fails because tekken.json flips AutoTokenizer to MistralCommonBackend** - Attempts 1-2: HTTP 400 'default chat template is no longer allowed ... provide a chat template'. Repo CPU analysis shows the pinned tokenizer_config.json does contain a 3,945-byte chat_template (sha256 e4676cb5...), but with tekken.json present transformers 5.16.1 returns MistralCommonBackend (no chat_template, get_chat_template raises); without tekken.json the template resolves and renders '<s>[INST]...[/INST]'. | INDEPENDENTLY_REPRODUCED: repo:docs/orneur/phase-21/evidence/GENESIS_MISTRAL_NEMO_CHAT_TEMPLATE_ROOT_CAUSE_ANALYSIS_V2_2026-09-26.json | Already addressed by candidate `mistral_nemo_native_v1` (--tokenizer-mode mistral, executed once as attempt 3). Offline alternatives for future work: stage a snapshot variant without tekken.json (changes the pinned file set and its hash manifest) or add a CPU preflight asserting 'tokenizer.chat_template is not None' before any GPU launch. | yes | no |
| HE-6 | **HTTP error bodies were not captured in Nemo attempt 1** - urllib raised HTTPError before status/body were recorded; attempt 1 was first classified MODEL_RUNTIME then re-classified UNATTRIBUTED_REQUEST_REJECTION after audit. | INDEPENDENTLY_REPRODUCED: repo:docs/orneur/phase-21/GENESIS_CONTROL_RUNTIME_QUALIFICATION_MATRIX_2026-09-24.md | None needed beyond keeping the regression test for error-body capture. | yes | no |
| HE-7 | **Qwen3-8B attempt 1 died on an uncaught builtin TimeoutError** - Modal 1.5.5 FunctionCall.get(timeout=) raises the builtin TimeoutError; the harness did not catch it; attempt 1 was cancelled after 34.6 s without serving the model. | INDEPENDENTLY_REPRODUCED: repo:docs/orneur/phase-21/GENESIS_CONTROL_RUNTIME_QUALIFICATION_MATRIX_2026-09-24.md | Add a stand-in test that raises builtin TimeoutError and asserts the poll loop handles it (CI cannot import the real Modal SDK). | yes | no |
| HE-8 | **Greedy decoding is implicit: vLLM applies the model's generation_config.json defaults for fields the request omits** - Repo raw log (Qwen3 attempt 5, line 78): 'Default vLLM sampling parameters have been overridden by the model's generation_config.json: {temperature: 0.6, top_k: 20, top_p: 0.95}'. The locked request sends temperature, top_p, seed and max_tokens only. | INDEPENDENTLY_REPRODUCED: repo:docs/orneur/phase-21/evidence/GENESIS_CONTROL_QWEN3_8B_MODAL_H100_ATTEMPT5_RAW_LOG_2026-09-24.txt | Record the effective sampling parameters in every evidence record (parse the vLLM startup warning) and add --generation-config vllm (or explicit top_k=-1, repetition_penalty=1.0) to a future protocol revision. | yes | yes |
| HE-9 | **Qwen3 attempt 4 judged TECHNICAL_SUCCESS then reclassified; attempt-5 record carried a stale reasoning_mode** - Attempt 4 used the default thinking-on template and earlier prompt wording, was first judged success, and was reclassified TECHNICAL_FAILURE by the audit; the attempt-5 record initially said reasoning_mode ENABLED while 0 reasoning tokens were produced (metadata_correction added). | INDEPENDENTLY_REPRODUCED: repo:docs/orneur/phase-21/GENESIS_CONTROL_RUNTIME_QUALIFICATION_MATRIX_2026-09-24.md | Keep the validator rule that metadata must be derived from the effective configuration; add a test asserting reasoning_tokens==0 whenever enable_thinking=false is recorded. | yes | no |
| HE-10 | **Settlement attribution: shared app description matching, aged-out apps and a false volume-metering block** - In-run settlement matched itemized rows by shared app description (included another attempt's app); an aged-out stopped app made reconciliation fail; a 0.196 USD 'volumes' meter caused a false financial block that the later gate correction cleared. | INDEPENDENTLY_REPRODUCED: repo:docs/orneur/phase-21/GENESIS_CONTROL_RUNTIME_QUALIFICATION_MATRIX_2026-09-24.md ; docs/orneur/phase-21/GLM_5_3_FLASH_COMPUTE_COST_INCIDENT_2026-09-23.md | None; keep the CPU tests. Note the decision package's 'owner billing stayed zero' is scoped to the 21B.4.20 control program, not the earlier GLM-5.3-Flash run. | yes | no |
| HE-11 | **Criteria list is inconsistent across documents (A-Q in the blueprint vs A-R in the decision package)** - PRETRAINING_FOUNDATION_QUALIFICATION_BLUEPRINT D1 says 'A-Q (gates A,B,K; weighted F-Q)'; the decision package defines A-R, and its weights sum to 100 only if R (8 points) is included. | DOCUMENTED_FACT: repo:docs/orneur/status/PRETRAINING_FOUNDATION_QUALIFICATION_BLUEPRINT.md ; docs/orneur/phase-21/GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26.md | Correct the blueprint reference in a future (non-frozen) edit; this reassessment follows the package (A-R). | yes | no |

These proposals respect the frozen prohibition on further control retries: they concern offline replay, protocol re-authoring and evidence-schema changes; none triggers a provider run.

## 13. What changed vs the 2026-09-26 package

- **CH-1** (DOCUMENTED_FACT): No drift: every pinned revision is still the repository HEAD on 2026-10-11 (15 days after the package); weights and tokenizer objects are unchanged (LFS sha256 identical to the repo manifests).
- **CH-2** (DOCUMENTED_FACT): Licence evidence upgraded from metadata tags to byte-verified texts: Qwen3-8B Apache-2.0 (git blob 6634c8cc..., identical to canonical Apache-2.0 with 'Copyright 2024 Alibaba Cloud'), Phi-4 MIT (git blob 700edcc5..., CRLF), Qwen research licence (git blob ed317377...). Nemo has no licence text to hash.
- **CH-3** (DOCUMENTED_FACT): NEW finding: Mistral-Nemo-Instruct-2407 ships no LICENSE file at the pinned commit; its gate K moves from 'PASS' to 'CONDITIONAL / REQUIRES_COUNSEL' in this document.
- **CH-4** (DOCUMENTED_FACT): NEW finding: the Qwen research licence contains output-use and indemnity clauses (4.b, 6.d) absent from the repo summaries; relevant to the current canonical base and to any plan that distills from Qwen outputs.
- **CH-5** (DOCUMENTED_FACT): Chat-template identity is now hashed (Qwen3-8B 4,168 B, Phi-4 462 B, Qwen2.5-3B 2,507 B, Nemo 3,945 B) and the Nemo hash independently matches the repo's recorded hash. The package recorded template behaviour but no template hashes for the candidates.
- **CH-6** (DOCUMENTED_FACT): Added (the package deliberately omitted them): vendor benchmark tables with explicit limitations, multilingual and safety statements, serving/quantization availability, public tracker issues, and serving-cost hypotheses.
- **CH-7** (UNTESTED_HYPOTHESIS): Estimates re-derived with explicit formulas (package static/peak figures agree within its +/-40% band; KV, BF16 and LoRA parameter counts reproduce exactly). Package range-based conclusion 'any of the three fits QLoRA' unchanged but still unproven.
- **CH-8** (DOCUMENTED_FACT): Landscape-admitted dense models of 3-14B (10) were re-checked for identity only: SHAs, parameter counts and licence tags unchanged since 2026-09-26. Gemma 4 licence_link resolves to a hosted Apache-2.0 page (not a repo file); Phi-4-mini carries the custom_code tag.
- **CH-9** (INDEPENDENTLY_REPRODUCED): New reproducible harness diagnoses from persisted evidence: unequal max_tokens (1024 vs 64) with a truncated Phi-4 smoke, prompts that do not request the accepted format, implicit generation_config sampling defaults (HE-1, HE-2, HE-8).
- **CH-10** (DOCUMENTED_FACT): Decision unchanged: FOUNDATION_DECISION_REQUIRES_CAPABILITY_EVAL. Nothing here selects, promotes or authorizes anything.

### Repo claims checked against primary sources

| ID | Verdict | Statement |
|---|---|---|
| RC-1 | **CONFIRMED** | Package s.3 gives Qwen3-8B context '32,768 native; 131,072 with YaRN' and the landscape marks config 40,960 vs vendor 32,768 as DIFFERS. Primary sources confirm BOTH numbers and the model card explains the gap (40,960 = 32,768 output + 8,192 prompt reservation). Not a contradiction; SFT sequence-length design should use 32,768 as the native figure. (DOCUMENTED_FACT) |
| RC-2 | **WEAKER_THAN_STATED** | Package s.3 and the Stage-0 matrix treat Mistral-Nemo's Apache-2.0 as established ('K: PASS', 'commercially clean') on the metadata tag. At the pinned commit the repository contains no LICENSE or NOTICE file (tree listing, 18 files); only the tag and README prose declare the licence. The package's K=PASS is therefore evidence-grade 'declared', not 'text verified'. (DOCUMENTED_FACT) |
| RC-3 | **INCOMPLETE_SUMMARY** | GENESIS_BASE_MODEL_QUALIFICATION and the shortlist summarise the qwen-research licence as non-commercial with attribution duties (a)-(c). The licence text also contains 4.b (display 'Built with Qwen'/'Improved using Qwen' when the Materials OR THEIR OUTPUTS are used to train/improve a distributed AI model), 6.d (indemnify Alibaba Cloud), 7.b (delete on termination) and 8 (PRC law, Hangzhou courts). These obligations are not in the repo summaries. (DOCUMENTED_FACT) |
| RC-4 | **INTERNAL_INCONSISTENCY** | The Stage-0 license matrix says the controls (Qwen3-8B, Mistral-Nemo, Phi-4) are 'control use only, never a candidate finalist' and the 2026-09-26 landscape marks them BASELINE_ONLY_CONTROL with admitted_to_capability_eval=false, while the same day's decision package calls them the 'admitted options' for Genesis Capability Eval v0 and this task's brief calls them finalists. The repo's own documents disagree on whether the three controls are in the candidate pool. (DOCUMENTED_FACT) |
| RC-5 | **DOCUMENT_DRIFT** | Blueprint WS-D D1 refers to pre-registered criteria 'A-Q (gates A,B,K; weighted F-Q)'; the decision package defines A-R and its 14 weighted weights sum to 100 only with R (8). This reassessment follows the package. (DOCUMENTED_FACT) |
| RC-6 | **CONFIRMED** | Package KV-cache per 8k sequence (1.21/1.34/1.68 GB) and bf16 weights (16.4/24.5/29.3 GB) are reproduced exactly by the formulas applied to primary-source config values; parameter counts (8.19/12.25/14.66 B) equal the safetensors totals. (DOCUMENTED_FACT) |
| RC-7 | **CONSISTENT_WITHIN_ESTIMATE_BAND** | Package QLoRA static/peak estimates are within the package's own +/-40% band of this pass's independently derived figures but not identical (formulas differ in activation accounting); see the delta table. Both are ESTIMATES; neither is a measurement. (UNTESTED_HYPOTHESIS) |
| RC-8 | **NOT_VERIFIED** | Package s.3 says Phi-4 uses 'fused qkv / gate_up projections'. The weight index (model.safetensors.index.json) was not read in this pass; vLLM/Automodel tracker evidence mentions fused QKV for Phi-4, but the gate_up fusion claim is NOT_VERIFIED here. (NOT_VERIFIED) |
| RC-9 | **SCOPE_CAVEAT** | Package s.1 'owner billing remained zero across the controlled program' is correct for the 21B.4.20 control program, but the earlier 21B.4.13 GLM-5.3-Flash run did bill the owner USD 3.52; the sentence should not be read as program-wide. (DOCUMENTED_FACT) |
| RC-10 | **CONFIRMED** | Shortlist: 'Phi-4 model card last modified 2026-07-14' is confirmed (API lastModified 2026-07-14T14:22:25Z at head sha == pinned sha). The pinned commit therefore post-dates the Dec-2024 release and includes data_summary_card.md (updated 24-Nov-2025); weights are the LFS objects the repo hashed on 2026-09-24 (identical sha256). (DOCUMENTED_FACT) |
| RC-11 | **CONFIRMED** | All 15 revision SHAs checked (3 controls, unsloth+upstream Qwen2.5-3B, 10 landscape-admitted dense models) still equal the repo's recorded SHAs; the three out-of-scope names that sounded unusual (Qwen3.8-27B, Mistral-Small-4-119B-2603, GLM-5.3-Flash) exist at the recorded revisions. No repo candidate is NOT_FOUND_AT_PRIMARY_SOURCE. (DOCUMENTED_FACT) |
| RC-12 | **CONFIRMED** | Mistral-Nemo chat template sha256 e4676cb5... recorded by the repo (from the cached snapshot) equals the sha256 of the template read from the Hugging Face model API at HEAD (== pinned sha) today, and tokenizer_config.json is 181,297 bytes in both. The repo's recorded template sizes for Qwen3-8B (4,168 chars) and Phi-4 (462 chars) also equal the byte lengths of the byte-verified templates stored here. (INDEPENDENTLY_REPRODUCED) |
| RC-13 | **CONFIRMED** | Weights integrity: every LFS sha256 and size of the three controls at the pinned commits equals the hf_lfs_sha256 values in the repo's pre-cache manifests (18 weight/tokenizer objects, 0 mismatches). (INDEPENDENTLY_REPRODUCED) |

## 14. NOT_VERIFIED

- NV-1: llama.cpp support for Mistral-Nemo, Phi-4 and Qwen2.5-3B: the README query returned nothing; only the Qwen3 model card's statement that llama.cpp supports Qwen3 is recorded.
- NV-2: Availability and quality of third-party quantised artifacts (GGUF/AWQ/GPTQ) beyond Ollama Q4_K_M listings was not enumerated.
- NV-3: vLLM docs LoRA mark for MistralForCausalLM in the current docs: the tool's table extraction omitted the row (the repo's 2026-09-26 collection lists the architecture).
- NV-4: Mistral-Nemo tokenizer_config bos/eos/unk string values: the tool strips angle-bracket tokens; only ids (config.json) and the repo's rendering '<s>[INST]...[/INST]' are recorded.
- NV-5: Phi-4 technical report (arXiv:2412.08905) safety numbers and contamination/decontamination methodology were not re-read; only the model card is recorded.
- NV-6: Qwen3 pretraining-token count and language count: the extraction did not return them; only the model card's '100+ languages and dialects' is recorded.
- NV-7: Mistral-Nemo benchmark harness, prompts and base-vs-instruct status are not stated by the vendor.
- NV-8: FP16 numerical behaviour of Qwen3-8B / Nemo / Phi-4 on T4-class (compute capability 7.5) GPUs - never run.
- NV-9: GPU rental prices other than the repo's persisted H100 list rate (USD 3.95/h), and the H100 memory bandwidth figure (3.35 TB/s assumed), are inputs that were not re-fetched.
- NV-10: Full licence texts of the ten IDENTITY_ONLY landscape candidates (Qwen3.5, Gemma 4, Granite 4.2, Olmo 3, SmolLM3, Phi-4-mini, Ministral 3) were not retrieved or hashed; their licence status is TAG_ONLY_UNVERIFIED or REQUIRES_COUNSEL.
- NV-11: Content of the cited HF discussion pages and GitHub issues was read from search excerpts only.
- NV-12: Whether trained weights are copyrightable / what an Apache-2.0 or MIT grant operates on: a legal question not answered here.

## 15. Landscape-admitted dense models (identity only, not scored)

| Model | Revision | Params | Licence tag | Licence status here | Note |
|---|---|---|---|---|---|
| `HuggingFaceTB/SmolLM3-3B` | `a07cc9a04f16` | 3,075,098,624 | apache-2.0 | TAG_ONLY_UNVERIFIED | text-generation; language tags en fr es it pt zh ar ru |
| `Qwen/Qwen3.5-4B` | `851bf6e806ef` | 4,659,865,088 | apache-2.0 | TAG_ONLY_UNVERIFIED | image-text-to-text pipeline (multimodal checkpoint); hybrid full/linear attention per repo landscape |
| `Qwen/Qwen3.5-9B` | `c20223623576` | 9,653,104,368 | apache-2.0 | TAG_ONLY_UNVERIFIED | image-text-to-text pipeline (multimodal checkpoint); hybrid attention per repo landscape |
| `allenai/Olmo-3-7B-Instruct` | `6e5971d9eba4` | 7,298,011,136 | apache-2.0 | TAG_ONLY_UNVERIFIED | text-generation; English only per card language tag |
| `google/gemma-4-E4B-it` | `ee0ef6023621` | 7,996,156,490 | apache-2.0 | REQUIRES_COUNSEL | any-to-any pipeline; license_link resolves to a hosted Apache-2.0 page (ai.google.dev/gemma/apache_2), not a repo LICENSE file |
| `google/gemma-4-12B-it` | `707f0a3b8a3c` | 11,959,730,224 | apache-2.0 | REQUIRES_COUNSEL | any-to-any pipeline; gemma4_unified architecture; license_link as above |
| `ibm-granite/granite-4.2-3b` | `e459acceac81` | 3,659,737,600 | apache-2.0 | TAG_ONLY_UNVERIFIED | text-generation; tags reasoning, thinking, tool-calling; 12 languages in card tags |
| `ibm-granite/granite-4.2-8b` | `f8de16cdcdbc` | 8,791,592,960 | apache-2.0 | TAG_ONLY_UNVERIFIED | text-generation; tags reasoning, thinking, tool-calling; 12 languages in card tags |
| `microsoft/Phi-4-mini-instruct` | `cfbefacb9925` | 3,836,021,760 | mit | TAG_ONLY_UNVERIFIED | carries the custom_code tag (trust_remote_code question unresolved in this pass) |
| `mistralai/Ministral-3-14B-Reasoning-2512` | `51f9210f3cd2` | 13,945,031,680 | apache-2.0 | TAG_ONLY_UNVERIFIED | mistral3 architecture, mistral-common tag, inference:false in card metadata |

These were re-checked for SHA/parameter/licence-tag drift only; architecture rows reuse the repo's 2026-09-26 collection of the same revision. Hybrid-attention and multimodal checkpoints (Qwen3.5, Gemma 4) carry the runtime caveats the repo landscape already records.

## 16. How to verify (offline)

```
python3 scripts/foundation/verify_evidence.py          # schema, hashes, licence rules, ranking guards; no network
python3 scripts/foundation/build_evidence.py           # regenerate JSON + this report from evidence_data.py
pytest tests/test_foundation_evidence_schema.py
```

