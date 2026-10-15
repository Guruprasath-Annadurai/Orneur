"""Static, hand-curated evidence inputs for the foundation-model evidence reassessment (Workstream D).

Every value here was read from a PUBLIC primary source on 2026-10-11 (Hugging Face repositories at exact commit
SHAs, publisher license text, the Qwen3 technical report, vendor model cards) or from this repository's own
persisted evidence.  Nothing in this module is computed; ``build_evidence.py`` derives estimates from it.

Retrieval path: Firecrawl scrape tool (HTTP GET only).  No model weights, no inference, no provider calls.
Timestamps are session-window approximations (minute precision), see ``RETRIEVAL_SESSION``.
"""
from __future__ import annotations

BASE_BRANCH = "claude/integration-candidate-1"
BASE_SHA = "cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d"
HF = "https://huggingface.co"

T_API = "2026-10-11T19:19:00Z"      # HF model/tree API reads
T_FILE = "2026-10-11T19:21:00Z"     # HF resolve/<sha>/<file> reads
T_PAPER = "2026-10-11T19:23:30Z"    # arXiv 2505.09388 (tool cache timestamp)
T_WEB = "2026-10-11T19:26:00Z"      # vLLM docs, ollama.com, GitHub/HF discussions search
T_REPO = "2026-10-11T19:15:00Z"     # repository files read
T_LAND = "2026-09-26T14:46:55Z"     # the repo's own landscape collection (09-26) reused for IDENTITY_ONLY tier

RETRIEVAL_SESSION = {
    "date": "2026-10-11",
    "window_utc": "19:15Z-19:32Z",
    "timestamp_precision": "MINUTE_APPROXIMATE_SESSION_WINDOW",
    "tool": "Firecrawl scrape/search (read-only HTTP GET); no WebFetch summarisation used for any recorded fact",
    "direct_curl": "Direct HTTPS to huggingface.co from the sandbox is policy-blocked (CONNECT 403); only www.apache.org was reachable by curl and was used for the canonical Apache-2.0 reference text.",
    "tool_limitations": [
        "The Firecrawl rawHtml format strips angle-bracket tokens (<think>, <tools>, <s>) from text/plain files; the markdown format preserves them for JSON/text files. Recorded texts were therefore taken from the markdown format.",
        "Tool output cannot be written to disk directly; each recorded text file was reconstructed by the agent and then mechanically verified against the Hugging Face git blob id (ETag / tree oid) of the file at the pinned commit. A text is stored only if its git blob sha1 equals the primary source's oid (byte-exact proof).",
        "Firecrawl 'query' extraction (used for arXiv PDF tables, vLLM docs rows, ollama.com pages) is an LLM-based extraction by the tool; those facts are labelled extraction=tool_query and are never used for license, identity or hash claims.",
        "Hugging Face reports lastModified at repository level; per-file commit dates were not retrieved.",
    ],
}

