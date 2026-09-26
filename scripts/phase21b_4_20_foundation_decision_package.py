"""
Phase 21B.4.20 FINAL CLOSEOUT -- Genesis foundation decision package generator (CPU / research / documentation only).

Reads the IMMUTABLE persisted control evidence (never writes it), combines it with public primary-source facts about the three pinned foundation options (Hugging Face config.json,
model.safetensors.index.json and README at the EXACT pinned revisions -- fetched once and recorded below with their URLs), computes clearly-labelled ESTIMATES with explicit formulas and
ranges, and writes two files:
    docs/orneur/phase-21/GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26.md   (human)
    docs/orneur/phase-21/GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26.json (machine readable companion)
No GPU, no Modal, no provider call, no generation. The locked A/B/C smokes were runtime/control-contract tests; nothing here ranks model quality by smoke counts.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = REPO_ROOT / "docs/orneur/phase-21/evidence"
OUT_MD = REPO_ROOT / "docs/orneur/phase-21/GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26.md"
OUT_JSON = REPO_ROOT / "docs/orneur/phase-21/GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26.json"
BASE_SHA = "dd4e0c13e48e6cb3c68fe46755e95d25d094637c"

# ── public primary-source facts (fetched 2026-09-26 from the EXACT pinned revisions; config.json / model.safetensors.index.json / README.md) ──────────────────────────────────────────
HF = "https://huggingface.co/{repo}/resolve/{rev}/{file}"
FACTS = {
    "Qwen3-8B": {"repo": "Qwen/Qwen3-8B", "revision": "b968826d9c46dd6066d109eabc6255188de91218", "license": "apache-2.0", "architecture": "Qwen3ForCausalLM (dense decoder-only, GQA)",
                 "layers": 36, "hidden": 4096, "intermediate": 12288, "heads": 32, "kv_heads": 8, "head_dim": 128, "vocab": 151936, "tie_embeddings": False, "safetensors_total_bytes": 16381470720,
                 "native_context": 32768, "max_position_embeddings_config": 40960, "extended_context": "131,072 tokens with YaRN (model card)",
                 "vendor_notes": ["single model with hybrid thinking / non-thinking modes (enable_thinking switch in the chat template)",
                                  "model card recommends Temperature 0.7 / TopP 0.8 / TopK 20 for non-thinking mode and says NOT to use greedy decoding in thinking mode (the locked smoke protocol uses temperature 0)",
                                  "100+ languages"]},
    "Mistral-Nemo-Instruct-2407": {"repo": "mistralai/Mistral-Nemo-Instruct-2407", "revision": "04d8a90549d23fc6bd7f642064003592df51e9b3", "license": "apache-2.0", "architecture": "MistralForCausalLM (dense decoder-only, GQA)",
                 "layers": 40, "hidden": 5120, "intermediate": 14336, "heads": 32, "kv_heads": 8, "head_dim": 128, "vocab": 131072, "tie_embeddings": False, "safetensors_total_bytes": 24495564800,
                 "native_context": 131072, "max_position_embeddings_config": 131072, "extended_context": "trained with a 128k context window (model card)",
                 "vendor_notes": ["Tekken tokenizer (tekken.json); the model card recommends mistral-inference / mistral_common; under vLLM 0.29.0 + transformers 5.16.1 the HF tokenizer path resolved no chat template (attempts 1-2) and the native Mistral tokenizer mode was required (attempt 3)",
                                  "model card recommends a low sampling temperature (0.3) unlike earlier Mistral models", "native function-calling format documented", "no built-in moderation mechanisms (model card)"]},
    "Phi-4": {"repo": "microsoft/phi-4", "revision": "2db69c1c3e91a05d2c64a3185acfbaf36f744e25", "license": "mit", "architecture": "Phi3ForCausalLM (dense decoder-only, GQA, fused qkv / gate_up projections)",
              "layers": 40, "hidden": 5120, "intermediate": 17920, "heads": 40, "kv_heads": 10, "head_dim": 128, "vocab": 100352, "tie_embeddings": False, "safetensors_total_bytes": 29319014400,
              "native_context": 16384, "max_position_embeddings_config": 16384, "extended_context": "none documented (16K tokens)",
              "vendor_notes": ["9.8T training tokens including newly created synthetic 'textbook-like' data for math, coding and reasoning (model card)", "trained primarily on English text; non-English performance is worse (model card)",
                               "majority of code training data is Python with common packages (model card)", "best suited to prompts in the chat format (model card)"]},
}
SOURCES = [{"model": k, "files": [HF.format(repo=v["repo"], rev=v["revision"], file=f) for f in ("config.json", "model.safetensors.index.json", "README.md")]} for k, v in FACTS.items()]
PUBLIC_SPEC_H100_BF16_DENSE_TFLOPS = 989          # NVIDIA H100 SXM public datasheet figure (dense bf16); used only to bound throughput estimates
MODAL_H100_USD_PER_HOUR = Decimal("3.95")         # persisted in the program's own preflight artifacts (rates_usd_per_hour.h100)
INR_PER_USD = (85, 90)                            # ASSUMPTION (not a live quote): a plausible range used only to convert the owner's INR budget
BUDGET_INR = 10000


def jload(name: str):
    return json.loads((EVIDENCE / name).read_text())


def persisted_controls() -> dict:
    """The final control matrix, read from the persisted (immutable) records. Nothing is written."""
    spec = {"Qwen3-8B": ("QWEN3_8B", "GENESIS_CONTROL_QWEN3_8B_MODAL_H100_ATTEMPT5"), "Mistral-Nemo-Instruct-2407": ("MISTRAL_NEMO", "GENESIS_CONTROL_MISTRAL_NEMO_MODAL_H100_ATTEMPT3"),
            "Phi-4": ("PHI4", "GENESIS_CONTROL_PHI4_MODAL_H100_ATTEMPT1")}
    out = {}
    for name, (tag, prefix) in spec.items():
        rec = jload(f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_2026-09-24.json")
        a = rec["attempts"][-1]
        after = jload(f"{prefix}_BILLING_AFTER_2026-09-24.json")
        cost = sum((Decimal(str(r["cost"])) for r in after.get("itemized_rows_for_app", [])), Decimal(0))
        acc = {x["smoke_id"]: ("PASS" if x["accepted"] else "FAIL") for x in rec["smoke_acceptance"]}
        out[name] = {"model_id": rec["model_id"], "revision": rec["model_revision"], "latest_authorized_attempt": a["attempt_number"], "outcome": a["outcome"], "failure_domain": a["failure_domain"],
                     "locked_smokes": [acc["A"], acc["B"], acc["C"]], "http_status": [o["http_status"] for o in rec["smoke_outputs"]], "technical_serving_status": rec["technical_serving_status"],
                     "runtime_qualification_status": rec["runtime_qualification_status"], "capability_status": rec["capability_status"], "financial_acceptance_status": rec["financial_acceptance_status"],
                     "owner_billed_delta_usd": str(Decimal(a["owner_billed_delta_usd"])), "settlement": a["billing_settlement_status"], "cleanup": a["cleanup_result"], "live_resources_after_cleanup": rec["live_resources_after_cleanup"],
                     "modal_app_id": a["modal_app_id"], "duration_seconds": a["duration_seconds"], "itemized_attempt_cost_usd": str(cost), "raw_log_artifact": a["raw_log_artifact"], "raw_log_sha256": a["raw_log_sha256"],
                     "runtime_candidate_configuration_id": rec.get("runtime_candidate_configuration_id"), "attempt_count": len(rec["attempts"]),
                     "attempt_history": [{"attempt": x["attempt_number"], "outcome": x["outcome"], "provider": x.get("provider")} for x in rec["attempts"]]}
    return out


def program_financials() -> dict:
    after = jload("GENESIS_CONTROL_PHI4_MODAL_H100_ATTEMPT1_BILLING_AFTER_2026-09-24.json")
    s = after["billing_summary_settled"]
    pre = jload("GENESIS_CONTROL_PHI4_MODAL_H100_ATTEMPT1_FINANCIAL_PREFLIGHT_2026-09-24.json")
    credits = -Decimal(s["adjustments"]["credits"])
    pool = Decimal(pre["credit_pool_usd"]) - Decimal(pre["unresolved_prior_settlement_upper_bound_deducted_usd"])
    return {"billing_read_at_utc": after["captured_at_utc"], "owner_billed_cost_usd": str(Decimal(s["billed_cost"])), "metered_cost_usd": s["metered_cost"], "promotional_credits_applied_usd": str(credits),
            "free_storage_adjustment_usd": s["adjustments"]["free_storage"], "effective_credit_pool_usd": str(pool.quantize(Decimal("0.0001"))), "remaining_promotional_credit_usd": str((pool - credits).quantize(Decimal("0.0001"))),
            "reserve_usd": "5.00", "headroom_above_reserve_usd": str((pool - credits - Decimal("5.00")).quantize(Decimal("0.0001"))),
            "live_resources_after_last_run": after["cleanup_snapshot"]["live_resources"], "containers_after_last_run": len(after["cleanup_snapshot"]["containers"]),
            "note": "promotional credit only; the owner's cash spend across the controlled program is exactly zero (every persisted attempt has owner billed delta 0)"}


# ── estimates ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def estimates() -> dict:
    res = {}
    lo_inr, hi_inr = INR_PER_USD
    usd_hi, usd_lo = BUDGET_INR / lo_inr, BUDGET_INR / hi_inr
    for name, f in FACTS.items():
        params = f["safetensors_total_bytes"] / 2                       # bf16 checkpoint: 2 bytes per parameter
        embed = f["vocab"] * f["hidden"]
        linear = params - 2 * embed                                     # untied embedding + lm_head stay bf16 (bitsandbytes quantizes Linear layers)
        h, L, kv, hd, ff, heads = f["hidden"], f["layers"], f["kv_heads"], f["head_dim"], f["intermediate"], f["heads"]
        r = 16
        per_layer = r * ((h + heads * hd) + 2 * (h + kv * hd) + (heads * hd + h) + 2 * (h + ff) + (ff + h))
        lora = L * per_layer                                            # rank-16 LoRA on q,k,v,o,gate,up,down (fused projections have identical totals)
        weights_gb = (linear * 0.53 + 2 * embed * 2) / 1e9              # NF4 ~0.53 B/param incl. quant constants; embeddings/lm_head bf16
        states_gb = lora * 16 / 1e9                                     # fp32 param + grad + 2 Adam moments
        peaks = {}
        for seq in (2048, 4096):
            ckpt = L * seq * h * 2 / 1e9                                # saved layer inputs (bf16) with gradient checkpointing, micro-batch 1
            layer = seq * (h * 34 + ff * 6) / 1e9                       # one layer's live activations during recompute (rough)
            logits = seq * f["vocab"] * 10 / 1e9                        # fp32 upcast + bf16 copy + grad of the logits
            total = weights_gb + states_gb + ckpt + layer + logits + 1.5   # + CUDA context / allocator slack
            peaks[str(seq)] = {"estimated_peak_gb": round(total, 1), "plausible_range_gb": [round(total * 0.8, 1), round(total * 1.4, 1)]}
        tps = [PUBLIC_SPEC_H100_BF16_DENSE_TFLOPS * 1e12 * mfu / (6 * params) for mfu in (0.15, 0.25)]    # QLoRA ~ 6N flops/token (fwd + recompute + activation-grad, no weight-grad)
        cost_per_m = [float(MODAL_H100_USD_PER_HOUR) * (1e6 / t) / 3600 for t in tps[::-1]]                # [cheapest, dearest] USD per 1M training tokens
        usable = (0.4, 0.6)                                                                                  # share of the budget that becomes training compute (rest: evals, failed runs, storage, export)
        max_tokens_m = [usd * u / c for usd, u, c in ((usd_lo, usable[0], cost_per_m[1]), (usd_hi, usable[1], cost_per_m[0]))]
        kv_per_tok = 2 * L * kv * hd * 2
        res[name] = {
            "parameters_b_from_checkpoint": round(params / 1e9, 3), "bf16_weights_gb": round(f["safetensors_total_bytes"] / 1e9, 1),
            "lora_rank16_all_linear_trainable_params_m": round(lora / 1e6, 1), "qlora_static_gb": {"nf4_base_plus_bf16_embeddings": round(weights_gb, 1), "lora_optimizer_states": round(states_gb, 2)},
            "qlora_peak_gb_microbatch1": peaks, "qlora_fits": {"24GB_class": peaks["2048"]["plausible_range_gb"][1] <= 24.0, "24GB_class_typical_only": peaks["2048"]["estimated_peak_gb"] <= 24.0,
                                                               "40GB_class": peaks["4096"]["plausible_range_gb"][1] <= 40.0, "80GB": True},
            "qlora_tokens_per_second_on_1xH100_range": [round(t) for t in tps], "usd_per_million_training_tokens_range": [round(c, 2) for c in cost_per_m],
            "training_tokens_affordable_under_budget_millions_range": [round(x) for x in max_tokens_m],
            "kv_cache_bytes_per_token_bf16": kv_per_tok, "kv_cache_gb_per_8k_context_sequence": round(kv_per_tok * 8192 / 1e9, 2),
            "serving_min_gpu_bf16": "24GB class (tight, short context)" if params < 9e9 else "40GB+ class" if params < 13e9 else "40GB+ class (48/80GB for comfortable KV)",
            "serving_4bit_weights_gb_approx": round((linear * 0.53 + 2 * embed * 2) / 1e9, 1)}
    return res


def eval_plan_cost() -> dict:
    """Minimum Foundation Capability Eval v0: cost from the persisted observed server-ready time and a small workload. All figures are estimates with stated inputs."""
    ready_s = (120, 144)                                                # observed server-ready times across the three authorized runs (Mistral 120 s ... Phi 138-144 s)
    requests_per_model = 420 * 2                                       # 420 items x 2 sampling configurations
    tokens_out = requests_per_model * 250
    gen_hours = (tokens_out / 1500) / 3600                              # batched vLLM decode of a 8-15B model on one H100, conservative 1,500 tok/s aggregate
    cold_hours = (ready_s[0] / 3600, ready_s[1] / 3600)
    per_model = [float(MODAL_H100_USD_PER_HOUR) * (gen_hours + c + 0.05) for c in cold_hours]      # + ~3 min teardown/settle margin
    pilot_tokens_m = 5
    return {"items": {"strict_format_instruction_following": 120, "structured_json_schema_output": 80, "short_verifiable_reasoning": 100, "coding_static_and_hermetic": 80, "long_context_retrieval_8k_16k": 40, "total": 420},
            "sampling_configurations": ["locked greedy (temperature 0, top_p 1, seed 0)", "vendor-recommended sampling per model card, fixed seeds"], "requests_per_model": requests_per_model,
            "estimated_output_tokens_per_model": tokens_out, "estimated_eval_usd_per_model_range": [round(per_model[0], 2), round(per_model[1], 2)],
            "estimated_eval_usd_three_models_range": [round(3 * per_model[0], 2), round(3 * per_model[1], 2)], "pilot": {"qlora_format_adherence_tokens_m": pilot_tokens_m,
            "note": "5M-token QLoRA format-adherence pilot per candidate; cost = 5 x usd_per_million_training_tokens from the estimates block"}}


def build() -> dict:
    controls = persisted_controls()
    fin = program_financials()
    est = estimates()
    ev = eval_plan_cost()
    pilot = {k: [round(5 * c, 2) for c in est[k]["usd_per_million_training_tokens_range"]] for k in est}
    total_lo = round(ev["estimated_eval_usd_three_models_range"][0] + sum(v[0] for v in pilot.values()), 2)
    total_hi = round(ev["estimated_eval_usd_three_models_range"][1] + sum(v[1] for v in pilot.values()), 2)
    ev["pilot_usd_per_model_range"] = pilot
    ev["decision_evidence_total_usd_range"] = [total_lo, total_hi]
    ev["decision_evidence_total_with_1_5x_contingency_usd_range"] = [round(total_lo * 1.5, 2), round(total_hi * 1.5, 2)]
    ev["decision_evidence_total_inr_range_with_contingency"] = [round(total_lo * 1.5 * INR_PER_USD[0]), round(total_hi * 1.5 * INR_PER_USD[1])]
    ev["exceeds_current_promotional_headroom"] = Decimal(str(total_lo)) > Decimal(fin["headroom_above_reserve_usd"])
    criteria = [
        ("A", "Architecture suitability for ORNEUR", "GATE", "dense decoder-only transformer supported by mainstream PEFT/vLLM stacks; GQA; no custom code required"),
        ("B", "Parameter count / memory requirements", "GATE", "must QLoRA-train within the frozen hardware plan and serve within the frozen deployment plan"),
        ("K", "Licensing / redistribution", "GATE", "license must permit fine-tuning, redistribution of derived weights and commercial use with obligations that ORNEUR can meet"),
        ("F", "Instruction-following characteristics", 12, "strict-format instruction following measured on the frozen eval, base and after a format-adherence LoRA pilot"),
        ("G", "Structured-output characteristics", 12, "JSON/schema validity and exactness on the frozen eval"),
        ("H", "Reasoning potential", 12, "verifiable short-reasoning accuracy; gain after pilot SFT"),
        ("I", "Coding potential", 12, "static + hermetic-sandbox scored coding items (execution only under a separate authorization)"),
        ("J", "Context-window characteristics", 4, "usable context measured at 8k/16k retrieval; vendor-stated native context recorded"),
        ("D", "Tokenizer and chat-template stability", 4, "template resolves identically across the pinned tooling versions; no path-dependent failure"),
        ("E", "Runtime compatibility", 4, "loads and serves under the pinned vLLM; observed in the control program"),
        ("L", "Ecosystem / tooling maturity", 4, "PEFT/TRL/vLLM/quantization support without workarounds"),
        ("M", "Training stability evidence from primary technical sources", 4, "vendor/independent reports of stable fine-tuning; own pilot loss curves"),
        ("N", "Quantization compatibility", 4, "NF4 QLoRA and 4-bit serving quantization quality retained on the frozen eval"),
        ("O", "Inference cost", 6, "GPU class and throughput needed at the frozen quality bar"),
        ("P", "Expected training cost", 6, "measured pilot cost extrapolated to the frozen training plan"),
        ("Q", "Ability to create differentiated ORNEUR behavior", 8, "pilot behavior shift toward ORNEUR-specific formats/policies without capability regression"),
        ("R", "Long-term migration path to ORNEUR-owned model families", 8, "license/data-flow permits distillation, continued pretraining and re-basing; adapters and data remain foundation-agnostic"),
    ]
    weighted = sum(c[2] for c in criteria if isinstance(c[2], int))
    def b_text(name, cls):
        e = est[name]
        p2, p4 = e["qlora_peak_gb_microbatch1"]["2048"], e["qlora_peak_gb_microbatch1"]["4096"]
        return (f"PASS on paper ({e['parameters_b_from_checkpoint']} B; NF4 base + bf16 embeddings ≈ {e['qlora_static_gb']['nf4_base_plus_bf16_embeddings']} GB; estimated QLoRA peak ≈ {p2['estimated_peak_gb']}–{p4['estimated_peak_gb']} GB "
                f"at seq 2k–4k, plausible range up to ≈{p4['plausible_range_gb'][1]} GB: {cls})")
    known = {
        "Qwen3-8B": {"A": "PASS (dense Qwen3ForCausalLM, GQA 32/8)", "B": b_text("Qwen3-8B", "24GB-class plausible"), "K": "PASS (Apache-2.0)", "J": "32,768 native; 131,072 with YaRN (vendor)",
                     "D": "hybrid thinking template adds a mode switch; stable through the pinned stack (observed)", "E": "OBSERVED: served and answered under vLLM 0.29.0 (attempts 4 and 5)", "O": "cheapest of the three (16.4 GB bf16)",
                     "P": "cheapest of the three", "F/G": "UNKNOWN: locked greedy contract failed on B only (attempt 5, non-thinking); vendor advises against greedy decoding in thinking mode"},
        "Mistral-Nemo-Instruct-2407": {"A": "PASS (dense MistralForCausalLM, GQA 32/8)", "B": b_text("Mistral-Nemo-Instruct-2407", "24GB-class plausible, 40GB-class comfortable"), "K": "PASS (Apache-2.0)", "J": "128k trained (vendor)",
                     "D": "FRICTION: HF-mode chat-template resolution failed under vLLM 0.29.0/transformers 5.16.1 (MistralCommonBackend selected because tekken.json is present); native tokenizer mode required",
                     "E": "OBSERVED: served under vLLM only after switching to native tokenizer mode (attempt 3)", "O": "mid (24.5 GB bf16)", "P": "mid", "F/G": "UNKNOWN: verbose chat-style answers on all three locked prompts (attempt 3)"},
        "Phi-4": {"A": "PASS (dense Phi3ForCausalLM, GQA 40/10, fused projections)", "B": b_text("Phi-4", "24GB-class tight, 40GB-class comfortable"), "K": "PASS (MIT)", "J": "16K only (vendor)",
                  "D": "stable: template resolves on the canonical HF path (attempt 1)", "E": "OBSERVED: served on the canonical path (attempt 1)", "O": "highest (29.3 GB bf16)", "P": "highest",
                  "F/G": "UNKNOWN: passed the exact READY contract, verbose on B and C (attempt 1); English-centric, Python-centric code data (vendor)"},
    }
    doc = {
        "document": "GENESIS_FOUNDATION_DECISION_PACKAGE", "phase": "21B.4.20", "date": "2026-09-26", "base_sha": BASE_SHA, "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "closeout": {"verdict": "PHASE_21B_4_20_CLOSED", "statements": [
            "all authorized control runs are complete (Qwen3-8B attempt 5, Mistral-Nemo attempt 3, Phi-4 attempt 1)",
            "no control achieved RUNTIME_QUALIFIED under the locked exact-output contract", "capability remains UNPROVEN for all controls", "no further control retry is authorized",
            "historical evidence is immutable and was not rewritten", "owner billing remained zero across the controlled program (every persisted attempt has owner billed delta 0)",
            "all latest required settlements are resolved (OBSERVED, or covered by the existing Qwen attempt-1 waiver)", "persisted evidence shows zero live GPU resources after the last run"],
            "no_control_runtime_qualified": all(c["runtime_qualification_status"] != "RUNTIME_QUALIFIED" for c in controls.values())},
        "final_control_matrix": controls, "program_financials": fin,
        "interpretation": "The locked A/B/C smokes were runtime/control-contract tests (exact-string / exact-JSON acceptance at temperature 0). They are NOT capability, reasoning, coding or knowledge benchmarks, NOT Genesis training evaluations and NOT quality rankings. "
                          "No foundation may be selected by counting smoke passes. Verbose chat-style answers to terse exact-output prompts are ordinary instruct-model behavior that behavior/format tuning is designed to change.",
        "foundation_options": {k: dict(v, source_urls=[s for s in SOURCES if s["model"] == k][0]["files"]) for k, v in FACTS.items()},
        "decision_criteria": [{"id": c[0], "criterion": c[1], "kind": "gate" if c[2] == "GATE" else "weighted", "weight": None if c[2] == "GATE" else c[2], "measure": c[3]} for c in criteria],
        "criteria_weight_total": weighted,
        "selection_rule": {"gates": "a candidate must pass gates A, B, K", "score": "weighted sum of F,G,H,I,J,D,E,L,M,N,O,P,Q,R on the frozen Genesis Foundation Capability Eval v0 + pilot (weights sum to 100)",
                           "decision": "select the top candidate only if it leads by >= 5 weighted points AND the paired-bootstrap 95% interval of the lead excludes 0 on the eval axes; otherwise apply the tie-break (lowest projected total cost, then longest usable context, then most permissive license) and record the tie",
                           "pre_registered": True},
        "evidence_known_now_by_criterion": known, "estimates": est, "estimate_assumptions": {
            "usd_inr_range_assumed_not_a_live_quote": list(INR_PER_USD), "budget_inr": BUDGET_INR, "budget_usd_range": [round(BUDGET_INR / INR_PER_USD[1]), round(BUDGET_INR / INR_PER_USD[0])],
            "h100_usd_per_hour_from_persisted_preflight": str(MODAL_H100_USD_PER_HOUR), "h100_bf16_dense_tflops_public_spec": PUBLIC_SPEC_H100_BF16_DENSE_TFLOPS, "qlora_mfu_range": [0.15, 0.25],
            "training_flops_per_token": "6 x parameters (forward + checkpoint recompute + activation-gradient; no weight-gradient for frozen base)", "usable_share_of_budget_for_training_compute": [0.4, 0.6],
            "nf4_bytes_per_parameter": 0.53, "activation_and_logit_model": "rough analytic model; treat peak memory as +/-40%", "no_fake_precision": "every number is an estimate with a stated formula and range; none is a measurement"},
        "training_reality": {
            "budget": "approximately INR 10,000 for the first Genesis training (owner statement); enough for parameter-efficient adaptation of an 8-15B model, NOT for pretraining any frontier-scale model from scratch",
            "one_time_training_vs_future_inference": "training is a one-time cost per run; serving cost recurs and depends on hosting design (always-on H100 at the persisted list rate is about USD 2,844/month = far above this budget; scale-to-zero or quantized small-GPU serving is required)",
            "recommended_path_if_selected": ["QLoRA (NF4 + bf16 compute, paged 8-bit AdamW, gradient checkpointing), rank 16-64 on all linear layers, sequence 2k-4k, learning rate around 1e-4-2e-4, 1-3 epochs",
                                             "stage 1: format/behavior SFT (strict formats, JSON, refusal/citation/evidence behavior)", "stage 2: capability/domain SFT on Genesis data", "stage 3: preference/behavior tuning (DPO/ORPO-class) only if stage-2 evals justify its cost",
                                             "evaluate after every stage on the frozen suite; keep adapters + data + eval as foundation-agnostic ORNEUR assets; merge and quantize only after the final stage"],
            "reserve_note": "the current promotional-credit headroom above the 5.00 USD reserve is far below any training budget; training therefore needs an explicit owner funding decision and would end the program's zero-cash constraint",
            "inference_note": "serving memory = weights + KV cache; see estimates.kv_cache_gb_per_8k_context_sequence and serving_min_gpu_bf16"},
        "minimum_capability_evaluation": {
            "name": "Genesis Foundation Capability Eval v0 (CPU-authored, frozen before any model is run)", "why": "no capability evidence exists for any control; selecting by intuition or smoke counts is not permitted",
            "design": ["ORNEUR-authored, novel items (no public benchmark items) to avoid contamination; hash-frozen before any model is run; train/eval split frozen",
                       "identical prompts and shipped chat templates for all candidates; both locked greedy and vendor-recommended sampling, fixed seeds",
                       "scoring by exact/JSON-schema/regex checks; code items scored by static analysis and, only under a separate authorization, a hermetic sandbox",
                       "a 5M-token QLoRA format-adherence pilot per candidate to measure trainability toward ORNEUR formats (the smoke failures were format-behaviour failures)",
                       "results reported with paired-bootstrap confidence intervals; nothing is averaged into a single 'smartness' number"],
            "cost": ev, "cpu_only_alternative": "CPU inference of 8-15B models is too slow for even this workload (days), so a small amount of GPU time is unavoidable; the workload is deliberately tiny",
            "prerequisites": ["owner authorization of the (small) evidence budget, since promotional headroom is insufficient", "eval item authoring and freezing (CPU-only)", "separate authorization for any hermetic code-execution sandbox"]},
        "chain_alignment": {
            "principle": "ORNEUR is not a renamed external model; the foundation is a starting substrate for Genesis.",
            "how_the_process_supports_the_chain": [
                "Genesis Data -> Genesis Foundation: the eval, data and adapters are owned assets that are independent of the chosen base, so the base can be swapped by re-running the pipeline",
                "-> ORNEUR behavior/intelligence training: behavior is expressed as data + adapters + evals, not as a vendor identity; vendor names are stripped from model outputs and product surfaces (license notices preserved as required)",
                "-> ORNEUR model family (Fast / Reason / Frontier): the selected base is the first rung; later rungs (larger bases, distillation from ORNEUR-trained teachers, continued pretraining) reuse the same data/eval/adapter interfaces",
                "-> Runtime/Router, Retrieval, Tools/Missions, Memory, Evidence, Public Product: served behind ORNEUR's own runtime contracts (the control program's exact-proof harness), so no layer depends on the base model's identity",
                "licenses (Apache-2.0 / MIT) permit fine-tuning, redistribution of derived weights and commercial use with notice/attribution obligations; verify at freeze time"]},
        "phase_21c_entry_gate": [
            {"id": "G1", "requirement": "Genesis foundation selected by the pre-registered rule from the frozen capability eval + pilot", "status": "NOT_MET"},
            {"id": "G2", "requirement": "Dataset V3 integrity green (manifest, hashes, provenance, license per source)", "status": "NOT_VERIFIED_IN_THIS_PACKAGE"},
            {"id": "G3", "requirement": "Contamination and de-duplication gates green against the frozen eval and public benchmarks", "status": "NOT_MET"},
            {"id": "G4", "requirement": "Train / eval split frozen and hash-pinned", "status": "NOT_MET"},
            {"id": "G5", "requirement": "Training objective frozen (stages, loss, hyperparameter ranges, stop rules)", "status": "NOT_MET"},
            {"id": "G6", "requirement": "Budget ceiling frozen by the owner (including the funding decision and the zero-cash policy change it implies)", "status": "NOT_MET"},
            {"id": "G7", "requirement": "Hardware plan frozen (GPU class, provider, region, max hours, kill-switch)", "status": "NOT_MET"},
            {"id": "G8", "requirement": "Checkpoint and rollback plan (adapter checkpoints, resume, byte-identical restore)", "status": "NOT_MET"},
            {"id": "G9", "requirement": "Reproducibility manifest (code SHA, data hashes, library versions, seeds, container digest)", "status": "NOT_MET"},
            {"id": "G10", "requirement": "Evaluation suite frozen (items, scorers, thresholds, decision rule)", "status": "NOT_MET"},
            {"id": "G11", "requirement": "No unresolved control-runtime evidence issue", "status": "MET_PENDING_INDEPENDENT_AUDIT", "basis": "all attempt settlements resolved, owner billed 0, zero live resources, exact-SHA CI green; the only known caveat is host-load flakiness of two unrelated local tests"},
            {"id": "G12", "requirement": "Explicit owner authorization to enter Phase 21C", "status": "NOT_MET"}],
        "verdict": "FOUNDATION_DECISION_REQUIRES_CAPABILITY_EVAL",
        "verdict_reason": "The current evidence contains no capability measurement for any candidate. The locked smokes are runtime contract tests; all three failed them for response-format behavior, none is RUNTIME_QUALIFIED, and public vendor facts alone (size, license, context) do not determine which base best serves ORNEUR. "
                          "Selecting now would be selection by intuition.",
        "selected_foundation": None, "phase_21c_authorized": False, "training_authorized": False, "gpu_authorized": False,
        "confirmations": {"no_gpu_used": True, "no_modal_used": True, "no_provider_call": True, "external_reads": "public Hugging Face files at the exact pinned revisions (read-only)", "control_evidence_mutated": False},
    }
    return doc


def md(doc: dict) -> str:
    c, m, est, ev = doc["closeout"], doc["final_control_matrix"], doc["estimates"], doc["minimum_capability_evaluation"]["cost"]
    L = []
    a = L.append
    a("# Genesis Foundation Decision Package — Phase 21B.4.20 Final Closeout")
    a("")
    a(f"Date: 2026-09-26 · Base SHA: `{doc['base_sha']}` · Companion: `GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26.json` (generated by `scripts/phase21b_4_20_foundation_decision_package.py`)")
    a("")
    a("> **Verdict: `FOUNDATION_DECISION_REQUIRES_CAPABILITY_EVAL`.** No foundation is selected. No training, GPU run or Phase 21C entry is authorized by this document.")
    a("")
    a("## 1. Phase 21B.4.20 closeout — `PHASE_21B_4_20_CLOSED`")
    for s in c["statements"]:
        a(f"- {s}")
    a("")
    a("### Immutable final control matrix (read from the persisted records)")
    a("")
    a("| Control | Revision | Latest authorized attempt | Locked smokes A/B/C | Outcome | Technical serving | Runtime qualification | Capability | Owner billed Δ | Settlement | Itemized cost (USD) | App |")
    a("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for k, v in m.items():
        cfg = f" (candidate `{v['runtime_candidate_configuration_id']}`)" if v["runtime_candidate_configuration_id"] else ""
        a(f"| {k} | `{v['revision'][:8]}…` | {v['latest_authorized_attempt']}{cfg} | {' / '.join(v['locked_smokes'])} | {v['outcome']} / {v['failure_domain']} | {v['technical_serving_status']} | {v['runtime_qualification_status']} | {v['capability_status']} | {v['owner_billed_delta_usd']} | {v['settlement']} | {v['itemized_attempt_cost_usd']} | `{v['modal_app_id']}` |")
    a("")
    a("**No control is RUNTIME_QUALIFIED.** " + doc["interpretation"])
    a("")
    f = doc["program_financials"]
    a(f"Program financials (last persisted reading {f['billing_read_at_utc']}): owner billed **{f['owner_billed_cost_usd']}**, metered {f['metered_cost_usd']}, promotional credits applied {f['promotional_credits_applied_usd']} of an effective pool {f['effective_credit_pool_usd']}, remaining promotional credit ≈ **{f['remaining_promotional_credit_usd']}**, reserve {f['reserve_usd']}, headroom above reserve ≈ {f['headroom_above_reserve_usd']}; live resources {f['live_resources_after_last_run']}, containers {f['containers_after_last_run']}.")
    a("")
    a("## 2. Foundation decision criteria (pre-registered)")
    a("")
    a("| ID | Criterion | Kind | Weight | How it will be measured |")
    a("|---|---|---|---|---|")
    for x in doc["decision_criteria"]:
        a(f"| {x['id']} | {x['criterion']} | {x['kind']} | {x['weight'] if x['weight'] is not None else '—'} | {x['measure']} |")
    a("")
    a(f"Weights of the non-gate criteria sum to **{doc['criteria_weight_total']}**. Selection rule: {doc['selection_rule']['decision']}. Gates: {doc['selection_rule']['gates']}. The A/B/C smoke count is **not** a criterion.")
    a("")
    a("## 3. Evidence reviewed — the admitted options (exact revisions already used in ORNEUR)")
    a("")
    a("| | Qwen3-8B | Mistral-Nemo-Instruct-2407 | Phi-4 |")
    a("|---|---|---|---|")
    fo = doc["foundation_options"]
    ks = list(fo)
    def row(label, fn):
        a(f"| {label} | " + " | ".join(fn(fo[k]) for k in ks) + " |")
    row("Repository @ revision", lambda v: f"`{v['repo']}` @ `{v['revision'][:12]}…`")
    row("License (model card)", lambda v: v["license"])
    row("Architecture", lambda v: v["architecture"])
    row("Parameters (from checkpoint bytes)", lambda v: f"{v['safetensors_total_bytes'] / 2e9:.2f} B")
    row("Layers / hidden / heads / KV heads", lambda v: f"{v['layers']} / {v['hidden']} / {v['heads']} / {v['kv_heads']}")
    row("Vocabulary", lambda v: f"{v['vocab']:,}")
    row("Context (vendor)", lambda v: f"{v['native_context']:,} native; {v['extended_context']}")
    a("")
    for k in ks:
        a(f"**{k} — vendor-documented notes and program observations**")
        for n in fo[k]["vendor_notes"]:
            a(f"- {n}")
        a("")
    a("Criterion-by-criterion evidence known now (UNKNOWN entries are exactly what the capability eval must supply):")
    a("")
    for k, v in doc["evidence_known_now_by_criterion"].items():
        a(f"- **{k}:** " + "; ".join(f"{cid}: {txt}" for cid, txt in v.items()))
    a("")
    a("Sources (public, read-only, exact pinned revisions): " + "; ".join(f"{s['model']}: " + ", ".join(f"<{u}>" for u in s["files"][:1]) + " (+ index, README)" for s in [{"model": k, "files": fo[k]["source_urls"]} for k in ks]) + ".")
    a("")
    a("## 4. Training-budget reality")
    a("")
    e = doc["estimate_assumptions"]
    a(f"Owner budget: about ₹{e['budget_inr']:,} ≈ **USD {e['budget_usd_range'][0]}–{e['budget_usd_range'][1]}** (assumed ₹{e['usd_inr_range_assumed_not_a_live_quote'][0]}–{e['usd_inr_range_assumed_not_a_live_quote'][1]} per USD; not a live quote). {doc['training_reality']['budget']}.")
    a("")
    a("**All numbers below are estimates with stated formulas and ranges, not measurements.** Assumptions: H100 at the program's persisted list rate USD 3.95/h; QLoRA ≈ 6 × parameters FLOPs/token at 15–25 % of the public 989-TFLOPs bf16 figure; 40–60 % of the budget becomes training compute (the rest covers evals, failed runs, storage, export); peak memory ±40 %.")
    a("")
    a("| | Qwen3-8B | Mistral-Nemo | Phi-4 |")
    a("|---|---|---|---|")
    def erow(label, fn):
        a(f"| {label} | " + " | ".join(fn(est[k]) for k in ks) + " |")
    erow("Parameters", lambda v: f"{v['parameters_b_from_checkpoint']} B")
    erow("LoRA r=16 all-linear trainable params", lambda v: f"{v['lora_rank16_all_linear_trainable_params_m']} M")
    erow("QLoRA static (NF4 base + bf16 embeddings)", lambda v: f"{v['qlora_static_gb']['nf4_base_plus_bf16_embeddings']} GB")
    erow("QLoRA peak, seq 2048, micro-batch 1", lambda v: f"≈{v['qlora_peak_gb_microbatch1']['2048']['estimated_peak_gb']} GB ({v['qlora_peak_gb_microbatch1']['2048']['plausible_range_gb'][0]}–{v['qlora_peak_gb_microbatch1']['2048']['plausible_range_gb'][1]})")
    erow("QLoRA peak, seq 4096, micro-batch 1", lambda v: f"≈{v['qlora_peak_gb_microbatch1']['4096']['estimated_peak_gb']} GB ({v['qlora_peak_gb_microbatch1']['4096']['plausible_range_gb'][0]}–{v['qlora_peak_gb_microbatch1']['4096']['plausible_range_gb'][1]})")
    erow("QLoRA tokens/s on 1×H100 (range)", lambda v: f"{v['qlora_tokens_per_second_on_1xH100_range'][0]:,}–{v['qlora_tokens_per_second_on_1xH100_range'][1]:,}")
    erow("USD per 1M training tokens (H100 list rate)", lambda v: f"{v['usd_per_million_training_tokens_range'][0]}–{v['usd_per_million_training_tokens_range'][1]}")
    erow("Training tokens affordable under the budget (M)", lambda v: f"{v['training_tokens_affordable_under_budget_millions_range'][0]:,}–{v['training_tokens_affordable_under_budget_millions_range'][1]:,}")
    erow("bf16 weights (serving)", lambda v: f"{v['bf16_weights_gb']} GB")
    erow("KV cache per 8k-context sequence (bf16)", lambda v: f"{v['kv_cache_gb_per_8k_context_sequence']} GB")
    erow("Serving GPU class (bf16)", lambda v: v["serving_min_gpu_bf16"])
    a("")
    a("**Reading the table.** Any of the three fits a parameter-efficient (QLoRA/LoRA) first-Genesis budget; the budget cannot pretrain a frontier model. Affordable *token counts* far exceed what behavior/format SFT needs (typically tens of millions of tokens), so the binding constraint is the number of iterations (failed runs, evals, data fixes), not raw compute. "
      "One-time training cost and future inference cost are separate: the recurring cost is hosting design — an always-on H100 at the persisted list rate is ≈ USD 2,844/month, so ORNEUR serving needs scale-to-zero or 4-bit small-GPU serving regardless of which base is chosen.")
    a("")
    a("**Recommended path if a base is selected:** " + "; ".join(doc["training_reality"]["recommended_path_if_selected"]) + ".")
    a("")
    a(f"**Funding note.** {doc['training_reality']['reserve_note']}.")
    a("")
    a("## 5. Decision — `FOUNDATION_DECISION_REQUIRES_CAPABILITY_EVAL`")
    a("")
    a(doc["verdict_reason"])
    a("")
    mce = doc["minimum_capability_evaluation"]
    a(f"### Minimum evaluation needed before choosing — {mce['name']}")
    a("")
    for x in mce["design"]:
        a(f"- {x}")
    a("")
    a(f"Workload: {ev['items']['total']} items ({', '.join(f'{k.replace(chr(95), chr(32))} {v}' for k, v in ev['items'].items() if k != 'total')}) × 2 sampling configurations per model. "
      f"Estimated GPU cost: eval ≈ USD {ev['estimated_eval_usd_three_models_range'][0]}–{ev['estimated_eval_usd_three_models_range'][1]} for all three models; 5M-token QLoRA format-adherence pilots ≈ USD "
      + ", ".join(f"{k.split('-')[0]} {v[0]}–{v[1]}" for k, v in ev["pilot_usd_per_model_range"].items()) +
      f"; total ≈ **USD {ev['decision_evidence_total_usd_range'][0]}–{ev['decision_evidence_total_usd_range'][1]}** (with a 1.5× contingency ≈ USD {ev['decision_evidence_total_with_1_5x_contingency_usd_range'][0]}–{ev['decision_evidence_total_with_1_5x_contingency_usd_range'][1]} ≈ ₹{ev['decision_evidence_total_inr_range_with_contingency'][0]:,}–{ev['decision_evidence_total_inr_range_with_contingency'][1]:,}), i.e. roughly a tenth of the ₹10,000 budget. "
      f"This exceeds the current promotional-credit headroom above the reserve, so it needs an explicit owner funding decision. {mce['cpu_only_alternative']}.")
    a("")
    a("Prerequisites: " + "; ".join(mce["prerequisites"]) + ".")
    a("")
    a("### Known risks and trade-offs of the three options (from primary sources and the control program)")
    a("- **Qwen3-8B** — smallest and cheapest to train/serve; Apache-2.0; hybrid thinking/non-thinking template needs a deliberate SFT template decision; vendor advises against greedy decoding in thinking mode; shortest path to a fast iteration loop. Unknown: format/JSON trainability, coding/reasoning at the ORNEUR bar.")
    a("- **Mistral-Nemo-Instruct-2407** — 128k context and a native function-calling format; Apache-2.0; the Tekken tokenizer needs the native Mistral tokenizer mode under the pinned vLLM (a tooling-friction risk); mid cost; low sampling temperature recommended by the vendor. Unknown: everything capability-related.")
    a("- **Phi-4** — MIT; strongest vendor emphasis on reasoning from synthetic 'textbook-like' data; highest training/serving cost; 16K context only; English-centric and Python-centric code data; canonical HF path is stable. Unknown: everything capability-related on ORNEUR tasks.")
    a("")
    a("## 6. How the eventual choice supports the ORNEUR chain")
    a("")
    a(doc["chain_alignment"]["principle"])
    for x in doc["chain_alignment"]["how_the_process_supports_the_chain"]:
        a(f"- {x}")
    a("")
    a("## 7. Phase 21C entry gate (all must be true; none is authorized here)")
    a("")
    a("| ID | Requirement | Status now |")
    a("|---|---|---|")
    for g in doc["phase_21c_entry_gate"]:
        a(f"| {g['id']} | {g['requirement']} | {g['status']} |")
    a("")
    a("## 8. Confirmations")
    a("- No GPU, Modal function or provider call occurred in this step; public Hugging Face files were read (read-only) at the exact pinned revisions.")
    a("- No control evidence was modified; no control retry, training or Phase 21C action is authorized; no control is claimed runtime-qualified; no capability qualification is claimed.")
    a("")
    return "\n".join(L) + "\n"


def main() -> int:
    doc = build()
    OUT_JSON.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    OUT_MD.write_text(md(doc))
    print(json.dumps({"md": OUT_MD.name, "json": OUT_JSON.name, "verdict": doc["verdict"], "criteria_weight_total": doc["criteria_weight_total"], "matrix": {k: v["locked_smokes"] for k, v in doc["final_control_matrix"].items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
