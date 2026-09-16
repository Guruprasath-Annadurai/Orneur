# Genesis 1 — Base Model Qualification

Phase 21B. Verified against authoritative upstream sources (Hugging Face
model repositories, their `config.json`, `README.md` YAML front matter,
and `LICENSE` file, plus the HF API's own `sha`/`lastModified` fields) --
retrieved live during this closure, not recalled from memory. Retrieval
date: **2026-09-16**.

## Currently selected base (unchanged by this document)

`orca/registry/model_spec.py::MODEL_SPECS["genesis"].base_model` =
`unsloth/Qwen2.5-3B-Instruct`, `base_model_status="SELECTED"`. This
document qualifies that existing selection; it does **not** change it.

## Repository identity

| Field | Value | Source |
|---|---|---|
| Selected repo | `unsloth/Qwen2.5-3B-Instruct` | `model_spec.py` (unchanged) |
| Selected repo commit SHA | `7548fff1f997f57b2e9e8ab1ec7be96949b00ed0` | `https://huggingface.co/api/models/unsloth/Qwen2.5-3B-Instruct` (`sha` field), retrieved 2026-09-16 |
| Selected repo last modified | 2025-03-06T00:08:34Z | same source |
| Upstream original repo | `Qwen/Qwen2.5-3B-Instruct` | `unsloth/...`'s own `config.json`: `"_name_or_path": "Qwen/Qwen2.5-3B-Instruct"`; also `README.md` front matter `base_model: Qwen/Qwen2.5-3B` |
| Upstream original commit SHA | `aa8e72537993ba99e69dfaafa59ed015b17504d1` | `https://huggingface.co/api/models/Qwen/Qwen2.5-3B-Instruct` (`sha` field) |
| Upstream original last modified | 2024-09-25T12:33:00Z | same source |
| Upstream organization | Alibaba Cloud (Qwen team) | `LICENSE` file text: `"We" (or "Us") shall mean Alibaba Cloud` |

`unsloth/Qwen2.5-3B-Instruct` is a repack of the identical upstream Qwen
weights for faster/lower-memory fine-tuning via the Unsloth library --
not an independently retrained or architecturally modified model
(confirmed by `config.json`'s `_name_or_path` field pointing directly at
the Qwen original, and the `unsloth_fixed: true` config flag denoting a
compatibility fix, not a retrain).

## Architecture (from `unsloth/Qwen2.5-3B-Instruct`'s live `config.json`)

| Field | Value |
|---|---|
| `architectures` | `Qwen2ForCausalLM` |
| `model_type` | `qwen2` |
| `hidden_size` | 2048 |
| `intermediate_size` | 11008 |
| `num_hidden_layers` | 36 |
| `num_attention_heads` | 16 |
| `num_key_value_heads` | 2 (GQA) |
| `max_position_embeddings` | 32768 |
| `rope_theta` | 1000000.0 |
| `vocab_size` | 151936 |
| `torch_dtype` | bfloat16 |
| `tie_word_embeddings` | true |
| Nominal parameters | 3.09B total / 2.77B non-embedding (per upstream Qwen model card) |
| Context length | 32,768 tokens (full), 8,192 generation -- note: `model_spec.py::context_length=4096` is a **training-time sequence-length choice**, not the model's architectural ceiling; this document does not change that field, but flags the distinction so it is not mistaken for the model's true context capability |

## Tokenizer

Same repo as the base model (`unsloth/Qwen2.5-3B-Instruct`); vocab size
151,936; no custom tokenizer training found anywhere in the repository
(consistent with the Phase 21A audit's finding). Tokenizer revision is
pinned to the same commit SHA as the base model, since HF repos version
tokenizer and model files together.

## License -- MATERIAL FINDING

**License: `qwen-research` (SPDX "other"), per the repo's own
`README.md` YAML front matter:**

```yaml
license: other
license_name: qwen-research
license_link: https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/main/LICENSE
```

The `unsloth/Qwen2.5-3B-Instruct` repack's own model card carries the
identical `license: other` declaration (inherited from its stated
`base_model: Qwen/Qwen2.5-3B-Instruct`).

**Full text retrieved from the upstream `LICENSE` file**
(`https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/raw/main/LICENSE`),
key clauses:

> "i. 'Non-Commercial' shall mean for research or evaluation purposes only."
>
> "2.a. You are granted a non-exclusive, worldwide, non-transferable and
> royalty-free limited license ... to use, reproduce, distribute, copy,
> create derivative works of, and make modifications to the Materials
> **FOR NON-COMMERCIAL PURPOSES ONLY**."
>
> "2.b. If you are commercially using the Materials, you shall request a
> license from us [Alibaba Cloud]."

Redistribution of derivative works (e.g. a fine-tuned Genesis checkpoint)
is permitted only with: (a) a copy of this same license agreement passed
to recipients, (b) prominent notice of modification, (c) a retained
"Qwen is licensed under the Qwen RESEARCH LICENSE AGREEMENT, Copyright
(c) Alibaba Cloud. All Rights Reserved." attribution notice.

**This is a genuine, material blocker for any commercial ORNEUR
deployment of a Genesis checkpoint fine-tuned from this exact base**,
not a formality. Per this closure's own instructions ("A base-model
replacement requires owner review" / "do not pick a replacement
casually"), the base model is **left unchanged** here, and this finding
is surfaced as a BLOCKING gap for owner decision (see
`PHASE21_GENESIS_BUILD_PREPARATION.md`'s blocker list) rather than
silently worked around.

## Options for the owner to consider (not decided here)

1. Proceed with `unsloth/Qwen2.5-3B-Instruct` for research/internal
   evaluation only, and separately pursue a commercial license from
   Alibaba Cloud before any commercial ORNEUR Genesis release.
2. Request Alibaba Cloud's commercial license explicitly (contact path
   not verified in this closure -- would need to be sourced from
   Alibaba Cloud's own channels, not guessed).
3. Replace the ~3B target with a same-size-class base model under a
   more permissive license (e.g. an Apache-2.0-licensed alternative) --
   this is an architecture-lock decision requiring explicit owner
   approval per this closure's own restriction, and is NOT recommended
   or selected here.

## Qualification result: **VERIFIED, BLOCKED (commercial-use license)**

Everything else about the base model (architecture, tokenizer, revision
pinning) is now formally qualified with authoritative, live-retrieved
evidence. The single remaining blocker before any *commercial* Genesis
release is the non-commercial license term above -- it does not block
research/internal training and evaluation (Phase 21C, once separately
authorized), only public/commercial release qualification.
