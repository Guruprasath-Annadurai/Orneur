"""Genesis foundation landscape refresh (2026-09-26): gate evaluation + estimates.

Pure functions over the committed raw Hugging Face metadata evidence. No network,
no GPU, no provider inference. Admission is gate-based (A-J); recency, size and
popularity never select a model. Nothing here selects a foundation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

GATES = ("A_license", "B_revision_pinned", "C_architecture_documented", "D_tokenizer_template",
         "E_peft_qlora_feasible", "F_training_cost_vs_budget", "G_inference_path",
         "H_artifacts_verifiable", "I_no_proprietary_only_stack", "J_ecosystem_maturity")

CLASSES = ("GENESIS_EVAL_ADMITTED", "TEACHER_REFERENCE", "FUTURE_REASON_CANDIDATE",
           "FUTURE_FRONTIER_ARCHITECTURE_REFERENCE", "BASELINE_ONLY_CONTROL", "NOT_ADMITTED")

# Program constants inherited from the audited decision package (Phase 21B.4.20 closeout).
H100_USD_PER_HOUR = 3.95
H100_BF16_TFLOPS = 989.0
UTILIZATION_RANGE = (0.15, 0.25)
BUDGET_USD_RANGE = (111.0, 118.0)  # ~INR 10,000 at INR 85-90/USD; planning only, NOT authorization
PILOT_TOKENS = 5_000_000
PILOT_MAX_FRACTION_OF_BUDGET = 0.10
GPU_MEMORY_GB = 80.0

# Curated, per-model facts that cannot be derived mechanically. Everything else is derived from raw evidence.
# active_b: active parameters in billions for MoE (name-derived unless noted); None => dense.
CURATED: dict[str, dict[str, Any]] = {
    "Qwen/Qwen3-8B": {"family": "Qwen", "role": "BASELINE_ONLY_CONTROL", "modality": "text",
        "caveats": ["Phase 21B.4.20 control: RUNTIME_QUALIFIED=false in ORNEUR's raw-model harness (smoke B FAIL); kept only as a regression baseline, not carried forward automatically."]},
    "mistralai/Mistral-Nemo-Instruct-2407": {"family": "Mistral", "role": "BASELINE_ONLY_CONTROL", "modality": "text",
        "caveats": ["Phase 21B.4.20 control: FAIL/FAIL/FAIL under native-tokenizer candidate; needs mistral-common tokenizer path; baseline only."]},
    "microsoft/phi-4": {"family": "Microsoft Phi", "role": "BASELINE_ONLY_CONTROL", "modality": "text",
        "caveats": ["Phase 21B.4.20 control: PASS/FAIL/FAIL; 16k context limit; baseline only."]},
    "Qwen/Qwen3.5-4B": {"family": "Qwen", "modality": "text+image", "vendor_quantized": [],
        "caveats": ["Hybrid full/linear attention (Gated-DeltaNet-style layers per config.layer_types): QLoRA/serving depend on specialised kernels; unverified by ORNEUR."]},
    "Qwen/Qwen3.5-9B": {"family": "Qwen", "modality": "text+image", "vendor_quantized": [],
        "caveats": ["Hybrid full/linear attention: QLoRA/serving depend on specialised kernels; unverified by ORNEUR."]},
    "Qwen/Qwen3.5-27B": {"family": "Qwen", "modality": "text+image", "vendor_quantized": [],
        "caveats": ["Hybrid full/linear attention; superseded within family by newer 27B releases but not excluded for that reason."]},
    "Qwen/Qwen3.6-27B": {"family": "Qwen", "modality": "text+image", "vendor_quantized": ["Qwen/Qwen3.6-27B-FP8"],
        "caveats": ["Hybrid full/linear attention; same architecture class as Qwen3.8-27B."]},
    "Qwen/Qwen3.8-27B": {"family": "Qwen", "modality": "text+image", "vendor_quantized": ["Qwen/Qwen3.8-27B-FP8", "nvidia/Qwen3.8-27B-NVFP4 (third-party)"],
        "caveats": ["Released 2026-08-05: young ecosystem; hybrid full/linear attention kernels; largest dense candidate that still fits a single 80GB GPU for QLoRA on paper."]},
    "Qwen/Qwen3.5-35B-A3B": {"family": "Qwen", "modality": "text+image",
        "caveats": ["MoE (256 experts, 8 active): QLoRA over fused experts not verified."]},
    "Qwen/Qwen3.6-35B-A3B": {"family": "Qwen", "modality": "text+image",
        "caveats": ["MoE (256 experts, 8 active): QLoRA over fused experts not verified; attractive FAST-serving profile if trainable."]},
    "Qwen/Qwen3.8-Flash-Next": {"family": "Qwen", "modality": "text+image", "role": "FUTURE_FRONTIER_ARCHITECTURE_REFERENCE",
        "caveats": ["License (qwen-community-1.0) requires a separate license from Qwen for any 'Model as a Service or AI Work Assistant business': incompatible with ORNEUR's intended business until legally cleared. Architecture (qwen4_exp) studied only."]},
    "Qwen/Qwen3.8-2.4T-A95B": {"family": "Qwen", "modality": "text", "role": "FUTURE_FRONTIER_ARCHITECTURE_REFERENCE",
        "caveats": ["2.4T parameters: reference only. License (qwen3.8-max) needs a separate license for AI-assistant/MaaS businesses above US$50M revenue; terms not fully legal-reviewed."]},
    "google/gemma-4-E4B-it": {"family": "Gemma", "modality": "text+image+audio (per vLLM listing T+I+V+A)", "vendor_quantized": ["google/gemma-4-E4B-it-qat-w4a16-ct"],
        "caveats": ["8.0B stored parameters include per-layer embeddings; 'E4B' effective size is a vendor label (not verified here).", "Repo has no LICENSE file; Apache-2.0 comes from model-card metadata only."]},
    "google/gemma-4-12B-it": {"family": "Gemma", "modality": "any-to-any (pipeline tag)", "vendor_quantized": ["google/gemma-4-12B-it-qat-w4a16-ct", "google/gemma-4-12B-it-qat-q4_0-gguf"],
        "caveats": ["Architecture Gemma4Unified: vLLM docs list it without a LoRA-support mark; repo has no LICENSE file (Apache-2.0 from card metadata)."]},
    "google/gemma-4-12B": {"family": "Gemma", "modality": "any-to-any (pipeline tag)",
        "caveats": ["Pretrained (non-'it') variant of the 12B; Gemma4Unified architecture; no LICENSE file in repo."]},
    "google/gemma-4-26B-A4B-it": {"family": "Gemma", "modality": "text+image",
        "caveats": ["MoE (128 experts): QLoRA over experts not verified; no LICENSE file in repo."]},
    "google/gemma-4-31B-it": {"family": "Gemma", "modality": "text+image", "vendor_quantized": ["google/gemma-4-31B-it-qat-w4a16-ct"],
        "caveats": ["31.3B dense: QLoRA fits one 80GB GPU on paper; no LICENSE file in repo."]},
    "mistralai/Ministral-3-8B-Instruct-2512": {"family": "Mistral", "modality": "text+image", "vendor_quantized": ["native F8_E4M3 weights", "GGUF"],
        "caveats": ["Ships FP8 weights only for the instruct 8B: QLoRA requires a dequantised path (unverified).", "Mistral tokenizer path (tekken.json + mistral-common) caused the Mistral-Nemo control failure; tokenizer/template behaviour must be re-qualified."]},
    "mistralai/Ministral-3-14B-Instruct-2512": {"family": "Mistral", "modality": "text+image", "vendor_quantized": ["BF16 variant", "GGUF"],
        "caveats": ["Same mistral-common/tekken caveat as the Mistral-Nemo control."]},
    "mistralai/Ministral-3-14B-Base-2512": {"family": "Mistral", "modality": "text+image",
        "caveats": ["Base checkpoint: needs full instruction/format SFT; same mistral-common/tekken caveat."]},
    "mistralai/Ministral-3-14B-Reasoning-2512": {"family": "Mistral", "modality": "text+image",
        "caveats": ["Reasoning post-trained variant; same mistral-common/tekken caveat."]},
    "mistralai/Mistral-Small-4-119B-2603": {"family": "Mistral", "modality": "text+image", "role": "TEACHER_REFERENCE",
        "caveats": ["119B (FP8 weights, 128 experts): teacher/reference only; provider or large-GPU serving needed."]},
    "mistralai/Mistral-Large-3-675B-Instruct-2512": {"family": "Mistral", "modality": "text", "role": "TEACHER_REFERENCE",
        "caveats": ["Native Mistral format only (no safetensors metadata/config.json via the HF API): artifact verification partial."]},
    "deepseek-ai/DeepSeek-V4.1-Flash": {"family": "DeepSeek", "modality": "text+image", "role": "TEACHER_REFERENCE",
        "caveats": ["763B stored parameters; architecture deepseek_v41 is not in transformers main or the vLLM supported-models docs at collection time: reference only."]},
    "deepseek-ai/DeepSeek-V4-Pro-0813": {"family": "DeepSeek", "modality": "text", "role": "TEACHER_REFERENCE",
        "caveats": ["1.65T stored parameters (mostly int8); 1M context; transformers has deepseek_v4; teacher/reference only."]},
    "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B": {"family": "DeepSeek (Qwen3 distill)", "modality": "text", "role": "DERIVATIVE_NOT_A_FOUNDATION",
        "caveats": ["MIT-licensed distillation onto the Qwen3-8B architecture; inherits the Qwen3-8B control caveats."]},
    "microsoft/Phi-4-mini-instruct": {"family": "Microsoft Phi", "modality": "text",
        "caveats": ["3.8B, 128k context; Phi-4 (14B) control had a 16k context limit."]},
    "microsoft/Fara1.5-9B": {"family": "Microsoft (Qwen3.5 derivative)", "modality": "text+image", "role": "DERIVATIVE_NOT_A_FOUNDATION",
        "caveats": ["Task-specialised (computer-use) derivative of Qwen3.5-9B: not a general foundation candidate; recorded to avoid double counting."]},
    "microsoft/MagenticBrain": {"family": "Microsoft (Qwen3 derivative)", "modality": "text", "role": "DERIVATIVE_NOT_A_FOUNDATION",
        "caveats": ["Task-specialised derivative on the Qwen3 architecture, F32 weights; not a general foundation candidate."]},
    "ibm-granite/granite-4.2-3b": {"family": "Granite", "modality": "text", "vendor_quantized": ["FP8", "MXFP4", "NVFP4", "GGUF"],
        "caveats": ["Config declares GraniteForCausalLM (dense); vLLM docs list Granite 3.x model names for this class: 4.2 serving is unverified."]},
    "ibm-granite/granite-4.2-8b": {"family": "Granite", "modality": "text", "vendor_quantized": ["FP8", "MXFP4", "NVFP4", "GGUF"],
        "caveats": ["As above: GraniteForCausalLM dense; 4.2 serving unverified."]},
    "ibm-granite/granite-4.2-30b": {"family": "Granite", "modality": "text", "vendor_quantized": ["FP8", "MXFP4", "NVFP4", "GGUF"],
        "caveats": ["29.3B dense; QLoRA fits one 80GB GPU on paper."]},
    "openai/gpt-oss-20b": {"family": "gpt-oss", "modality": "text", "vendor_quantized": ["native MXFP4 experts"],
        "caveats": ["MoE with MXFP4 expert weights: QLoRA/PEFT over quantised experts unverified."]},
    "openai/gpt-oss-120b": {"family": "gpt-oss", "modality": "text", "role": "TEACHER_REFERENCE",
        "caveats": ["116.8B stored parameters (MXFP4 experts): teacher/reference; hostable on one 80GB-class GPU per vendor claim (not verified here)."]},
    "zai-org/GLM-5.3-Flash": {"family": "GLM", "modality": "text+image", "role": "TEACHER_REFERENCE", "vendor_quantized": ["nvidia/GLM-5.3-Flash-NVFP4 (third-party)"],
        "caveats": ["321B stored parameters, MIT; architecture glm5_next in transformers main but not in vLLM docs at collection time."]},
    "zai-org/GLM-5.3": {"family": "GLM", "modality": "text", "role": "FUTURE_FRONTIER_ARCHITECTURE_REFERENCE",
        "caveats": ["Custom GLM-5.3 License (MaaS clause above US$10B revenue): architecture reference only; unaudited by counsel."]},
    "zai-org/GLM-4.7-Flash": {"family": "GLM", "modality": "text",
        "caveats": ["MoE 31.2B (64 experts): QLoRA over experts unverified."]},
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16": {"family": "Nemotron-H", "modality": "text",
        "caveats": ["Hybrid Mamba/attention MoE (nemotron_h): valuable for architecture diversity; NVIDIA custom open-model license not legally reviewed."]},
    "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Base-BF16": {"family": "Nemotron-H", "modality": "text",
        "caveats": ["Base checkpoint under openmdw-1.1 (card metadata): license text not reviewed this phase."]},
    "allenai/Olmo-3-7B-Instruct": {"family": "OLMo", "modality": "text",
        "caveats": ["Fully-open lineage (data/training documented by vendor, not re-verified); 65k context; released 2025-10 (older than other candidates)."]},
    "LiquidAI/LFM2.5-2.6B": {"family": "Liquid", "modality": "text",
        "caveats": ["LFM1.0 licence: commercial use licensed only below a US$10M annual-revenue threshold: not permissive."]},
    "HuggingFaceTB/SmolLM3-3B": {"family": "SmolLM3", "modality": "text",
        "caveats": ["3.1B; 64k native context; full-attention only."]},
    "meta-llama/Llama-3.3-70B-Instruct": {"family": "Llama", "modality": "text",
        "caveats": ["Manually gated repo + custom community licence; 70B exceeds the first-stage budget in any case."]},
    "meta-llama/Llama-4-Scout-17B-16E-Instruct": {"family": "Llama", "modality": "text+image",
        "caveats": ["Manually gated repo + custom Llama 4 licence; 109B total parameters."]},
}


K = 1024
# Vendor model-card claims. Each quote MUST appear verbatim in the captured README lines of the raw evidence
# (tests enforce this). Claims are attributed, never verified measurements. K/M shorthand is converted with the
# K=1024 convention and flagged SHORTHAND_K1024_ASSUMED; exact digits are EXACT.
def _c(text, tokens, precision, quote, ext=None, ext_prec=None, source="VENDOR_MODEL_CARD_CLAIM"):
    return {"text": text, "tokens": tokens, "precision": precision, "quote": quote,
            "extended_tokens": ext, "extended_precision": ext_prec, "source": source}


_QWEN35 = _c("262,144 natively and extensible up to 1,010,000 tokens", 262144, "EXACT",
             "262,144 natively and extensible up to 1,010,000 tokens", 1010000, "EXACT")
_QWEN38 = _c("262,144 natively and extensible up to 1,000,000 tokens", 262144, "EXACT",
             "262,144 natively and extensible up to 1,000,000 tokens", 1000000, "EXACT")
_GEMMA_TABLE = "| **Context Length** | 128K tokens | 128K tokens | 256K tokens  | 256K tokens  |"
_GRANITE = _c("Natively Supports 128K (Long-context extension to 512K)", 128 * K, "SHORTHAND_K1024_ASSUMED",
              "Natively Supports 128K (Long-context extension to 512K)", 512 * K, "SHORTHAND_K1024_ASSUMED")
_MINISTRAL = _c("Supports a 256k context window", 256 * K, "SHORTHAND_K1024_ASSUMED", "Supports a 256k context window")

VENDOR_CONTEXT: dict[str, dict[str, Any]] = {
    "HuggingFaceTB/SmolLM3-3B": _c("Trained on 64k context and supports up to 128k tokens using YARN extrapolation", 64 * K,
        "SHORTHAND_K1024_ASSUMED", "Trained on 64k context", 128 * K, "SHORTHAND_K1024_ASSUMED"),
    "LiquidAI/LFM2.5-2.6B": _c("Context length: 131,072 tokens", 131072, "EXACT", "131,072 tokens"),
    "Qwen/Qwen3-8B": _c("32,768 natively and 131,072 tokens with YaRN", 32768, "EXACT", "32,768 natively", 131072, "EXACT"),
    "Qwen/Qwen3.5-4B": _QWEN35, "Qwen/Qwen3.5-9B": _QWEN35, "Qwen/Qwen3.5-27B": _QWEN35, "Qwen/Qwen3.5-35B-A3B": _QWEN35,
    "Qwen/Qwen3.6-27B": _QWEN35, "Qwen/Qwen3.6-35B-A3B": _QWEN35,
    "Qwen/Qwen3.8-27B": _QWEN38, "Qwen/Qwen3.8-Flash-Next": _QWEN38,
    "Qwen/Qwen3.8-2.4T-A95B": _QWEN35,
    "google/gemma-4-E4B-it": _c("128K tokens (family table, column inferred from parameter row)", 128 * K, "SHORTHAND_K1024_ASSUMED",
        _GEMMA_TABLE, source="VENDOR_MODEL_CARD_TABLE_COLUMN_INFERRED"),
    "google/gemma-4-12B-it": _c("256K tokens (family table, column inferred from parameter row)", 256 * K, "SHORTHAND_K1024_ASSUMED",
        _GEMMA_TABLE, source="VENDOR_MODEL_CARD_TABLE_COLUMN_INFERRED"),
    "google/gemma-4-12B": _c("256K tokens (family table, column inferred from parameter row)", 256 * K, "SHORTHAND_K1024_ASSUMED",
        _GEMMA_TABLE, source="VENDOR_MODEL_CARD_TABLE_COLUMN_INFERRED"),
    "google/gemma-4-31B-it": _c("256K tokens (family table, column inferred from parameter row)", 256 * K, "SHORTHAND_K1024_ASSUMED",
        _GEMMA_TABLE, source="VENDOR_MODEL_CARD_TABLE_COLUMN_INFERRED"),
    "google/gemma-4-26B-A4B-it": _c("256K tokens", 256 * K, "SHORTHAND_K1024_ASSUMED", "| **Context Length** | 256K tokens |"),
    "ibm-granite/granite-4.2-3b": _GRANITE, "ibm-granite/granite-4.2-8b": _GRANITE, "ibm-granite/granite-4.2-30b": _GRANITE,
    "meta-llama/Llama-3.3-70B-Instruct": _c("128k (model-family table)", 128 * K, "SHORTHAND_K1024_ASSUMED",
        "Multilingual Text and code  | 128k |"),
    "microsoft/Fara1.5-9B": _c("262,144 tokens", 262144, "EXACT", "262,144 tokens"),
    "microsoft/MagenticBrain": _c("32,768 tokens", 32768, "EXACT", "32,768 tokens"),
    "microsoft/Phi-4-mini-instruct": _c("128K tokens", 128 * K, "SHORTHAND_K1024_ASSUMED", "128K tokens"),
    "microsoft/phi-4": _c("16K tokens", 16 * K, "SHORTHAND_K1024_ASSUMED", "16K tokens"),
    "mistralai/Ministral-3-8B-Instruct-2512": _MINISTRAL, "mistralai/Ministral-3-14B-Instruct-2512": _MINISTRAL,
    "mistralai/Ministral-3-14B-Base-2512": _MINISTRAL, "mistralai/Ministral-3-14B-Reasoning-2512": _MINISTRAL,
    "mistralai/Mistral-Large-3-675B-Instruct-2512": _MINISTRAL,
    "mistralai/Mistral-Small-4-119B-2603": _c("256k context length", 256 * K, "SHORTHAND_K1024_ASSUMED", "256k context length"),
    "mistralai/Mistral-Nemo-Instruct-2407": _c("Trained with a 128k context window", 128 * K, "SHORTHAND_K1024_ASSUMED", "128k context window"),
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16": _c("supports up to a 1M context size, although the default context size in the Hugging Face configuration is 256k",
        1024 * K, "SHORTHAND_K1024_ASSUMED", "supports up to a 1M context size"),
    "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Base-BF16": _c("supports up to 1M context length", 1024 * K, "SHORTHAND_K1024_ASSUMED",
        "supports up to 1M context length"),
    "deepseek-ai/DeepSeek-V4.1-Flash": _c("`context_window` 1M tokens", 1024 * K, "SHORTHAND_K1024_ASSUMED", "| `context_window` | 1M tokens |"),
}

# Active parameters (billions): (value, source, quote-or-None, note). VENDOR_MODEL_CARD_CLAIM values are attributed claims;
# NAME_DERIVED comes only from a 'A<n>B' style model name. Nothing here is a verified measurement.
VENDOR_ACTIVE: dict[str, tuple[float | None, str, str | None, str | None]] = {
    "Qwen/Qwen3.5-35B-A3B": (3.0, "VENDOR_MODEL_CARD_CLAIM", "35B in total and 3B activated", None),
    "Qwen/Qwen3.6-35B-A3B": (3.0, "VENDOR_MODEL_CARD_CLAIM", "35B in total and 3B activated", None),
    "Qwen/Qwen3.8-2.4T-A95B": (95.0, "VENDOR_MODEL_CARD_CLAIM", "2.4T in total and 95B activated", None),
    "Qwen/Qwen3.8-Flash-Next": (6.0, "VENDOR_MODEL_CARD_CLAIM", "125B with 6B activated",
                                "card: 125B + 51B n-gram embedding + 4B MTP (= 180B stored, matching the safetensors total)"),
    "google/gemma-4-26B-A4B-it": (3.8, "VENDOR_MODEL_CARD_CLAIM", "| **Active Parameters** | 3.8B |",
                                  "model name says A4B; card table says 3.8B active and 25.2B total (safetensors total is 25.8B)"),
    "mistralai/Mistral-Small-4-119B-2603": (6.5, "VENDOR_MODEL_CARD_CLAIM", "6.5B activated per token", None),
    "mistralai/Mistral-Large-3-675B-Instruct-2512": (41.0, "VENDOR_MODEL_CARD_CLAIM", "**41B active parameters** and **675B total parameters**",
                                                     "the same card also states 39B active for the language model alone"),
    "openai/gpt-oss-20b": (3.6, "VENDOR_MODEL_CARD_CLAIM", "21B parameters with 3.6B active parameters", None),
    "openai/gpt-oss-120b": (5.1, "VENDOR_MODEL_CARD_CLAIM", "117B parameters with 5.1B active parameters", None),
    "zai-org/GLM-5.3-Flash": (18.0, "VENDOR_MODEL_CARD_CLAIM", "320B total parameters and just 18B active parameters", None),
    "zai-org/GLM-4.7-Flash": (3.0, "NAME_DERIVED", "30B-A3B MoE model", "card only names the model '30B-A3B'; no explicit active count"),
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16": (3.0, "NAME_DERIVED", None, "from the 'A3B' model name; card gives experts-per-token, not an active count"),
    "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Base-BF16": (3.0, "NAME_DERIVED", None, "from the 'A3B' model name"),
    "deepseek-ai/DeepSeek-V4.1-Flash": (None, "NOT_RECORDED", "| # Activated Params | — | 13B | 49B | 8B / 16B |",
                                        "vendor table lists '8B / 16B' (input/output path per earlier landscape doc); column attribution not verified"),
}


def context_info(model: str, raw_row: Mapping[str, Any]) -> dict[str, Any]:
    cfg = raw_row.get("config_subset") or {}
    conf = next((v for k, v in cfg.items() if k.endswith("max_position_embeddings")), None)
    v = VENDOR_CONTEXT.get(model)
    out: dict[str, Any] = {"config_max_position_embeddings": conf,
                           "vendor_supported_context_tokens": v["tokens"] if v else None,
                           "vendor_supported_context_text": v["text"] if v else None,
                           "vendor_supported_context_precision": v["precision"] if v else None,
                           "vendor_extended_context_tokens": v["extended_tokens"] if v else None,
                           "context_source": v["source"] if v else "NOT_CAPTURED_FROM_MODEL_CARD",
                           "vendor_context_quote": v["quote"] if v else None}
    if conf is None:
        rel = "CONFIG_NOT_AVAILABLE"
    elif v is None:
        rel = "VENDOR_CLAIM_NOT_CAPTURED"
    else:
        rel = "MATCH" if v["tokens"] == conf else "DIFFERS"
    out["context_config_vs_vendor"] = rel
    return out


def active_info(model: str) -> dict[str, Any]:
    if model in VENDOR_ACTIVE:
        val, src, quote, note = VENDOR_ACTIVE[model]
        return {"active_parameters_b": val, "active_parameters_source": src, "active_parameters_quote": quote,
                "active_parameters_note": note, "active_parameters_verified": False}
    return {"active_parameters_b": None, "active_parameters_source": None, "active_parameters_quote": None,
            "active_parameters_note": None, "active_parameters_verified": False}


GATED_OR_CUSTOM_LICENSE = {"other", "llama3.3", "llama4"}
PERMISSIVE = {"apache-2.0", "mit"}


def _params_b(raw_row: Mapping[str, Any]) -> float | None:
    st = raw_row.get("safetensors") or {}
    total = st.get("total")
    return round(total / 1e9, 2) if total else None


def is_moe(raw_row: Mapping[str, Any]) -> bool:
    cfg = raw_row.get("config_subset") or {}
    mtype = cfg.get("model_type") or cfg.get("text_config.model_type") or ""
    arch = (cfg.get("architectures") or cfg.get("text_config.architectures") or [""])[0] or ""
    return bool(any(v for k, v in cfg.items() if k.split(".")[-1] in {"num_experts", "num_local_experts", "n_routed_experts"})
                or "moe" in mtype or "MoE" in arch)


def qlora_vram_gb(total_b: float) -> tuple[float, float]:
    """Rough 4-bit QLoRA single-GPU memory range (GB): weights + adapters/optimizer/activations."""
    return round(0.5 * total_b + 4.0, 1), round(0.7 * total_b + 8.0, 1)


def usd_per_million_tokens(compute_b: float) -> tuple[float, float]:
    """6*N FLOPs/token at 15-25% of bf16 peak, at the program's persisted H100 list rate."""
    def one(u: float) -> float:
        secs = 6.0 * compute_b * 1e9 * 1e6 / (u * H100_BF16_TFLOPS * 1e12)
        return secs / 3600.0 * H100_USD_PER_HOUR
    return round(one(UTILIZATION_RANGE[1]), 3), round(one(UTILIZATION_RANGE[0]), 3)


