#!/usr/bin/env python3
"""Deterministically build the foundation landscape refresh JSON + Markdown from committed raw evidence.

CPU-only. Reads docs/orneur/phase-21/evidence/GENESIS_FOUNDATION_LANDSCAPE_RAW_HF_METADATA_2026-09-26.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orca.eval import foundation_landscape as fl  # noqa: E402

JSON_OUT = ROOT / "docs/orneur/phase-21/GENESIS_FOUNDATION_LANDSCAPE_REFRESH_2026-09-26.json"
MD_OUT = ROOT / "docs/orneur/phase-21/GENESIS_FOUNDATION_LANDSCAPE_REFRESH_2026-09-26.md"

GATE_TEXT = {
    "A_license": "License is permissive (Apache-2.0 or MIT) and ungated; custom, revenue-threshold, MaaS-clause or manually gated terms fail until legally cleared.",
    "B_revision_pinned": "An exact 40-hex revision is available to pin.",
    "C_architecture_documented": "config.json is retrievable and the architecture has a native implementation in transformers main or the vLLM supported-models docs.",
    "D_tokenizer_template": "A tokenizer and a chat template are shipped and were probed.",
    "E_peft_qlora_feasible": "PEFT/QLoRA is feasible ON PAPER: dense, natively implemented, BF16-stored, <=40B parameters. MoE and natively-quantised checkpoints are UNVERIFIED; >40B fails. Basis is INFERRED_NOT_EXECUTED, so a PASS here means 'expected', never 'proven trainable' (see trainability_proven).",
    "F_training_cost_vs_budget": "A 5M-token QLoRA pilot costs <=10% of the low end of the planning budget and the estimated QLoRA memory fits 80GB.",
    "G_inference_path": "A vLLM-listed or transformers-native inference path exists.",
    "H_artifacts_verifiable": "Immutable revision plus safetensors metadata at that revision.",
    "I_no_proprietary_only_stack": "An open serving/training stack exists.",
    "J_ecosystem_maturity": "Architecture is native in transformers main AND listed in the vLLM docs.",
}


def short(m: dict) -> str:
    g = m["gates"]
    return "".join({"PASS": "P", "FAIL": "F", "UNVERIFIED": "?"}[g[k]["status"]] for k in fl.GATES)


def md(doc: dict) -> str:
    M = doc["models"]
    ev = doc["evidence"]
    L: list[str] = []
    a = L.append
    a("# Genesis Foundation Landscape Refresh — 2026-09-26")
    a("")
    a("**Verdict:** `FOUNDATION_LANDSCAPE_REFRESHED_NO_FOUNDATION_SELECTED`. No foundation is selected, no training or GPU is authorized, Phase 21C is not authorized.")
    a("")
    a("The Qwen3-8B / Mistral-Nemo / Phi-4 pool was a **control pool** for runtime qualification. It does not automatically remain the Genesis candidate pool. This refresh re-derives the candidate pool from live primary sources and admits models only through gates A–J.")
    a("")
    a("## 1. Evidence and method")
    a("")
    a(f"- Collected read-only at `{ev['collected_at_utc']}` by `scripts/orneur_foundation_landscape_collect.py` (public Hugging Face API, `config.json`, `LICENSE` texts, chat templates, transformers-main model directory listing, vLLM supported-models docs, PyPI). Raw record: `{ev['raw_metadata_file']}`.")
    a("- **No weights downloaded, no GPU, no provider inference, no training.** Nothing below was executed on a model: every 'feasible' statement is documentation-level or a formula estimate and is labelled by *basis*.")
    a(f"- Latest package versions observed on PyPI: `{json.dumps(ev['ecosystem_versions_latest_pypi'], sort_keys=True)}`.")
    a("- Parameter counts come from the safetensors metadata at the pinned revision. Active parameters for MoE models are **name-derived or vendor claims**, marked as such, and never used as verified fact.")
    a("- Vendor benchmark claims were deliberately **not** collected: this refresh admits candidates for ORNEUR's own frozen eval; it does not rank capability.")
    a("- The previous landscape (`GENESIS_FRONTIER_MODEL_LANDSCAPE_2026_09.md`) is unchanged. Where it and this file disagree, this file reflects the newer live collection and the previous file is historical.")
    a("")
    a("## 2. Admission gates (a model enters the Genesis Capability Eval only if A–J all PASS)")
    a("")
    for g in fl.GATES:
        a(f"- **{g}** — {GATE_TEXT[g]}")
    a("")
    a("Status semantics: `PASS` documented evidence satisfies the gate; `FAIL` evidence violates it; `UNVERIFIED` no adequate evidence and is treated as *not passed*. Basis: `PRIMARY_SOURCE`, `DERIVED_FROM_PRIMARY_SOURCE`, `DERIVED_ESTIMATE`, `INFERRED_NOT_EXECUTED`, `NOT_VERIFIED`. A gate marked `INFERRED_NOT_EXECUTED` is exactly what the future capability/trainability probe must confirm.")
    a("")
    a("## 3. Classification")
    a("")
    for c in fl.CLASSES:
        a(f"- **{c}** ({len(doc['class_membership'][c])})")
    a("")
    a("Classes are assigned by rules in `orca/eval/foundation_landscape.py`, not by recency, size or popularity. Giant MoE models are **not** forced into the current budget: they are teacher/reference or architecture-reference material.")
    a("")
    a("**Terminology (corrected in the audit-corrections phase).** `GENESIS_EVAL_ADMITTED` (formerly `GENESIS_TRAINABLE_NOW`) means *admitted for evaluation* by documented gates. It does **not** mean proven trainable: every record carries `trainability_proven=false` and `trainability_evidence_ref=null` until Stage-0/Stage-3 evidence exists. `BASELINE_ONLY_CONTROL` models are never admitted (`admitted_to_capability_eval=false`) even when they would pass the gates; they are regression baselines only.")
    a("")
    a("## 4. All investigated models (gate string = A B C D E F G H I J; P=PASS F=FAIL ?=UNVERIFIED)")
    a("")
    a("| Model | Class | Admitted | Gates | Total params (B) | Active (B, attributed claim) | Context: config / vendor-supported | License | Revision |")
    a("|---|---|---|---|---|---|---|---|---|")
    for mid in sorted(M):
        r = M[mid]
        act = (f"{r['active_parameters_b']} ({r['active_parameters_source']})" if r["active_parameters_b"]
               else ("dense" if r["active_parameters_source"] == "DENSE" else "MoE (active not recorded)"))
        ctx = f"{r['config_max_position_embeddings']} / {r['vendor_supported_context_tokens']} ({r['context_config_vs_vendor']})"
        a(f"| `{mid}` | {r['class']} | {'yes' if r['admitted_to_capability_eval'] else 'no'} | `{short(r)}` | {r['total_parameters_b']} | {act} | {ctx} | {r['license']['card']} | `{(r['revision_sha'] or '')[:12]}` |")
    a("")
    a("## 5. Per-candidate admission / exclusion reasons and records")
    a("")
    for c in fl.CLASSES:
        a(f"### {c}")
        a("")
        for mid in doc["class_membership"][c]:
            r = M[mid]
            a(f"#### `{mid}`")
            a("")
            a(f"- Exact revision: `{r['revision_sha']}`; license: `{r['license']['card']}` (name `{r['license']['name']}`, gated `{r['license']['gated']}`)")
            a(f"- Architecture: `{r['architecture']}` / `{r['model_type']}`; total parameters {r['total_parameters_b']}B; active {r['active_parameters_b'] or ('dense' if r['active_parameters_source'] == 'DENSE' else 'not recorded')} ({r['active_parameters_source']})")
            a(f"- Context: config `max_position_embeddings`={r['config_max_position_embeddings']}; vendor-supported={r['vendor_supported_context_tokens']} ({r['vendor_supported_context_precision']}; extended {r['vendor_extended_context_tokens']}); source `{r['context_source']}`; config-vs-vendor: **{r['context_config_vs_vendor']}**" + (f"; vendor text: \"{r['vendor_supported_context_text']}\"" if r['vendor_supported_context_text'] else ""))
            a(f"- Active parameters: {r['active_parameters_b']} — source `{r['active_parameters_source']}`, verified={r['active_parameters_verified']}" + (f"; note: {r['active_parameters_note']}" if r['active_parameters_note'] else ""))
            a(f"- Admission meaning: {r['admission_meaning']} (trainability_proven={r['trainability_proven']})")
            a(f"- Multimodality: {r['multimodality']}; tool-calling template: {r['tool_calling_template']}; reasoning/thinking template: {r['reasoning_template']}")
            a(f"- Structured output: {r['structured_output']}")
            a(f"- Quantization: vendor variants observed {r['quantization_support']['vendor_quantized_observed'] or 'none recorded'}; runtime 4-bit {r['quantization_support']['runtime_4bit']}")
            if "estimates" in r:
                e = r["estimates"]
                a(f"- ESTIMATES (not measurements): QLoRA VRAM {e['qlora_vram_gb_range'][0]}–{e['qlora_vram_gb_range'][1]} GB; USD {e['usd_per_million_training_tokens_range'][0]}–{e['usd_per_million_training_tokens_range'][1]} per 1M training tokens; 5M-token pilot USD {e['pilot_5m_tokens_usd_range'][0]}–{e['pilot_5m_tokens_usd_range'][1]}")
            a(f"- **Class reason:** {r['class_reason']}")
            bad = [f"{k}={r['gates'][k]['status']} ({r['gates'][k]['note']})" for k in fl.GATES if r["gates"][k]["status"] != "PASS"]
            a(f"- Gates not passed: {'; '.join(bad) if bad else 'none'}")
            if r["known_caveats"]:
                a(f"- Known caveats: {' | '.join(r['known_caveats'])}")
            a(f"- Primary sources: {', '.join(r['primary_sources'])}")
            a("")
    a("## 6. Shortlists (no ranking, no selection)")
    a("")
    a("**Eval-admitted pool (admitted to the Genesis Capability Eval by gates alone; NOT proven trainable):** " + ", ".join(f"`{m}`" for m in doc["class_membership"]["GENESIS_EVAL_ADMITTED"]) + ".")
    a("")
    a("**Teacher / reference (studied, not a base):** " + ", ".join(f"`{m}`" for m in doc["class_membership"]["TEACHER_REFERENCE"]) + ".")
    a("")
    a("**Future reason candidates (blocked by an UNVERIFIED gate, mostly QLoRA-over-MoE or native-FP8 checkpoints):** " + ", ".join(f"`{m}`" for m in doc["class_membership"]["FUTURE_REASON_CANDIDATE"]) + ".")
    a("")
    a("**Future frontier architecture references:** " + ", ".join(f"`{m}`" for m in doc["class_membership"]["FUTURE_FRONTIER_ARCHITECTURE_REFERENCE"]) + ".")
    a("")
    a("**Baseline-only controls (not carried forward automatically):** " + ", ".join(f"`{m}`" for m in doc["class_membership"]["BASELINE_ONLY_CONTROL"]) + ". They may serve as regression baselines; their historical `RUNTIME_QUALIFIED=false` results are unchanged.")
    a("")
    a("The pool is deliberately larger than can be sensibly trained. It is a *screening* pool: the capability eval design uses a staged funnel so that only a few models receive the expensive stages.")
    a("")
    a("## 6a. Context and active-parameter semantics (audit correction)")
    a("")
    a("Two different things were previously conflated. `config_max_position_embeddings` is what the shipped `config.json` says and is never overwritten. `vendor_supported_context_tokens` is what the vendor's model card states is supported; it is an attributed claim (`context_source`), quoted verbatim from the captured card text, not a measurement. K/M shorthand is converted with the K=1024 convention and flagged `SHORTHAND_K1024_ASSUMED`. Likewise `active_parameters_b` is an attributed claim (`VENDOR_MODEL_CARD_CLAIM`) or a name-derived value (`NAME_DERIVED`), never verified (`active_parameters_verified=false`).")
    a("")
    M = doc["models"]
    differs = sorted(m for m, r in M.items() if r["context_config_vs_vendor"] == "DIFFERS")
    a("Config-vs-vendor context **differs** for: " + ", ".join(f"`{m}` (config {M[m]['config_max_position_embeddings']}, vendor {M[m]['vendor_supported_context_tokens']})" for m in differs) + ".")
    a("")
    for k, label in (("VENDOR_CLAIM_NOT_CAPTURED", "no vendor context claim was captured from the model card"), ("CONFIG_NOT_AVAILABLE", "no config.json retrievable (gated or native-format repo)")):
        ms = sorted(m for m, r in M.items() if r["context_config_vs_vendor"] == k)
        a(f"`{k}` ({label}): " + ", ".join(f"`{m}`" for m in ms) + ".")
        a("")
    a("## 7. Owner budget reality (planning only — does not authorize spending)")
    a("")
    b = doc["budget_planning"]
    a(f"- Approximate first-stage budget: INR 10,000 ≈ USD {b['usd_range'][0]:.0f}–{b['usd_range'][1]:.0f} (assumed INR 85–90/USD, not a live quote). H100 list rate used: USD {b['h100_usd_per_hour_persisted_list_rate']}/h (the program's persisted rate). Compute model: 6·N FLOPs/token at {int(b['utilization_range'][0]*100)}–{int(b['utilization_range'][1]*100)}% of the public 989 TFLOPs bf16 peak; N is total parameters for dense models and *name-derived* active parameters for MoE. Real QLoRA overhead (dequantisation, gradient checkpointing, padding) makes actual cost higher; treat every figure as a lower-bound planning estimate.")
    a("- **This budget cannot pretrain or continue-pretrain a frontier model.** It can fund parameter-efficient adaptation (QLoRA/LoRA), small controlled SFT, small preference optimisation, and license-permitting distillation experiments.")
    a("- Three cost buckets are kept separate: **(1) initial adaptation cost** (the per-model estimates above, plus evals and failed runs; roughly 40–60% of a budget becomes training compute); **(2) production inference cost** (recurring; an always-on H100 at the persisted rate is ≈ USD " + f"{b['always_on_h100_usd_per_month']:,.0f}" + "/month, so scale-to-zero or small-GPU 4-bit serving is required regardless of base — small-GPU serving costs are NOT measured here); **(3) future full-pretraining / continued-pretraining research** (out of scope and out of budget; teacher/reference and architecture-reference models inform it only).")
    a("- Funding still requires an explicit owner decision: current promotional-credit headroom is below any training budget (per the Phase 21B.4.20 closeout).")
    a("")
    a("## 8. Selection rule (pre-registered here; applies after the capability eval)")
    a("")
    a(doc["selection_rule"])
    a("")
    a("## 9. Remaining uncertainties")
    a("")
    for u in [
        "Every PEFT/QLoRA statement for dense models is `INFERRED_NOT_EXECUTED`; the hybrid linear-attention Qwen3.5/3.6/3.8 family and the Gemma 4 family may need specialised kernels or newer library versions than a given host provides.",
        "Serving statements rely on the vLLM docs on `main` at collection time (vLLM PyPI latest observed above); the ORNEUR harness pins vLLM 0.29.0, so support must be re-qualified per model at the pinned version.",
        "Gemma 4 repositories carry no LICENSE file; the Apache-2.0 statement is model-card metadata only and should be confirmed against the vendor's terms page before any commitment.",
        "License review here is a mechanical screen of card metadata and selected LICENSE clauses, not legal advice. Custom licenses (Qwen community/max, GLM-5.3, NVIDIA, Llama, LFM) were screened only for headline restrictions.",
        "MoE active-parameter counts are name-derived or vendor claims and only affect the compute estimate.",
        "Frontier-scale teachers (DeepSeek V4.x, GLM-5.3-Flash, gpt-oss-120b, Mistral Large/Small 4) require provider or multi-GPU serving; teacher-output licensing for distillation was not legally reviewed.",
        "Release ordering shows a young ecosystem for the newest families; 'newest' was never used as a selection input.",
        "Task-specialised derivatives (Fara1.5, MagenticBrain, DeepSeek-R1-0528-Qwen3-8B) are recorded but not counted as foundations.",
    ]:
        a(f"- {u}")
    a("")
    a("## 10. Authorizations")
    a("")
    a("`training_authorized=false`, `gpu_authorized=false`, `provider_inference_authorized=false`, `phase_21c_authorized=false`, `foundation_selected=false`.")
    a("")
    return "\n".join(L)


def main() -> None:
    raw = fl.load_raw(ROOT)
    doc = fl.build_document(raw)
    JSON_OUT.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    MD_OUT.write_text(md(doc))
    print("wrote", JSON_OUT.name, MD_OUT.name, len(doc["models"]), "models")


if __name__ == "__main__":
    main()
