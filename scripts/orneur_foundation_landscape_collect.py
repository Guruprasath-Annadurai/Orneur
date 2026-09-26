#!/usr/bin/env python3
"""Read-only collector for the Genesis 2026 foundation landscape refresh.

Fetches public Hugging Face model metadata (exact revision sha, license tag,
safetensors parameter counts, config.json) for a fixed candidate list.
No model weights are downloaded. No GPU, provider inference or training.
"""
from __future__ import annotations
import json, sys, urllib.request, urllib.error, datetime

CANDIDATES = [
    "Qwen/Qwen3-8B","Qwen/Qwen3.5-9B","Qwen/Qwen3.5-4B","Qwen/Qwen3.5-27B","Qwen/Qwen3.5-35B-A3B",
    "Qwen/Qwen3.6-27B","Qwen/Qwen3.6-35B-A3B","Qwen/Qwen3.8-27B","Qwen/Qwen3.8-Flash-Next",
    "Qwen/Qwen3.8-2.4T-A95B",
    "google/gemma-4-E4B-it","google/gemma-4-12B-it","google/gemma-4-12B","google/gemma-4-26B-A4B-it","google/gemma-4-31B-it",
    "mistralai/Mistral-Nemo-Instruct-2407","mistralai/Ministral-3-8B-Instruct-2512","mistralai/Ministral-3-14B-Instruct-2512",
    "mistralai/Ministral-3-14B-Base-2512","mistralai/Ministral-3-14B-Reasoning-2512",
    "mistralai/Mistral-Small-4-119B-2603","mistralai/Mistral-Large-3-675B-Instruct-2512",
    "deepseek-ai/DeepSeek-V4.1-Flash","deepseek-ai/DeepSeek-V4-Pro-0813","deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
    "microsoft/phi-4","microsoft/Phi-4-mini-instruct","microsoft/Fara1.5-9B","microsoft/MagenticBrain",
    "ibm-granite/granite-4.2-8b","ibm-granite/granite-4.2-3b","ibm-granite/granite-4.2-30b",
    "openai/gpt-oss-20b","openai/gpt-oss-120b",
    "zai-org/GLM-5.3-Flash","zai-org/GLM-5.3","zai-org/GLM-4.7-Flash",
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16","nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Base-BF16",
    "allenai/Olmo-3-7B-Instruct","LiquidAI/LFM2.5-2.6B","HuggingFaceTB/SmolLM3-3B",
    "meta-llama/Llama-4-Scout-17B-16E-Instruct","meta-llama/Llama-3.3-70B-Instruct",
]

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "orneur-landscape-collector"})
    return json.load(urllib.request.urlopen(req, timeout=40))

def raw(url):
    req = urllib.request.Request(url, headers={"User-Agent": "orneur-landscape-collector"})
    return urllib.request.urlopen(req, timeout=40).read().decode()


ARCH_PROBE = ["Qwen3_5ForConditionalGeneration","Qwen3_5MoeForConditionalGeneration","Gemma4ForConditionalGeneration",
    "Gemma4UnifiedForConditionalGeneration","GraniteForCausalLM","Olmo3ForCausalLM","Mistral3ForConditionalGeneration",
    "MistralForCausalLM","Qwen3ForCausalLM","GptOssForCausalLM","Glm4MoeLiteForCausalLM","NemotronHForCausalLM",
    "DeepseekV41ForCausalLM","DeepseekV4ForCausalLM","Glm5NextForConditionalGeneration","Qwen4ExpForConditionalGeneration",
    "Phi3ForCausalLM","Lfm2ForCausalLM","SmolLM3ForCausalLM","GlmMoeDsaForCausalLM","Qwen3_5MoeForCausalLM"]
LICENSE_MODELS = ["Qwen/Qwen3.8-Flash-Next","Qwen/Qwen3.8-2.4T-A95B","zai-org/GLM-5.3","LiquidAI/LFM2.5-2.6B"]
PROBE_MODELS = CANDIDATES  # every candidate is probed for the tokenizer/template gate