def _gate(status: str, basis: str, note: str) -> dict[str, str]:
    return {"status": status, "basis": basis, "note": note}


def evaluate_gates(model: str, raw_row: Mapping[str, Any], eco: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    cur = CURATED.get(model, {})
    cfg = raw_row.get("config_subset") or {}
    top = lambda k: cfg.get(k)  # noqa: E731
    mtype = top("model_type") or top("text_config.model_type") or ""
    arch = (top("architectures") or top("text_config.architectures") or [None])[0]
    dirs = set(eco.get("transformers_main_model_dirs", []))
    base_type = mtype[:-5] if mtype.endswith("_text") else mtype
    vllm = eco.get("vllm_supported_models_lines", {})
    vllm_line = vllm.get(arch) if arch else None
    total = _params_b(raw_row)
    active = VENDOR_ACTIVE.get(model, (None,))[0]
    moe = bool(any(v for k, v in cfg.items() if k.split(".")[-1] in {"num_experts", "num_local_experts", "n_routed_experts"})
               or "moe" in mtype or "MoE" in (arch or ""))
    dtypes = (raw_row.get("safetensors") or {}).get("parameters") or {}
    native_quantized = bool(dtypes) and sum(v for k, v in dtypes.items() if k in {"F8_E4M3", "F8_E5M2", "U8", "I8"}) > 0.5 * sum(dtypes.values())
    lic = raw_row.get("license_card")
    g: dict[str, dict[str, str]] = {}

    # A: license
    if raw_row.get("gated") not in (False, None) or lic in GATED_OR_CUSTOM_LICENSE:
        note = f"license tag '{lic}' / name '{raw_row.get('license_name')}', gated={raw_row.get('gated')}: custom or gated terms; not admitted without legal review"
        g["A_license"] = _gate("FAIL", "PRIMARY_SOURCE", note)
    elif lic in PERMISSIVE:
        g["A_license"] = _gate("PASS", "PRIMARY_SOURCE", f"{lic} per Hugging Face model-card metadata")
    else:
        g["A_license"] = _gate("UNVERIFIED", "NOT_VERIFIED", f"license tag '{lic}'")
    # B: exact revision
    sha = raw_row.get("revision_sha")
    g["B_revision_pinned"] = _gate("PASS", "PRIMARY_SOURCE", f"revision {sha}") if sha and len(sha) == 40 else _gate("FAIL", "PRIMARY_SOURCE", "no 40-hex revision")
    # C: architecture documented
    if cfg and (base_type in dirs or vllm_line):
        g["C_architecture_documented"] = _gate("PASS", "PRIMARY_SOURCE", f"config.json architecture {arch}; transformers-main dir={base_type in dirs}; vLLM-docs-listed={bool(vllm_line)}")
    elif cfg:
        g["C_architecture_documented"] = _gate("UNVERIFIED", "PRIMARY_SOURCE", f"config.json present ({arch}) but no native transformers/vLLM implementation found at collection time")
    else:
        g["C_architecture_documented"] = _gate("UNVERIFIED", "NOT_VERIFIED", "no config.json retrievable")
    # D: tokenizer/template
    probe = (eco.get("template_and_layer_probes") or {}).get(model)
    if probe and probe.get("template_present"):
        extra = "; tekken.json present: prior Mistral-Nemo control failed on the tokenizer path, so tokenizer behaviour must be re-qualified" if any("tekken" in f for f in probe.get("files_of_interest", [])) else ""
        g["D_tokenizer_template"] = _gate("PASS", "PRIMARY_SOURCE", f"chat template present; mentions tools={probe.get('template_mentions_tools')}; files={probe.get('files_of_interest')}{extra}")
    elif probe is not None:
        g["D_tokenizer_template"] = _gate("UNVERIFIED", "PRIMARY_SOURCE", "no chat template found")
    else:
        g["D_tokenizer_template"] = _gate("UNVERIFIED", "NOT_VERIFIED", "template not probed for this model")
    # E: PEFT/QLoRA feasibility
    if total is None:
        g["E_peft_qlora_feasible"] = _gate("UNVERIFIED", "NOT_VERIFIED", "no parameter total")
    elif total > 40:
        g["E_peft_qlora_feasible"] = _gate("FAIL", "DERIVED_FROM_PRIMARY_SOURCE", f"{total}B exceeds single-GPU QLoRA envelope for the first-stage budget")
    elif moe:
        g["E_peft_qlora_feasible"] = _gate("UNVERIFIED", "NOT_VERIFIED", "MoE: adapter/QLoRA support over fused or quantised experts is not verified")
    elif native_quantized:
        g["E_peft_qlora_feasible"] = _gate("UNVERIFIED", "DERIVED_FROM_PRIMARY_SOURCE", "checkpoint ships natively quantised (FP8/INT8) weights: a dequantise-then-QLoRA path is not verified")
    elif base_type in dirs:
        g["E_peft_qlora_feasible"] = _gate("PASS", "INFERRED_NOT_EXECUTED", "dense architecture native in transformers main: adapters target Linear layers; 4-bit loading is expected but NOT executed by ORNEUR")
    else:
        g["E_peft_qlora_feasible"] = _gate("UNVERIFIED", "NOT_VERIFIED", "no native transformers implementation found")
    # F: training cost vs budget
    if total is None:
        g["F_training_cost_vs_budget"] = _gate("UNVERIFIED", "NOT_VERIFIED", "no parameter total")
    else:
        compute_b = active if (moe and active) else total
        lo, hi = usd_per_million_tokens(compute_b)
        pilot_hi = round(hi * PILOT_TOKENS / 1e6, 2)
        vram_lo, vram_hi = qlora_vram_gb(total)
        ok = pilot_hi <= PILOT_MAX_FRACTION_OF_BUDGET * BUDGET_USD_RANGE[0] and vram_hi <= GPU_MEMORY_GB
        g["F_training_cost_vs_budget"] = _gate("PASS" if ok else "FAIL", "DERIVED_ESTIMATE",
            f"5M-token pilot ~USD {round(lo*5,2)}-{pilot_hi} (<= {int(PILOT_MAX_FRACTION_OF_BUDGET*100)}% of USD {BUDGET_USD_RANGE[0]:.0f}); est. QLoRA VRAM {vram_lo}-{vram_hi} GB vs {GPU_MEMORY_GB:.0f} GB")
    # G: inference path
    if vllm_line:
        g["G_inference_path"] = _gate("PASS", "PRIMARY_SOURCE", f"listed in vLLM supported-models docs ({arch})")
    elif base_type in dirs:
        g["G_inference_path"] = _gate("PASS", "DERIVED_FROM_PRIMARY_SOURCE", "transformers-native generate path only; not listed in vLLM docs at collection time")
    else:
        g["G_inference_path"] = _gate("FAIL", "PRIMARY_SOURCE", "no transformers-native or vLLM-listed inference path found")
    # H: artifacts verifiable
    if sha and raw_row.get("safetensors"):
        g["H_artifacts_verifiable"] = _gate("PASS", "PRIMARY_SOURCE", "immutable revision + safetensors metadata (per-file hashes verifiable at download time)")
    else:
        g["H_artifacts_verifiable"] = _gate("UNVERIFIED", "PRIMARY_SOURCE", "no safetensors metadata at the pinned revision")
    # I: no proprietary-only stack
    if vllm_line or base_type in dirs:
        g["I_no_proprietary_only_stack"] = _gate("PASS", "DERIVED_FROM_PRIMARY_SOURCE", "open serving/training stack available (transformers and/or vLLM)")
    else:
        g["I_no_proprietary_only_stack"] = _gate("UNVERIFIED", "NOT_VERIFIED", "no open serving stack identified")
    # J: ecosystem maturity (requires BOTH open stacks; age recorded as a caveat, not a gate)
    if base_type in dirs and vllm_line:
        g["J_ecosystem_maturity"] = _gate("PASS", "DERIVED_FROM_PRIMARY_SOURCE", f"native in transformers main and listed in vLLM docs; created {raw_row.get('created_at')}")
    else:
        g["J_ecosystem_maturity"] = _gate("UNVERIFIED", "DERIVED_FROM_PRIMARY_SOURCE", f"transformers-native={base_type in dirs}, vLLM-listed={bool(vllm_line)}")
    return g


def classify(model: str, gates: Mapping[str, Mapping[str, str]], raw_row: Mapping[str, Any]) -> tuple[str, str, bool]:
    """Return (class, reason, admitted_to_capability_eval). Admission is purely gate-based."""
    cur = CURATED.get(model, {})
    admitted = all(gates[k]["status"] == "PASS" for k in GATES)
    role = cur.get("role")
    if role == "BASELINE_ONLY_CONTROL":
        return "BASELINE_ONLY_CONTROL", "Phase 21B.4.20 control; never admitted as a candidate; may serve only as a regression baseline", False
    if role == "DERIVATIVE_NOT_A_FOUNDATION":
        return "NOT_ADMITTED", "fine-tuned derivative of another candidate architecture: recorded to avoid double counting, not a separate foundation", False
    if role in {"TEACHER_REFERENCE", "FUTURE_FRONTIER_ARCHITECTURE_REFERENCE"}:
        lic_ok = gates["A_license"]["status"] == "PASS"
        if role == "TEACHER_REFERENCE" and not lic_ok:
            return "FUTURE_FRONTIER_ARCHITECTURE_REFERENCE", "license not permissive: architecture reference only, not a distillation source", False
        return role, "too large for the first-stage budget; studied as reference, not admitted as a base", False
    if gates["A_license"]["status"] == "FAIL":
        return "NOT_ADMITTED", "fails the license gate: " + gates["A_license"]["note"], False
    if admitted:
        return "GENESIS_EVAL_ADMITTED", "passes all admission gates A-J on documented evidence: admitted for evaluation only; trainability is NOT proven", True
    failing = [f"{k}={gates[k]['status']}" for k in GATES if gates[k]["status"] != "PASS"]
    if raw_row.get("safetensors") and (_params_b(raw_row) or 0) <= 40:
        return "FUTURE_REASON_CANDIDATE", "fits the size envelope but gate(s) not passed: " + ", ".join(failing), False
    return "NOT_ADMITTED", "gate(s) not passed: " + ", ".join(failing), False


def build_refresh(raw: Mapping[str, Any]) -> dict[str, Any]:
    eco = raw["ecosystem"]
    models: dict[str, Any] = {}
    for mid, row in sorted(raw["models"].items()):
        cur = CURATED.get(mid, {})
        gates = evaluate_gates(mid, row, eco)
        klass, reason, admitted = classify(mid, gates, row)
        total = _params_b(row)
        ai = active_info(mid)
        moe_active = ai["active_parameters_b"]
        compute_b = moe_active if moe_active else total
        rec: dict[str, Any] = {
            "model": mid, "family": cur.get("family"), "revision_sha": row.get("revision_sha"),
            "license": {"card": row.get("license_card"), "name": row.get("license_name"), "gated": row.get("gated")},
            "architecture": (row.get("config_subset") or {}).get("architectures"),
            "model_type": (row.get("config_subset") or {}).get("model_type"),
            "total_parameters_b": total,
            "is_moe": is_moe(row),
            **{**ai, "active_parameters_source": ai["active_parameters_source"] or ("NOT_RECORDED" if is_moe(row) else "DENSE")},
            "trainability_proven": False, "trainability_evidence_ref": None,
            "admission_meaning": "admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists",
            **context_info(mid, row),
            "multimodality": cur.get("modality"),
            "tool_calling_template": (eco.get("template_and_layer_probes", {}).get(mid) or {}).get("template_mentions_tools"),
            "reasoning_template": (eco.get("template_and_layer_probes", {}).get(mid) or {}).get("template_mentions_thinking"),
            "structured_output": "NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase",
            "quantization_support": {"vendor_quantized_observed": cur.get("vendor_quantized", []),
                                     "runtime_4bit": "INFERRED_NOT_EXECUTED"},
            "gates": gates, "admitted_to_capability_eval": admitted,
            "class": klass, "class_reason": reason, "known_caveats": cur.get("caveats", []),
            "primary_sources": [f"https://huggingface.co/{mid}", f"https://huggingface.co/api/models/{mid}",
                                f"https://huggingface.co/{mid}/blob/main/config.json"],
        }
        if total:
            v = qlora_vram_gb(total)
            lo, hi = usd_per_million_tokens(compute_b)
            rec["estimates"] = {"kind": "ESTIMATE_NOT_MEASUREMENT", "qlora_vram_gb_range": list(v),
                                "usd_per_million_training_tokens_range": [lo, hi],
                                "pilot_5m_tokens_usd_range": [round(lo * 5, 2), round(hi * 5, 2)]}
        models[mid] = rec
    return models


def load_raw(root: Path) -> dict[str, Any]:
    return json.loads((root / "docs/orneur/phase-21/evidence/GENESIS_FOUNDATION_LANDSCAPE_RAW_HF_METADATA_2026-09-26.json").read_text())


SELECTION_RULE = (
    "No model is selected in this phase. A future selection must use per-capability results from the frozen "
    "Genesis Capability Eval V1 and this pre-registered rule, applied only after every finalist has completed the "
    "same trainability pilot: (1) a model must clear every frozen floor on the gating categories; (2) among "
    "survivors, drop any model Pareto-dominated on every gating category at equal or lower cost; (3) rank the "
    "remainder lexicographically by verification, then evidence_use, then trainability, then cost; (4) ties or "
    "irreconcilable trade-offs go to an explicit owner decision. strict_contracts is a report-only recovery-cost "
    "signal and is never a floor or a ranking input. Release date, parameter count and popularity are never inputs."
)


def build_document(raw: Mapping[str, Any]) -> dict[str, Any]:
    models = build_refresh(raw)
    by_class: dict[str, list[str]] = {c: [] for c in CLASSES}
    for mid, rec in models.items():
        by_class[rec["class"]].append(mid)
    return {
        "document": "GENESIS_FOUNDATION_LANDSCAPE_REFRESH",
        "date": "2026-09-26",
        "base_sha": "1eb31d92508a1da227d9457dd0e16ee370217c9a",
        "verdict": "FOUNDATION_LANDSCAPE_REFRESHED_NO_FOUNDATION_SELECTED",
        "selected_foundation": None,
        "foundation_selected": False,
        "training_authorized": False, "gpu_authorized": False, "provider_inference_authorized": False,
        "phase_21c_authorized": False,
        "evidence": {"raw_metadata_file": "docs/orneur/phase-21/evidence/GENESIS_FOUNDATION_LANDSCAPE_RAW_HF_METADATA_2026-09-26.json",
                     "collected_at_utc": raw["collected_at_utc"], "collector": "scripts/orneur_foundation_landscape_collect.py",
                     "weights_downloaded": raw["weights_downloaded"], "gpu_used": raw["gpu_used"],
                     "provider_inference": raw["provider_inference"],
                     "ecosystem_versions_latest_pypi": raw["ecosystem"].get("pypi_latest")},
        "gate_definitions": {g: "see GENESIS_FOUNDATION_LANDSCAPE_REFRESH_2026-09-26.md" for g in GATES},
        "gate_status_semantics": {"PASS": "documented evidence satisfies the gate", "FAIL": "documented evidence violates the gate",
                                  "UNVERIFIED": "no adequate evidence; treated as NOT passed"},
        "gate_basis_semantics": {"PRIMARY_SOURCE": "read directly from the vendor repo/API",
                                 "DERIVED_FROM_PRIMARY_SOURCE": "computed from primary-source fields",
                                 "DERIVED_ESTIMATE": "formula estimate, not a measurement",
                                 "INFERRED_NOT_EXECUTED": "expected from architecture; ORNEUR has NOT executed it",
                                 "NOT_VERIFIED": "unknown"},
        "budget_planning": {"kind": "PLANNING_ONLY_NOT_AUTHORIZATION", "owner_budget_inr": 10000,
                            "usd_range": list(BUDGET_USD_RANGE), "h100_usd_per_hour_persisted_list_rate": H100_USD_PER_HOUR,
                            "utilization_range": list(UTILIZATION_RANGE), "pilot_tokens": PILOT_TOKENS,
                            "pilot_max_fraction_of_budget": PILOT_MAX_FRACTION_OF_BUDGET,
                            "always_on_h100_usd_per_month": round(H100_USD_PER_HOUR * 720, 2),
                            "frontier_pretraining_possible_within_budget": False},
        "selection_rule": SELECTION_RULE,
        "class_membership": {c: sorted(v) for c, v in by_class.items()},
        "models": models,
    }
