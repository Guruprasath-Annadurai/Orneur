#!/usr/bin/env python3
"""Build docs/orneur/status/foundation/foundation_evidence.json (+ the readable report) from evidence_data.py.

Offline and deterministic: reads only files already in the repository (retrieved texts, tree manifests, repo evidence).
Performs NO network access, NO model loading, NO inference.  Run:  python3 scripts/foundation/build_evidence.py
The result is verified by scripts/foundation/verify_evidence.py.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evidence_data as D  # noqa: E402
from report_text import render_report  # noqa: E402

ROOT = HERE.parent.parent
OUTDIR = ROOT / "docs" / "orneur" / "status" / "foundation"
RET = OUTDIR / "retrieved"
GB = 1e9
CLAIM_CLASSES = ["DOCUMENTED_FACT", "INDEPENDENTLY_REPRODUCED", "UNTESTED_HYPOTHESIS", "NOT_VERIFIED"]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def blob_sha1(b: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def hf_file_url(repo: str, rev: str, path: str) -> str:
    return f"{D.HF}/{repo}/resolve/{rev}/{path}"


class Claims:
    def __init__(self, prefix: str):
        self.prefix, self.items = prefix, []

    def add(self, topic, statement, value, cls, url, rev, ts, **extra):
        assert cls in CLAIM_CLASSES, cls
        if not url.startswith(("http://", "https://", "repo:")):
            url = "repo:" + url
        c = {"id": f"{self.prefix}.{len(self.items) + 1:03d}", "topic": topic, "statement": statement, "value": value,
             "claim_class": cls, "source_url": url, "retrieved_at": ts, "revision": rev}
        c.update(extra)
        self.items.append(c)
        return c


# ----------------------------------------------------------------------------------------------------------
# Estimates (formulas shown in the report; every output is an UNTESTED_HYPOTHESIS)
# ----------------------------------------------------------------------------------------------------------
NF4_BYTES_PER_PARAM = 0.5 + 1 / 64 + 4 / (64 * 256)      # 4-bit code + 8-bit absmax per 64 + fp32 constant per 256 blocks
OVERHEAD = 1.5 * GB
H100_RATE = 3.95                                            # USD/h, "persisted list rate" quoted in the decision package
H100_BW = 3.35e12                                           # B/s, ASSUMPTION (public SXM spec; not re-fetched)
H100_BF16_TFLOPS = 989e12                                   # FLOP/s, as used by the decision package


def lora_params(c, r):
    q_out = c["heads"] * c["head_dim"]
    kv_out = c["kv_heads"] * c["head_dim"]
    h, I = c["hidden"], c["intermediate"]
    per_layer = r * ((h + q_out) + 2 * (h + kv_out) + (q_out + h) + 3 * (h + I))
    return per_layer * c["layers"]


def estimates(N, c):
    embed_all = c["vocab"] * c["hidden"] * (1 if c["tied"] else 2)
    nf4 = (N - embed_all) * NF4_BYTES_PER_PARAM + embed_all * 2
    out = {"params": N, "embed_params_all": embed_all, "bf16_weights_bytes": 2 * N, "nf4_static_bytes": nf4}
    kv_tok = 2 * c["layers"] * c["kv_heads"] * c["head_dim"] * 2
    out["kv_bytes_per_token_bf16"] = kv_tok
    out["kv_bytes_8k_seq"] = kv_tok * 8192
    for r in (16, 64):
        out[f"lora_r{r}_params"] = lora_params(c, r)
        out[f"lora_r{r}_state_bytes_adamw_fp32"] = lora_params(c, r) * 16
    L, h, V = c["layers"], c["hidden"], c["vocab"]
    for s in (2048, 4096):
        layer = 34 * s * h
        logits = s * V * (2 + 4)
        out[f"act_s{s}_ckpt_bytes"] = L * 2 * s * h + layer + logits
        out[f"act_s{s}_noshckpt_bytes"] = L * layer + logits
        for ck, key in ((True, "ckpt"), (False, "noshckpt")):
            act = out[f"act_s{s}_{key}_bytes"]
            central = nf4 + lora_params(c, 16) * 16 + act + OVERHEAD
            out[f"peak_s{s}_{key}_bytes"] = central
            out[f"peak_s{s}_{key}_range_bytes"] = [0.8 * central, 1.4 * central]
    lo_tps, hi_tps = 0.15 * H100_BF16_TFLOPS / (6 * N), 0.25 * H100_BF16_TFLOPS / (6 * N)
    out["qlora_tokens_per_s_range"] = [lo_tps, hi_tps]
    out["usd_per_1M_train_tokens_range"] = [H100_RATE / 3600 / hi_tps * 1e6, H100_RATE / 3600 / lo_tps * 1e6]
    # serving
    B, ctx, eff = 16, 2048, 0.5
    step = (2 * N + B * ctx * kv_tok) / (H100_BW * eff)
    tps = B / step
    out["serve_model"] = {"batch": B, "avg_ctx": ctx, "bandwidth_efficiency": eff, "step_seconds": step, "tokens_per_s": tps,
                          "usd_per_1M_output_tokens_at_full_utilisation": H100_RATE / 3600 / tps * 1e6}
    out["serve_4bit_weights_bytes_hypothesis"] = (N - embed_all) * (4.5 / 8) + embed_all * 2
    need = (2 * N + 8 * 8192 * kv_tok + OVERHEAD) / 0.9
    out["serve_bf16_gpu_memory_needed_bytes_batch8_ctx8k"] = need
    return out


def gpu_class(bytes_):
    gb = bytes_ / GB
    for cls in (16, 24, 40, 48, 80):
        if gb <= cls:
            return f"{cls}GB-class"
    return ">80GB (multi-GPU)"


# ----------------------------------------------------------------------------------------------------------
def build():
    repo_raw = load_json(ROOT / D.REPO_EVIDENCE["landscape_raw"])
    nemo_rca = load_json(ROOT / D.REPO_EVIDENCE["nemo_template_rca"])
    nemo_template_sha_repo = nemo_rca["A_pinned_tokenizer_config"]["chat_template_sha256"]
    nemo_tokcfg_sha_repo = nemo_rca["A_pinned_tokenizer_config"]["tokenizer_config_json_sha256"]

    # ---- retrieved text registry (hash verified)
    texts = {}
    trees = {}
    for slug, files in D.RETRIEVED_TEXTS.items():
        tree = load_json(RET / slug / "tree.json")
        trees[slug] = tree
        oid_by_path = {f["path"]: f for f in tree["files"]}
        for fn in files:
            p = RET / slug / fn
            b = p.read_bytes()
            entry = {"slug": slug, "file": fn, "path": str(p.relative_to(ROOT)), "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(),
                     "repo": tree["repo"], "revision": tree["revision"], "retrieved_at": D.T_FILE}
            if fn in oid_by_path:
                assert blob_sha1(b) == oid_by_path[fn]["git_blob_sha1"], (slug, fn, "blob id mismatch")
                entry["git_blob_sha1"] = oid_by_path[fn]["git_blob_sha1"]
                entry["verification"] = "BYTE_EXACT: git blob sha1 of stored bytes == Hugging Face tree oid at pinned revision"
                entry["source_url"] = hf_file_url(tree["repo"], tree["revision"], fn)
            else:  # extracted chat template
                tc = json.loads((RET / slug / "tokenizer_config.json").read_text(encoding="utf-8")) if (RET / slug / "tokenizer_config.json").exists() else None
                if tc is not None:
                    assert tc["chat_template"].encode("utf-8") == b, (slug, "template != tokenizer_config.chat_template")
                    entry["verification"] = "EXTRACTED_FROM_BYTE_EXACT_FILE: equals json.loads(tokenizer_config.json)['chat_template']; parent file git blob verified"
                    entry["parent_file"] = "tokenizer_config.json"
                    entry["git_blob_sha1_of_parent"] = oid_by_path["tokenizer_config.json"]["git_blob_sha1"]
                else:
                    assert entry["sha256"] == nemo_template_sha_repo, "nemo template sha != repo-recorded sha"
                    entry["verification"] = ("MATCHES_REPO_RECORDED_SHA256: sha256 equals chat_template_sha256 recorded from the cached pinned snapshot in "
                                             + D.REPO_EVIDENCE["nemo_template_rca"] + "; template read from the HF model API field config.tokenizer_config.chat_template at HEAD == pinned sha")
                    entry["repo_evidence_path"] = D.REPO_EVIDENCE["nemo_template_rca"]
                    entry["parent_file_git_blob_sha1"] = oid_by_path["tokenizer_config.json"]["git_blob_sha1"]
                    entry["parent_file_sha256_repo_recorded"] = nemo_tokcfg_sha_repo
                entry["source_url"] = hf_file_url(tree["repo"], tree["revision"], "tokenizer_config.json") + "#chat_template"
            texts[(slug, fn)] = entry
    apache_ref = ROOT / "docs/orneur/status/foundation/retrieved/reference/apache-2.0.txt"
    ref_texts = []
    if apache_ref.exists():
        ref_texts.append({"file": "apache-2.0.txt", "path": str(apache_ref.relative_to(ROOT)), "bytes": apache_ref.stat().st_size,
                          "sha256": sha256_file(apache_ref), "source_url": "https://www.apache.org/licenses/LICENSE-2.0.txt",
                          "retrieved_at": "2026-10-11T19:16:00Z", "revision": "UNVERSIONED_WEB_PAGE@2026-10-11T19:16:00Z",
                          "basis": "curl GET of the canonical Apache-2.0 text; reference only, NOT a repository license file of any candidate"})
    q3_lic_bytes = (RET / "qwen3-8b" / "LICENSE").read_bytes()
    canon = apache_ref.read_bytes() if apache_ref.exists() else b""
    q3_equals_canon = bool(canon) and q3_lic_bytes == canon.replace(b"Copyright [yyyy] [name of copyright owner]", b"Copyright 2024 Alibaba Cloud").rstrip(b"\n")

    est = {}
    cands = []
    for slug, d in D.DEEP.items():
        N, c = d["params"], d["cfg"]
        est[slug] = estimates(N, c)
        cl = Claims(slug)
        rev, repo = d["revision"], d["repo"]
        api = f"{D.HF}/api/models/{repo}"
        tree = trees[slug]
        cl.add("identity", f"Repository {repo} resolves at exact commit {rev}; the model API 'sha' at retrieval time equals this commit (no drift since the 2026-09-26 package).",
               {"repo": repo, "revision": rev, "head_sha_at_retrieval": d["head_sha_retrieved"], "lastModified": d["last_modified"]},
               "DOCUMENTED_FACT", api, rev, D.T_API)
        cl.add("identity", "File list with git blob ids and LFS sha256 of every weight/tokenizer file at the pinned commit (stored as retrieved/<slug>/tree.json).",
               {"tree_file": f"docs/orneur/status/foundation/retrieved/{slug}/tree.json", "n_files": len(tree["files"])},
               "DOCUMENTED_FACT", f"{D.HF}/api/models/{repo}/tree/{rev}", rev, D.T_API)
        cl.add("parameters", f"Total parameters from safetensors metadata: {N:,} (all BF16).", {"total": N},
               "DOCUMENTED_FACT", api, rev, D.T_API)
        cfgurl = hf_file_url(repo, rev, "config.json")
        cl.add("architecture", f"architectures={d['architectures']} model_type={d['model_type']} (dense decoder-only).",
               {"architectures": d["architectures"], "model_type": d["model_type"]}, "DOCUMENTED_FACT", cfgurl, rev, D.T_FILE,
               evidence_text=f"retrieved/{slug}/config.json")
        cl.add("architecture", f"layers={c['layers']} hidden={c['hidden']} heads={c['heads']} kv_heads={c['kv_heads']} (GQA ratio {c['heads'] // c['kv_heads']}:1) head_dim={c['head_dim']} intermediate={c['intermediate']}.",
               {k: c[k] for k in ("layers", "hidden", "heads", "kv_heads", "head_dim", "intermediate")} | {"head_dim_source": c["head_dim_source"]},
               "DOCUMENTED_FACT", cfgurl, rev, D.T_FILE, evidence_text=f"retrieved/{slug}/config.json")
        cl.add("architecture", f"vocab_size={c['vocab']} tie_word_embeddings={c['tied']} rope_theta={c['rope_theta']} dtype={c['dtype']}.",
               {"vocab": c["vocab"], "tied_embeddings": c["tied"], "rope_theta": c["rope_theta"], "dtype": c["dtype"], "sliding_window": c["sliding_window"]},
               "DOCUMENTED_FACT", cfgurl, rev, D.T_FILE, evidence_text=f"retrieved/{slug}/config.json")
        cl.add("context", f"config.json max_position_embeddings={c['max_pos']}.", {"max_position_embeddings": c["max_pos"]},
               "DOCUMENTED_FACT", cfgurl, rev, D.T_FILE, evidence_text=f"retrieved/{slug}/config.json")
        cands.append((slug, d, cl))

    # ---- per-candidate specific claims -------------------------------------------------------------------
    by = {s: cl for s, d, cl in cands}
    # Qwen3-8B ------------------------------------------------------------------------------------------
    s, d = "qwen3-8b", D.DEEP["qwen3-8b"]
    cl, rev, repo = by[s], d["revision"], d["repo"]
    readme = hf_file_url(repo, rev, "README.md")
    cl.add("context", "Model card: context length 32,768 natively and 131,072 tokens with YaRN; non-embedding parameters 6.95B; the card explains that config max_position_embeddings=40,960 reserves 32,768 output + 8,192 prompt tokens, and warns static YaRN may degrade short-text quality.",
           {"native": 32768, "yarn_extended": 131072, "config_max_position_embeddings": 40960, "non_embedding_params_B": 6.95}, "DOCUMENTED_FACT", readme, rev, D.T_FILE)
    tc_url = hf_file_url(repo, rev, "tokenizer_config.json")
    t = texts[(s, "chat_template.jinja.txt")]
    cl.add("tokenizer", "tokenizer_class=Qwen2Tokenizer; eos_token='<|im_end|>' (151645); pad_token='<|endoftext|>' (151643); bos_token=null; model_max_length=131072; add_bos_token=false. generation_config eos_token_id=[151645,151643], pad_token_id=151643.",
           {"tokenizer_class": "Qwen2Tokenizer", "eos": "<|im_end|>", "pad": "<|endoftext|>", "bos": None, "generation_config_eos_ids": [151645, 151643]},
           "DOCUMENTED_FACT", tc_url, rev, D.T_FILE, evidence_text=f"retrieved/{s}/tokenizer_config.json")
    cl.add("chat_template", f"ChatML template ({t['bytes']} bytes, sha256 {t['sha256']}) with a hybrid thinking switch: add_generation_prompt appends '<|im_start|>assistant\\n' and, when enable_thinking is defined and false, an empty '<think>\\n\\n</think>\\n\\n' block; assistant history keeps <think> content only after the last user query; tool calls use <tool_call> JSON; no default system prompt is injected.",
           {"template_sha256": t["sha256"], "template_bytes": t["bytes"], "thinking_switch": "enable_thinking (default on); soft switches /think and /no_think (model card)", "special_think_tokens": {"<think>": 151667, "</think>": 151668, "special_flag": False}},
           "DOCUMENTED_FACT", tc_url + "#chat_template", rev, D.T_FILE, evidence_text=f"retrieved/{s}/chat_template.jinja.txt")
    cl.add("generation_defaults", "generation_config.json: do_sample=true temperature=0.6 top_k=20 top_p=0.95. Model card: thinking mode Temperature=0.6/TopP=0.95/TopK=20/MinP=0 and 'DO NOT use greedy decoding'; non-thinking Temperature=0.7/TopP=0.8/TopK=20/MinP=0; recommended output length 32,768 (38,912 for hard math/code).",
           {"thinking": {"temperature": 0.6, "top_p": 0.95, "top_k": 20}, "non_thinking": {"temperature": 0.7, "top_p": 0.8, "top_k": 20}, "greedy": "discouraged in thinking mode"},
           "DOCUMENTED_FACT", readme, rev, D.T_FILE, evidence_text=f"retrieved/{s}/generation_config.json")
    cl.add("serving", "Model card requires transformers>=4.51.0 ('KeyError: qwen3' otherwise); recommends vllm>=0.8.5 or sglang>=0.4.6.post1 with a reasoning parser; states Ollama, LMStudio, MLX-LM, llama.cpp and KTransformers support Qwen3.",
           {"transformers_min": "4.51.0", "vllm_min": "0.8.5", "sglang_min": "0.4.6.post1"}, "DOCUMENTED_FACT", readme, rev, D.T_FILE)
    cl.add("serving", "vLLM docs list Qwen3ForCausalLM (example Qwen/Qwen3-8B) with LoRA and PP support marks.", {"architecture": "Qwen3ForCausalLM", "lora": True, "pp": True, "extraction": "tool_query"},
           "DOCUMENTED_FACT", "https://docs.vllm.ai/en/latest/models/supported_models/", "UNVERSIONED_WEB_PAGE@" + D.T_WEB, D.T_WEB)
    cl.add("quantization", "Ollama library qwen3:8b: 8.19B parameters, Q4_K_M, Apache-2.0 text shown (third-party registry, not the vendor).", {"ollama_tag": "qwen3:8b", "quant": "Q4_K_M", "extraction": "tool_query"},
           "DOCUMENTED_FACT", "https://ollama.com/library/qwen3:8b", "UNVERSIONED_WEB_PAGE@" + D.T_WEB, D.T_WEB)
    cl.add("benchmarks", "Vendor-reported (Qwen3 Technical Report, arXiv 2505.09388) Qwen3-8B THINKING mode: " + ", ".join(f"{k} {v}" for k, v in D.QWEN3_8B_THINKING.items()) + ".",
           D.QWEN3_8B_THINKING, "DOCUMENTED_FACT", "https://arxiv.org/pdf/2505.09388", "arXiv:2505.09388 (version as served 2026-10-11)", D.T_PAPER,
           limitations=["VENDOR_REPORTED, not independently reproduced", "Thinking mode with up to 32,768 output tokens (38,912 for AIME) - not comparable to the locked 64-token greedy smoke contract",
                        "Sampling temp 0.6/top-p 0.95/top-k 20; harness and prompts are the vendor's own; contamination status of public benchmarks unknowable from outside",
                        "Table values obtained through the tool's PDF query extraction (LLM-assisted), spot-consistent with the paper but not hand-verified cell by cell"],
           extraction="tool_query")
    cl.add("benchmarks", "Vendor-reported Qwen3-8B NON-THINKING mode: " + ", ".join(f"{k} {v}" for k, v in D.QWEN3_8B_NONTHINKING.items()) + ".",
           D.QWEN3_8B_NONTHINKING, "DOCUMENTED_FACT", "https://arxiv.org/pdf/2505.09388", "arXiv:2505.09388 (version as served 2026-10-11)", D.T_PAPER,
           limitations=["VENDOR_REPORTED, not independently reproduced", "non-thinking sampling temp 0.7/top-p 0.8/top-k 20 and presence penalty 1.5 per the paper, max output 32,768 tokens",
                        "IFEval strict-prompt 83.0 is the only strict-format figure in the table; ORNEUR's contract-style exact-output behaviour is not measured by any listed benchmark"],
           extraction="tool_query")
    cl.add("multilingual", "Model card: 'Support of 100+ languages and dialects'; vendor tables report Multi-IF 71.2/69.2, INCLUDE 67.8/62.5, MMMLU(14 languages) 74.4/66.9 (thinking/non-thinking).",
           {"languages_claim": "100+ languages and dialects", "MMMLU14_thinking": 74.4, "MMMLU14_nonthinking": 66.9}, "DOCUMENTED_FACT", readme, rev, D.T_FILE,
           limitations=["vendor-reported; per-language breakdown not in the card"])
    cl.add("safety", "The model card contains no safety evaluation, red-team report or acceptable-use policy section (card read in full at the pinned commit).", {"safety_section_present": False},
           "DOCUMENTED_FACT", readme, rev, D.T_FILE, limitations=["absence in the card; the arXiv report was only queried for evaluation tables"])
    cl.add("known_issues", "Repo control program: attempt 5 (non-thinking `qwen3_8b_non_thinking_v1`, vLLM 0.29.0, transformers 5.16.1): server ready, HTTP 200 x3; smokes A PASS 'READY', B FAIL '2 + 3 = 5', C PASS; 0 reasoning tokens; capability unproven.",
           {"attempt": 5, "smokes": "PASS/FAIL/PASS", "finish_reason": "stop x3"}, "INDEPENDENTLY_REPRODUCED", D.REPO_EVIDENCE["qwen3_runtime"], "repo@" + D.BASE_SHA, D.T_REPO)
    cl.add("known_issues", "Repo raw log (attempt 5): 'Default vLLM sampling parameters have been overridden by the model's generation_config.json: {temperature: 0.6, top_k: 20, top_p: 0.95}'. The locked requests send temperature 0, top_p 1, seed 0 but not top_k, so the effective sampler is greedy only because temperature=0; the generation_config silently supplies other defaults.",
           {"log_line": 78}, "INDEPENDENTLY_REPRODUCED", D.REPO_EVIDENCE["qwen5_log"], "repo@" + D.BASE_SHA, D.T_REPO)
    cl.add("known_issues", "Public tracker: Unsloth issue #2771 reports 'train on completions only' failing with Qwen3 (all labels -100, sequences truncated to 1024 tokens so the assistant part was removed) - a response-masking pitfall when fine-tuning with the Qwen3 template.",
           {"issue": "unslothai/unsloth#2771"}, "DOCUMENTED_FACT", "https://github.com/unslothai/unsloth/issues/2771", "UNVERSIONED_WEB_PAGE@" + D.T_WEB, D.T_WEB,
           limitations=["issue excerpt only, not reproduced; version-specific (unsloth 2025.6.2 / trl 0.18.2 at report time)"])
    cl.add("known_issues", "Public tutorial guidance (third-party): when fine-tuning Qwen3 pass enable_thinking=False while formatting data and strip residual <think></think> blocks - consistent with the template reading above (empty think block inserted when enable_thinking=false).",
           {}, "DOCUMENTED_FACT", "https://github.com/fractal-nyc/bootcamp-monorepo/blob/41558ff3c498431695de0e5d45c59b17b15a7371/curriculum/weeks/06-models-and-evals/sp2026/day2.md", "41558ff3c498431695de0e5d45c59b17b15a7371", D.T_WEB,
           limitations=["third-party educational material, not authoritative"])

    # Mistral Nemo --------------------------------------------------------------------------------------
    s, d = "mistral-nemo-instruct-2407", D.DEEP["mistral-nemo-instruct-2407"]
    cl, rev, repo = by[s], d["revision"], d["repo"]
    readme = hf_file_url(repo, rev, "README.md")
    t = texts[(s, "chat_template.jinja.txt")]
    cl.add("context", "Model card: 'Trained with a 128k context window'; config max_position_embeddings=131,072, rope_theta=1e6, no sliding window. Ollama's page shows a '1000K context window' for the default tag, which conflicts with the vendor's 128k and is NOT adopted.",
           {"vendor_trained_context_tokens": "128k", "config_max_position_embeddings": 131072, "ollama_listing_conflict": "1000K"}, "DOCUMENTED_FACT", readme, rev, D.T_FILE)
    cl.add("tokenizer", "Two tokenizer paths ship in the repo: tekken.json (14,801,223 bytes; Tekken/tiktoken-style, used by mistral_common/mistral-inference and by vLLM '--tokenizer-mode mistral') and an HF tokenizer.json + tokenizer_config.json (181,297 bytes) containing a Jinja chat template. config.json bos_token_id=1, eos_token_id=2; the HF API tokenizer_config summary lists bos/eos/unk but NO pad_token (pad must be set explicitly for batch training).",
           {"tekken_json_bytes": 14801223, "tokenizer_config_bytes": 181297, "bos_id": 1, "eos_id": 2, "pad_token_defined": False, "vocab_size": 131072},
           "DOCUMENTED_FACT", f"{D.HF}/api/models/{repo}/tree/{rev}", rev, D.T_API,
           limitations=["bos/eos strings (<s>, </s>) could not be read verbatim because the tool strips angle-bracket tokens; ids are from config.json"])
    cl.add("chat_template", f"HF Jinja template ({t['bytes']} bytes, sha256 {t['sha256']}): '[INST]...[/INST]' format, system message prepended to the LAST user message, strict user/assistant alternation (raises otherwise), [AVAILABLE_TOOLS]/[TOOL_CALLS]/[TOOL_RESULTS] with 9-character tool-call ids, no thinking mode. This sha256 equals the repo-recorded hash of the cached pinned snapshot.",
           {"template_sha256": t["sha256"], "template_bytes": t["bytes"], "matches_repo_recorded_sha256": True, "thinking_switch": None},
           "DOCUMENTED_FACT", hf_file_url(repo, rev, "tokenizer_config.json") + "#chat_template", rev, D.T_API, evidence_text=f"retrieved/{s}/chat_template.jinja.txt")
    cl.add("chat_template", "Repo root-cause analysis: under transformers 5.16.1 / tokenizers 0.23.2 AutoTokenizer on the pinned snapshot returns MistralCommonBackend (selected because tekken.json is present), which carries no chat_template -> vLLM 0.29.0 raises ChatTemplateResolutionError (HTTP 400) before generation; the same files without tekken.json resolve the template (sha256 e4676cb5...).",
           {"attempts": [1, 2], "http": 400}, "INDEPENDENTLY_REPRODUCED", D.REPO_EVIDENCE["nemo_template_rca"], "repo@" + D.BASE_SHA, D.T_REPO,
           limitations=["the container's own tokenizer class was not directly observed (repo states this)"])
    cl.add("generation_defaults", "generation_config.json contains only bos/eos ids (no sampling defaults). Model card: 'Unlike previous Mistral models, Mistral Nemo requires smaller temperatures. We recommend to use a temperature of 0.3'; examples use temperature 0.35.",
           {"recommended_temperature": 0.3}, "DOCUMENTED_FACT", readme, rev, D.T_FILE, evidence_text=f"retrieved/{s}/generation_config.json")
    cl.add("serving", "Model card recommends mistral_inference / mistral_common; transformers usage needs a version supporting the model ('install from source' note); function calling requires 9-character alphanumeric tool-call ids. Ollama lists mistral-nemo:latest at 7.1GB.",
           {"ollama_default_tag_size": "7.1GB", "extraction": "tool_query"}, "DOCUMENTED_FACT", readme, rev, D.T_FILE)
    cl.add("known_issues", "Repo control program: attempts 1-2 (HF tokenizer path) HTTP 400 template-resolution errors; attempt 3 (`mistral_nemo_native_v1`, --tokenizer-mode mistral) HTTP 200 x3, smokes FAIL/FAIL/FAIL (verbose prose: 'Understood. I'm ready.', explanation with calculation, fenced JSON twice).",
           {"attempts": 3, "smokes": "FAIL/FAIL/FAIL"}, "INDEPENDENTLY_REPRODUCED", D.REPO_EVIDENCE["nemo_runtime"], "repo@" + D.BASE_SHA, D.T_REPO)
    cl.add("known_issues", "Public trackers: vLLM PR #7739 (a user reports HTTP 400 with --tokenizer-mode mistral on Mistral-Nemo-Instruct-2407; maintainer fix = special-token decode policy); HF discussions #14 (system role not included correctly in chat_template) and #61 (template raises 'roles must alternate' after tool use).",
           {"vllm_pr": 7739, "hf_discussions": [14, 61]}, "DOCUMENTED_FACT", "https://github.com/vllm-project/vllm/issues/7739", "UNVERSIONED_WEB_PAGE@" + D.T_WEB, D.T_WEB,
           limitations=["search excerpts only; fixes landed in 2024 vLLM and are not shown to apply to vLLM 0.29.0"])
    cl.add("benchmarks", "Vendor model card benchmarks: " + ", ".join(f"{k} {v}%" for k, v in D.NEMO_README_BENCH.items()) + ".", D.NEMO_README_BENCH, "DOCUMENTED_FACT", readme, rev, D.T_FILE,
           limitations=["VENDOR_REPORTED; the card does not state the harness, prompts or whether these are base-model or instruct-model numbers", "no coding, math, instruction-following or structured-output benchmark is reported", "TruthfulQA/NaturalQuestions-style numbers are not comparable with Qwen3/Phi-4 report suites"])
    cl.add("multilingual", "Model card: trained on a large proportion of multilingual and code data; languages en fr de es it pt ru zh ja; MMLU per language: " + ", ".join(f"{k} {v}%" for k, v in D.NEMO_README_MMLU_LANG.items()) + ".",
           {"languages": ["en", "fr", "de", "es", "it", "pt", "ru", "zh", "ja"], "mmlu_by_language": D.NEMO_README_MMLU_LANG}, "DOCUMENTED_FACT", readme, rev, D.T_FILE, limitations=["vendor-reported; harness unstated"])
    cl.add("safety", "Model card 'Limitations': 'It does not have any moderation mechanisms'. No safety evaluation is published in the card.", {"moderation_mechanisms": False},
           "DOCUMENTED_FACT", readme, rev, D.T_FILE)

    # Phi-4 ---------------------------------------------------------------------------------------------
    s, d = "phi-4", D.DEEP["phi-4"]
    cl, rev, repo = by[s], d["revision"], d["repo"]
    readme = hf_file_url(repo, rev, "README.md")
    t = texts[(s, "chat_template.jinja.txt")]
    cl.add("context", "Model card: context length 16K tokens; config max_position_embeddings=original_max_position_embeddings=16,384; rope_scaling=null (no vendor-documented extension).",
           {"native": 16384, "extension": None}, "DOCUMENTED_FACT", readme, rev, D.T_FILE)
    cl.add("tokenizer", "tokenizer_class=GPT2Tokenizer (100,352 vocab); bos_token='<|endoftext|>' (100257); eos_token='<|im_end|>' (100265); pad_token='<|dummy_85|>' (100349); generation_config eos_token_id=[100257,100265]. Special tokens carry lstrip/rstrip=true. The pad token differs from eos (an earlier public Unsloth write-up describes a pad==eos problem in other revisions; not present in this revision).",
           {"tokenizer_class": "GPT2Tokenizer", "bos": "<|endoftext|>", "eos": "<|im_end|>", "pad": "<|dummy_85|>", "pad_equals_eos": False}, "DOCUMENTED_FACT",
           hf_file_url(repo, rev, "tokenizer_config.json"), rev, D.T_FILE, evidence_text=f"retrieved/{s}/tokenizer_config.json")
    cl.add("chat_template", f"ChatML-like template ({t['bytes']} bytes, sha256 {t['sha256']}): <|im_start|>role<|im_sep|>content<|im_end|>; roles system/user/assistant only (no tool role, no thinking switch); no BOS added; no default system prompt; add_generation_prompt appends '<|im_start|>assistant<|im_sep|>'.",
           {"template_sha256": t["sha256"], "template_bytes": t["bytes"], "thinking_switch": None, "tool_support": False}, "DOCUMENTED_FACT",
           hf_file_url(repo, rev, "tokenizer_config.json") + "#chat_template", rev, D.T_FILE, evidence_text=f"retrieved/{s}/chat_template.jinja.txt")
    cl.add("generation_defaults", "generation_config.json: eos=[100257,100265], pad=100349, no sampling defaults; card widget metadata sets temperature 0.", {"sampling_defaults": None},
           "DOCUMENTED_FACT", hf_file_url(repo, rev, "generation_config.json"), rev, D.T_FILE, evidence_text=f"retrieved/{s}/generation_config.json")
    cl.add("serving", "vLLM docs list Phi3ForCausalLM (Phi-4, Phi-3; example microsoft/phi-4) with LoRA and PP marks; Ollama library phi4 (14B, 16k context).",
           {"architecture": "Phi3ForCausalLM", "lora": True, "pp": True, "extraction": "tool_query"}, "DOCUMENTED_FACT", "https://docs.vllm.ai/en/latest/models/supported_models/", "UNVERSIONED_WEB_PAGE@" + D.T_WEB, D.T_WEB)
    cl.add("benchmarks", "Vendor model card (OpenAI simple-evals): " + ", ".join(f"{k} {v}" for k, v in D.PHI4_README_SIMPLE_EVALS.items()) + ".", D.PHI4_README_SIMPLE_EVALS, "DOCUMENTED_FACT", readme, rev, D.T_FILE,
           limitations=["VENDOR_REPORTED with the simple-evals harness; the card itself notes Llama scores are lower than Meta reports because simple-evals has strict formatting requirements - harness format-sensitivity is acknowledged",
                        "SimpleQA 3.0 shows weak factual recall; DROP 75.5 trails Qwen2.5-14B (85.5) in the card's own table",
                        "card says training data cutoff June 2024 and synthetic data used; contamination of MMLU/MATH/HumanEval cannot be excluded from outside (technical report not re-read this pass)"])
    cl.add("multilingual", "Model card: multilingual data about 8% of training data; 'trained primarily on English text. Languages other than English will experience worse performance ... phi-4 is not intended to support multilingual use'.",
           {"multilingual_share": "about 8%", "intended": "English"}, "DOCUMENTED_FACT", readme, rev, D.T_FILE)
    cl.add("safety", "Model card: safety post-training with SFT + iterative DPO on open and in-house synthetic datasets; quantitative evaluation on open-source safety benchmarks and adversarial conversation simulation; independent Microsoft AI Red Team (AIRT) assessment. Numeric results are NOT in the card ('refer to the technical report'). Card also warns about Python-centric code data and recommends Azure AI Content Safety style guardrails.",
           {"post_training": "SFT + iterative DPO", "red_team": "Microsoft AIRT", "numeric_results_in_card": False}, "DOCUMENTED_FACT", readme, rev, D.T_FILE,
           limitations=["vendor-reported; not independently reproduced; numbers live in the technical report (arXiv:2412.08905), not re-read"])
    cl.add("training_data", "data_summary_card.md (updated 24-Nov-2025, present in the pinned commit): data cutoff 30-Jun-2024; commercially licensed datasets used; synthetic AI-generated data used; private third-party datasets 'cannot be provided due to unavailability of the underlying data'.",
           {"cutoff": "2024-06-30", "synthetic_data": True, "licensed_data": True}, "DOCUMENTED_FACT", hf_file_url(repo, rev, "data_summary_card.md"), rev, D.T_FILE)
    cl.add("known_issues", "Repo control program: attempt 1 on the canonical HF path: HTTP 200 x3; smokes A PASS 'READY', B FAIL '2 + 3 equals 5.', C FAIL (prose + fenced JSON, finish_reason=length at the 64-token budget).",
           {"attempt": 1, "smokes": "PASS/FAIL/FAIL", "C_finish_reason": "length"}, "INDEPENDENTLY_REPRODUCED", D.REPO_EVIDENCE["phi4_runtime"], "repo@" + D.BASE_SHA, D.T_REPO)
    cl.add("known_issues", "Public: Unsloth's Phi-4 write-up documents tokenizer/pad-token bugs in the original release (masked eos -> endless generations); NVIDIA Automodel tracker lists microsoft/phi-4 PEFT with fused-QKV splitting as a tested path - fused qkv_proj/gate_up projections require framework support when exporting LoRA adapters.",
           {}, "DOCUMENTED_FACT", "https://unsloth.ai/blog/phi4", "UNVERSIONED_WEB_PAGE@" + D.T_WEB, D.T_WEB, limitations=["third-party; applies to revisions that may predate the pinned commit"])

    # Qwen2.5-3B unsloth --------------------------------------------------------------------------------
    s, d = "unsloth-qwen2.5-3b-instruct", D.DEEP["unsloth-qwen2.5-3b-instruct"]
    cl, rev, repo = by[s], d["revision"], d["repo"]
    up = d["upstream"]
    readme = hf_file_url(repo, rev, "README.md")
    t = texts[(s, "chat_template.jinja.txt")]
    cl.add("identity", "Upstream original Qwen/Qwen2.5-3B-Instruct is at commit aa8e72537993ba99e69dfaafa59ed015b17504d1 (unchanged since 2024-09-25); the unsloth repack's weight shards are byte-identical (same LFS sha256 and sizes) to upstream; differences are config (unsloth_fixed, sliding_window) and tokenizer files.",
           {"upstream_revision": up["revision"], "weights_identical_to_upstream": True}, "DOCUMENTED_FACT", f"{D.HF}/api/models/{up['repo']}/tree/{up['revision']}", up["revision"], D.T_API)
    cl.add("context", "Model card: full 32,768 tokens, generation 8,192 tokens; 'Long-context Support up to 128K tokens' also appears in the card intro (inconsistent with the 32,768 architecture line; no rope_scaling in config). ModelSpec.context_length=4096 is a training-time choice, not the architectural ceiling.",
           {"native": 32768, "card_intro_claim": "128K (unsupported by config)", "model_spec_context_length": 4096}, "DOCUMENTED_FACT", readme, rev, D.T_FILE)
    cl.add("tokenizer", "tokenizer_class=Qwen2Tokenizer; eos='<|im_end|>'; pad='<|vision_pad|>' (151654); padding_side=left; bos=null.",
           {"eos": "<|im_end|>", "pad": "<|vision_pad|>", "padding_side": "left"}, "DOCUMENTED_FACT", hf_file_url(repo, rev, "tokenizer_config.json"), rev, D.T_FILE, evidence_text=f"retrieved/{s}/tokenizer_config.json")
    cl.add("chat_template", f"ChatML template ({t['bytes']} bytes, sha256 {t['sha256']}) that INJECTS the default system prompt 'You are Qwen, created by Alibaba Cloud. You are a helpful assistant.' whenever no system message is supplied; tool calls via <tool_call>; no thinking mode. Vendor identity text is therefore in every default prompt.",
           {"template_sha256": t["sha256"], "template_bytes": t["bytes"], "default_system_prompt": "You are Qwen, created by Alibaba Cloud. You are a helpful assistant.", "thinking_switch": None},
           "DOCUMENTED_FACT", hf_file_url(repo, rev, "tokenizer_config.json") + "#chat_template", rev, D.T_FILE, evidence_text=f"retrieved/{s}/chat_template.jinja.txt")
    cl.add("generation_defaults", "generation_config.json: do_sample=true temperature=0.7 top_k=20 top_p=0.8 repetition_penalty=1.05 max_length=32768. A repetition_penalty default is not neutralised by temperature=0 if a server applies generation_config defaults (see harness finding HE-8).",
           {"repetition_penalty": 1.05, "temperature": 0.7, "top_p": 0.8, "top_k": 20}, "DOCUMENTED_FACT", hf_file_url(repo, rev, "generation_config.json"), rev, D.T_FILE, evidence_text=f"retrieved/{s}/generation_config.json")
    cl.add("serving", "vLLM docs list Qwen2ForCausalLM with LoRA and PP marks (example Qwen/Qwen2-7B-Instruct). Not a repo control; no repo runtime evidence for this model under the pinned vLLM 0.29.0 / transformers 5.16.1 stack.",
           {"architecture": "Qwen2ForCausalLM", "lora": True, "pp": True, "extraction": "tool_query"}, "DOCUMENTED_FACT", "https://docs.vllm.ai/en/latest/models/supported_models/", "UNVERSIONED_WEB_PAGE@" + D.T_WEB, D.T_WEB)
    cl.add("benchmarks", "Vendor-reported (Qwen3 Technical Report Table 20, non-thinking comparison column for Qwen2.5-3B-Instruct): " + ", ".join(f"{k} {v}" for k, v in D.QWEN25_3B_NONTHINKING_IN_QWEN3_REPORT.items()) + ".",
           D.QWEN25_3B_NONTHINKING_IN_QWEN3_REPORT, "DOCUMENTED_FACT", "https://arxiv.org/pdf/2505.09388", "arXiv:2505.09388 (version as served 2026-10-11)", D.T_PAPER,
           limitations=["VENDOR_REPORTED by the publisher of a competing newer model (comparison baseline, not a model-card result)", "Qwen2.5-3B's own card defers to a blog and reports no numbers", "same-harness comparison inside one report, extraction via tool_query"],
           extraction="tool_query")
    cl.add("multilingual", "Model card: 'Multilingual support for over 29 languages' including Chinese, English, French, Spanish, Portuguese, German, Italian, Russian, Japanese, Korean, Vietnamese, Thai, Arabic.", {"languages_claim": "29+"}, "DOCUMENTED_FACT", readme, rev, D.T_FILE)
    cl.add("safety", "The card contains no safety evaluation or acceptable-use section; the license disclaims safety/stability of the Materials and outputs (6.b).", {"safety_section_present": False}, "DOCUMENTED_FACT", readme, rev, D.T_FILE)

    # ------------------------------------------------------------------------------------------------------
    # estimates as claims (UNTESTED_HYPOTHESIS)
    for slug, dd, cl in cands:
        e = est[slug]
        cl.add("memory_estimate", "ESTIMATE: BF16 serving weights = 2 x params; QLoRA static = (params - embeddings) x 0.5159 B (NF4 + double-quant constants) + embeddings x 2 B.",
               {"bf16_weights_GB": round(e["bf16_weights_bytes"] / GB, 2), "qlora_static_GB": round(e["nf4_static_bytes"] / GB, 2), "formula": "see report section 'Estimates: formulas'"},
               "UNTESTED_HYPOTHESIS", "repo:scripts/foundation/build_evidence.py", "repo@" + D.BASE_SHA, D.T_REPO, derivation="arithmetic over documented parameter/config values")
        cl.add("memory_estimate", "ESTIMATE: QLoRA peak (r=16, micro-batch 1, gradient checkpointing, flash-attention-class kernels), central value with the package's 0.8x-1.4x band.",
               {"peak_2048_GB": round(e["peak_s2048_ckpt_bytes"] / GB, 1), "peak_2048_range_GB": [round(x / GB, 1) for x in e["peak_s2048_ckpt_range_bytes"]],
                "peak_4096_GB": round(e["peak_s4096_ckpt_bytes"] / GB, 1), "peak_4096_range_GB": [round(x / GB, 1) for x in e["peak_s4096_ckpt_range_bytes"]],
                "without_checkpointing_2048_GB": round(e["peak_s2048_noshckpt_bytes"] / GB, 1), "without_checkpointing_4096_GB": round(e["peak_s4096_noshckpt_bytes"] / GB, 1)},
               "UNTESTED_HYPOTHESIS", "repo:scripts/foundation/build_evidence.py", "repo@" + D.BASE_SHA, D.T_REPO,
               derivation="activation term = 34*s*h per layer (Korthikanti et al. 2022 style, flash attention) + fp32 logits s*V*6 bytes; not measured")
        cl.add("serving_estimate", "ESTIMATE: KV cache per token (BF16) = 2 x layers x kv_heads x head_dim x 2 B; serving memory for batch 8 x 8k context = weights + KV + 1.5 GB overhead, divided by 0.9 utilisation.",
               {"kv_bytes_per_token": e["kv_bytes_per_token_bf16"], "kv_GB_per_8k_sequence": round(e["kv_bytes_8k_seq"] / GB, 2),
                "gpu_memory_needed_GB_batch8_ctx8k": round(e["serve_bf16_gpu_memory_needed_bytes_batch8_ctx8k"] / GB, 1), "class": gpu_class(e["serve_bf16_gpu_memory_needed_bytes_batch8_ctx8k"]),
                "four_bit_weights_GB_hypothesis": round(e["serve_4bit_weights_bytes_hypothesis"] / GB, 2)},
               "UNTESTED_HYPOTHESIS", "repo:scripts/foundation/build_evidence.py", "repo@" + D.BASE_SHA, D.T_REPO, derivation="arithmetic over documented config values")
        sm = e["serve_model"]
        cl.add("cost_hypothesis", f"HYPOTHESIS: H100 at the repo's list rate USD {H100_RATE}/h, memory-bandwidth-bound decode (3.35 TB/s assumed, 50% efficiency), batch 16, average context 2048 -> ~{sm['tokens_per_s']:.0f} output tokens/s -> USD {sm['usd_per_1M_output_tokens_at_full_utilisation']:.2f} per 1M output tokens at 100% paid-hour utilisation.",
               {"tokens_per_s": round(sm["tokens_per_s"]), "usd_per_1M_out_tokens_u100": round(sm["usd_per_1M_output_tokens_at_full_utilisation"], 2),
                "usd_per_1M_out_tokens_u30": round(sm["usd_per_1M_output_tokens_at_full_utilisation"] / 0.3, 2), "usd_per_1M_out_tokens_u10": round(sm["usd_per_1M_output_tokens_at_full_utilisation"] / 0.1, 2),
                "assumptions": {"gpu": "H100 80GB", "rate_usd_per_h": H100_RATE, "rate_source": D.REPO_EVIDENCE["decision_package"], "bandwidth_Bps": H100_BW, "efficiency": 0.5, "batch": 16, "avg_ctx": 2048}},
               "UNTESTED_HYPOTHESIS", "repo:scripts/foundation/build_evidence.py", "repo@" + D.BASE_SHA, D.T_REPO, derivation="decode step time = (weights + batch*ctx*kv)/(BW*eff); no engine overhead, no prefill, no scheduling loss")
        cl.add("cost_hypothesis", "HYPOTHESIS: QLoRA throughput = 15-25% of 989 TFLOP/s / (6 x params) tokens/s on one H100; cost per 1M training tokens at the list rate (this reproduces the decision package arithmetic).",
               {"tokens_per_s_range": [round(x) for x in e["qlora_tokens_per_s_range"]], "usd_per_1M_train_tokens_range": [round(x, 2) for x in e["usd_per_1M_train_tokens_range"]]},
               "UNTESTED_HYPOTHESIS", "repo:scripts/foundation/build_evidence.py", "repo@" + D.BASE_SHA, D.T_REPO, derivation="same formula as the package section 4")

    # hardware compatibility claim (shared)
    for slug, dd, cl in cands:
        e = est[slug]
        cl.add("hardware_compat", "BF16 needs NVIDIA compute capability >= 8.0 (Ampere or newer). vLLM refuses BF16 on a Tesla T4 (compute capability 7.5: 'Bfloat16 is only supported on GPUs with compute capability of at least 8.0'), so T4 serving would use FP16 (numerical behaviour of this model in FP16 NOT tested) or quantisation.",
               {"bf16_min_compute_capability": 8.0, "t4_compute_capability": 7.5}, "DOCUMENTED_FACT", "https://github.com/vllm-project/vllm/issues/1157", "UNVERSIONED_WEB_PAGE@" + D.T_WEB, D.T_WEB,
               limitations=["issue title/excerpt from a 2023 tracker issue; message text is stable in vLLM but not re-verified against 0.29.0 source"])
        t4 = e["bf16_weights_bytes"] / GB
        cl.add("hardware_compat", f"ESTIMATE: BF16/FP16 weights {t4:.1f} GB vs a T4's 16 GB (about 15 GB usable): {'fits for short contexts' if t4 < 12 else 'does NOT fit; needs 4-bit weights'}.",
               {"weights_GB": round(t4, 2), "t4_total_GB": 16}, "UNTESTED_HYPOTHESIS", "repo:scripts/foundation/build_evidence.py", "repo@" + D.BASE_SHA, D.T_REPO, derivation="2 x params vs 16 GB")

    # ------------------------------------------------------------------------------------------------------
    # licenses
    def lic_text_entry(slug, fn):
        t = texts[(slug, fn)]
        return {"file": t["path"], "sha256": t["sha256"], "git_blob_sha1": t["git_blob_sha1"], "bytes": t["bytes"], "source_url": t["source_url"], "retrieved_at": D.T_FILE, "revision": t["revision"]}

    licenses = {
        "qwen3-8b": {
            "license_status": "GRANTED", "license_id": "Apache-2.0", "text": lic_text_entry("qwen3-8b", "LICENSE"),
            "text_identical_to_canonical_apache_2_0_with_appendix_copyright_2024_alibaba_cloud": bool(q3_equals_canon),
            "claim_class": "DOCUMENTED_FACT", "source_url": hf_file_url("Qwen/Qwen3-8B", D.DEEP["qwen3-8b"]["revision"], "LICENSE"), "retrieved_at": D.T_FILE, "revision": D.DEEP["qwen3-8b"]["revision"],
            "status_meaning": "License TEXT retrieved, byte-verified and hashed; this is not a selection and not legal advice.",
            "notice_file_in_repo": False, "acceptable_use_policy": "none found in LICENSE or README at the pinned commit",
            "gated": False,
        },
        "mistral-nemo-instruct-2407": {
            "license_status": "REQUIRES_COUNSEL", "license_id": "Apache-2.0 (declared)", "text": None,
            "claim_class": "DOCUMENTED_FACT", "source_url": hf_file_url("mistralai/Mistral-Nemo-Instruct-2407", D.DEEP["mistral-nemo-instruct-2407"]["revision"], "README.md"), "retrieved_at": D.T_FILE, "revision": D.DEEP["mistral-nemo-instruct-2407"]["revision"],
            "status_meaning": "Apache-2.0 is declared in the card metadata (license: apache-2.0) and README prose ('Released under the Apache 2 License') but the repository at the pinned commit contains NO LICENSE file (tree.json); no license text hash exists, so GRANTED is not assigned.",
            "notice_file_in_repo": False, "acceptable_use_policy": "none found; README states 'does not have any moderation mechanisms'", "gated": False,
            "reference_text_not_a_repo_file": ref_texts[0] if ref_texts else None,
        },
        "phi-4": {
            "license_status": "GRANTED", "license_id": "MIT", "text": lic_text_entry("phi-4", "LICENSE"),
            "claim_class": "DOCUMENTED_FACT", "source_url": hf_file_url("microsoft/phi-4", D.DEEP["phi-4"]["revision"], "LICENSE"), "retrieved_at": D.T_FILE, "revision": D.DEEP["phi-4"]["revision"],
            "status_meaning": "License TEXT retrieved, byte-verified (CRLF line endings, 1,105 bytes) and hashed; this is not a selection and not legal advice.",
            "notice_file_in_repo": False, "acceptable_use_policy": "none in LICENSE; model card says nothing in it modifies the license", "gated": False,
        },
        "unsloth-qwen2.5-3b-instruct": {
            "license_status": "RESTRICTED_NONCOMMERCIAL", "license_id": "qwen-research (Qwen RESEARCH LICENSE AGREEMENT, release 2024-09-19)",
            "text": {"file": texts[("qwen2.5-3b-instruct-upstream", "LICENSE")]["path"], "sha256": texts[("qwen2.5-3b-instruct-upstream", "LICENSE")]["sha256"],
                     "git_blob_sha1": texts[("qwen2.5-3b-instruct-upstream", "LICENSE")]["git_blob_sha1"], "bytes": texts[("qwen2.5-3b-instruct-upstream", "LICENSE")]["bytes"],
                     "source_url": hf_file_url("Qwen/Qwen2.5-3B-Instruct", "aa8e72537993ba99e69dfaafa59ed015b17504d1", "LICENSE"), "retrieved_at": D.T_FILE, "revision": "aa8e72537993ba99e69dfaafa59ed015b17504d1"},
            "claim_class": "DOCUMENTED_FACT", "source_url": hf_file_url("Qwen/Qwen2.5-3B-Instruct", "aa8e72537993ba99e69dfaafa59ed015b17504d1", "LICENSE"), "retrieved_at": D.T_FILE, "revision": "aa8e72537993ba99e69dfaafa59ed015b17504d1",
            "status_meaning": "Text is from the UPSTREAM repo (the unsloth mirror ships no LICENSE file; its card points to the upstream file). Commercial use is not granted.",
            "notice_file_in_repo": False, "acceptable_use_policy": "none separate; export-control compliance clause 4.a", "gated": False,
        },
    }

    # ------------------------------------------------------------------------------------------------------
    # light tier
    light = []
    for repo, v in D.LIGHT.items():
        raw = repo_raw["models"][repo]
        assert raw["revision_sha"] == v["sha"], (repo, "sha differs from repo landscape record")
        cl = Claims(repo.split("/")[1].lower())
        url = f"{D.HF}/api/models/{repo}"
        cl.add("identity", f"{repo} model API sha at retrieval = {v['sha']} (identical to the repo's 2026-09-26 landscape record: no drift); lastModified {v['lm']}.",
               {"revision": v["sha"], "lastModified": v["lm"], "same_as_2026_09_26_record": True}, "DOCUMENTED_FACT", url, v["sha"], D.T_API)
        cl.add("parameters", f"Total parameters from safetensors metadata: {v['params']:,}.", {"total": v["params"]}, "DOCUMENTED_FACT", url, v["sha"], D.T_API)
        cl.add("license_tag", f"Card metadata license tag = {v['lic']}" + (f"; license_link = {v['lic_link']}" if v["lic_link"] else "") + ". License TEXT NOT retrieved/hashed in this pass.",
               {"license_tag": v["lic"], "license_link": v["lic_link"], "text_retrieved": False}, "DOCUMENTED_FACT", url, v["sha"], D.T_API)
        cs = raw["config_subset"]
        cl.add("architecture", "config.json subset as collected by the repo on 2026-09-26 at this revision (not re-read today): " + json.dumps(cs, sort_keys=True),
               cs, "DOCUMENTED_FACT", f"{D.HF}/{repo}/blob/main/config.json", v["sha"], D.T_LAND, evidence_path=D.REPO_EVIDENCE["landscape_raw"],
               limitations=["reused from the repository's own collection; sha unchanged today so the file content at this revision is unchanged"])
        cl.add("notes", v["note"], {}, "DOCUMENTED_FACT", url, v["sha"], D.T_API)
        light.append({"id": repo, "depth": "IDENTITY_ONLY", "repo": repo, "revision": v["sha"], "params": v["params"], "claims": cl.items,
                      "license": {"license_status": "REQUIRES_COUNSEL" if repo.startswith("google/") else "TAG_ONLY_UNVERIFIED", "license_id": v["lic"], "text": None,
                                  "claim_class": "DOCUMENTED_FACT", "source_url": url, "retrieved_at": D.T_API, "revision": v["sha"],
                                  "status_meaning": "Metadata tag only; no license text hashed. Gemma 4: license_link points to a hosted Apache-2.0 page, no repo LICENSE file (per the repo landscape)." if repo.startswith("google/") else "Metadata tag only; license text not retrieved in this pass.",
                                  "gated": False},
                      "repo_classification_2026_09_26": "GENESIS_EVAL_ADMITTED (docs/orneur/phase-21/GENESIS_FOUNDATION_LANDSCAPE_REFRESH_2026-09-26.md)"})

    # assemble deep candidates
    out_cands = []
    for slug, dd, cl in cands:
        out_cands.append({"id": slug, "depth": "DEEP", "display_name": dd["display"], "role": dd["role"], "repo": dd["repo"], "revision": dd["revision"],
                          "params": dd["params"], "config": dd["cfg"], "claims": cl.items, "license": licenses[slug], "estimates": est[slug]})

    return dict(out_cands=out_cands, light=light, texts=texts, trees=trees, est=est, licenses=licenses, ref_texts=ref_texts, q3_equals_canon=q3_equals_canon)


def main():
    built = build()
    doc = render_report(built, D, CLAIM_CLASSES)
    (OUTDIR / "foundation_evidence.json").write_text(json.dumps(doc["json"], indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
    (OUTDIR / "FOUNDATION_EVIDENCE_REASSESSMENT.md").write_text(doc["markdown"], encoding="utf-8")
    print("wrote", OUTDIR / "foundation_evidence.json", len(doc["json"]["candidates"]), "deep +", len(doc["json"]["identity_only_candidates"]), "identity-only")


if __name__ == "__main__":
    main()