def ecosystem():
    eco = {}
    try:
        eco["pypi_latest"] = {p: get(f"https://pypi.org/pypi/{p}/json")["info"]["version"]
                              for p in ["transformers", "peft", "bitsandbytes", "vllm", "trl", "accelerate"]}
    except Exception as e:
        eco["pypi_error"] = repr(e)
    try:
        names = [x["name"] for x in get("https://api.github.com/repos/huggingface/transformers/contents/src/transformers/models")]
        eco["transformers_main_model_dirs"] = sorted(names)
    except Exception as e:
        eco["transformers_error"] = repr(e)
    try:
        doc = raw("https://raw.githubusercontent.com/vllm-project/vllm/main/docs/models/supported_models.md")
        eco["vllm_supported_models_lines"] = {a: (next((l[:200] for l in doc.splitlines() if f"`{a}`" in l), None)) for a in ARCH_PROBE}
    except Exception as e:
        eco["vllm_error"] = repr(e)
    lic = {}
    for m in LICENSE_MODELS:
        try:
            t = raw(f"https://huggingface.co/{m}/resolve/main/LICENSE")
            lic[m] = {"bytes": len(t), "sha256": __import__("hashlib").sha256(t.encode()).hexdigest(),
                      "clauses": [l.strip()[:300] for l in t.splitlines() if any(
                          w in l.lower() for w in ["model as a service", "ai work assistant", "revenue", "threshold",
                                                   "non-commercial", "monthly active"])][:8]}
        except Exception as e:
            lic[m] = {"error": repr(e)}
    eco["license_probes"] = lic
    probes = {}
    for m in PROBE_MODELS:
        r = {}
        try:
            info = get(f"https://huggingface.co/api/models/{m}")
            files = [s["rfilename"] for s in info.get("siblings", [])]
            r["files_of_interest"] = [f for f in files if f.lower().startswith(("license", "notice", "chat_template", "tokenizer", "tekken", "params"))][:14]
            tpl = None
            try:
                tpl = json.loads(raw(f"https://huggingface.co/{m}/resolve/main/tokenizer_config.json")).get("chat_template")
            except Exception:
                pass
            if tpl is None:
                try:
                    tpl = raw(f"https://huggingface.co/{m}/resolve/main/chat_template.jinja")
                except Exception:
                    pass
            if isinstance(tpl, list):
                tpl = json.dumps(tpl)
            r["template_present"] = tpl is not None
            if tpl:
                r["template_mentions_tools"] = "tools" in tpl
                r["template_mentions_thinking"] = any(k in tpl.lower() for k in ["think", "reasoning"])
            cfg = json.loads(raw(f"https://huggingface.co/{m}/resolve/main/config.json"))
            lt = cfg.get("text_config", cfg).get("layer_types")
            if lt:
                r["layer_types"] = sorted(set(lt))
        except Exception as e:
            r["error"] = repr(e)
        probes[m] = r
    eco["template_and_layer_probes"] = probes
    return eco


CLAIM_RE = ("context (length|window)|max(imum)? context|context_window|supports? (a )?\\d+\\s?[KkMm]|\\d+\\s?[KkMm]\\s?(token|context)|"
            "\\|\\s*\\d+\\s?[kK]\\s*\\||supports up to|\\bactive\\b|activated|A\\d+B|\\d+(\\.\\d+)?B (total|parameters)|parameters? .{0,20}total|total parameters|Number of Parameters")


def readme_claims(mid):
    """Vendor model-card lines that mention context or active parameters. Claims, not measurements."""
    import re
    try:
        t = raw(f"https://huggingface.co/{mid}/resolve/main/README.md")
    except Exception as e:
        return {"error": repr(e)}
    lines = [l.strip()[:300] for l in t.splitlines() if re.search(CLAIM_RE, l, re.I) and len(l) < 500
             and "<th" not in l and "<td" not in l]
    return {"readme_bytes": len(t), "readme_sha256": __import__("hashlib").sha256(t.encode()).hexdigest(), "lines": lines[:40]}


def main(out):
    rows = {}
    for mid in CANDIDATES:
        row = {"model": mid}
        try:
            info = get(f"https://huggingface.co/api/models/{mid}")
            card = info.get("cardData") or {}
            row.update({
                "revision_sha": info.get("sha"),
                "last_modified": info.get("lastModified"),
                "created_at": info.get("createdAt"),
                "gated": info.get("gated"),
                "license_card": card.get("license"),
                "license_name": card.get("license_name"),
                "license_link": card.get("license_link"),
                "pipeline_tag": info.get("pipeline_tag"),
                "library_name": info.get("library_name"),
                "tags": [t for t in (info.get("tags") or []) if not t.startswith("region:")][:40],
                "safetensors": info.get("safetensors"),
                "siblings_count": len(info.get("siblings") or []),
            })
        except Exception as e:  # recorded, never hidden
            row["info_error"] = repr(e)
        try:
            cfg = get(f"https://huggingface.co/{mid}/resolve/main/config.json")
            keep = {}
            def pick(d, prefix=""):
                for k, v in d.items():
                    if isinstance(v, (int, float, str, bool)) or v is None:
                        if k in {"model_type","architectures","hidden_size","num_hidden_layers","num_attention_heads",
                                 "num_key_value_heads","vocab_size","max_position_embeddings","intermediate_size",
                                 "num_experts","num_local_experts","n_routed_experts","num_experts_per_tok",
                                 "moe_intermediate_size","torch_dtype","dtype","sliding_window","head_dim"}:
                            keep[prefix + k] = v
                    elif isinstance(v, list) and k == "architectures":
                        keep[prefix + k] = v
                    elif isinstance(v, dict) and k in {"text_config","language_config","llm_config"}:
                        pick(v, k + ".")
            pick(cfg)
            row["config_subset"] = keep
            row["config_has_quantization_config"] = "quantization_config" in cfg
        except Exception as e:
            row["config_error"] = repr(e)
        row["vendor_card_claims"] = readme_claims(mid)
        rows[mid] = row
        print(mid, row.get("revision_sha","?")[:12] if row.get("revision_sha") else row.get("info_error","?")[:60],
              row.get("license_card"), file=sys.stderr)
    doc = {
        "collected_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "source": "https://huggingface.co/api/models/<id> and resolve/main/config.json",
        "weights_downloaded": False, "gpu_used": False, "provider_inference": False,
        "ecosystem": ecosystem(),
        "models": rows,
    }
    with open(out, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True); f.write("\n")

if __name__ == "__main__":
    main(sys.argv[1])