# ---------------------------------------------------------------------------------------------------------
# Deep-tier candidates (primary files re-read and hashed at the pinned commit)
# ---------------------------------------------------------------------------------------------------------
DEEP = {
    "qwen3-8b": dict(
        display="Qwen3-8B", role="documented finalist 1 / control (runtime-failed, capability unproven)",
        repo="Qwen/Qwen3-8B", revision="b968826d9c46dd6066d109eabc6255188de91218",
        head_sha_retrieved="b968826d9c46dd6066d109eabc6255188de91218", last_modified="2025-07-26T03:49:13Z",
        params=8190735360, model_type="qwen3", architectures=["Qwen3ForCausalLM"],
        cfg=dict(layers=36, hidden=4096, heads=32, kv_heads=8, head_dim=128, head_dim_source="config.json head_dim",
                 intermediate=12288, vocab=151936, tied=False, max_pos=40960, rope_theta=1000000, sliding_window=None,
                 dtype="bfloat16", rope_scaling=None),
        base_model="Qwen/Qwen3-8B-Base", pipeline_tag="text-generation", library="transformers",
    ),
    "mistral-nemo-instruct-2407": dict(
        display="Mistral-Nemo-Instruct-2407", role="documented finalist 2 / control (runtime-failed, capability unproven)",
        repo="mistralai/Mistral-Nemo-Instruct-2407", revision="04d8a90549d23fc6bd7f642064003592df51e9b3",
        head_sha_retrieved="04d8a90549d23fc6bd7f642064003592df51e9b3", last_modified="2025-07-28T17:16:02Z",
        params=12247782400, model_type="mistral", architectures=["MistralForCausalLM"],
        cfg=dict(layers=40, hidden=5120, heads=32, kv_heads=8, head_dim=128, head_dim_source="config.json head_dim",
                 intermediate=14336, vocab=131072, tied=False, max_pos=131072, rope_theta=1000000.0, sliding_window=None,
                 dtype="bfloat16", rope_scaling=None),
        base_model="mistralai/Mistral-Nemo-Base-2407", pipeline_tag=None, library="vllm",
    ),
    "phi-4": dict(
        display="Phi-4", role="documented finalist 3 / control (runtime-failed, capability unproven)",
        repo="microsoft/phi-4", revision="2db69c1c3e91a05d2c64a3185acfbaf36f744e25",
        head_sha_retrieved="2db69c1c3e91a05d2c64a3185acfbaf36f744e25", last_modified="2026-07-14T14:22:25Z",
        params=14659507200, model_type="phi3", architectures=["Phi3ForCausalLM"],
        cfg=dict(layers=40, hidden=5120, heads=40, kv_heads=10, head_dim=128,
                 head_dim_source="DERIVED hidden_size/num_attention_heads (config.json has no head_dim key)",
                 intermediate=17920, vocab=100352, tied=False, max_pos=16384, rope_theta=250000, sliding_window=None,
                 dtype="bfloat16", rope_scaling=None),
        base_model=None, pipeline_tag="text-generation", library="transformers",
    ),
    "unsloth-qwen2.5-3b-instruct": dict(
        display="Qwen2.5-3B-Instruct (unsloth mirror, current canonical Genesis base)",
        role="current canonical Genesis base (MODEL_SPECS['genesis']); license gate FAIL for commercial use",
        repo="unsloth/Qwen2.5-3B-Instruct", revision="7548fff1f997f57b2e9e8ab1ec7be96949b00ed0",
        head_sha_retrieved="7548fff1f997f57b2e9e8ab1ec7be96949b00ed0", last_modified="2025-03-06T00:08:34Z",
        params=3085938688, model_type="qwen2", architectures=["Qwen2ForCausalLM"],
        cfg=dict(layers=36, hidden=2048, heads=16, kv_heads=2, head_dim=128,
                 head_dim_source="DERIVED hidden_size/num_attention_heads (config.json has no head_dim key)",
                 intermediate=11008, vocab=151936, tied=True, max_pos=32768, rope_theta=1000000.0, sliding_window=32768,
                 dtype="bfloat16", rope_scaling=None),
        base_model="Qwen/Qwen2.5-3B-Instruct", pipeline_tag=None, library="transformers",
        upstream=dict(repo="Qwen/Qwen2.5-3B-Instruct", revision="aa8e72537993ba99e69dfaafa59ed015b17504d1",
                      head_sha_retrieved="aa8e72537993ba99e69dfaafa59ed015b17504d1", last_modified="2024-09-25T12:33:00Z",
                      params=3085938688),
    ),
}

# Files whose bytes were reconstructed and verified against the HF git blob oid (see retrieved/<slug>/tree.json)
RETRIEVED_TEXTS = {
    "qwen3-8b": ["LICENSE", "config.json", "generation_config.json", "tokenizer_config.json", "chat_template.jinja.txt"],
    "mistral-nemo-instruct-2407": ["config.json", "generation_config.json", "chat_template.jinja.txt"],
    "phi-4": ["LICENSE", "config.json", "generation_config.json", "tokenizer_config.json", "chat_template.jinja.txt"],
    "unsloth-qwen2.5-3b-instruct": ["config.json", "generation_config.json", "tokenizer_config.json", "chat_template.jinja.txt"],
    "qwen2.5-3b-instruct-upstream": ["LICENSE"],
}

# repo evidence the verifier/reader can cross-check (all paths relative to repository root)
EV = "docs/orneur/phase-21/evidence/"
P21 = "docs/orneur/phase-21/"
REPO_EVIDENCE = {
    "qwen3_precache": EV + "GENESIS_CONTROL_QWEN3_8B_MODAL_PRECACHE_MANIFEST_2026-09-24.json",
    "nemo_precache": EV + "GENESIS_CONTROL_MISTRAL_NEMO_MODAL_PRECACHE_MANIFEST_2026-09-24.json",
    "phi4_precache": EV + "GENESIS_CONTROL_PHI4_MODAL_PRECACHE_MANIFEST_2026-09-24.json",
    "qwen3_runtime": EV + "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json",
    "nemo_runtime": EV + "GENESIS_CONTROL_MISTRAL_NEMO_RUNTIME_QUALIFICATION_2026-09-24.json",
    "phi4_runtime": EV + "GENESIS_CONTROL_PHI4_RUNTIME_QUALIFICATION_2026-09-24.json",
    "nemo_template_rca": EV + "GENESIS_MISTRAL_NEMO_CHAT_TEMPLATE_ROOT_CAUSE_ANALYSIS_V2_2026-09-26.json",
    "qwen5_log": EV + "GENESIS_CONTROL_QWEN3_8B_MODAL_H100_ATTEMPT5_RAW_LOG_2026-09-24.txt",
    "landscape_raw": EV + "GENESIS_FOUNDATION_LANDSCAPE_RAW_HF_METADATA_2026-09-26.json",
    "decision_package": P21 + "GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26.md",
    "decision_package_json": P21 + "GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26.json",
    "control_matrix": P21 + "GENESIS_CONTROL_RUNTIME_QUALIFICATION_MATRIX_2026-09-24.md",
    "locked_protocol": "orca/eval/locked_smoke_protocol.py",
    "control_runner": "scripts/phase21b_4_20_control_runtime_qualification.py",
    "stage0_matrix": P21 + "GENESIS_STAGE0_LICENSE_MATRIX.md",
    "base_qualification": P21 + "GENESIS_BASE_MODEL_QUALIFICATION.md",
    "shortlist": P21 + "GENESIS_FOUNDATION_SHORTLIST_2026.md",
    "blueprint": "docs/orneur/status/PRETRAINING_FOUNDATION_QUALIFICATION_BLUEPRINT.md",
    "glm_incident": P21 + "GLM_5_3_FLASH_COMPUTE_COST_INCIDENT_2026-09-23.md",
    "model_spec": "orca/registry/model_spec.py",
}

