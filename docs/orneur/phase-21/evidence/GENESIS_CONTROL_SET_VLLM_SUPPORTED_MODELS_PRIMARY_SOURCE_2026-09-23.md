# vLLM Official Supported-Models Table Excerpt — Genesis Control Set

Source: `https://raw.githubusercontent.com/vllm-project/vllm/main/docs/models/supported_models.md`
Retrieved: 2026-09-23T12:45Z, from the `vllm-project/vllm` repository's `main` branch HEAD.

This is current-support documentation (not an immutable pinned-artifact revision), so `main`
branch HEAD is the correct fetch target for "what does vLLM currently support" questions,
distinct from the exact-pinned-revision fetches used for each control's own identity/license/
weight/tokenizer evidence.

Table header (Text Generation architectures section):

```
| Architecture | Models | Example HF Models | LoRA | PP |
| ------------ | ------ | ----------------- | -------------------- | ------------------------- |
```

Rows relevant to the three Genesis controls, quoted verbatim:

```
| `Qwen3ForCausalLM` | Qwen3 | `Qwen/Qwen3-8B`, etc. | ✅︎ | ✅︎ |
| `MistralForCausalLM` | Ministral-3, Mistral, Mistral-Instruct | `mistralai/Ministral-3-3B-Instruct-2512`, `mistralai/Mistral-7B-v0.1`, `mistralai/Mistral-7B-Instruct-v0.1`, etc. | ✅︎ | ✅︎ |
| `Phi3ForCausalLM` | Phi-4, Phi-3 | `microsoft/Phi-4-mini-instruct`, `microsoft/Phi-4`, `microsoft/Phi-3-mini-4k-instruct`, `microsoft/Phi-3-mini-128k-instruct`, `microsoft/Phi-3-medium-128k-instruct`, etc. | ✅︎ | ✅︎ |
```

## Interpretation per control

- **Qwen3-8B**: `Qwen/Qwen3-8B` is named explicitly as an Example HF Model for the
  `Qwen3ForCausalLM` architecture row. Direct, model-specific confirmation.
- **Phi-4**: `microsoft/Phi-4` is named explicitly as an Example HF Model for the
  `Phi3ForCausalLM` architecture row. Direct, model-specific confirmation — this is the
  strongest available upgrade over the prior "mainstream, long-established architecture"
  framing, which was accurate but unsupported by a cited primary source.
- **Mistral-Nemo-Instruct-2407**: the `MistralForCausalLM` architecture row is confirmed, but
  the Example HF Models column lists other Mistral models (Ministral-3, Mistral-7B family),
  **not** `mistralai/Mistral-Nemo-Instruct-2407` by name. This is genuine architecture-class
  support evidence, not model-specific confirmation — recorded honestly as that weaker (but
  still real) evidence tier, consistent with this repository's own `library_name: vllm` tag
  recorded separately in Phase 21B.4.16.

All three architecture classes show LoRA support and pipeline-parallel (PP) support checked
in this table. This does not itself constitute a production-serving qualification claim for
any control — it is current-support documentation only.
