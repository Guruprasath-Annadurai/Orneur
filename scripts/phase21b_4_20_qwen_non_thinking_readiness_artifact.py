"""
Phase 21B.4.20 -- CPU-ONLY implementation-readiness artifact for Qwen3-8B `qwen3_8b_non_thinking_v1`.

Reads the canonical modules, the runner's request builder and the persisted evidence; writes ONE artifact. It launches nothing,
calls no Modal function, performs no inference, spends nothing and never modifies existing evidence.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from orca.eval import control_runtime_configuration as rc  # noqa: E402
from orca.eval import locked_smoke_protocol as lp  # noqa: E402

EVIDENCE_DIR = REPO_ROOT / "docs/orneur/phase-21/evidence"
OUT = EVIDENCE_DIR / "GENESIS_QWEN3_8B_NON_THINKING_V1_IMPLEMENTATION_READINESS_2026-09-25.json"
MODEL_ID = "Qwen/Qwen3-8B"
DATE_TAG = "2026-09-24"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_runner():
    spec = importlib.util.spec_from_file_location("p21b420_runner_for_readiness", REPO_ROOT / "scripts/phase21b_4_20_lightning_runner.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    runner = load_runner()
    approved = rc.configuration_for_model(MODEL_ID)
    gen_cfg = {"temperature": 0, "top_p": 1, "seed": 0, "max_tokens": runner.LOCKED["qwen3_8b"]["smoke_max_tokens"]}
    smoke_b = next(s for s in runner.SMOKES if s["smoke_id"] == "B")
    cfg_qwen = runner.serving_config("qwen3_8b")
    cfg_qwen_without = dict(cfg_qwen, runtime_configuration=None)
    payload_after = runner.build_chat_payload(cfg_qwen, smoke_b, gen_cfg)
    payload_before = runner.build_chat_payload(cfg_qwen_without, smoke_b, gen_cfg)
    others = {key: runner.build_chat_payload(runner.serving_config(key), smoke_b, gen_cfg) for key in ("mistral_nemo", "phi4")}

    attempts = json.loads((EVIDENCE_DIR / f"GENESIS_CONTROL_QWEN3_8B_ATTEMPTS_{DATE_TAG}.json").read_text())["attempts"]
    record_path = EVIDENCE_DIR / f"GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_{DATE_TAG}.json"
    snapshot = EVIDENCE_DIR / f"GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_ATTEMPT4_SNAPSHOT_{DATE_TAG}.json"
    record = json.loads(record_path.read_text())
    harness_text = (REPO_ROOT / "scripts/phase21b_4_20_modal_h100_control.py").read_text()
    digest = re.search(r'VLLM_IMAGE_DIGEST = "(sha256:[0-9a-f]{64})"', harness_text).group(1)
    hard_timeout = int(re.search(r"HARD_TIMEOUT_SECONDS = (\d+)", harness_text).group(1))

    artifact = {
        "evidence_type": "QWEN3_8B_NON_THINKING_V1_IMPLEMENTATION_READINESS_CPU_ONLY", "phase": "21B.4.20",
        "captured_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "no_gpu_used": True, "no_modal_function_called": True, "no_inference_performed": True, "owner_cash_spent_usd": "0", "generated_output_executed": False,
        "approved_configuration": {"runtime_configuration_id": approved["id"], "configuration": approved, "configuration_sha256": rc.configuration_sha256(MODEL_ID),
                                   "source_of_truth": "orca/eval/control_runtime_configuration.py (stdlib only; shipped beside the runner into the container)",
                                   "required_from_attempt": rc.REQUIRED_FROM_ATTEMPT[MODEL_ID],
                                   "pinned_runtime_policy_sha256": rc.PINNED_RUNTIME_POLICY_SHA256, "protected_policy_document": rc.runtime_policy_document(),
                                   "policy_fingerprint_verified_on_import": True, "pinned_configuration_sha256": rc.PINNED_QWEN_CONFIGURATION_SHA256,
                                   "analysis_basis": "GENESIS_QWEN3_8B_RUNTIME_CONFIGURATION_ANALYSIS_V2_CANONICAL_PROMPTS_2026-09-25.json"},
        "request_payload_delta": {
            "smoke_id": "B", "before_qwen_thinking_default": payload_before, "after_qwen_non_thinking_v1": payload_after,
            "delta": {"added_field": "chat_template_kwargs", "value": payload_after["chat_template_kwargs"]},
            "applied_to": "EVERY locked smoke request of Qwen3-8B (A, B and C)",
            "mistral_nemo_payload_has_chat_template_kwargs": "chat_template_kwargs" in others["mistral_nemo"],
            "phi4_payload_has_chat_template_kwargs": "chat_template_kwargs" in others["phi4"],
            "single_builder": "build_chat_payload in the shared runner (the only place a request body is built)"},
        "unchanged": {"model_id": MODEL_ID, "revision": runner.LOCKED["qwen3_8b"]["revision"], "precision": "bfloat16", "quantization": None, "model_substitution": False,
                      "vllm_version": runner.VLLM_VERSION, "container_digest": digest, "gpu": "Modal H100 80GB", "server_extra_args": runner.LOCKED["qwen3_8b"]["extra_args"],
                      "max_model_len": runner.MAX_MODEL_LEN, "sampling": gen_cfg, "smoke_max_tokens": gen_cfg["max_tokens"],
                      "hard_timeout_seconds": hard_timeout, "generated_output_executed": False},
        "canonical_smoke_protocol": {"protocol_sha256": lp.protocol_sha256(), "prompt_sha256": {sid: lp.prompt_sha256(sid) for sid in lp.smoke_ids()},
                                     "prompts_unchanged": True, "source": "orca/eval/locked_smoke_protocol.py"},
        "acceptance_logic": {"authoritative_implementation": "orca.eval.locked_smoke_protocol.acceptance", "runner_duplicate_removed": not hasattr(runner, "_meets_acceptance")},
        "validator_requirements": [
            "Qwen3-8B records whose final attempt number >= 5 must carry runtime_configuration",
            "runtime_configuration.id == qwen3_8b_non_thinking_v1 (missing/other id fails)",
            "chat_template_kwargs must be exactly {\"enable_thinking\": false} (true, absent, or any extra kwarg fails)",
            "a valid runtime attempt must carry the container proof and it must agree with the record: configuration id (declared and applied), kwargs actually sent with every smoke, configuration fingerprint, canonical protocol fingerprint, per-prompt sha256, model id, served model id, revision, precision bfloat16, quantization none, reasoning parser qwen3",
            "controls without an approved configuration (Mistral-Nemo, Phi-4) must carry none",
            "record, container proof and the locally pinned runtime-policy sha256 must all be equal (three-way)",
            "a QUALIFIED record must use the canonical prompts and protocol fingerprint (unchanged rule)"],
        "harness_fail_closed": "cmd_run turns any missing/disagreeing container proof into HARNESS_FAILURE (never a model-runtime result)",
        "historical_attempt_4": {"status": {"technical_serving_status": record["technical_serving_status"], "runtime_qualification_status": record["runtime_qualification_status"]},
                                 "record_sha256": sha(record_path), "byte_identical_snapshot": snapshot.name, "snapshot_sha256": sha(snapshot),
                                 "record_equals_snapshot": record_path.read_bytes() == snapshot.read_bytes(), "raw_log_sha256": record["raw_log_sha256"],
                                 "smoke_outputs_sha256": hashlib.sha256(json.dumps(record["smoke_outputs"], sort_keys=True).encode()).hexdigest(),
                                 "ran_with": "thinking default ON and the earlier drifted prompt wording; never retro-fitted",
                                 "runtime_configuration_field": "absent (not applied retroactively)"},
        "attempt_5_readiness": {
            "attempts_recorded": [a["attempt_number"] for a in attempts], "next_attempt_number": len(attempts) + 1,
            "history_preserved": "attempts 1-4 are never overwritten or renumbered; before attempt 5 writes the control record, the harness snapshots the current record byte-identically (attempt 4 already snapshotted)",
            "financial_gate_unchanged": ["owner billed delta == 0", "credit runway >= $5.00 reserve + worst-case run cost", "maximum authorized run cost <= $1.25 (H100 900 s cap ~= $1.083)",
                                         "zero live Modal resources", "prior settlement gating (attempt 1: strictly validated owner waiver, attempt 1 only; attempt 4: OBSERVED reconciliation artifact)",
                                         "exact model cache verified (pre-cache manifest)"],
            "financial_gates_evaluated_here": False, "note": "the live gate is evaluated by the existing preflight immediately before any future authorized launch; this artifact launches nothing",
            "execution_authorized": False},
        "status_unchanged": {"qwen3_8b": "FAILED", "mistral_nemo": "NOT_TESTED", "phi4": "NOT_TESTED", "capability": "UNPROVEN"},
    }
    OUT.write_text(json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps({"artifact": OUT.name, "next_attempt_number": artifact["attempt_5_readiness"]["next_attempt_number"], "sha256": sha(OUT)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