# ---------------------------------------------------------------------------------------------------------
# IDENTITY_ONLY tier: models the repo's 2026-09-26 landscape classes GENESIS_EVAL_ADMITTED (dense, 3-14B).
# Live fields (sha, lastModified, safetensors total, license tag) were re-read on 2026-10-11 via the HF model API;
# architecture / context fields are the repo's own 2026-09-26 collection of the same revision (cited as such).
# ---------------------------------------------------------------------------------------------------------
LIGHT = {
    "HuggingFaceTB/SmolLM3-3B": dict(sha="a07cc9a04f16550a088caea529712d1d335b0ac1", lm="2025-09-10T12:28:11Z", params=3075098624, lic="apache-2.0", lic_link=None, note="text-generation; language tags en fr es it pt zh ar ru"),
    "Qwen/Qwen3.5-4B": dict(sha="851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a", lm="2026-03-02T00:52:52Z", params=4659865088, lic="apache-2.0", lic_link="https://huggingface.co/Qwen/Qwen3.5-4B/blob/main/LICENSE", note="image-text-to-text pipeline (multimodal checkpoint); hybrid full/linear attention per repo landscape"),
    "Qwen/Qwen3.5-9B": dict(sha="c202236235762e1c871ad0ccb60c8ee5ba337b9a", lm="2026-03-02T00:51:43Z", params=9653104368, lic="apache-2.0", lic_link="https://huggingface.co/Qwen/Qwen3.5-9B/blob/main/LICENSE", note="image-text-to-text pipeline (multimodal checkpoint); hybrid attention per repo landscape"),
    "allenai/Olmo-3-7B-Instruct": dict(sha="6e5971d9eba42665f5bd5a0fcf047f299ce1dccc", lm="2026-06-25T21:41:37Z", params=7298011136, lic="apache-2.0", lic_link=None, note="text-generation; English only per card language tag"),
    "google/gemma-4-E4B-it": dict(sha="ee0ef6023621cff504d758262d4e04895a5af4a2", lm="2026-07-20T16:42:03Z", params=7996156490, lic="apache-2.0", lic_link="https://ai.google.dev/gemma/docs/gemma_4_license", note="any-to-any pipeline; license_link resolves to a hosted Apache-2.0 page (ai.google.dev/gemma/apache_2), not a repo LICENSE file"),
    "google/gemma-4-12B-it": dict(sha="707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7", lm="2026-07-20T16:42:08Z", params=11959730224, lic="apache-2.0", lic_link="https://ai.google.dev/gemma/docs/gemma_4_license", note="any-to-any pipeline; gemma4_unified architecture; license_link as above"),
    "ibm-granite/granite-4.2-3b": dict(sha="e459acceac81e5fe67c07d9cfc72329a332e7eb1", lm="2026-09-02T21:57:50Z", params=3659737600, lic="apache-2.0", lic_link=None, note="text-generation; tags reasoning, thinking, tool-calling; 12 languages in card tags"),
    "ibm-granite/granite-4.2-8b": dict(sha="f8de16cdcdbc6c779ca517604e050d82cc119e44", lm="2026-09-04T21:02:25Z", params=8791592960, lic="apache-2.0", lic_link=None, note="text-generation; tags reasoning, thinking, tool-calling; 12 languages in card tags"),
    "microsoft/Phi-4-mini-instruct": dict(sha="cfbefacb99257ffa30c83adab238a50856ac3083", lm="2025-12-10T20:24:40Z", params=3836021760, lic="mit", lic_link="https://huggingface.co/microsoft/Phi-4-mini-instruct/resolve/main/LICENSE", note="carries the custom_code tag (trust_remote_code question unresolved in this pass)"),
    "mistralai/Ministral-3-14B-Reasoning-2512": dict(sha="51f9210f3cd20f3452a80d5819d15dc61cc50630", lm="2026-07-15T12:21:23Z", params=13945031680, lic="apache-2.0", lic_link=None, note="mistral3 architecture, mistral-common tag, inference:false in card metadata"),
}

