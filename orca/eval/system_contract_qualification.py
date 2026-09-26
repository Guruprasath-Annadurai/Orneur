"""
ORNEUR_SYSTEM_CONTRACT_QUALIFICATION -- a NEW category, deliberately separate from RAW_MODEL_RUNTIME_QUALIFICATION.

It replays the three canonical locked-smoke inputs through the ORNEUR Contract Compliance Engine and through the model-independent ContractEnforcedGateway, with a model backend
that EXPLODES if it is ever called. It measures ORNEUR's contract engine, never a model: the historical raw-model results of Qwen3-8B / Mistral-Nemo / Phi-4 are read only for
the "unchanged" proof and are never altered or reinterpreted. The verdict SYSTEM_CONTRACT_QUALIFIED is produced only when the real implementation and validators satisfy all three.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from orca.contracts import ContractEngine, ContractStatus, ContractType, ContractViolationError
from orca.contracts.gateway import ContractEnforcedGateway
from orca.eval import locked_smoke_protocol as lp
from orca.gateway.contracts import InferenceRequest

QUALIFICATION_TYPE = "SYSTEM_CONTRACT_QUALIFICATION"
SUITE = "ORNEUR_SYSTEM_CONTRACT_QUALIFICATION"
EXPECTED = {"A": (ContractType.EXACT_TEXT, "READY"), "B": (ContractType.DETERMINISTIC_MATH, "5"), "C": (ContractType.JSON_LITERAL, '{"status":"ready"}')}


class _Counter:
    def __init__(self):
        self.model_calls = 0
        self.gpu_calls = 0
        self.provider_calls = 0


def _exploding_model_factory(counter: _Counter):
    def exploding_model(_req):
        counter.model_calls += 1
        raise AssertionError("model must not be called for a deterministic contract")
    return exploding_model


class _ExplodingGateway:
    """Stands in for the Model Gateway: any call is a violation (and is counted)."""
    def __init__(self, counter: _Counter):
        self.counter = counter

    async def generate(self, request, allow_experimental=False):
        self.counter.model_calls += 1
        self.counter.gpu_calls += 1
        self.counter.provider_calls += 1
        raise AssertionError("gateway/model must not be called for a deterministic contract")

    async def stream(self, request, allow_experimental=False):
        self.counter.model_calls += 1
        raise AssertionError("gateway/model must not be called for a deterministic contract")
        yield  # pragma: no cover


def run_system_contract_qualification(engine: ContractEngine | None = None) -> dict:
    engine = engine or ContractEngine()
    counter = _Counter()
    exploding = _exploding_model_factory(counter)
    gateway = ContractEnforcedGateway(_ExplodingGateway(counter), engine)
    cases = {}
    for sid in lp.smoke_ids():
        text = lp.messages(sid)[0]["content"]
        want_type, want_out = EXPECTED[sid]
        result = engine.execute(text, exploding)                                              # direct engine path
        req = InferenceRequest(request_id=f"syscontract-{sid}", model_id="orneur-contract-qualification", messages=[{"role": "user", "content": text}])
        try:
            resp = asyncio.run(gateway.generate(req))                                         # model-independent gateway boundary path
        except ContractViolationError:
            resp = None                                                                       # a failed contract is a failed case, never a crash and never a pass
        final = result.final_output
        parsed_ok = None
        if want_type is ContractType.JSON_LITERAL and final is not None:
            try:
                parsed_ok = json.loads(final) == json.loads(want_out)
            except ValueError:
                parsed_ok = False
        passed = bool(result.status is ContractStatus.SATISFIED and result.spec.contract_type is want_type and final == want_out and final is not None
                      and final.encode("utf-8") == want_out.encode("utf-8") and resp is not None and resp.output == want_out and resp.runtime == "orneur-contract-engine"
                      and result.evidence.model_calls == 0 and result.evidence.validator_result == "PASS" and (parsed_ok in (None, True)))
        cases[sid] = {"input": text, "input_sha256": hashlib.sha256(text.encode()).hexdigest(), "expected_contract_type": want_type.value, "detected_contract_type": result.spec.contract_type.value,
                      "expected_output": want_out, "final_output": final, "final_output_byte_equal": final == want_out, "gateway_path_output": None if resp is None else resp.output, "gateway_path_runtime": None if resp is None else resp.runtime,
                      "validator": result.evidence.validator, "validator_result": result.evidence.validator_result, "json_parse_and_value_equal": parsed_ok, "contract_status": result.status.value,
                      "model_calls": result.evidence.model_calls, "evidence": result.evidence.to_dict(), "passed": passed}
    all_ok = all(c["passed"] for c in cases.values()) and counter.model_calls == 0 and counter.gpu_calls == 0 and counter.provider_calls == 0
    return {"qualification_type": QUALIFICATION_TYPE, "suite": SUITE, "cases": cases, "model_calls": counter.model_calls, "gpu_calls": counter.gpu_calls, "provider_calls": counter.provider_calls,
            "all_contracts_satisfied": all_ok, "verdict": "SYSTEM_CONTRACT_QUALIFIED" if all_ok else "SYSTEM_CONTRACT_NOT_QUALIFIED"}


def historical_control_state(evidence_dir: Path) -> dict:
    """Read-only: the immutable raw-model control results and the SHA256 of every control evidence file (Qwen3-8B, Mistral-Nemo, Phi-4)."""
    out, files = {}, {}
    for name, tag in (("Qwen3-8B", "QWEN3_8B"), ("Mistral-Nemo-Instruct-2407", "MISTRAL_NEMO"), ("Phi-4", "PHI4")):
        rec = json.loads((evidence_dir / f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
        acc = {x["smoke_id"]: ("PASS" if x["accepted"] else "FAIL") for x in rec["smoke_acceptance"]}
        out[name] = {"locked_smokes": [acc["A"], acc["B"], acc["C"]], "runtime_qualification_status": rec["runtime_qualification_status"], "RUNTIME_QUALIFIED": rec["runtime_qualification_status"] == "RUNTIME_QUALIFIED",
                     "technical_serving_status": rec["technical_serving_status"], "capability_status": rec["capability_status"], "latest_attempt": rec["attempts"][-1]["attempt_number"]}
        for p in sorted(evidence_dir.glob(f"GENESIS_CONTROL_{tag}_*")):
            files[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    agg = hashlib.sha256(json.dumps(sorted(files.items())).encode()).hexdigest()
    return {"raw_model_results_unchanged_and_separate": out, "control_evidence_file_sha256": files, "control_evidence_aggregate_sha256": agg, "file_count": len(files)}


def build_artifact(evidence_dir: Path) -> dict:
    q = run_system_contract_qualification()
    q.update({"generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "phase": "post-21B.4.20",
              "statement": "SYSTEM_CONTRACT_QUALIFICATION measures the ORNEUR contract engine, NOT a model. RAW_MODEL_RUNTIME_QUALIFICATION of Qwen3-8B, Mistral-Nemo and Phi-4 is unchanged and remains "
                           "RUNTIME_QUALIFIED = false for all three; the two categories must never be conflated.",
              "historical_control_state": historical_control_state(evidence_dir), "no_gpu_used": True, "no_modal_used": True, "no_provider_call": True, "generated_output_executed": False})
    return q