SPOTCHECK_EXISTENCE = [
    {"repo": "Qwen/Qwen3.8-27B", "sha": "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0", "lastModified": "2026-08-14T15:00:01Z", "params": 27781427952, "license_tag": "apache-2.0", "result": "FOUND"},
    {"repo": "mistralai/Mistral-Small-4-119B-2603", "sha": "a11f36bebf709121056b1dbcc943d1c6afbe494d", "lastModified": "2026-07-15T12:23:29Z", "params": 119401317952, "license_tag": "apache-2.0", "result": "FOUND"},
    {"repo": "zai-org/GLM-5.3-Flash", "sha": "eb9eb208eb0d988989d07a6a12d0fdeb5f52574a", "lastModified": "2026-09-07T12:13:47Z", "params": 321323031390, "license_tag": "mit", "result": "FOUND"},
]

# Vendor-reported benchmark rows (never independently reproduced here).  Source: arXiv 2505.09388 tables (tool_query extraction).
QWEN3_8B_THINKING = {"MMLU-Redux": 87.5, "GPQA-Diamond": 62.0, "C-Eval": 83.4, "LiveBench 2024-11-25": 67.1, "IFEval strict prompt": 85.0,
                     "Arena-Hard": 85.8, "MATH-500": 97.4, "AIME'24": 76.0, "AIME'25": 67.3, "BFCL v3": 68.1, "LiveCodeBench v5": 57.5,
                     "Multi-IF": 71.2, "INCLUDE": 67.8, "MMMLU 14 languages": 74.4}
QWEN3_8B_NONTHINKING = {"MMLU-Redux": 79.5, "GPQA-Diamond": 39.3, "C-Eval": 77.9, "LiveBench 2024-11-25": 53.5, "IFEval strict prompt": 83.0,
                        "Arena-Hard": 79.6, "MATH-500": 87.4, "AIME'24": 29.1, "AIME'25": 20.9, "BFCL v3": 60.2, "LiveCodeBench v5": 22.8,
                        "Multi-IF": 69.2, "INCLUDE": 62.5, "MMMLU 14 languages": 66.9}
QWEN25_3B_NONTHINKING_IN_QWEN3_REPORT = {"MMLU-Redux": 64.4, "GPQA-Diamond": 30.3, "C-Eval": 68.2, "LiveBench 2024-11-25": 23.8, "IFEval strict prompt": 58.2,
                                         "Arena-Hard": 23.7, "MATH-500": 67.2, "AIME'24": 6.7, "AIME'25": 4.2, "BFCL v3": 50.4, "LiveCodeBench v5": 9.2,
                                         "Multi-IF": 32.3, "INCLUDE": 43.8, "MMMLU 14 languages": 51.8}
PHI4_README_SIMPLE_EVALS = {"MMLU": 84.8, "GPQA": 56.1, "MGSM": 80.6, "MATH": 80.4, "HumanEval": 82.6, "SimpleQA": 3.0, "DROP": 75.5}
NEMO_README_BENCH = {"HellaSwag (0-shot)": 83.5, "Winogrande (0-shot)": 76.8, "OpenBookQA (0-shot)": 60.6, "CommonSenseQA (0-shot)": 70.4,
                     "TruthfulQA (0-shot)": 50.3, "MMLU (5-shot)": 68.0, "TriviaQA (5-shot)": 73.8, "NaturalQuestions (5-shot)": 31.2}
NEMO_README_MMLU_LANG = {"French": 62.3, "German": 62.7, "Spanish": 64.6, "Italian": 61.3, "Portuguese": 63.3, "Russian": 59.2, "Chinese": 59.0, "Japanese": 59.0}

# Package (2026-09-26) memory/cost numbers, for the delta table (GB, 1e9 bytes)
PACKAGE_NUMBERS = {
    "qwen3-8b": dict(static=6.2, peak2k=12.5, peak4k=16.7, bf16=16.4, kv8k=1.21, lora16_m=43.6),
    "mistral-nemo-instruct-2407": dict(static=8.5, peak2k=14.9, peak4k=19.0, bf16=24.5, kv8k=1.34, lora16_m=57.0),
    "phi-4": dict(static=9.3, peak2k=15.3, peak4k=18.8, bf16=29.3, kv8k=1.68, lora16_m=65.5),
}
