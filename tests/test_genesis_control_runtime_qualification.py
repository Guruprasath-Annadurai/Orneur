"""Phase 21B.4.20: Genesis CONTROL runtime qualification -- fail-closed gate,
result validator, harness security, and evidence integrity.

CPU-ONLY. No GPU, no provider call, no billing-affecting action. Proves the
rules that make a control's runtime qualification trustworthy:

  A/B  the exact three controls, no substitutions      C  no QUALIFIED without technical+financial PASS
  D/E  financial PASS needs delta == 0; positive => NOT_ACCEPTED
  F    capability stays UNPROVEN    G  benchmark output can't masquerade as runtime evidence
  H    cleanup must be zero-live-resource      I  identity is required
  J    every persisted hash verifies           K  attempt history can't be omitted
  L    zero-cash unavailable => GPU blocked    + harness security (no exec/eval/Sandbox/retry)

Every "synthetic" record lives only in pytest's tmp_path; none is evidence.
"""

import ast
import copy
import hashlib
import importlib.util
import json
import types
from decimal import Decimal
from pathlib import Path

import pytest

from orca.eval import locked_smoke_protocol as locked_protocol
from orca.eval.candidate_registry import CandidateExecutionRegistry, EXPECTED_CONTROL_NAMES
from orca.eval.control_runtime_qualification import (
    compute_smoke_acceptance, smoke_locked_acceptance,
    ATTEMPT_OUTCOMES,
    CAPABILITY_STATUS,
    LOCKED_CONTROL_IDENTITIES,
    REQUIRED_SMOKE_IDS,
    RUNTIME_QUALIFICATION_STATUSES,
    ControlRuntimeError,
    derive_runtime_status,
    financial_gate_decision,
    RECONCILIATION_FIELDS,
    SETTLEMENT_NOT_OBSERVABLE,
    SETTLEMENT_OBSERVED,
    assess_settlement,
    build_financial_reconciliation,
    retry_permitted,
    validate_control_runtime_record,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CANDIDATE_EXECUTION_REGISTRY.json"
EVIDENCE_DIR = REPO_ROOT / "docs/orneur/phase-21/evidence"
HARNESS_PATH = REPO_ROOT / "scripts/phase21b_4_20_control_runtime_qualification.py"
VALIDATOR_PATH = REPO_ROOT / "orca/eval/control_runtime_qualification.py"
MATRIX_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CONTROL_RUNTIME_QUALIFICATION_MATRIX_2026-09-24.md"
INDEX_PATH = EVIDENCE_DIR / "GENESIS_CONTROL_RUNTIME_SHA256_INDEX_2026-09-24.json"

CONTROL_TAGS = {"Qwen3-8B": "QWEN3_8B", "Mistral-Nemo-Instruct-2407": "MISTRAL_NEMO", "Phi-4": "PHI4"}


@pytest.fixture(scope="module")
def registry():
    return CandidateExecutionRegistry.load(REGISTRY_PATH)


def _write(path: Path, data: bytes) -> str:
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _qualified_record(tmp_path: Path, control="Phi-4") -> dict:
    """SYNTHETIC TEST FIXTURE -- a fully-consistent RUNTIME_QUALIFIED record
    with real (tmp) artifacts so every hash verifies. NOT evidence."""
    locked = LOCKED_CONTROL_IDENTITIES[control]
    pre = _write(tmp_path / "pre.json", b'{"synthetic": "preflight"}')
    bef = _write(tmp_path / "before.json", b'{"synthetic": "before"}')
    aft = _write(tmp_path / "after.json", b'{"synthetic": "after"}')
    disc = _write(tmp_path / "discrepancy.json", b'{"synthetic": "discrepancy"}')
    log_sha = _write(tmp_path / "raw.log", b"SYNTHETIC RAW LOG")
    outputs, prompts = [], []
    for sid in REQUIRED_SMOKE_IDS:
        raw = json.dumps({"content": {"A": "\n\nREADY", "B": " 5\n", "C": '\n{"status": "ready"}'}[sid]})     # locked contents, surrounding whitespace only
        outputs.append({"smoke_id": sid, "http_status": 200, "raw_response": raw,
                        "raw_response_sha256": hashlib.sha256(raw.encode()).hexdigest(), "executed": False})
        prompts.append({"smoke_id": sid, "messages": locked_protocol.messages(sid)})
    return {
        "phase": "21B.4.20", "evidence_kind": "RUNTIME_QUALIFICATION_SMOKE", "control_name": control,
        "model_id": locked["model_id"], "model_revision": locked["revision"], "tokenizer_revision": locked["revision"],
        "architecture": "SyntheticArch", "license": "mit", "runtime_name": "vLLM", "runtime_version": "0.0.0-synthetic",
        "container_image": "synthetic:image", "container_digest": "sha256:" + "0" * 64,
        "gpu_provider": "Modal", "gpu_type": "A100-80GB", "gpu_count": 1, "tensor_parallel": 1, "precision": "bfloat16",
        "max_model_len": 4096, "attention_backend": "synthetic", "reasoning_parser": None,
        "chat_template_source": "synthetic", "stop_behavior": "synthetic",
        "started_at_utc": "2000-01-01T00:00:00Z", "finished_at_utc": "2000-01-01T00:10:00Z",
        "cold_start_seconds": 100.0, "load_seconds": 50.0, "peak_gpu_memory_bytes": 1, "steady_gpu_memory_bytes": 1,
        "smoke_prompts": prompts, "smoke_protocol": locked_protocol.protocol_document(), "generation_config": {"temperature": 0}, "smoke_outputs": outputs,
        "latency_seconds": 1.0, "ttft_seconds": 0.1, "generated_tokens": 3, "tokens_per_second": 3.0,
        "technical_serving_status": "QUALIFIED", "financial_preflight_status": "PASSED",
        "financial_acceptance_status": "PASS", "owner_billed_delta_usd": "0",
        "runtime_qualification_status": "RUNTIME_QUALIFIED", "capability_status": "UNPROVEN",
        "cleanup_status": "PASS", "live_resources_after_cleanup": 0,
        "raw_log_artifact": "raw.log", "raw_log_sha256": log_sha, "notes": "synthetic",
        "attempts": [{"attempt_number": 1, "outcome": "TECHNICAL_SUCCESS", "reason": "synthetic", "resource_type": "synthetic",
                      "duration_seconds": 1.0, "owner_billed_delta_usd": "0", "cleanup_result": "PASS"}],
        "identity_verification": {
            "pinned_revision_matches_runtime_artifact": True, "runtime_served_model_matches_pinned_id": True,
            "weight_bytes_observed": locked["expected_weight_bytes"], "no_silent_model_fallback": True,
            "identity_evidence_strength": "synthetic"},
        "financial_evidence": {"preflight_artifact": "pre.json", "preflight_sha256": pre,
                               "billing_before_artifact": "before.json", "billing_before_sha256": bef,
                               "billing_after_artifact": "after.json", "billing_after_sha256": aft},
        "generated_output_executed": False,
        "unobservable_reasons": {"reasoning_parser": "not applicable: non-reasoning model"},
        "financial_reconciliation": _recon(),
        "billing_settlement": {"status": "OBSERVED", "reasons": [], "stop_before_next_control": False},
        "billing_discrepancy_observation": {"artifact": "discrepancy.json", "sha256": disc},
    }


def _recon(**over):
    r = build_financial_reconciliation(
        _summary(), _summary(metered="20.90", credits="-20.90"),
        credit_pool_usd="30.00", reserve_usd="5.00", max_run_cost_usd="1.25")
    r.update(over)
    return r


def _mutated(tmp_path, **changes):
    rec = _qualified_record(tmp_path)
    rec.update(changes)
    return rec


# ══ A/B: locked identities, no substitutions ═════════════════════════════


def test_A_exact_controls_and_pinned_identities_match_the_registry(registry):
    assert set(LOCKED_CONTROL_IDENTITIES) == set(EXPECTED_CONTROL_NAMES) == set(CONTROL_TAGS)
    for control in registry.controls:
        locked = LOCKED_CONTROL_IDENTITIES[control["canonical_candidate_name"]]
        assert control["artifact_repository"] == locked["model_id"]
        assert control["exact_immutable_revision"] == locked["revision"]


def test_B_no_substitution_is_accepted(tmp_path):
    for bad in ("Qwen3-4B", "Qwen3-32B", "Mistral-Small-4", "Mistral-Nemo-Base-2407", "Phi-4-mini", "Phi-3", "GPT-4"):
        with pytest.raises(ControlRuntimeError, match="locked controls"):
            validate_control_runtime_record(_mutated(tmp_path, control_name=bad), evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["model_id"] = "microsoft/Phi-4-mini-instruct"
    with pytest.raises(ControlRuntimeError, match="identity mismatch"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


# ══ C/D/E/§34: RUNTIME_QUALIFIED needs technical PASS + financial PASS ═══


def test_a_fully_consistent_synthetic_record_validates(tmp_path):
    validate_control_runtime_record(_qualified_record(tmp_path), evidence_root=tmp_path)


@pytest.mark.parametrize("changes,match", [
    ({"technical_serving_status": "FAILED"}, "derives|QUALIFIED|model-runtime"),
    ({"technical_serving_status": "INCONCLUSIVE"}, "derives|QUALIFIED"),
    ({"financial_acceptance_status": "FAILED"}, "derives|financial"),
    ({"financial_acceptance_status": "NOT_TESTED"}, "derives|financial"),
    ({"owner_billed_delta_usd": "0.01"}, "positive incremental|disagrees|PASS requires"),
    ({"owner_billed_delta_usd": "3.52"}, "positive incremental|disagrees|PASS requires"),
    ({"cleanup_status": "FAIL"}, "derives|cleanup"),
    ({"live_resources_after_cleanup": 1}, "derives|zero live"),
    ({"financial_preflight_status": "FAILED"}, "PASSED fresh financial preflight"),
    ({"financial_preflight_status": "NOT_PERFORMED"}, "PASSED fresh financial preflight"),
])
def test_C_D_H_qualified_is_rejected_unless_every_gate_passes(tmp_path, changes, match):
    with pytest.raises(ControlRuntimeError, match=match):
        validate_control_runtime_record(_mutated(tmp_path, **changes), evidence_root=tmp_path)


def test_E_positive_billing_means_NOT_ACCEPTED_never_QUALIFIED(tmp_path):
    rec = _qualified_record(tmp_path)
    rec.update(owner_billed_delta_usd="3.52", financial_acceptance_status="FAILED",
               runtime_qualification_status="NOT_ACCEPTED")
    rec["attempts"][0]["owner_billed_delta_usd"] = "3.52"
    rec["financial_reconciliation"]["billing_delta_usd"] = "3.52"
    validate_control_runtime_record(rec, evidence_root=tmp_path)  # honest NOT_ACCEPTED is valid
    assert rec["technical_serving_status"] == "QUALIFIED"  # technically fine...
    rec["runtime_qualification_status"] = "RUNTIME_QUALIFIED"  # ...but can never be labeled qualified
    with pytest.raises(ControlRuntimeError, match="positive incremental owner billing"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


def test_D_financial_PASS_requires_a_delta_of_exactly_zero(tmp_path):
    for delta in ("0.00000001", "0.0001", "-0.01"):
        rec = _qualified_record(tmp_path)
        rec["owner_billed_delta_usd"] = delta
        rec["attempts"][0]["owner_billed_delta_usd"] = delta
        with pytest.raises(ControlRuntimeError):
            validate_control_runtime_record(rec, evidence_root=tmp_path)
    for zero in ("0", "0.0", "0E-8", "0.00000000"):
        rec = _qualified_record(tmp_path)
        rec["owner_billed_delta_usd"] = zero
        rec["attempts"][0]["owner_billed_delta_usd"] = zero
        validate_control_runtime_record(rec, evidence_root=tmp_path)


def test_derive_runtime_status_is_the_only_correct_mapping():
    ok = dict(technical="QUALIFIED", financial_acceptance="PASS", cleanup="PASS", owner_billed_delta_usd="0",
              live_resources_after_cleanup=0)
    assert derive_runtime_status(**ok) == "RUNTIME_QUALIFIED"
    assert derive_runtime_status(**dict(ok, owner_billed_delta_usd="0.01")) == "NOT_ACCEPTED"
    assert derive_runtime_status(**dict(ok, financial_acceptance="FAILED")) == "NOT_ACCEPTED"
    assert derive_runtime_status(**dict(ok, cleanup="FAIL")) == "NOT_ACCEPTED"
    assert derive_runtime_status(**dict(ok, live_resources_after_cleanup=2)) == "NOT_ACCEPTED"
    assert derive_runtime_status(**dict(ok, technical="FAILED")) == "FAILED"
    assert derive_runtime_status(**dict(ok, technical="NOT_TESTED")) == "NOT_TESTED"
    assert derive_runtime_status(**dict(ok, technical="NOT_PROVEN")) == "NOT_COMPLETED"
    assert derive_runtime_status(**dict(ok, technical="BLOCKED_PENDING_ZERO_CASH_RUNWAY")) == "BLOCKED_PENDING_ZERO_CASH_RUNWAY"
    assert derive_runtime_status(**dict(ok, settlement_status="BILLING_SETTLEMENT_NOT_YET_OBSERVABLE")) == "PENDING_SETTLEMENT_OBSERVATION"
    assert derive_runtime_status(**dict(ok, settlement_status="OBSERVED")) == "RUNTIME_QUALIFIED"
    assert derive_runtime_status(**dict(ok, technical="FAILED", settlement_status="BILLING_SETTLEMENT_NOT_YET_OBSERVABLE")) == "FAILED"
    assert derive_runtime_status(**dict(ok, owner_billed_delta_usd="0.01", settlement_status="BILLING_SETTLEMENT_NOT_YET_OBSERVABLE")) == "NOT_ACCEPTED"
    assert set(RUNTIME_QUALIFICATION_STATUSES) == {"RUNTIME_QUALIFIED", "PENDING_SETTLEMENT_OBSERVATION", "NOT_ACCEPTED", "FAILED", "NOT_COMPLETED", "NOT_TESTED", "BLOCKED_PENDING_ZERO_CASH_RUNWAY"}


# ══ F/G: capability stays UNPROVEN; no benchmark masquerading ════════════


def test_F_capability_must_remain_unproven(tmp_path):
    assert CAPABILITY_STATUS == "UNPROVEN"
    for bad in ("STRONG", "FRONTIER", "EVALUATED", "PROVEN", "WEAK", None):
        with pytest.raises(ControlRuntimeError, match="capability_status"):
            validate_control_runtime_record(_mutated(tmp_path, capability_status=bad), evidence_root=tmp_path)


def test_G_benchmark_or_capability_output_cannot_be_labeled_runtime_evidence(tmp_path):
    with pytest.raises(ControlRuntimeError, match="evidence_kind"):
        validate_control_runtime_record(_mutated(tmp_path, evidence_kind="BENCHMARK_RESULT"), evidence_root=tmp_path)
    for key in ("mmlu_score", "humaneval_pass_at_1", "benchmark_results", "accuracy", "gsm8k", "win_rate", "quality_score"):
        rec = _qualified_record(tmp_path)
        rec[key] = 0.5
        with pytest.raises(ControlRuntimeError, match="benchmark/capability"):
            validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["smoke_outputs"][0]["swe_bench_result"] = "x"
    with pytest.raises(ControlRuntimeError, match="benchmark/capability"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


# ══ I/§26: identity is required and must be verified ═════════════════════


@pytest.mark.parametrize("field,value", [
    ("pinned_revision_matches_runtime_artifact", False),
    ("runtime_served_model_matches_pinned_id", False),
    ("no_silent_model_fallback", False),
    ("weight_bytes_observed", 12345),
])
def test_I_runtime_identity_must_match_the_pinned_revision(tmp_path, field, value):
    rec = _qualified_record(tmp_path)
    rec["identity_verification"][field] = value
    with pytest.raises(ControlRuntimeError):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


def test_I_missing_identity_fields_and_wrong_revision_are_rejected(tmp_path):
    rec = _qualified_record(tmp_path)
    del rec["identity_verification"]["weight_bytes_observed"]
    with pytest.raises(ControlRuntimeError, match="identity_verification missing"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["model_revision"] = "0" * 40
    with pytest.raises(ControlRuntimeError, match="identity mismatch"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    del rec["model_id"]
    with pytest.raises(ControlRuntimeError, match="missing required"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


# ══ J: every persisted raw log / evidence hash verifies ══════════════════


def test_J_raw_log_and_evidence_hashes_must_verify(tmp_path):
    rec = _qualified_record(tmp_path)
    (tmp_path / "raw.log").write_bytes(b"TAMPERED")
    with pytest.raises(ControlRuntimeError, match="raw log bytes do not match"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["raw_log_sha256"] = "0" * 64
    with pytest.raises(ControlRuntimeError, match="raw log bytes do not match"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    for missing in (None, "", "not-hex"):
        rec = _qualified_record(tmp_path)
        rec["raw_log_sha256"] = missing
        with pytest.raises(ControlRuntimeError):
            validate_control_runtime_record(rec, evidence_root=tmp_path)
    for art in ("preflight_artifact", "billing_before_artifact", "billing_after_artifact"):
        rec = _qualified_record(tmp_path)
        rec["financial_evidence"][art.replace("artifact", "sha256")] = "0" * 64
        with pytest.raises(ControlRuntimeError, match="hash does not verify"):
            validate_control_runtime_record(rec, evidence_root=tmp_path)
        rec = _qualified_record(tmp_path)
        rec["financial_evidence"][art] = "missing.json"
        with pytest.raises(ControlRuntimeError, match="does not exist"):
            validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["financial_evidence"]["preflight_artifact"] = "../escape.json"
    with pytest.raises(ControlRuntimeError, match="escapes"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["smoke_outputs"][1]["raw_response_sha256"] = "0" * 64
    with pytest.raises(ControlRuntimeError, match="raw_response_sha256 does not verify"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


def test_smoke_outputs_are_complete_successful_and_never_executed(tmp_path):
    rec = _qualified_record(tmp_path)
    rec["smoke_outputs"].pop()
    with pytest.raises(ControlRuntimeError, match="smoke prompts/outputs"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["smoke_outputs"][0]["http_status"] = 500
    with pytest.raises(ControlRuntimeError, match="no successful raw response"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["smoke_outputs"][2]["executed"] = True
    with pytest.raises(ControlRuntimeError, match="executed=False"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["generated_output_executed"] = True
    with pytest.raises(ControlRuntimeError, match="never be executed"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


# ══ K: attempt history cannot be omitted; no retry after positive billing ═


def test_K_attempt_history_cannot_be_omitted_or_reordered(tmp_path):
    rec = _qualified_record(tmp_path)
    rec["attempts"] = []
    with pytest.raises(ControlRuntimeError, match="complete attempt history"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["attempts"][0]["attempt_number"] = 2  # a hidden earlier attempt
    with pytest.raises(ControlRuntimeError, match="gap or reorder"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    del rec["attempts"][0]["reason"]
    with pytest.raises(ControlRuntimeError, match="missing required"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["attempts"][0]["outcome"] = "GREAT_SUCCESS"
    with pytest.raises(ControlRuntimeError, match="unrecognized outcome"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    assert "TECHNICAL_SUCCESS" in ATTEMPT_OUTCOMES


def test_K_a_failed_first_attempt_must_be_reported_alongside_the_success(tmp_path):
    rec = _qualified_record(tmp_path)
    failed = {"attempt_number": 1, "outcome": "HARNESS_FAILURE", "reason": "client parse bug", "resource_type": "synthetic",
              "duration_seconds": 5.0, "owner_billed_delta_usd": "0", "cleanup_result": "PASS"}
    rec["attempts"][0]["attempt_number"] = 2
    rec["attempts"].insert(0, failed)
    validate_control_runtime_record(rec, evidence_root=tmp_path)  # honest two-attempt history is valid


def test_no_attempt_may_follow_a_positive_billing_attempt(tmp_path):
    rec = _qualified_record(tmp_path)
    bad = {"attempt_number": 1, "outcome": "TECHNICAL_SUCCESS", "reason": "x", "resource_type": "synthetic",
           "duration_seconds": 1, "owner_billed_delta_usd": "0.50", "cleanup_result": "PASS"}
    rec["attempts"][0]["attempt_number"] = 2
    rec["attempts"].insert(0, bad)
    rec["owner_billed_delta_usd"] = "0.50"
    with pytest.raises(ControlRuntimeError, match="after a positive-billing attempt"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


def test_retry_permitted_only_for_clean_zero_cost_technical_failures():
    def a(outcome, delta="0", cleanup="PASS"):
        return {"outcome": outcome, "owner_billed_delta_usd": delta, "cleanup_result": cleanup}
    assert retry_permitted([]) is True
    assert retry_permitted([a("HARNESS_FAILURE")]) is True
    assert retry_permitted([a("TECHNICAL_FAILURE")]) is True
    assert retry_permitted([a("TECHNICAL_SUCCESS")]) is False
    assert retry_permitted([a("HARNESS_FAILURE", delta="0.01")]) is False
    assert retry_permitted([a("HARNESS_FAILURE", cleanup="FAIL")]) is False
    assert retry_permitted([a("ABORTED_FINANCIAL_GUARD")]) is False
    assert retry_permitted([a("HARNESS_FAILURE", delta="3.52"), a("HARNESS_FAILURE")]) is False


# ══ H: cleanup must be zero-live-resource ════════════════════════════════


def test_H_cleanup_must_leave_zero_live_resources(tmp_path):
    for count in (1, 3):
        with pytest.raises(ControlRuntimeError):
            validate_control_runtime_record(_mutated(tmp_path, live_resources_after_cleanup=count), evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["attempts"][0]["cleanup_result"] = "FAIL"
    with pytest.raises(ControlRuntimeError):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


# ══ secrets / null-with-reason ═══════════════════════════════════════════


def test_secrets_are_never_persisted(tmp_path):
    for secret in ("hf_" + "a" * 30, "sk-" + "b" * 30, "Bearer " + "c" * 30, "MODAL_TOKEN_SECRET=abc123"):
        rec = _qualified_record(tmp_path)
        rec["notes"] = f"leaked {secret}"
        with pytest.raises(ControlRuntimeError, match="secret"):
            validate_control_runtime_record(rec, evidence_root=tmp_path)


def test_unobservable_metrics_must_be_null_with_a_reason_never_fabricated(tmp_path):
    rec = _qualified_record(tmp_path)
    rec["ttft_seconds"] = None
    with pytest.raises(ControlRuntimeError, match="null without a recorded unobservable reason"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec["unobservable_reasons"]["ttft_seconds"] = "no streamed first token observed"
    validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["started_at_utc"] = None
    with pytest.raises(ControlRuntimeError, match="may not be null"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


# ══ L: zero-cash unavailable => GPU execution blocked ════════════════════


def _summary(metered="20.03", billed="0E-8", credits="-20.03"):
    return {"metered_cost": metered, "billed_cost": billed, "adjustments": {"credits": credits}}


def _gate(summary, **kw):
    args = dict(worst_case_job_cost_usd="1.25", credit_pool_usd="30.00", reserve_usd="5.00")
    args.update(kw)
    return financial_gate_decision(summary, **args)


def test_L_a_healthy_fresh_reading_allows_the_run():
    d = _gate(_summary())
    assert d["allowed"] is True and d["reasons"] == []
    assert d["remaining_credit_usd"].startswith("9.97")


@pytest.mark.parametrize("summary,kwargs,match", [
    (None, {}, "no fresh live billing summary"),
    ({}, {}, "no fresh live billing summary"),  # an empty reading is no reading
    ({"metered_cost": "x", "billed_cost": "0", "adjustments": {"credits": "0"}}, {}, "unreadable"),
    (_summary(billed="0.01"), {}, "billed_cost is already"),
    (_summary(billed="3.52", metered="33.52", credits="-30.00"), {}, "billed_cost is already"),
    (_summary(metered="25.00", credits="-20.03"), {}, "do not cover metered"),
    (_summary(metered="30.00", credits="-30.00"), {}, "no known credit remains"),
    (_summary(metered="27.00", credits="-27.00"), {}, "credit-coverage gate"),
    (_summary(), {"worst_case_job_cost_usd": "4.98"}, "credit-coverage gate"),
    (_summary(), {"worst_case_job_cost_usd": "0"}, "positive estimate"),
    (_summary(), {"prior_positive_billing_seen": True}, "positive owner billing already occurred"),
])
def test_L_zero_cash_not_proven_means_the_GPU_run_is_blocked(summary, kwargs, match):
    d = _gate(summary, **kwargs)
    assert d["allowed"] is False
    assert any(match in r for r in d["reasons"]), d["reasons"]


def test_L_the_gate_never_trusts_a_spend_limit_or_wall_clock_alone():
    # a healthy-looking billing state still blocks if the worst-case cost could exhaust the runway
    d = _gate(_summary(metered="24.50", credits="-24.50"), worst_case_job_cost_usd="1.25")
    assert d["allowed"] is False
    assert "spend_limit" not in json.dumps(d).lower()


def test_blocked_or_untested_records_may_not_contain_a_gpu_attempt(tmp_path):
    rec = _qualified_record(tmp_path)
    rec.update(technical_serving_status="NOT_TESTED", runtime_qualification_status="NOT_TESTED",
               financial_acceptance_status="NOT_TESTED", cleanup_status="NOT_APPLICABLE")
    with pytest.raises(ControlRuntimeError, match="may not contain a GPU attempt"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec.update(technical_serving_status="BLOCKED_PENDING_ZERO_CASH_RUNWAY", runtime_qualification_status="BLOCKED_PENDING_ZERO_CASH_RUNWAY",
               financial_preflight_status="PASSED", attempts=[])
    with pytest.raises(ControlRuntimeError, match="contradicts a PASSED financial preflight"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec["financial_preflight_status"] = "FAILED"
    validate_control_runtime_record(rec, evidence_root=tmp_path)  # a genuinely blocked, never-run control is valid


# ══ persisted evidence for the three controls ════════════════════════════


@pytest.mark.parametrize("control", sorted(CONTROL_TAGS))
def test_persisted_control_records_validate_and_stay_honest(control):
    tag = CONTROL_TAGS[control]
    path = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_2026-09-24.json"
    record = json.loads(path.read_text())
    validate_control_runtime_record(record, evidence_root=EVIDENCE_DIR)
    assert record["control_name"] == control
    assert record["capability_status"] == "UNPROVEN"
    assert record["generated_output_executed"] is False
    assert record["runtime_qualification_status"] in RUNTIME_QUALIFICATION_STATUSES
    if record["runtime_qualification_status"] == "RUNTIME_QUALIFIED":
        assert record["financial_acceptance_status"] == "PASS" and record["owner_billed_delta_usd"] in ("0", "0.0", "0E-8")
    if record["runtime_qualification_status"] == "NOT_TESTED":
        assert record["attempts"] == [] and record["smoke_outputs"] == []
        assert record["technical_serving_status"] == "NOT_TESTED"


@pytest.mark.parametrize("control", sorted(CONTROL_TAGS))
def test_preflight_artifacts_prove_the_gate_was_evaluated_from_live_billing_before_any_gpu(control):
    tag = CONTROL_TAGS[control]
    pre = json.loads((EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_ATTEMPT1_FINANCIAL_PREFLIGHT_ONLY_2026-09-24.json").read_text())
    assert pre["financial_acceptance_rule"].startswith("OWNER_BILLED_DELTA_USD == 0")
    assert pre["billing_summary_live"]["billed_cost"] in ("0E-8", "0", "0.0")
    assert pre["gate_decision"]["allowed"] is True
    assert pre["gpu_execution_allowed"] is False  # preflight-only: no GPU was authorized by this artifact
    assert pre["hard_runtime_timeout_seconds"] == 1200 and pre["safety_reserve_usd"] == "5.00"
    assert pre["authorization_basis"]
    assert "billing_summary_live" in pre and pre["credit_pool_provenance"]


def test_control_registry_state_is_unchanged(registry):
    for control in registry.controls:
        assert control["runtime_qualification_status"] == "NOT_TESTED"
        assert control["runtime_preflight_status"] == "READY"
        assert control["control_admission_status"] == "ADMITTED"
        assert control["runtime_smoke_eligibility"] == "ELIGIBLE"


def test_regression_lock_other_candidates_and_program_state_unchanged(registry):
    mistral_small = registry.find_deployable("Mistral Small 4")
    assert mistral_small["production_serving_status"] == "QUALIFIED"
    glm = registry.find_deployable("GLM-5.3-Flash")
    assert glm["financial_acceptance_status"] == "ZERO_OWNER_CASH_FAILED"
    assert glm["production_serving_status"] == "TECHNICALLY_SUCCEEDED_FINANCIAL_GATE_FAILED"
    qwen27 = registry.find_deployable("Qwen3.8-27B")
    assert qwen27["load_compatibility_status"] == "QUALIFIED" and qwen27["production_serving_status"] == "NOT_TESTED"
    flash = registry.find_deployable("Qwen3.8-Flash-Next")
    assert flash["license_status"] == "LICENSE_REVIEW_REQUIRED" and flash["runtime_smoke_eligibility"] == "BLOCKED"
    for entry in registry.deployable_candidates:
        assert entry["capability_status"] == "UNPROVEN"
    for ref in registry.frontier_references:
        assert ref["access_preflight_status"] == "UNQUALIFIED"


# ══ security: the harness never executes generated output ════════════════


def _harness_tree():
    return ast.parse(HARNESS_PATH.read_text())


def test_harness_never_evals_execs_compiles_or_shells_out():
    tree = _harness_tree()
    banned_calls = {"eval", "exec", "compile", "__import__", "system", "popen", "getoutput", "check_call"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            assert name not in banned_calls, f"banned call {name!r} at line {node.lineno}"
            for kw in node.keywords:
                assert not (kw.arg == "shell" and getattr(kw.value, "value", False) is True), f"shell=True at line {node.lineno}"
    text = HARNESS_PATH.read_text()
    for banned in ("modal.Sandbox", "Sandbox.create", "os.system(", "shell=True", "importlib.import_module(",
                   "chat.completions.create(", "requests.post(", "openai.OpenAI(", "anthropic"):
        assert banned not in text, banned


def test_no_model_output_reaches_any_subprocess_call():
    """Every subprocess call's arguments may only reference constants or the
    server argv builder -- never the smoke results / responses."""
    tree = _harness_tree()
    forbidden_names = {"entry", "smoke", "outputs", "content", "reasoning", "parsed", "msg", "body", "raw", "chunk", "result_text"}
    checked = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("run", "Popen"):
            base = node.func.value
            if isinstance(base, ast.Name) and base.id in ("sp", "subprocess"):
                checked += 1
                names = {n.id for arg in node.args for n in ast.walk(arg) if isinstance(n, ast.Name)}
                assert not (names & forbidden_names), f"model-derived name in subprocess call at line {node.lineno}: {names & forbidden_names}"
    assert checked >= 4  # nvidia-smi, pgrep, the vLLM server, and the modal CLI wrapper are all covered


def test_harness_uses_a_plain_function_not_a_sandbox_and_polls_billing_live():
    text = HARNESS_PATH.read_text()
    assert "@app.function(" in text and "serve_and_smoke.spawn(" in text
    assert "except (TimeoutError, modal.exception.TimeoutError)" in text  # Modal 1.5.5 get(timeout=) raises the builtin; catch both
    assert "call.cancel(terminate_containers=True)" in text
    for guard in ("billed_cost rose", "exceeds worst-case cap", "projected runway exhausted"):
        assert guard in text


def test_financial_gate_runs_before_any_gpu_allocation_and_blocks_retry_after_positive_billing():
    text = HARNESS_PATH.read_text()
    gate = text.index("financial_gate_decision(\n        before")
    launch = text.index("with app.run():")
    assert gate < launch, "the financial gate must be evaluated before the ephemeral app (GPU) is started"
    assert "prior_positive_billing_seen=any_positive_billing_seen()" in text
    assert "FINANCIAL GATE BLOCKED -- NO GPU STARTED" in text
    assert "retry" not in text.split("def run_control")[1].split("def build_record")[0].lower().replace("never retries", "")  # no retry loop in the run path


def test_harness_delta_rule_is_strict():
    text = HARNESS_PATH.read_text()
    assert "delta = peak_billed - billed_before" in text  # any observed positive billed reading fails acceptance
    assert "billed_after - billed_before" in text


def test_harness_imports_module_level_only_stdlib_and_modal():
    tree = _harness_tree()
    roots = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots <= {"__future__", "argparse", "hashlib", "json", "re", "subprocess", "sys", "time", "datetime", "decimal", "pathlib", "modal"}


def test_validator_module_has_no_execution_or_network_code():
    text = VALIDATOR_PATH.read_text()
    for banned in ("subprocess", "requests", "urllib", "socket", "eval(", "exec(", "modal", "gpu=", "from_pretrained("):
        assert banned not in text, banned


def test_harness_module_imports_without_side_effects_and_pins_the_runtime():
    pytest.importorskip("modal", reason="the Modal SDK is a harness-only dependency, not in the deterministic CI image; the AST tests still cover the harness source")
    spec = importlib.util.spec_from_file_location("p21b420_harness", HARNESS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # defines the Modal app/function objects only; starts nothing
    assert mod.VLLM_IMAGE_DIGEST.startswith("sha256:") and len(mod.VLLM_IMAGE_DIGEST) == 71
    assert mod.HARD_CEILING_SECONDS == 1200 and mod.RESERVE_USD == "5.00"
    assert set(mod.CONTROLS) == {"qwen3_8b", "mistral_nemo", "phi4"}
    assert {c["control_name"] for c in mod.CONTROLS.values()} == set(EXPECTED_CONTROL_NAMES)
    assert [s["smoke_id"] for s in mod.SMOKES] == ["A", "B", "C"]
    assert mod.CONTROLS["qwen3_8b"]["reasoning_parser"] == "qwen3"
    assert mod.CONTROLS["mistral_nemo"]["extra_args"][:2] == ["--tokenizer-mode", "hf"]
    assert not mod.any_positive_billing_seen()  # nothing was executed, so no positive billing exists


# ══ artifacts, matrix, hash index ════════════════════════════════════════


def test_matrix_states_the_true_status_and_program_state():
    text = MATRIX_PATH.read_text()
    for name in ("Qwen3-8B", "Mistral-Nemo-Instruct-2407", "Phi-4"):
        assert name in text
    assert "NOT_TESTED" in text
    assert "UNPROVEN" in text
    assert "PHASE 21C: NOT AUTHORIZED" in text and "GENESIS FOUNDATION: NOT SELECTED" in text


def test_runtime_sha256_index_hashes_exactly():
    index = json.loads(INDEX_PATH.read_text())
    assert index["entries"]
    for entry in index["entries"]:
        path = REPO_ROOT / entry["path"]
        assert path.is_file(), entry["path"]
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["path"]
        assert len(data) == entry["size_bytes"], entry["path"]


# ══ financial patch: owner-payable gate AND credit-coverage gate ═══════════


def test_reconciliation_keeps_billed_metered_and_credit_figures_separate():
    r = _recon()
    assert r["billing_baseline_usd"] == "0E-8" and r["billing_delta_usd"] == "0E-8"
    assert Decimal(r["metered_delta_usd"]) == Decimal("0.87")
    assert Decimal(r["credits_applied_postrun_usd"]) - Decimal(r["credits_applied_baseline_usd"]) == Decimal("0.87")
    assert Decimal(r["derived_credit_remaining_before_usd"]) == Decimal("9.97")
    assert Decimal(r["derived_credit_remaining_after_usd"]) == Decimal("9.10")
    assert r["reserve_usd"] == "5.00" and r["maximum_authorized_run_cost_usd"] == "1.25"
    assert all(k in r for k in RECONCILIATION_FIELDS)


def test_reconciliation_nulls_carry_a_reason():
    r = build_financial_reconciliation(_summary(), None, credit_pool_usd="30", reserve_usd="5", max_run_cost_usd="1.25")
    assert r["metered_postrun_usd"] is None and r["null_reasons"]["metered_postrun_usd"]
    assert r["billing_delta_usd"] is None and r["null_reasons"]["billing_delta_usd"]


def test_reconciliation_uses_the_peak_billed_reading():
    r = build_financial_reconciliation(_summary(), _summary(), credit_pool_usd="30", reserve_usd="5",
                                       max_run_cost_usd="1.25", peak_billed_usd="0.01")
    assert Decimal(r["billing_delta_usd"]) == Decimal("0.01")


def test_gate_allows_exact_equality_but_never_less_than_reserve_plus_max_cost():
    # remaining 6.25 == reserve 5 + 1.25
    assert _gate(_summary(metered="23.75", credits="-23.75"))["allowed"] is True
    d = _gate(_summary(metered="23.76", credits="-23.76"))
    assert d["allowed"] is False and any("credit-coverage gate" in x for x in d["reasons"])


def test_gate_refuses_a_worst_case_above_the_authorized_maximum():
    d = _gate(_summary(metered="1", credits="-1"), worst_case_job_cost_usd="1.26")
    assert d["allowed"] is False and any("maximum authorized run cost" in x for x in d["reasons"])


def test_gate_blocks_the_next_control_when_settlement_is_unresolved():
    d = _gate(_summary(), prior_settlement_unresolved=True)
    assert d["allowed"] is False and any(SETTLEMENT_NOT_OBSERVABLE in x for x in d["reasons"])


def _settle(**over):
    return assess_settlement(_recon(**over), run_report_metered_usd="0.87")


def test_settlement_observed_only_when_usage_visible_credits_cover_and_billed_flat():
    assert _settle()["status"] == SETTLEMENT_OBSERVED


@pytest.mark.parametrize("over,frag", [
    ({"metered_delta_usd": "0E-8"}, "not yet visible in the account totals"),
    ({"credits_applied_postrun_usd": "20.03"}, "credit coverage not confirmed"),
    ({"billing_delta_usd": "0.01"}, "owner-payable"),
    ({"derived_credit_remaining_after_usd": "4.99"}, "below the reserve"),
    ({"metered_delta_usd": "1.30", "credits_applied_postrun_usd": "21.33"}, "exceeds the maximum"),
])
def test_settlement_is_not_claimed_without_evidence(over, frag):
    r = assess_settlement(_recon(**over), run_report_metered_usd=None)
    assert r["status"] == SETTLEMENT_NOT_OBSERVABLE and r["stop_before_next_control"] is True
    assert any(frag in x for x in r["reasons"])


def test_a_report_row_alone_is_not_settlement_without_account_total_growth_and_credit_coverage():
    r = assess_settlement(_recon(metered_delta_usd="0E-8", credits_applied_postrun_usd="20.03"), run_report_metered_usd="0.87")
    assert r["status"] == SETTLEMENT_NOT_OBSERVABLE and any("not yet visible in the account totals" in m for m in r["reasons"])


def test_growth_without_an_attributable_itemized_row_is_not_settlement():
    r = assess_settlement(_recon(), run_report_metered_usd="0")
    assert r["status"] == SETTLEMENT_NOT_OBSERVABLE and any("cannot be attributed" in m for m in r["reasons"])


def test_qualified_requires_reconciliation_settlement_and_discrepancy_reference(tmp_path):
    for key, frag in (("financial_reconciliation", "financial_reconciliation"), ("billing_settlement", "billing_settlement"),
                      ("billing_discrepancy_observation", "discrepancy")):
        rec = _qualified_record(tmp_path)
        del rec[key]
        with pytest.raises(ControlRuntimeError, match=frag):
            validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["billing_settlement"] = {"status": SETTLEMENT_NOT_OBSERVABLE, "reasons": ["x"]}
    with pytest.raises(ControlRuntimeError, match="observed|PENDING_SETTLEMENT_OBSERVATION"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec["runtime_qualification_status"] = "PENDING_SETTLEMENT_OBSERVATION"       # the honest label for the same evidence
    validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["billing_discrepancy_observation"]["sha256"] = "0" * 64
    with pytest.raises(ControlRuntimeError, match="hash"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["financial_reconciliation"]["billing_delta_usd"] = "0.01"
    with pytest.raises(ControlRuntimeError, match="disagrees"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["financial_reconciliation"]["metered_postrun_usd"] = None
    with pytest.raises(ControlRuntimeError, match="without a recorded reason"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


# ══ audit patch: attempt result != model-runtime result ════════════════════


def _failed_attempt(outcome, **extra):
    a = {"attempt_number": 1, "outcome": outcome, "reason": "synthetic", "resource_type": "synthetic", "duration_seconds": 34.6,
         "owner_billed_delta_usd": "0", "cleanup_result": "PASS", "billing_settlement_status": SETTLEMENT_NOT_OBSERVABLE}
    a.update(extra)
    return a


def _no_success_record(tmp_path, attempt, technical, runtime):
    rec = _qualified_record(tmp_path)
    rec.update(technical_serving_status=technical, runtime_qualification_status=runtime, smoke_outputs=[],
               attempts=[attempt], raw_log_artifact=None, raw_log_sha256=None)
    rec["billing_settlement"] = {"status": SETTLEMENT_NOT_OBSERVABLE, "reasons": ["x"]}
    return rec


def test_a_harness_failure_leaves_runtime_compatibility_UNPROVEN_not_model_FAILED(tmp_path):
    a = _failed_attempt("HARNESS_FAILURE", failure_domain="HARNESS", valid_runtime_attempt=False)
    validate_control_runtime_record(_no_success_record(tmp_path, a, "NOT_PROVEN", "NOT_COMPLETED"), evidence_root=tmp_path)
    with pytest.raises(ControlRuntimeError, match="cannot become a model-runtime FAILED"):
        validate_control_runtime_record(_no_success_record(tmp_path, a, "FAILED", "FAILED"), evidence_root=tmp_path)


def test_harness_and_guard_attempts_force_NOT_PROVEN(tmp_path):
    for outcome, dom in (("HARNESS_FAILURE", "HARNESS"), ("ABORTED_FINANCIAL_GUARD", "FINANCIAL_GUARD")):
        a = _failed_attempt(outcome, failure_domain=dom, valid_runtime_attempt=False)
        with pytest.raises(ControlRuntimeError, match="must be NOT_PROVEN"):
            validate_control_runtime_record(_no_success_record(tmp_path, a, "INCONCLUSIVE", "FAILED"), evidence_root=tmp_path)


def test_a_model_runtime_FAILED_requires_an_actual_valid_runtime_attempt(tmp_path):
    bad = _failed_attempt("TECHNICAL_FAILURE", failure_domain="MODEL_RUNTIME")
    with pytest.raises(ControlRuntimeError, match="valid runtime attempt"):
        validate_control_runtime_record(_no_success_record(tmp_path, bad, "FAILED", "FAILED"), evidence_root=tmp_path)
    bad2 = _failed_attempt("TECHNICAL_FAILURE", failure_domain="MODEL_RUNTIME", valid_runtime_attempt=False)
    with pytest.raises(ControlRuntimeError, match="valid runtime attempt"):
        validate_control_runtime_record(_no_success_record(tmp_path, bad2, "FAILED", "FAILED"), evidence_root=tmp_path)
    ok = _failed_attempt("TECHNICAL_FAILURE", failure_domain="MODEL_RUNTIME", valid_runtime_attempt=True)
    validate_control_runtime_record(_no_success_record(tmp_path, ok, "FAILED", "FAILED"), evidence_root=tmp_path)


def test_failure_domain_must_agree_with_the_outcome(tmp_path):
    a = _failed_attempt("HARNESS_FAILURE", failure_domain="MODEL_RUNTIME", valid_runtime_attempt=True)
    with pytest.raises(ControlRuntimeError, match="contradicts outcome"):
        validate_control_runtime_record(_no_success_record(tmp_path, a, "NOT_PROVEN", "NOT_COMPLETED"), evidence_root=tmp_path)


def test_a_later_attempt_keeps_the_earlier_harness_failure_in_the_history(tmp_path):
    first = _failed_attempt("HARNESS_FAILURE", failure_domain="HARNESS", valid_runtime_attempt=False)
    rec = _qualified_record(tmp_path)
    second = dict(rec["attempts"][0], attempt_number=2)
    rec["attempts"] = [first, second]
    validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec["attempts"] = [second]
    with pytest.raises(ControlRuntimeError, match="gap or reorder"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


# ══ audit patch: cost-free harness coverage WITHOUT the Modal SDK ══════════
# The deterministic CI image does not install `modal`. These tests load the real
# harness source against a recording STAND-IN for the SDK, so module syntax,
# constants, decorator arguments, gate wiring and the read-only reconcile path are
# exercised in CI. They do NOT test real Modal SDK behaviour (see the matrix,
# "Environment-only behaviour"): FunctionCall.get()/cancel semantics, image build,
# GPU scheduling, container lifecycle and the billing CLI are environment-only.

import re
import sys
import types


def _load_harness_with_stub_modal(monkeypatch, name="p21b420_harness_stub"):
    calls = {"function_kwargs": [], "image_from_registry": []}

    class _Image:
        @classmethod
        def from_registry(cls, ref, **kw):
            calls["image_from_registry"].append((ref, kw))
            return cls()

        def entrypoint(self, _cmd):
            return self

    class _App:
        def __init__(self, app_name):
            self.name = app_name

        def function(self, **kw):
            calls["function_kwargs"].append(kw)
            return lambda fn: fn

    stub = types.ModuleType("modal")
    stub.Image, stub.App = _Image, _App
    stub.exception = types.SimpleNamespace(TimeoutError=type("TimeoutError", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "modal", stub)
    spec = importlib.util.spec_from_file_location(name, HARNESS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, calls


def test_harness_loads_against_a_stub_sdk_and_pins_image_gpu_and_ceiling(monkeypatch):
    mod, calls = _load_harness_with_stub_modal(monkeypatch)
    assert calls["image_from_registry"][0][0] == f"vllm/vllm-openai@{mod.VLLM_IMAGE_DIGEST}"
    (fn_kwargs,) = calls["function_kwargs"]
    assert fn_kwargs["gpu"] == "A100-80GB:1" and fn_kwargs["timeout"] == 1200
    assert mod.app.name == "orneur-p21b420-control-runtime-qualification"
    assert mod.MAX_MODEL_LEN == 4096 and mod.COST_MARGIN == mod.Decimal("1.5")
    assert mod.worst_case_cost(mod.Decimal("2.5")) == mod.Decimal("1.25")


def test_cli_declares_exactly_the_four_modes_and_the_three_controls():
    tree = _harness_tree()
    choices = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_argument":
            for kw in node.keywords:
                if kw.arg == "choices" and isinstance(kw.value, ast.Tuple):
                    choices.append([e.value for e in kw.value.elts])
    assert ["preflight", "run", "record-not-tested", "reconcile"] in choices


def _func(tree, name):
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def _called_names(fn):
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            out.append(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return out


def test_run_control_wires_the_gate_with_settlement_and_positive_billing_inputs_and_the_validator():
    fn = _func(_harness_tree(), "run_control")
    gate = next(n for n in ast.walk(fn) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "financial_gate_decision")
    kws = {k.arg for k in gate.keywords}
    assert {"prior_positive_billing_seen", "prior_settlement_unresolved", "worst_case_job_cost_usd", "credit_pool_usd", "reserve_usd"} <= kws
    names = _called_names(fn)
    assert "validate_control_runtime_record" in names and "build_financial_reconciliation" in names and "assess_settlement" in names
    assert "write_not_tested" not in names


def test_reconcile_mode_is_read_only_and_can_never_start_a_resource():
    fn = _func(_harness_tree(), "reconcile_attempt")
    names = _called_names(fn)
    for forbidden in ("run", "spawn", "remote", "map", "cancel", "deploy"):
        assert forbidden not in names, forbidden
    text = ast.unparse(fn)
    assert "app.run" not in text and "serve_and_smoke" not in text
    assert "billing" in text and "assess_settlement" in text


def test_harness_writes_no_launch_when_no_gpu_authorized_for_reconcile_or_record_modes():
    main = ast.unparse(_func(_harness_tree(), "main"))
    assert "reconcile_attempt" in main and "write_not_tested" in main and "run_control" in main


def test_a_prior_attempt_blocks_the_next_launch_until_reconciliation_observes_it(monkeypatch, tmp_path):
    mod, _ = _load_harness_with_stub_modal(monkeypatch, "p21b420_harness_stub2")
    monkeypatch.setattr(mod, "EVIDENCE_DIR", tmp_path)
    attempt = {"attempt_number": 1, "billing_settlement_status": SETTLEMENT_NOT_OBSERVABLE}
    (tmp_path / f"GENESIS_CONTROL_QWEN3_8B_ATTEMPTS_{mod.DATE_TAG}.json").write_text(json.dumps({"attempts": [attempt]}))
    assert mod.any_unresolved_settlement() is True
    art = tmp_path / f"GENESIS_CONTROL_QWEN3_8B_ATTEMPT1_SETTLEMENT_RECONCILIATION_20260924T000000Z.json"
    art.write_text(json.dumps({"attempt_number": 1, "settlement": {"status": SETTLEMENT_NOT_OBSERVABLE}, "live_resources": 0,
                               "owner_billed_delta_usd": "0"}))
    assert mod.any_unresolved_settlement() is True
    art.write_text(json.dumps({"attempt_number": 1, "settlement": {"status": SETTLEMENT_OBSERVED}, "live_resources": 0,
                               "owner_billed_delta_usd": "0"}))
    assert mod.any_unresolved_settlement() is False
    art.write_text(json.dumps({"attempt_number": 1, "settlement": {"status": SETTLEMENT_OBSERVED}, "live_resources": 1,
                               "owner_billed_delta_usd": "0"}))
    assert mod.any_unresolved_settlement() is True  # live resources still present
    art.write_text(json.dumps({"attempt_number": 1, "settlement": {"status": SETTLEMENT_OBSERVED}, "live_resources": 0,
                               "owner_billed_delta_usd": "0.01"}))
    assert mod.any_unresolved_settlement() is True  # a positive payable amount never resolves


def test_persisted_qwen_history_keeps_modal_attempt_1_unchanged_and_adds_the_blocked_lightning_attempt():
    rec = json.loads((EVIDENCE_DIR / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
    a, b, c, d, e = rec["attempts"]
    assert e["attempt_number"] == 5 and e["provider"] == "Modal" and e["outcome"] == "TECHNICAL_FAILURE" and e["valid_runtime_attempt"] is True
    assert d["provider"] == "Modal" and d["attempt_number"] == 4 and d["outcome"] == "TECHNICAL_FAILURE" and d["valid_runtime_attempt"] is True
    assert d["original_classification"]["outcome"] == "TECHNICAL_SUCCESS"      # audit reclassification (locked Smoke B) keeps the original judgement
    assert a["outcome"] == "HARNESS_FAILURE" and a["status"] == "HARNESS_FAILURE" and a["failure_domain"] == "HARNESS"
    assert a["valid_runtime_attempt"] is False and a["duration_seconds"] == 34.6
    assert a["owner_billed_delta_usd"] == "0E-8" and a["cleanup_result"] == "PASS"
    assert a["billing_settlement_status"] == SETTLEMENT_NOT_OBSERVABLE
    assert a["annotation"]["pre_annotation_attempts_file_sha256"] == "eaa18cb6ce2718bc7c510d4c4de533b202694e5c04453a72989497410a8de365"
    assert b["provider"] == "Lightning AI" and b["outcome"] == "BLOCKED_NO_GPU" and b["failure_domain"] == "NONE"
    assert b["valid_runtime_attempt"] is False and b["credits_consumed"] in ("0E-7", "0") and "verified payment method" in b["reason"]
    assert c["provider"] == "razorBridge" and c["outcome"] == "BLOCKED_NO_GPU" and c["credits_consumed"] == "0" and c["valid_runtime_attempt"] is False
    assert rec["technical_serving_status"] == "FAILED" and rec["runtime_qualification_status"] == "FAILED"
    assert rec["capability_status"] == "UNPROVEN" and len(rec["smoke_outputs"]) == 3


def test_the_matrix_records_what_ci_cannot_test_about_live_modal():
    text = MATRIX_PATH.read_text()
    assert "Environment-only behaviour" in text
    for needle in ("FunctionCall.get", "cancel", "GPU scheduling", "billing CLI"):
        assert needle in text


def test_qwen_attempt_1_execution_attribution_is_unresolved_and_keeps_the_gate_closed():
    art = json.loads((EVIDENCE_DIR / "GENESIS_CONTROL_QWEN3_8B_ATTEMPT1_EXECUTION_ATTRIBUTION_2026-09-24.json").read_text())
    assert art["read_only"] is True and art["no_gpu_started"] is True
    assert art["classification"].startswith("C. EXECUTION_ATTRIBUTION_UNRESOLVED")
    assert art["qwen_retry_eligible"] is False and art["gate"] == "CLOSED"
    assert art["true_settled_cost"].startswith("unconfirmed")
    assert art["statuses_unchanged"] == {"technical_serving_status": "NOT_PROVEN", "runtime_qualification_status": "NOT_COMPLETED",
                                         "capability_status": "UNPROVEN"}
    assert art["what_the_evidence_cannot_show"] and "created_by" not in json.dumps(art).replace('"created_by": "[redacted]"', "")


def test_provider_migration_artifact_preserves_modal_evidence_and_records_that_no_lightning_gpu_ran():
    art = json.loads((EVIDENCE_DIR / "GENESIS_CONTROL_PROVIDER_MIGRATION_MODAL_TO_LIGHTNING_2026-09-24.json").read_text())
    assert art["provider_from"] == "Modal" and art["provider_to"] == "Lightning AI"
    q = art["modal_qwen_attempt_1"]
    assert q["outcome"] == "HARNESS_FAILURE" and q["valid_runtime_attempt"] is False
    assert q["technical_serving_status"] == "NOT_PROVEN" and q["runtime_qualification_status"] == "NOT_COMPLETED"
    for name, digest in q["evidence"].items():  # the preserved Modal evidence must still hash to what the migration recorded
        assert hashlib.sha256((EVIDENCE_DIR / name).read_bytes()).hexdigest() == digest, name
    assert art["gpu_started"] is False and art["live_account_verification"]["status"].startswith("PERFORMED_AFTER_THIS_ARTIFACT")
    assert art["update_2026-09-24T15:05Z"]["gpu_started"] is False and art["update_2026-09-24T15:05Z"]["credits_unchanged"]
    assert art["hard_financial_rules"]["owner_cash"] == "INR 0" and art["capability_status"] == "UNPROVEN"
    assert art["locked_controls_in_order"] == ["Qwen3-8B", "Mistral-Nemo-Instruct-2407", "Phi-4"]
    assert art["cost_envelope_credits"]["planned_per_control_credits"] < art["cost_envelope_credits"]["per_attempt_stop_threshold_credits"]


# ══ Lightning AI migration: gate, financial validator, runner parity, static safety ══

from orca.eval.control_runtime_qualification import (  # noqa: E402
    LIGHTNING_EXPECTED_USERNAME, LIGHTNING_FINANCIAL_REQUIRED, LIGHTNING_PROVIDER, lightning_gate_decision,
)

LIGHTNING_RUNNER = REPO_ROOT / "scripts/phase21b_4_20_lightning_runner.py"
LIGHTNING_CONTROL = REPO_ROOT / "scripts/phase21b_4_20_lightning_control.py"


def _lstate(**over):
    s = {"username": LIGHTNING_EXPECTED_USERNAME, "plan": "Free", "payment_method_present": False, "credits_available": "4.98",
         "balance_limit": "0.0", "live_gpu_machines": 0,
         "machine": {"enabled": True, "tier_restricted": False, "out_of_capacity": False}}
    s.update(over)
    return s


def _lgate(state=None, **kw):
    args = dict(machine_rate_credits_per_hour="3.54", hard_runtime_cap_seconds=900)
    args.update(kw)
    return lightning_gate_decision(_lstate() if state is None else state, **args)


def test_lightning_gate_allows_the_observed_account_and_bounds_the_cost():
    d = _lgate()
    assert d["allowed"] is True and Decimal(d["worst_case_credits"]) == Decimal("0.885")


@pytest.mark.parametrize("over,frag", [
    ({"username": "annaduraiguruprasath7"}, "not the verified account"),
    ({"plan": "Pro"}, "not FREE"),
    ({"payment_method_present": True}, "payment method"),
    ({"payment_method_present": None}, "payment method"),
    ({"balance_limit": "-5"}, "balance_limit"),
    ({"credits_available": "1.50"}, "reserve"),
    ({"live_gpu_machines": 1}, "already running"),
    ({"live_gpu_machines": None}, "already running"),
    ({"machine": {"enabled": True, "tier_restricted": True, "out_of_capacity": False}}, "tier-restricted"),
    ({"machine": {"enabled": False, "tier_restricted": False, "out_of_capacity": False}}, "not enabled"),
    ({"machine": {"enabled": True, "tier_restricted": False, "out_of_capacity": True}}, "out of capacity"),
])
def test_lightning_gate_blocks_every_unsafe_state(over, frag):
    d = _lgate(_lstate(**over))
    assert d["allowed"] is False and any(frag in r for r in d["reasons"]), d["reasons"]


def test_lightning_gate_enforces_the_per_attempt_cap_and_never_allows_a_missing_state():
    assert _lgate(hard_runtime_cap_seconds=1200)["allowed"] is False  # 3.54 x 1200/3600 = 1.18 > 1.00
    assert lightning_gate_decision(None, machine_rate_credits_per_hour="3.54", hard_runtime_cap_seconds=900)["allowed"] is False
    assert _lgate(prior_positive_owner_charge=True)["allowed"] is False
    assert _lgate(_lstate(credits_available="1.885"))["allowed"] is True   # exactly worst + reserve
    assert _lgate(_lstate(credits_available="1.884"))["allowed"] is False


def _lightning_record(tmp_path, **fin_over):
    rec = _qualified_record(tmp_path)
    pre = _write(tmp_path / "lpre.json", b'{"lightning": "pre"}')
    bef = _write(tmp_path / "lbefore.json", b'{"lightning": "before"}')
    aft = _write(tmp_path / "lafter.json", b'{"lightning": "after"}')
    fin = {"plan": "FREE", "payment_method_present": False, "machine_slug": "lit-l40s-1", "machine_rate_credits_per_hour": "3.54",
           "gpu_runtime_seconds": 600.0, "credits_before": "4.98", "credits_after": "4.40", "credit_delta": "0.58",
           "expected_credit_cost": "0.5900", "observed_credit_cost": "0.58", "owner_charge_before_usd": "0", "owner_charge_after_usd": "0",
           "owner_cash_delta_usd": "0", "balance_limit": "0.0", "credit_meter_stopped": True, "hard_runtime_cap_seconds": 900,
           "artifacts": {"preflight": {"artifact": "lpre.json", "sha256": pre}, "credits_before": {"artifact": "lbefore.json", "sha256": bef},
                         "credits_after": {"artifact": "lafter.json", "sha256": aft}}}
    fin.update(fin_over)
    for k in ("financial_reconciliation", "billing_settlement", "billing_discrepancy_observation"):
        rec.pop(k, None)   # Modal-only evidence is not required for a Lightning result
    rec.update(gpu_provider=LIGHTNING_PROVIDER, lightning_financial=fin, financial_evidence={"provider": LIGHTNING_PROVIDER})
    return rec


def test_a_consistent_lightning_record_validates_and_modal_only_evidence_is_not_required(tmp_path):
    validate_control_runtime_record(_lightning_record(tmp_path), evidence_root=tmp_path)


def test_a_lightning_record_keeps_the_modal_attempt_history(tmp_path):
    rec = _lightning_record(tmp_path)
    modal_attempt = _failed_attempt("HARNESS_FAILURE", failure_domain="HARNESS", valid_runtime_attempt=False, provider="Modal")
    rec["attempts"] = [modal_attempt, dict(rec["attempts"][0], attempt_number=2, provider=LIGHTNING_PROVIDER)]
    validate_control_runtime_record(rec, evidence_root=tmp_path)


@pytest.mark.parametrize("over,frag", [
    ({"payment_method_present": True}, "payment_method_present"),
    ({"credits_after": "-0.10", "credit_delta": "5.08"}, "negative"),
    ({"credit_delta": "0.10"}, "credit_delta must equal"),
    ({"owner_charge_after_usd": "0.50", "owner_cash_delta_usd": "0.50"}, "owner_billed_delta_usd disagrees"),
    ({"owner_cash_delta_usd": "0.50"}, "owner_cash_delta_usd disagrees"),
])
def test_lightning_financial_invariants_are_enforced(tmp_path, over, frag):
    with pytest.raises(ControlRuntimeError, match=frag):
        validate_control_runtime_record(_lightning_record(tmp_path, **over), evidence_root=tmp_path)


def test_lightning_qualified_requires_the_credit_meter_stopped_and_verified_artifacts(tmp_path):
    with pytest.raises(ControlRuntimeError, match="credit meter stopped"):
        validate_control_runtime_record(_lightning_record(tmp_path, credit_meter_stopped=False), evidence_root=tmp_path)
    rec = _lightning_record(tmp_path)
    rec["lightning_financial"]["artifacts"]["credits_after"]["sha256"] = "0" * 64
    with pytest.raises(ControlRuntimeError, match="hash does not verify"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _lightning_record(tmp_path)
    del rec["lightning_financial"]["credits_before"]
    with pytest.raises(ControlRuntimeError, match="lightning_financial"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


def _fn_source(path, name):
    text = path.read_text()
    tree = ast.parse(text)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(text, node)


def test_the_lightning_serving_function_is_the_modal_function_apart_from_the_interpreter():
    modal_src = _fn_source(HARNESS_PATH, "serve_and_smoke")
    light_src = _fn_source(LIGHTNING_RUNNER, "serve_and_smoke")
    normalise = lambda s: s.replace("    import sys\n", "").replace("sys.executable", '"python3"')
    assert normalise(light_src) == normalise(modal_src)


def _runner_module():
    spec = importlib.util.spec_from_file_location("p21b420_lightning_runner", LIGHTNING_RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_runner_locks_the_same_identities_smokes_and_settings_as_the_modal_harness():
    mod, modal_mod = _runner_module(), None
    tree_text = HARNESS_PATH.read_text()
    assert mod.SMOKES == json.loads(json.dumps(mod.SMOKES))  # plain data
    import types as _t
    stub = _t.ModuleType("modal")
    stub.Image = type("Image", (), {"from_registry": classmethod(lambda cls, *a, **k: cls())})
    stub.Image.entrypoint = lambda self, _c: self
    stub.App = lambda n: _t.SimpleNamespace(name=n, function=lambda **k: (lambda f: f))
    stub.exception = _t.SimpleNamespace(TimeoutError=TimeoutError)
    saved = sys.modules.get("modal")
    sys.modules["modal"] = stub
    try:
        spec = importlib.util.spec_from_file_location("p21b420_modal_for_parity", HARNESS_PATH)
        modal_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modal_mod)
    finally:
        if saved is None:
            sys.modules.pop("modal", None)
        else:
            sys.modules["modal"] = saved
    assert mod.SMOKES == modal_mod.SMOKES
    assert mod.MAX_MODEL_LEN == modal_mod.MAX_MODEL_LEN and mod.GPU_MEMORY_UTILIZATION == modal_mod.GPU_MEMORY_UTILIZATION
    assert mod.VLLM_VERSION == "0.29.0"
    for key, cfg in modal_mod.CONTROLS.items():
        locked = LOCKED_CONTROL_IDENTITIES[cfg["control_name"]]
        r = mod.LOCKED[key]
        assert (r["model_id"], r["revision"], r["expected_weight_bytes"]) == (locked["model_id"], locked["revision"], locked["expected_weight_bytes"])
        assert r["extra_args"] == cfg["extra_args"] and r["smoke_max_tokens"] == cfg["smoke_max_tokens"]
    assert tree_text  # harness untouched by the migration


@pytest.mark.parametrize("path", [LIGHTNING_RUNNER, LIGHTNING_CONTROL])
def test_lightning_scripts_never_eval_exec_compile_or_shell_out_with_generated_text(path):
    tree = ast.parse(path.read_text())
    bad_calls = {"eval", "exec", "compile", "__import__"}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            assert name not in bad_calls, (path.name, name)
            assert name not in ("system", "popen"), (path.name, name)
            for kw in n.keywords:
                assert not (kw.arg == "shell" and getattr(kw.value, "value", None) is True), (path.name, "shell=True")
    text = path.read_text()
    for forbidden in ("Sandbox", "sandbox", "api.openai", "deepseek", "kimi", "minimax", "MODAL_TOKEN", "LIGHTNING_API_KEY", "credentials.json"):
        assert forbidden not in text, (path.name, forbidden)


def test_lightning_control_wiring_gate_before_gpu_cap_watchdog_and_cleanup():
    text = LIGHTNING_CONTROL.read_text()
    tree = ast.parse(text)
    run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "cmd_run")
    src = ast.unparse(run)
    assert src.index("gate_decision") < src.index("switch_machine")          # gate decided before any GPU allocation
    assert "force_cpu_and_verify" in src and "finally" in src                 # cleanup on every path
    assert "meter_proof" in src and "validate_control_runtime_record" in src
    assert "watchdog" in src and "HARD_CAP_SECONDS" in src
    cap = int(re.search(r"^HARD_CAP_SECONDS = (\d+)", text, re.M).group(1))
    dog = int(re.search(r"^WATCHDOG_SECONDS = (\d+)", text, re.M).group(1))
    assert dog < cap and Decimal("3.54") * cap / 3600 <= Decimal("1.00")     # per-attempt cost cap holds at the quoted rate
    assert "Machine.CPU" in ast.unparse(next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "force_cpu_and_verify"))
    assert 'purpose == "run"' in text and "Machine.A100" not in text and "H100" not in text


def test_lightning_control_imports_without_the_lightning_or_modal_sdk_and_blocks_a_second_gpu(monkeypatch):
    spec = importlib.util.spec_from_file_location("p21b420_lightning_control", LIGHTNING_CONTROL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)   # top-level imports are stdlib + orca only; SDKs are imported lazily
    assert set(mod.CONTROLS) == set(mod.CONTROL_KEYS) == {"qwen3_8b", "mistral_nemo", "phi4"}
    assert mod.HARD_CAP_SECONDS == 900 and mod.WATCHDOG_SECONDS < mod.HARD_CAP_SECONDS


def test_a_known_provider_gpu_rejection_blocks_the_gate_and_is_recorded_honestly():
    d = _lgate(_lstate(known_provider_gpu_block="Free-tier users must have a verified payment method before starting GPU compute"))
    assert d["allowed"] is False and any("provider is known to refuse GPU start" in r for r in d["reasons"])
    rej = json.loads((EVIDENCE_DIR / "GENESIS_LIGHTNING_PROVIDER_GPU_REJECTION_2026-09-24.json").read_text())
    assert rej["http_status"] == 400 and rej["gpu_allocated"] is False and rej["credit_delta"] == "0"
    assert "verified payment method" in rej["provider_message"] and rej["blocks_gpu_while_no_payment_method"] is True
    assert rej["gate_state_when_rejected"]["gate_allowed"] is True   # the pre-check did not predict it; recorded, not hidden
    assert "will not, add or verify a card" in rej["owner_rule_conflict"]


def test_lightning_account_and_staging_evidence_records_verified_staging_and_no_gpu():
    acc = json.loads((EVIDENCE_DIR / "GENESIS_LIGHTNING_ACCOUNT_AND_STAGING_EVIDENCE_2026-09-24.json").read_text())
    assert acc["account_state"]["plan"] == "Free" and acc["account_state"]["card_verified"] is False
    assert acc["no_gpu_ran"] is True and acc["credits_consumed_by_gpu"] == "0"
    assert set(acc["cpu_staging"]["models"].values()) == {"verified"}
    for m in acc["cpu_staging"]["manifests"]:
        man = json.loads((EVIDENCE_DIR / m).read_text())
        assert man["staging_verified"] is True and man["all_lfs_sha256_match"] is True
        locked = LOCKED_CONTROL_IDENTITIES[next(c["control_name"] for c in [{"control_name": n} for n in LOCKED_CONTROL_IDENTITIES]
                                                if LOCKED_CONTROL_IDENTITIES[c["control_name"]]["model_id"] == man["model_id"])]
        assert man["revision"] == locked["revision"] and man["weight_bytes_observed"] == locked["expected_weight_bytes"]


# ══ Hugging Face ZeroGPU: model runtime compatibility != production serving ═══

from orca.eval.control_runtime_qualification import (  # noqa: E402
    MODEL_RUNTIME_COMPATIBILITY_STATUSES, PRODUCTION_SERVING_UNCHANGED, ZEROGPU_PROVIDER,
    derive_model_runtime_compatibility, validate_zerogpu_classification,
)


def _zg(**over):
    args = dict(provider_eligible=True, identity_pass=True, bf16_exact_model_loaded=True, smokes_pass=True,
                evidence_verified=True, cleanup_pass=True, owner_cash_delta_usd="0")
    args.update(over)
    return derive_model_runtime_compatibility(**args)


def test_zerogpu_compatibility_needs_every_condition():
    assert _zg() == "QUALIFIED"
    for k in ("identity_pass", "evidence_verified", "cleanup_pass"):
        assert _zg(**{k: False}) == "NOT_PROVEN", k
    assert _zg(bf16_exact_model_loaded=False) == "FAILED" and _zg(smokes_pass=False) == "FAILED"
    assert _zg(owner_cash_delta_usd="0.01") == "NOT_PROVEN"
    assert _zg(provider_eligible=False) == "NOT_ELIGIBLE" and _zg(attempted=False) == "NOT_TESTED"


def _zrec(**over):
    r = {"gpu_provider": ZEROGPU_PROVIDER, "production_serving_runtime_status": PRODUCTION_SERVING_UNCHANGED,
         "model_runtime_compatibility_status": "QUALIFIED", "capability_status": "UNPROVEN", "precision": "bfloat16",
         "quantization": None, "owner_cash_delta_usd": "0"}
    r.update(over)
    return r


def test_zerogpu_never_changes_production_serving_and_never_uses_the_production_label():
    validate_zerogpu_classification(_zrec())
    for over, frag in (
        ({"production_serving_runtime_status": "QUALIFIED"}, "UNCHANGED"),
        ({"production_serving_runtime_status": None}, "UNCHANGED"),
        ({"runtime_qualification_status": "RUNTIME_QUALIFIED"}, "production-runtime label"),
        ({"capability_status": "QUALIFIED"}, "UNPROVEN"),
        ({"precision": "float16"}, "BF16"),
        ({"quantization": "int4"}, "BF16"),
        ({"owner_cash_delta_usd": "0.5"}, "owner cash"),
        ({"model_runtime_compatibility_status": "RUNTIME_QUALIFIED"}, "not one of"),
    ):
        with pytest.raises(ControlRuntimeError, match=frag):
            validate_zerogpu_classification(_zrec(**over))
    assert "RUNTIME_QUALIFIED" not in MODEL_RUNTIME_COMPATIBILITY_STATUSES   # the two vocabularies never merge


def test_hf_zerogpu_eligibility_is_recorded_as_not_established_and_nothing_was_created():
    art = json.loads((EVIDENCE_DIR / "GENESIS_HF_ZEROGPU_ELIGIBILITY_AND_HEADROOM_2026-09-24.json").read_text())
    assert art["result"] == "ELIGIBILITY_NOT_ESTABLISHED" and "NOT HF_ZEROGPU_NOT_ELIGIBLE" in art["result_meaning"]
    assert set(art["fields_not_verified"].values()) >= {"NOT_VERIFIED"} and art["gpu_started"] is False
    assert art["created_or_launched"].startswith("nothing") and art["owner_cash_incurred"] == "none"
    for name, m in art["memory_headroom_estimates_large_48gb"].items():
        locked = LOCKED_CONTROL_IDENTITIES[name]
        assert m["weights_bytes_exact_bf16"] == locked["expected_weight_bytes"]
        assert m["fits_large_48gb"] is True and m["estimated_headroom_bytes"] > 10 * 10**9
        assert "ASSUMED" in m["basis"] and "not a measurement" in m["basis"]
    assert art["quota_plan"]["total_planned_seconds"] <= art["quota_plan"]["free_daily_quota_seconds"]
    assert "no quota bypass" in art["quota_plan"]["rule"] and "no PRO purchase" in art["hard_rules"]
    assert "UNCHANGED" in art["hard_rules"][-1]


def test_hf_zerogpu_account_verification_is_not_eligible_by_age_and_persists_no_email_or_credentials():
    path = EVIDENCE_DIR / "GENESIS_HF_ZEROGPU_ACCOUNT_VERIFICATION_2026-09-24.json"
    raw = path.read_text()
    art = json.loads(raw)
    assert art["result"] == "HF_ZEROGPU_NOT_ELIGIBLE"
    acct = art["authenticated_account"]
    assert acct["older_than_30_days"] is False and acct["created_at_utc"] == "2026-09-24T15:34:25Z"
    assert acct["email"] == "[not persisted]" and acct["credentials"] == "[not persisted]"
    assert "@" not in raw and "hotmail" not in raw.lower() and "gmail" not in raw.lower()
    checks = art["checks"]
    assert checks["4_account_older_than_30_days"].startswith("FAILED") and checks["11_owner_payable_exposure"].startswith("$0.00")
    assert checks["7_free_daily_zerogpu_quota"].endswith("0/5 minutes") and "UNVERIFIED" in checks["12_account_specific_hardware"]
    assert art["gpu_started"] is False and art["owner_cash_incurred"] == "none" and art["production_serving_qualification"] == "UNCHANGED"
    assert "no purchased credits" in art["explicitly_not_done"] and "no Space creation" in art["explicitly_not_done"]
    assert art["earliest_age_eligibility_utc"] == "2026-10-24T15:34:25Z"


# ══ razorBridge: gate, financial validator, static safety ═══════════════════

from orca.eval.control_runtime_qualification import (  # noqa: E402
    RAZORBRIDGE_FINANCIAL_REQUIRED, RAZORBRIDGE_PROVIDER, razorbridge_gate_decision,
)

RB_CONTROL = REPO_ROOT / "scripts/phase21b_4_20_razorbridge_control.py"


def _rgate(**over):
    args = dict(balance_eur="10", payment_method_present=False, auto_topup_available=False, owner_payable_eur="0",
                rate_eur_per_hour="4.29", hard_runtime_cap_seconds=1200, h100_selectable=True, live_blades=0)
    args.update(over)
    return razorbridge_gate_decision(**args)


def test_razorbridge_gate_allows_the_observed_account_and_bounds_the_attempt_cost():
    d = _rgate()
    assert d["allowed"] is True and Decimal(d["worst_case_eur"]) == Decimal("1.43") and Decimal(d["required_balance_eur"]) == Decimal("4.29")


@pytest.mark.parametrize("over,frag", [
    ({"payment_method_present": True}, "payment method"), ({"payment_method_present": None}, "payment method"),
    ({"auto_topup_available": True}, "top-up"), ({"auto_topup_available": None}, "top-up"),
    ({"owner_payable_eur": "0.01"}, "owner payable"), ({"balance_eur": "0"}, "no promotional"),
    ({"h100_selectable": False}, "not selectable"), ({"rate_eur_per_hour": "4.30"}, "exceeds the authorized"),
    ({"live_blades": 1}, "already live"), ({"live_blades": None}, "already live"),
    ({"hard_runtime_cap_seconds": 1300}, "per-attempt authorization"),
    ({"balance_eur": "3.49"}, "authorization + reserve"), ({"balance_eur": "4.28"}, "whole-session"),
    ({"prior_positive_owner_cash": True}, "already charged"),
])
def test_razorbridge_gate_blocks_every_unsafe_state(over, frag):
    d = _rgate(**over)
    assert d["allowed"] is False and any(frag in r for r in d["reasons"]), d["reasons"]


def _rb_record(tmp_path, **fin_over):
    rec = _qualified_record(tmp_path)
    gate = _write(tmp_path / "rgate.json", b'{"rb": "gate"}')
    bef = _write(tmp_path / "rbefore.json", b'{"rb": "before"}')
    aft = _write(tmp_path / "rafter.json", b'{"rb": "after"}')
    fin = {"payment_method_present": False, "auto_topup_available": False, "gpu_type": "H100", "gpu_rate_eur_per_hour": "4.29",
           "blade_runtime_seconds": 720.0, "credits_before_eur": "10", "credits_after_eur": "9.1416", "credit_delta_eur": "0.8584",
           "expected_max_charge_eur": "0.8580", "observed_charge_eur": "0.8584", "owner_payable_before_eur": "0", "owner_payable_after_eur": "0",
           "owner_cash_delta_eur": "0", "credit_meter_stopped": True, "hard_runtime_cap_seconds": 1200, "per_attempt_authorization_eur": "1.50",
           "live_blades_after": 0, "artifacts": {"account_gate": {"artifact": "rgate.json", "sha256": gate},
                                                 "credits_before": {"artifact": "rbefore.json", "sha256": bef},
                                                 "credits_after": {"artifact": "rafter.json", "sha256": aft}}}
    fin.update(fin_over)
    for k in ("financial_reconciliation", "billing_settlement", "billing_discrepancy_observation"):
        rec.pop(k, None)
    rec.update(gpu_provider=RAZORBRIDGE_PROVIDER, razorbridge_financial=fin, financial_evidence={"provider": RAZORBRIDGE_PROVIDER})
    return rec


def test_a_consistent_razorbridge_record_validates(tmp_path):
    validate_control_runtime_record(_rb_record(tmp_path), evidence_root=tmp_path)


@pytest.mark.parametrize("over,frag", [
    ({"payment_method_present": True}, "must both be False"), ({"auto_topup_available": True}, "must both be False"),
    ({"credits_after_eur": "-0.5", "credit_delta_eur": "10.5"}, "negative"), ({"credit_delta_eur": "0.10"}, "credit_delta_eur must equal"),
    ({"owner_payable_after_eur": "0.50", "owner_cash_delta_eur": "0.50"}, "owner_billed_delta_usd disagrees"),
    ({"owner_cash_delta_eur": "0.50"}, "owner_cash_delta_eur disagrees"),
    ({"credit_meter_stopped": False}, "billing stopped"), ({"live_blades_after": 1}, "billing stopped"),
])
def test_razorbridge_financial_invariants_are_enforced(tmp_path, over, frag):
    with pytest.raises(ControlRuntimeError, match=frag):
        validate_control_runtime_record(_rb_record(tmp_path, **over), evidence_root=tmp_path)


def test_razorbridge_artifact_hashes_and_required_fields_must_verify(tmp_path):
    rec = _rb_record(tmp_path)
    rec["razorbridge_financial"]["artifacts"]["credits_after"]["sha256"] = "0" * 64
    with pytest.raises(ControlRuntimeError, match="hash does not verify"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _rb_record(tmp_path)
    del rec["razorbridge_financial"]["gpu_rate_eur_per_hour"]
    with pytest.raises(ControlRuntimeError, match="razorbridge_financial"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    assert "auto_topup_available" in RAZORBRIDGE_FINANCIAL_REQUIRED


def test_razorbridge_script_is_statically_safe_and_sets_its_caps():
    text = RB_CONTROL.read_text()
    tree = ast.parse(text)
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            assert name not in {"eval", "exec", "compile", "__import__", "system", "popen"}, name
            for kw in n.keywords:
                assert not (kw.arg == "shell" and getattr(kw.value, "value", None) is True)
    for forbidden in ("Sandbox", "api.openai", "deepseek", "kimi", "minimax", "credentials.json", "print(pw", "print(password"):
        assert forbidden not in text, forbidden
    assert 'os.environ.get("RB_BLADE_PASSWORD")' in text            # password only from the environment
    assert int(re.search(r"^HARD_CAP_SECONDS = (\d+)", text, re.M).group(1)) == 1200
    assert int(re.search(r"^ABORT_SECONDS = (\d+)", text, re.M).group(1)) < 1200
    assert Decimal("4.29") * 1200 / 3600 <= Decimal("1.50") and "gpu-h100x1-80gb" in text
    assert "H200" not in text.replace('"gpu-h200x1-141gb"', "").replace("H200 141", "")   # H100 only; H200 is a named fallback, never selected here


def test_razorbridge_gate_and_start_refusal_are_recorded_without_secrets_and_with_no_cost():
    gate = json.loads((EVIDENCE_DIR / "GENESIS_RAZORBRIDGE_ACCOUNT_GATE_QWEN3_8B_2026-09-24.json").read_text())
    rej_path = EVIDENCE_DIR / "GENESIS_RAZORBRIDGE_PROVIDER_START_REFUSED_2026-09-24.json"
    rej = json.loads(rej_path.read_text())
    raw = json.dumps(gate) + rej_path.read_text()
    assert gate["gate_decision"]["allowed"] is True and gate["payment_method"]["present"] is False and gate["auto_topup"]["available"] is False
    assert gate["account"]["email"] == "[not persisted]" and "@" not in raw and "hotmail" not in raw.lower() and "gmail" not in raw.lower()
    assert rej["blade_created"] is False and rej["gpu_allocated"] is False and rej["cost_eur"] == "0" and rej["owner_cash_eur"] == "0"
    assert "temporarily paused for maintenance" in rej["provider_message"] and rej["verification_after"]["credit_balance_eur"] == "10"
    assert rej["account_gate"]["sha256"] == hashlib.sha256((EVIDENCE_DIR / rej["account_gate"]["artifact"]).read_bytes()).hexdigest()
    assert "NEVER been exercised" in rej["tooling_state"] and rej["production_serving_qualification"] == "UNCHANGED"


# ══ Modal H100 simplified harness: static wiring, caps, no polling, shared serving function ═══

MODAL_H100 = REPO_ROOT / "scripts/phase21b_4_20_modal_h100_control.py"


def _load_modal_h100(monkeypatch):
    return _load_harness_stub(monkeypatch, MODAL_H100, "p21b420_modal_h100_stub")


def _load_harness_stub(monkeypatch, path, name):
    import types as _t
    calls = {"function_kwargs": [], "local_files": []}

    class _Img:
        @classmethod
        def from_registry(cls, ref, **kw):
            calls["registry"] = (ref, kw)
            return cls()

        def entrypoint(self, _c):
            return self

        def add_local_file(self, src, dst, **kw):
            calls["local_files"].append((src, dst))
            return self

    class _Vol:
        @classmethod
        def from_name(cls, n, **kw):
            calls["volume"] = (n, kw)
            return cls()

    class _App:
        def __init__(self, n):
            self.name = n

        def function(self, **kw):
            calls["function_kwargs"].append(kw)
            return lambda fn: fn

    stub = _t.ModuleType("modal")
    stub.Image, stub.App, stub.Volume = _Img, _App, _Vol
    stub.exception = _t.SimpleNamespace(TimeoutError=type("TimeoutError", (Exception,), {}))
    stub.is_local = lambda: True
    monkeypatch.setitem(sys.modules, "modal", stub)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, calls


def test_modal_h100_harness_pins_image_gpu_volume_and_uses_the_function_timeout_as_the_hard_cap(monkeypatch):
    mod, calls = _load_modal_h100(monkeypatch)
    assert calls["registry"][0] == f"vllm/vllm-openai@{mod.VLLM_IMAGE_DIGEST}" and mod.VLLM_IMAGE_DIGEST.startswith("sha256:")
    assert calls["volume"][0] == "orneur-p21b420-model-cache" and calls["volume"][1] == {"create_if_missing": True}
    assert calls["local_files"][0][1] == "/root/runner.py"
    cpu_fn, gpu_fn = calls["function_kwargs"]
    assert "gpu" not in cpu_fn and cpu_fn["timeout"] == 1800 and cpu_fn["volumes"] == {"/models": mod.volume}
    assert gpu_fn["gpu"] == "H100" and gpu_fn["timeout"] == mod.HARD_TIMEOUT_SECONDS == 900 and mod.HARD_TIMEOUT_SECONDS <= 1200
    # worst case (H100 + CPU + memory) for the hard cap stays inside the EXISTING $1.25 per-attempt maximum: no guard was loosened
    r = {"h100": Decimal("3.95"), "cpu": Decimal("0.0473"), "mem": Decimal("0.008")}
    worst = mod.worst_case_cost(r, gpu=True, cores=mod.CPU_CORES, memory_mib=mod.GPU_MEMORY_MIB, seconds=mod.HARD_TIMEOUT_SECONDS)
    assert worst <= Decimal("1.25") and worst > Decimal("1.0")


def test_modal_h100_harness_has_no_polling_loop_no_cancel_no_sandbox_and_a_single_blocking_gpu_call():
    text = MODAL_H100.read_text()
    tree = ast.parse(text)
    run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "cmd_run")
    src = ast.unparse(run)
    assert src.count("serve_and_smoke.remote(") == 1 and ".spawn(" not in text and ".cancel(" not in text
    assert "while True" not in text and ".get(timeout" not in text and "Sandbox" not in text
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in {"precache", "serve_and_smoke"}):
        body = ast.unparse(fn)
        for banned in ("eval(", "exec(", "compile(", "os.system", "shell=True", "subprocess"):
            assert banned not in body, (fn.name, banned)
    assert src.index("_preflight") < src.index("app.run()")                      # gate decided before any GPU allocation
    assert "pre-cached and verified" in src and "validate_control_runtime_record" in src
    assert "financial_gate_decision" in ast.unparse(next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_preflight"))


def test_modal_h100_uses_the_same_serving_function_as_every_other_provider_and_offline_verified_weights():
    text = MODAL_H100.read_text()
    assert "phase21b_4_20_lightning_runner.py" in text and "runner.serve_and_smoke(cfg)" in text
    assert 'os.environ["HF_HUB_OFFLINE"] = "1"' in text and "volume.reload()" in text and "volume.commit()" in text
    assert "runner.cmd_stage_model(control)" in text                              # hash-verified pre-cache (LFS sha256 + exact bytes)
    assert not any(k in text for k in ("api.openai", "deepseek", "kimi", "minimax"))


def test_modal_h100_worst_case_gate_keeps_the_existing_maximum_and_blocks_on_unresolved_settlement(monkeypatch, tmp_path):
    mod, _ = _load_modal_h100(monkeypatch)
    monkeypatch.setattr(mod, "EVIDENCE_DIR", tmp_path)
    (tmp_path / f"GENESIS_CONTROL_QWEN3_8B_ATTEMPTS_{mod.DATE_TAG}.json").write_text(json.dumps({"attempts": [
        {"attempt_number": 1, "outcome": "HARNESS_FAILURE", "owner_billed_delta_usd": "0E-8", "billing_settlement_status": "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE", "duration_seconds": 34.6},
        {"attempt_number": 2, "provider": "Lightning AI", "outcome": "BLOCKED_NO_GPU", "owner_billed_delta_usd": "0"}]}))
    (tmp_path / "GENESIS_BILLING_DISCREPANCY_OBSERVATION_2026-09-24.json").write_text("{}")
    tag, a = next(iter(mod._modal_attempts()))
    assert tag == "QWEN3_8B" and a["attempt_number"] == 1                        # only Modal attempts count; Lightning/other are excluded
    assert mod.settlement_resolved(tag, a) is False
    assert Decimal("0.03") < mod.unresolved_settlement_upper_bound_usd() < Decimal("0.05")   # conservative upper bound is deducted from runway
    (tmp_path / f"GENESIS_OWNER_SETTLEMENT_WAIVER_QWEN3_8B_ATTEMPT1_{mod.DATE_TAG}.json").write_text("{}")
    assert mod.settlement_resolved(tag, a) is False                              # existence alone is NOT authorization
    (tmp_path / f"GENESIS_OWNER_SETTLEMENT_WAIVER_QWEN3_8B_ATTEMPT1_{mod.DATE_TAG}.json").write_text(json.dumps(_valid_waiver()))
    assert mod.settlement_resolved(tag, a) is True                               # only a strictly valid owner waiver lifts the gate
    assert mod.any_positive_billing_seen() is False


def test_modal_h100_script_never_writes_a_waiver_or_touches_the_shared_guards():
    text = MODAL_H100.read_text()
    assert "GENESIS_OWNER_SETTLEMENT_WAIVER" in text and "never created by this script" in text
    assert "write_json(EVIDENCE_DIR / f\"GENESIS_OWNER_SETTLEMENT_WAIVER" not in text
    assert "MAX_AUTHORIZED_RUN_COST_USD" not in text and "max_authorized_run_cost_usd" not in text


# ── strict owner-waiver validation (fixtures live in tmp_path only; the real owner artifact is never created) ──
def _valid_waiver() -> dict:
    return {
        "artifact_type": "OWNER_SETTLEMENT_WAIVER", "phase": "21B.4.20", "authorized_by": "ORNEUR_OWNER", "decision": "AUTHORIZED",
        "created_at_utc": "2026-09-25T10:00:00Z",
        "scope": {"provider": "Modal", "control": "Qwen3-8B", "historical_attempt": 1, "waiver": "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE", "historical_only": True},
        "authorization_text": "The ORNEUR owner authorizes a one-time waiver for Modal Qwen3-8B historical attempt 1 only.",
        "asserts": {"attempt_1_cost_was_zero": False, "settlement_resolved": False, "attempt_1_valid_model_qualification_attempt": False,
                    "attempt_1_status": "HARNESS_FAILURE", "attempt_1_billing_settlement_status": "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE",
                    "attempt_1_conservative_exposure_reserved_usd": "0.038"},
        "does_not_waive": ["zero_owner_cash_invariant", "promotional_credit_sufficiency", "model_identity_and_revision_verification",
                           "cleanup_requirements", "evidence_integrity", "security_controls"],
        "does_not_authorize": ["frontier_inference", "benchmarks", "genesis_training", "phase_21c"],
        "authorized_execution": {"controls_in_order": ["Qwen3-8B", "Mistral-Nemo-Instruct-2407", "Phi-4"], "provider": "Modal", "gpu": "H100 80GB",
                                 "precision": "BF16", "quantization": False, "model_substitution": False, "sequential_only": True},
        "note": "Creating this artifact does not itself authorize GPU execution.",
    }


def _waiver_env(monkeypatch, tmp_path, waiver=None, raw=None):
    mod, _ = _load_modal_h100(monkeypatch)
    monkeypatch.setattr(mod, "EVIDENCE_DIR", tmp_path)
    (tmp_path / f"GENESIS_CONTROL_QWEN3_8B_ATTEMPTS_{mod.DATE_TAG}.json").write_text(json.dumps({"attempts": [
        {"attempt_number": 1, "outcome": "HARNESS_FAILURE", "owner_billed_delta_usd": "0E-8",
         "billing_settlement_status": "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE", "duration_seconds": 34.6}]}))
    wp = tmp_path / f"GENESIS_OWNER_SETTLEMENT_WAIVER_QWEN3_8B_ATTEMPT1_{mod.DATE_TAG}.json"
    if raw is not None:
        wp.write_text(raw)
    elif waiver is not None:
        wp.write_text(json.dumps(waiver))
    tag, a = next(iter(mod._modal_attempts()))
    return mod, tag, a


def _mut(fn):
    w = _valid_waiver()
    fn(w)
    return w


_INVALID_WAIVERS = {
    "empty_object": lambda: {},
    "wrong_phase": lambda: _mut(lambda w: w.update(phase="21B.4.19")),
    "wrong_authorized_by": lambda: _mut(lambda w: w.update(authorized_by="CLAUDE")),
    "wrong_decision": lambda: _mut(lambda w: w.update(decision="DENIED")),
    "missing_timestamp": lambda: _mut(lambda w: w.pop("created_at_utc")),
    "bad_timestamp": lambda: _mut(lambda w: w.update(created_at_utc="yesterday")),
    "wrong_provider": lambda: _mut(lambda w: w["scope"].update(provider="Lightning AI")),
    "wrong_control": lambda: _mut(lambda w: w["scope"].update(control="Phi-4")),
    "wrong_attempt": lambda: _mut(lambda w: w["scope"].update(historical_attempt=2)),
    "attempt_as_bool": lambda: _mut(lambda w: w["scope"].update(historical_attempt=True)),
    "wrong_settlement_status": lambda: _mut(lambda w: w["scope"].update(waiver="OBSERVED")),
    "not_historical_only": lambda: _mut(lambda w: w["scope"].update(historical_only=False)),
    "claims_cost_zero": lambda: _mut(lambda w: w["asserts"].update(attempt_1_cost_was_zero=True)),
    "claims_settlement_resolved": lambda: _mut(lambda w: w["asserts"].update(settlement_resolved=True)),
    "claims_valid_qualification_attempt": lambda: _mut(lambda w: w["asserts"].update(attempt_1_valid_model_qualification_attempt=True)),
    "wrong_attempt_status": lambda: _mut(lambda w: w["asserts"].update(attempt_1_status="RUNTIME_QUALIFIED")),
    "wrong_asserted_settlement_status": lambda: _mut(lambda w: w["asserts"].update(attempt_1_billing_settlement_status="OBSERVED")),
    "negative_exposure": lambda: _mut(lambda w: w["asserts"].update(attempt_1_conservative_exposure_reserved_usd="-0.01")),
    "missing_exposure": lambda: _mut(lambda w: w["asserts"].pop("attempt_1_conservative_exposure_reserved_usd")),
    "missing_zero_owner_cash_preservation": lambda: _mut(lambda w: w["does_not_waive"].remove("zero_owner_cash_invariant")),
    "missing_credit_sufficiency_preservation": lambda: _mut(lambda w: w["does_not_waive"].remove("promotional_credit_sufficiency")),
    "missing_identity_preservation": lambda: _mut(lambda w: w["does_not_waive"].remove("model_identity_and_revision_verification")),
    "missing_cleanup_preservation": lambda: _mut(lambda w: w["does_not_waive"].remove("cleanup_requirements")),
    "missing_evidence_integrity_preservation": lambda: _mut(lambda w: w["does_not_waive"].remove("evidence_integrity")),
    "missing_security_preservation": lambda: _mut(lambda w: w["does_not_waive"].remove("security_controls")),
    "authorizes_benchmarks_by_omission": lambda: _mut(lambda w: w["does_not_authorize"].remove("benchmarks")),
    "authorizes_frontier_inference_by_omission": lambda: _mut(lambda w: w["does_not_authorize"].remove("frontier_inference")),
    "authorizes_training_by_omission": lambda: _mut(lambda w: w["does_not_authorize"].remove("genesis_training")),
    "authorizes_21c_by_omission": lambda: _mut(lambda w: w["does_not_authorize"].remove("phase_21c")),
    "extra_authorizes_key": lambda: _mut(lambda w: w.update(authorizes=["benchmarks"])),
    "wrong_gpu": lambda: _mut(lambda w: w["authorized_execution"].update(gpu="A100 80GB")),
    "wrong_precision": lambda: _mut(lambda w: w["authorized_execution"].update(precision="FP8")),
    "quantization_true": lambda: _mut(lambda w: w["authorized_execution"].update(quantization=True)),
    "model_substitution_true": lambda: _mut(lambda w: w["authorized_execution"].update(model_substitution=True)),
    "not_sequential": lambda: _mut(lambda w: w["authorized_execution"].update(sequential_only=False)),
    "wrong_control_ordering": lambda: _mut(lambda w: w["authorized_execution"].update(controls_in_order=["Phi-4", "Qwen3-8B", "Mistral-Nemo-Instruct-2407"])),
    "extra_control": lambda: _mut(lambda w: w["authorized_execution"]["controls_in_order"].append("Llama")),
    "empty_authorization_text": lambda: _mut(lambda w: w.update(authorization_text=" ")),
}


def test_owner_waiver_absent_is_not_accepted_and_settlement_stays_unresolved(monkeypatch, tmp_path):
    mod, tag, a = _waiver_env(monkeypatch, tmp_path)
    assert mod.validate_owner_settlement_waiver(tag, a)[0] == "WAIVER_ABSENT" and mod.settlement_resolved(tag, a) is False


def test_owner_waiver_malformed_json_is_invalid_and_fails_closed(monkeypatch, tmp_path):
    for raw in ("{not json", "[]", "null", ""):
        mod, tag, a = _waiver_env(monkeypatch, tmp_path, raw=raw)
        status, reasons = mod.validate_owner_settlement_waiver(tag, a)
        assert status == "WAIVER_INVALID" and reasons and mod.settlement_resolved(tag, a) is False


@pytest.mark.parametrize("name", sorted(_INVALID_WAIVERS))
def test_owner_waiver_every_defect_is_waiver_invalid_and_settlement_stays_unresolved(monkeypatch, tmp_path, name):
    mod, tag, a = _waiver_env(monkeypatch, tmp_path, waiver=_INVALID_WAIVERS[name]())
    status, reasons = mod.validate_owner_settlement_waiver(tag, a)
    assert status == "WAIVER_INVALID" and reasons, name
    assert mod.settlement_resolved(tag, a) is False


def test_owner_waiver_valid_canonical_is_accepted_but_does_not_launch_or_resolve_the_record(monkeypatch, tmp_path):
    mod, tag, a = _waiver_env(monkeypatch, tmp_path, waiver=_valid_waiver())
    assert mod.validate_owner_settlement_waiver(tag, a) == ("WAIVER_ACCEPTED", [])
    assert mod.settlement_resolved(tag, a) is True
    assert a["billing_settlement_status"] == "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE"          # historical record untouched
    assert Decimal("0.03") < mod.unresolved_settlement_upper_bound_usd() < Decimal("0.05")    # exposure still deducted after the waiver
    assert not any(n.name.startswith("GENESIS_CONTROL_") and "H100_RUN" in n.name for n in tmp_path.iterdir())


def test_owner_waiver_applies_only_to_qwen_attempt_1_and_contradicting_history_invalidates_it(monkeypatch, tmp_path):
    mod, tag, a = _waiver_env(monkeypatch, tmp_path, waiver=_valid_waiver())
    other_attempt = dict(a, attempt_number=2)
    other_control = "MISTRAL_NEMO"
    assert mod.validate_owner_settlement_waiver(tag, other_attempt)[0] == "WAIVER_ABSENT" and mod.settlement_resolved(tag, other_attempt) is False
    assert mod.validate_owner_settlement_waiver(other_control, a)[0] == "WAIVER_ABSENT" and mod.settlement_resolved(other_control, a) is False
    # copying the Qwen waiver to another control/attempt filename does not lift any other settlement
    for name in ("GENESIS_OWNER_SETTLEMENT_WAIVER_MISTRAL_NEMO_ATTEMPT1_2026-09-24.json", "GENESIS_OWNER_SETTLEMENT_WAIVER_QWEN3_8B_ATTEMPT2_2026-09-24.json"):
        (tmp_path / name).write_text(json.dumps(_valid_waiver()))
    assert mod.settlement_resolved(other_control, a) is False and mod.settlement_resolved(tag, other_attempt) is False
    # the waiver contradicts a history record that is not a harness failure with unobserved settlement
    contradicting = dict(a, outcome="RUNTIME_QUALIFIED")
    assert mod.validate_owner_settlement_waiver(tag, contradicting)[0] == "WAIVER_INVALID"


def test_invalid_waiver_is_reported_in_the_gate_reasons(monkeypatch, tmp_path):
    mod, tag, a = _waiver_env(monkeypatch, tmp_path, waiver=_mut(lambda w: w["asserts"].update(settlement_resolved=True)))
    monkeypatch.setattr(mod, "_load_lightning_control", lambda: types.SimpleNamespace(CONTROLS={"qwen3_8b": {"control_name": "Qwen3-8B", "tag": "QWEN3_8B"}}))
    monkeypatch.setattr(mod, "rates", lambda: {"h100": Decimal("3.95"), "cpu": Decimal("0.0473"), "mem": Decimal("0.008")})
    monkeypatch.setattr(mod, "billing_summary", lambda: {"billed_cost_usd": "0", "metered_cost_usd": "20.07", "credits_applied_usd": "20.07"})
    monkeypatch.setattr(mod, "cleanup_snapshot", lambda: {"live_resources": 0})
    decision = mod._preflight("gpu", "qwen3_8b", gpu=True)[-1]
    assert decision["allowed"] is False and any(r.startswith("WAIVER_INVALID") for r in decision["reasons"])


# ── delayed-settlement reconcile mode (read-only; no GPU, no Modal function, no generated-output execution) ──
_RECON_APP_ID = "ap-SYNTHETICATTEMPT4"


def _rc_summary(metered, credits, billed="0E-8", eph=None):
    out = {"billed_cost": billed, "metered_cost": metered, "adjustments": {"credits": credits, "plan_cost": "0E-8"}}
    if eph is not None:
        out["metered_cost_breakdown"] = {"deployed_apps": "0.00101405", "ephemeral_apps": eph, "llm_tokens": "0E-8", "volumes": "0E-8"}
    return out


def _reconcile_env(monkeypatch, tmp_path, *, metered_now="20.31000000", credits_now="-20.31000000", billed_now="0E-8", rows=None,
                   live=0, app_state="stopped", tamper_before=False, eph_before=None, eph_now=None, run_cost="0.23000000"):
    mod, _ = _load_modal_h100(monkeypatch)
    monkeypatch.setattr(mod, "EVIDENCE_DIR", tmp_path)
    monkeypatch.setattr(mod, "_load_lightning_control", lambda: types.SimpleNamespace(CONTROLS={"qwen3_8b": {"control_name": "Qwen3-8B", "tag": "QWEN3_8B"}}))
    rec = _qualified_record(tmp_path, "Qwen3-8B")
    baseline = _rc_summary("20.08000000", "-20.08000000", eph=eph_before)
    pre = {"credit_pool_usd": "30.00", "unresolved_prior_settlement_upper_bound_deducted_usd": "0.0380", "reserve_usd": "5.00", "worst_case_cost_usd": "1.0828"}
    fin = {}
    for key, doc in (("preflight", pre), ("billing_before", {"billing_summary": baseline}), ("billing_after", {"peak_observed_billed_usd": "0E-8"})):
        name = f"synthetic_{key}.json"
        (tmp_path / name).write_text(json.dumps(doc))
        fin[f"{key}_artifact"] = name
        fin[f"{key}_sha256"] = hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
    (tmp_path / "raw_attempt4.txt").write_text("synthetic raw log")
    raw_sha = hashlib.sha256(b"synthetic raw log").hexdigest()
    attempt = {"attempt_number": 4, "provider": "Modal", "outcome": "TECHNICAL_SUCCESS", "status": "TECHNICAL_SUCCESS", "failure_domain": "NONE",
               "valid_runtime_attempt": True, "reason": "synthetic", "resource_type": "synthetic", "duration_seconds": 196.5, "owner_billed_delta_usd": "0E-8",
               "billing_settlement_status": "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE", "cleanup_result": "PASS", "started_at_utc": "2026-09-24T20:53:32Z",
               "finished_at_utc": "2026-09-24T20:56:49Z", "modal_app_name": "orneur-p21b420-h100-control-runtime", "modal_app_id": _RECON_APP_ID,
               "raw_log_artifact": "raw_attempt4.txt", "raw_log_sha256": raw_sha}
    history = [{"attempt_number": 1, "outcome": "HARNESS_FAILURE", "status": "HARNESS_FAILURE", "failure_domain": "HARNESS", "valid_runtime_attempt": False,
                "reason": "synthetic historical", "resource_type": "synthetic", "duration_seconds": 34.6, "owner_billed_delta_usd": "0E-8", "cleanup_result": "PASS",
                "billing_settlement_status": "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE"},
               {"attempt_number": 2, "provider": "Lightning AI", "outcome": "BLOCKED_NO_GPU", "valid_runtime_attempt": False, "reason": "synthetic", "resource_type": "synthetic",
                "duration_seconds": 0, "owner_billed_delta_usd": "0", "cleanup_result": "NOT_APPLICABLE"},
               {"attempt_number": 3, "provider": "razorBridge", "outcome": "BLOCKED_NO_GPU", "valid_runtime_attempt": False, "reason": "synthetic", "resource_type": "synthetic",
                "duration_seconds": 0, "owner_billed_delta_usd": "0", "cleanup_result": "NOT_APPLICABLE"}]
    rec.update({"attempts": history + [attempt], "financial_evidence": fin, "owner_billed_delta_usd": "0E-8", "raw_log_artifact": "raw_attempt4.txt", "raw_log_sha256": raw_sha,
                "billing_settlement": {"status": "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE", "reasons": ["not yet visible"], "stop_before_next_control": True},
                "runtime_qualification_status": "RUNTIME_QUALIFIED", "validator_note": "record FAILED its own validator: RUNTIME_QUALIFIED requires observed"})
    rec["financial_reconciliation"] = build_financial_reconciliation(baseline, baseline, credit_pool_usd="29.9620", reserve_usd="5.00", max_run_cost_usd="1.0828", peak_billed_usd="0E-8")
    (tmp_path / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json").write_text(json.dumps(rec))
    (tmp_path / f"GENESIS_CONTROL_QWEN3_8B_ATTEMPTS_{mod.DATE_TAG}.json").write_text(json.dumps({"control_name": "Qwen3-8B", "attempts": history + [attempt]}))
    if tamper_before:
        (tmp_path / "synthetic_billing_before.json").write_text("{}")
    monkeypatch.setattr(mod, "billing_summary", lambda: _rc_summary(metered_now, credits_now, billed_now, eph=eph_now))
    monkeypatch.setattr(mod, "cleanup_snapshot", lambda: {"live_resources": live, "containers": [], "apps": [], "volumes": []})
    monkeypatch.setattr(mod, "_app_row", lambda name, app_id: {"app_id": _RECON_APP_ID, "state": app_state, "tasks": "0"})
    report_rows = [{"object_id": _RECON_APP_ID, "description": "orneur-p21b420-h100-control-runtime", "cost": run_cost, "interval_start": "2026-09-24T20:00:00"},
                   {"object_id": "ap-OTHER", "description": "orneur-p21b420-h100-control-runtime", "cost": "9.99", "interval_start": "2026-09-24T19:00:00"}] if rows is None else rows
    monkeypatch.setattr(mod, "_cli_json", lambda *args: report_rows)
    for banned in ("serve_and_smoke", "precache"):
        monkeypatch.setattr(mod, banned, types.SimpleNamespace(remote=lambda *a, **k: (_ for _ in ()).throw(AssertionError("reconcile must not start a Modal function"))), raising=False)
    monkeypatch.setattr(mod.app, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("reconcile must not open a Modal app run")), raising=False)
    return mod, rec


def _rc_args(mod, attempt=4):
    return types.SimpleNamespace(control="qwen3_8b", attempt=attempt)


def _rc_record(tmp_path):
    return json.loads((tmp_path / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())


def _rc_artifacts(tmp_path):
    return sorted(tmp_path.glob("GENESIS_CONTROL_QWEN3_8B_ATTEMPT4_SETTLEMENT_RECONCILIATION_*.json"))


def test_reconcile_mode_is_read_only_by_construction():
    tree = ast.parse(MODAL_H100.read_text())
    src = ast.unparse(next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "cmd_reconcile"))
    fin_src = ast.unparse(next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_finalize_record"))
    for body in (src, fin_src):
        for banned in ("serve_and_smoke", ".remote(", "app.run", ".spawn(", "precache", "eval(", "exec(", "compile(", "os.system", "shell=True", "subprocess",
                       "Sandbox", "WAIVER", "waiver_path"):
            assert banned not in body, banned
    assert "no_gpu_started" in src and "no_modal_function_called" in src


def test_reconcile_unknown_attempt_fails_closed(monkeypatch, tmp_path):
    mod, _ = _reconcile_env(monkeypatch, tmp_path)
    before = _rc_record(tmp_path)
    assert mod.cmd_reconcile(_rc_args(mod, attempt=9)) == 2
    assert mod.cmd_reconcile(_rc_args(mod, attempt=1)) == 2                     # attempt 1 is not a Modal H100 attempt in this history
    assert _rc_artifacts(tmp_path) == [] and _rc_record(tmp_path) == before


def test_reconcile_still_unobservable_keeps_qualification_pending_and_labels_honestly(monkeypatch, tmp_path):
    mod, _ = _reconcile_env(monkeypatch, tmp_path, metered_now="20.08000000", credits_now="-20.08000000", rows=[])
    assert mod.cmd_reconcile(_rc_args(mod)) == 5
    art = json.loads(_rc_artifacts(tmp_path)[0].read_text())
    assert art["settlement"]["status"] == "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE" and art["verdict"] == "SETTLEMENT_STILL_NOT_OBSERVABLE"
    assert art["no_gpu_started"] is True and art["no_modal_function_called"] is True and art["owner_billed_delta_usd"] == "0E-8"
    rec = _rc_record(tmp_path)
    assert rec["runtime_qualification_status"] == "PENDING_SETTLEMENT_OBSERVATION" and rec["technical_serving_status"] == "QUALIFIED"
    assert rec["status_correction"]["to"] == "PENDING_SETTLEMENT_OBSERVATION" and rec["original_validator_note"]
    validate_control_runtime_record(rec, evidence_root=tmp_path)
    assert mod.settlement_resolved("QWEN3_8B", rec["attempts"][-1]) is False    # the next control stays blocked


def test_reconcile_observed_finalizes_without_rerunning_and_preserves_original_evidence(monkeypatch, tmp_path):
    mod, before = _reconcile_env(monkeypatch, tmp_path)
    assert mod.cmd_reconcile(_rc_args(mod)) == 0
    art_path = _rc_artifacts(tmp_path)[0]
    art = json.loads(art_path.read_text())
    assert art["settlement"]["status"] == "OBSERVED" and art["itemized_run_cost_usd"] == "0.23000000"      # only this app's rows, not ap-OTHER
    assert art["promotional_credit_delta_attributable_usd"] == "0.23000000" and art["owner_cash_delta_usd"] == "0E-8"
    assert art["waiver_applies"] is False and art["live_resources"] == 0 and art["cache_volume_counted_as_live_resource"] is False
    rec = _rc_record(tmp_path)
    assert rec["runtime_qualification_status"] == "RUNTIME_QUALIFIED" and rec["billing_settlement"]["status"] == "OBSERVED"
    assert rec["original_in_run_billing_settlement"]["status"] == "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE"      # the in-run delay stays historical truth
    assert rec["attempts"] == before["attempts"] and rec["smoke_outputs"] == before["smoke_outputs"] and rec["raw_log_sha256"] == before["raw_log_sha256"]
    assert rec["generated_output_executed"] is False and rec["capability_status"] == "UNPROVEN"
    assert rec["settlement_reconciliation"]["sha256"] == hashlib.sha256(art_path.read_bytes()).hexdigest()
    assert rec["settlement_reconciliation"]["promotional_credit_used_usd"] == "0.23000000" and rec["owner_billed_delta_usd"] == "0E-8"
    validate_control_runtime_record(rec, evidence_root=tmp_path)
    assert mod.settlement_resolved("QWEN3_8B", rec["attempts"][-1]) is True    # now unlocks the next control via evidence, not a waiver


def test_reconcile_refuses_positive_owner_billing(monkeypatch, tmp_path):
    mod, before = _reconcile_env(monkeypatch, tmp_path, billed_now="0.01000000")
    assert mod.cmd_reconcile(_rc_args(mod)) == 4
    art = json.loads(_rc_artifacts(tmp_path)[0].read_text())
    assert art["settlement"]["status"] == "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE" and art["owner_billed_delta_usd"] != "0E-8"
    assert _rc_record(tmp_path) == before                                       # nothing finalized


def test_reconcile_requires_zero_live_resources_and_a_stopped_app(monkeypatch, tmp_path):
    for kw in ({"live": 1}, {"app_state": "running"}):
        mod, before = _reconcile_env(monkeypatch, tmp_path, **kw)
        assert mod.cmd_reconcile(_rc_args(mod)) == 5
        assert _rc_record(tmp_path)["runtime_qualification_status"] == "PENDING_SETTLEMENT_OBSERVATION"


def test_reconcile_will_not_attribute_unexplained_metered_growth_to_the_run(monkeypatch, tmp_path):
    mod, _ = _reconcile_env(monkeypatch, tmp_path, metered_now="20.50000000", credits_now="-20.50000000")   # 0.42 grew, only 0.23 itemized to the app
    assert mod.cmd_reconcile(_rc_args(mod)) == 5
    art = json.loads(_rc_artifacts(tmp_path)[0].read_text())
    assert art["settlement"]["status"] == "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE" and any("cannot be attributed" in r for r in art["settlement"]["reasons"])


def test_reconcile_detects_tampered_original_evidence(monkeypatch, tmp_path):
    mod, _ = _reconcile_env(monkeypatch, tmp_path, tamper_before=True)
    assert mod.cmd_reconcile(_rc_args(mod)) == 6 and _rc_artifacts(tmp_path) == []


def test_attempt_1_owner_waiver_never_applies_to_attempt_4(monkeypatch, tmp_path):
    mod, _ = _reconcile_env(monkeypatch, tmp_path, metered_now="20.08000000", credits_now="-20.08000000", rows=[])
    (tmp_path / f"GENESIS_OWNER_SETTLEMENT_WAIVER_QWEN3_8B_ATTEMPT1_{mod.DATE_TAG}.json").write_text(json.dumps(_valid_waiver()))
    (tmp_path / f"GENESIS_OWNER_SETTLEMENT_WAIVER_QWEN3_8B_ATTEMPT4_{mod.DATE_TAG}.json").write_text(json.dumps(_valid_waiver()))
    a4 = _rc_record(tmp_path)["attempts"][-1]
    assert mod.validate_owner_settlement_waiver("QWEN3_8B", a4)[0] == "WAIVER_ABSENT" and mod.settlement_resolved("QWEN3_8B", a4) is False


def test_validator_rejects_a_delayed_settlement_finalization_without_a_verified_reconciliation_artifact(tmp_path):
    rec = _qualified_record(tmp_path)
    rec["original_in_run_billing_settlement"] = {"status": SETTLEMENT_NOT_OBSERVABLE, "reasons": ["lag"]}
    with pytest.raises(ControlRuntimeError, match="reconciliation artifact"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    art = {"attempt_number": 1, "settlement": {"status": "OBSERVED"}, "live_resources": 0, "owner_billed_delta_usd": "0"}
    sha = _write(tmp_path / "recon.json", json.dumps(art).encode())
    rec["settlement_reconciliation"] = {"artifact": "recon.json", "sha256": sha}
    validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec["settlement_reconciliation"]["sha256"] = "0" * 64
    with pytest.raises(ControlRuntimeError, match="hash"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    art["live_resources"] = 1
    rec["settlement_reconciliation"]["sha256"] = _write(tmp_path / "recon.json", json.dumps(art).encode())
    with pytest.raises(ControlRuntimeError, match="zero live resources"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


def test_reconcile_uses_the_exact_metered_breakdown_because_account_totals_are_rounded_to_the_cent(monkeypatch, tmp_path):
    # totals show 20.08 -> 20.31 (0.23) but the exact per-category growth is 0.22772907, which the app's own row explains exactly
    mod, _ = _reconcile_env(monkeypatch, tmp_path, eph_before="20.07689253", eph_now="20.30462160", run_cost="0.22772907")
    assert mod.cmd_reconcile(_rc_args(mod)) == 0
    art = json.loads(_rc_artifacts(tmp_path)[0].read_text())
    assert art["metered_delta_precise_usd"] == "0.22772907" and art["itemized_run_cost_usd"] == "0.22772907" and art["settlement"]["status"] == "OBSERVED"
    assert _rc_record(tmp_path)["settlement_reconciliation"]["promotional_credit_used_usd"] == "0.22772907"


def test_reconcile_still_refuses_when_the_exact_breakdown_shows_unexplained_growth(monkeypatch, tmp_path):
    mod, _ = _reconcile_env(monkeypatch, tmp_path, eph_before="20.07689253", eph_now="20.30462160", run_cost="0.20000000")
    assert mod.cmd_reconcile(_rc_args(mod)) == 5 and _rc_record(tmp_path)["runtime_qualification_status"] == "PENDING_SETTLEMENT_OBSERVATION"


# ── locked smoke semantics (audit finding: HTTP 200 + non-empty is NOT acceptance) ──
def _with_smoke(tmp_path, sid, content):
    rec = _qualified_record(tmp_path)
    for o in rec["smoke_outputs"]:
        if o["smoke_id"] == sid:
            o["raw_response"] = json.dumps({"content": content})
            o["raw_response_sha256"] = hashlib.sha256(o["raw_response"].encode()).hexdigest()
    return rec


@pytest.mark.parametrize("sid,content", [
    ("A", "Ready"), ("A", "READY."), ("A", "The word is READY"), ("A", "READY READY"), ("A", ""), ("A", "anything non-empty"),
    ("B", "The result of adding 2 and 3 is 5.\n\n**Answer:** 5"), ("B", "5."), ("B", "five"), ("B", "The answer is 5"), ("B", "$$2 + 3 = 5$$"), ("B", "6"),
    ("C", "{status: ready}"), ("C", "not json"), ("C", '{"status":"ready","extra":1}'), ("C", '{"status":"READY"}'), ("C", '```json\n{"status":"ready"}\n```'),
    ("C", '["status","ready"]'), ("C", '{"status":"ready"} trailing'),
])
def test_locked_smoke_wrong_or_verbose_output_blocks_runtime_qualified(tmp_path, sid, content):
    rec = _with_smoke(tmp_path, sid, content)
    assert rec["smoke_outputs"] and all(o["http_status"] == 200 and o["raw_response"] for o in rec["smoke_outputs"])      # HTTP 200 + non-empty is present
    with pytest.raises(ControlRuntimeError, match="LOCKED (smoke|protocol)"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


@pytest.mark.parametrize("sid,content", [
    ("A", "READY"), ("A", "\n\nREADY\n"), ("A", "  READY  "), ("B", "5"), ("B", "\n 5 \n"), ("B", "\t5"),
    ("C", '{"status":"ready"}'), ("C", '\n\n{"status":"ready"}\n'), ("C", '{ "status" : "ready" }'),
])
def test_locked_smoke_exact_outputs_with_only_surrounding_whitespace_pass(tmp_path, sid, content):
    validate_control_runtime_record(_with_smoke(tmp_path, sid, content), evidence_root=tmp_path)


def test_locked_smoke_acceptance_is_derived_from_raw_output_not_a_stored_flag_or_forged_summary(tmp_path):
    rec = _with_smoke(tmp_path, "B", "a verbose answer that ends in 5")
    for o in rec["smoke_outputs"]:
        o["matches_expected_exactly"] = True                                             # a forged boolean changes nothing
    with pytest.raises(ControlRuntimeError, match="LOCKED (smoke|protocol)"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["smoke_outputs"][1]["content"] = "5"                                             # persisted summary disagreeing with the raw response
    rec["smoke_outputs"][1]["raw_response"] = json.dumps({"content": "verbose 5"})
    rec["smoke_outputs"][1]["raw_response_sha256"] = hashlib.sha256(rec["smoke_outputs"][1]["raw_response"].encode()).hexdigest()
    with pytest.raises(ControlRuntimeError, match="LOCKED (smoke|protocol)"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["smoke_acceptance"] = [{"smoke_id": s, "accepted": False} for s in ("A", "B", "C")]
    with pytest.raises(ControlRuntimeError, match="smoke_acceptance"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


def test_openai_chat_shaped_raw_response_is_read_from_choices(tmp_path):
    rec = _qualified_record(tmp_path)
    raw = json.dumps({"choices": [{"message": {"role": "assistant", "content": "\n\n5", "reasoning": "long thinking"}}]})
    rec["smoke_outputs"][1].update(raw_response=raw, raw_response_sha256=hashlib.sha256(raw.encode()).hexdigest(), content="\n\n5")
    validate_control_runtime_record(rec, evidence_root=tmp_path)


PERSISTED_QWEN_SMOKE_OUTPUTS_SHA256 = "88909b4935ba571da2275835428cba8221b05caba264a4902122e192b6e8a4b4"


def _persisted_qwen():
    """The CURRENT Qwen3-8B record (final attempt 5, after the authorized non-thinking run)."""
    return json.loads((EVIDENCE_DIR / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())


def _attempt4_record():
    """The preserved byte-identical snapshot of the Qwen3-8B record as it stood after attempt 4."""
    return json.loads((EVIDENCE_DIR / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_ATTEMPT4_SNAPSHOT_2026-09-24.json").read_text())


def test_persisted_qwen_attempt_4_cannot_be_runtime_qualified_with_its_existing_smoke_b_output():
    rec = _attempt4_record()
    acc = {a["smoke_id"]: a for a in compute_smoke_acceptance(rec)}
    assert acc["A"]["accepted"] and acc["C"]["accepted"] and acc["B"]["accepted"] is False
    forced = copy.deepcopy(rec)
    forced.update(technical_serving_status="QUALIFIED", runtime_qualification_status="RUNTIME_QUALIFIED")
    with pytest.raises(ControlRuntimeError, match="LOCKED (smoke|protocol)"):
        validate_control_runtime_record(forced, evidence_root=EVIDENCE_DIR)
    assert rec["runtime_qualification_status"] == "FAILED" and rec["technical_serving_status"] == "FAILED"     # the honest derived status
    validate_control_runtime_record(rec, evidence_root=EVIDENCE_DIR)
    assert rec["attempts"][-1]["outcome"] == "TECHNICAL_FAILURE" and rec["attempts"][-1]["valid_runtime_attempt"] is True
    assert rec["attempts"][-1]["original_classification"]["outcome"] == "TECHNICAL_SUCCESS"                   # history of the original judgement kept
    assert rec["failure_analysis"]["kind"].startswith("LOCKED_SMOKE_CONTRACT_NOT_MET") and rec["capability_status"] == "UNPROVEN"


def test_persisted_qwen_raw_evidence_financials_and_no_execution_are_unchanged():
    rec = _attempt4_record()
    canon = hashlib.sha256(json.dumps(rec["smoke_outputs"], sort_keys=True).encode()).hexdigest()
    assert canon == PERSISTED_QWEN_SMOKE_OUTPUTS_SHA256                                    # raw smoke outputs byte-for-byte as first persisted
    assert rec["raw_log_sha256"] == "068332b340ddcf73d1d61e326c1e95646a610ac6864b2a47848cf218355d5bbd"
    assert hashlib.sha256((EVIDENCE_DIR / rec["raw_log_artifact"]).read_bytes()).hexdigest() == rec["raw_log_sha256"]
    assert all(o["executed"] is False for o in rec["smoke_outputs"]) and rec["generated_output_executed"] is False
    ref = rec["settlement_reconciliation"]
    art_path = EVIDENCE_DIR / ref["artifact"]
    assert hashlib.sha256(art_path.read_bytes()).hexdigest() == ref["sha256"]
    art = json.loads(art_path.read_text())
    assert rec["financial_reconciliation"] == art["financial_reconciliation"] and rec["billing_settlement"]["status"] == "OBSERVED"
    assert ref["promotional_credit_used_usd"] == "0.22772907" and rec["owner_billed_delta_usd"] == "0E-8"
    assert rec["original_in_run_billing_settlement"]["status"] == "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE"     # in-run delay stays historical truth


def test_smoke_acceptance_functions_never_execute_generated_text():
    tree = ast.parse((REPO_ROOT / "orca/eval/control_runtime_qualification.py").read_text())
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in {"smoke_locked_acceptance", "extract_smoke_content", "compute_smoke_acceptance", "_check_locked_smokes"}):
        body = ast.unparse(fn)
        for banned in ("eval(", "exec(", "compile(", "os.system", "subprocess", "__import__", "importlib", "pickle"):
            assert banned not in body, (fn.name, banned)


def test_modal_harness_run_judges_technical_success_by_the_locked_smoke_semantics():
    text = MODAL_H100.read_text()
    run = ast.unparse(next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and n.name == "cmd_run"))
    assert "smoke_locked_acceptance" in run and "smokes_ok" in run and "compute_smoke_acceptance" in run


def _rc_finalized_env(monkeypatch, tmp_path):
    mod, before = _reconcile_env(monkeypatch, tmp_path)
    assert mod.cmd_reconcile(_rc_args(mod)) == 0
    return mod


def _degrade_b(tmp_path):
    p = tmp_path / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json"
    rec = json.loads(p.read_text())
    o = rec["smoke_outputs"][1]
    o["raw_response"] = json.dumps({"content": "\n\nThe result is calculated by adding.\n\n**Answer:** 5"})
    o["raw_response_sha256"] = hashlib.sha256(o["raw_response"].encode()).hexdigest()
    p.write_text(json.dumps(rec))
    return rec


def test_reevaluate_smokes_reclassifies_a_verbose_b_without_touching_raw_evidence_or_financials(monkeypatch, tmp_path):
    mod = _rc_finalized_env(monkeypatch, tmp_path)
    before = _degrade_b(tmp_path)
    assert mod.cmd_reevaluate_smokes(_rc_args(mod)) == 0
    after = _rc_record(tmp_path)
    assert after["technical_serving_status"] == "FAILED" and after["runtime_qualification_status"] == "FAILED" and after["runtime_qualification_status"] != "RUNTIME_QUALIFIED"
    assert after["smoke_outputs"] == before["smoke_outputs"] and after["raw_log_sha256"] == before["raw_log_sha256"]
    assert after["financial_reconciliation"] == before["financial_reconciliation"] and after["billing_settlement"] == before["billing_settlement"]
    assert after["settlement_reconciliation"] == before["settlement_reconciliation"] and after["owner_billed_delta_usd"] == before["owner_billed_delta_usd"]
    last = after["attempts"][-1]
    assert last["outcome"] == "TECHNICAL_FAILURE" and last["failure_domain"] == "MODEL_RUNTIME" and last["original_classification"]["outcome"] == "TECHNICAL_SUCCESS"
    assert [(a["smoke_id"], a["accepted"]) for a in after["smoke_acceptance"]] == [("A", True), ("B", False), ("C", True)]
    attempts_file = json.loads((tmp_path / f"GENESIS_CONTROL_QWEN3_8B_ATTEMPTS_{mod.DATE_TAG}.json").read_text())["attempts"]
    assert attempts_file[-1] == last and attempts_file[:-1] == after["attempts"][:-1]
    validate_control_runtime_record(after, evidence_root=tmp_path)


def test_reevaluate_smokes_leaves_a_fully_compliant_record_qualified(monkeypatch, tmp_path):
    mod = _rc_finalized_env(monkeypatch, tmp_path)
    assert mod.cmd_reevaluate_smokes(_rc_args(mod)) == 0
    after = _rc_record(tmp_path)
    assert after["runtime_qualification_status"] == "RUNTIME_QUALIFIED" and after["technical_serving_status"] == "QUALIFIED" and all(a["accepted"] for a in after["smoke_acceptance"])


def test_reevaluate_smokes_is_cpu_only_and_refuses_the_wrong_attempt(monkeypatch, tmp_path):
    body = ast.unparse(next(n for n in ast.walk(ast.parse(MODAL_H100.read_text())) if isinstance(n, ast.FunctionDef) and n.name == "cmd_reevaluate_smokes"))
    for banned in ("serve_and_smoke", ".remote(", "app.run", "billing_summary", "_cli_json", "subprocess", "eval(", "exec("):
        assert banned not in body, banned
    mod = _rc_finalized_env(monkeypatch, tmp_path)
    assert mod.cmd_reevaluate_smokes(_rc_args(mod, attempt=3)) == 2


def test_every_phase_21b_4_20_modal_h100_evidence_file_is_in_the_sha256_index():
    index = json.loads(INDEX_PATH.read_text())
    indexed = {e["path"] for e in index["entries"]}
    patterns = ("*MODAL_H100*", "*MODAL_PRECACHE_MANIFEST*", "*OWNER_SETTLEMENT_WAIVER*", "*ATTEMPT4*", "*SETTLEMENT_RECONCILIATION*",
                "GENESIS_CONTROL_*_RUNTIME_QUALIFICATION_2026-09-24.json", "GENESIS_CONTROL_*_ATTEMPTS_2026-09-24.json", "*NON_THINKING_V1*", "*SNAPSHOT*")
    missing = sorted({str(p.relative_to(REPO_ROOT)) for pat in patterns for p in EVIDENCE_DIR.glob(pat)} - indexed)
    assert not missing, missing
    assert any("GPU_PREFLIGHT_2026-09-24T205041Z" in p for p in indexed)


# ── CPU-only Qwen3-8B runtime-configuration analysis (no GPU; decision document, not a qualification) ──
QWEN_ANALYSIS = EVIDENCE_DIR / "GENESIS_QWEN3_8B_RUNTIME_CONFIGURATION_ANALYSIS_2026-09-25.json"


def test_qwen_configuration_analysis_is_cpu_only_and_identity_preserving():
    a = json.loads(QWEN_ANALYSIS.read_text())
    assert a["no_gpu_used"] and a["no_modal_used"] and a["no_model_loaded"] and a["no_generation"] and a["generated_output_executed"] is False
    assert a["model"] == {"model_id": "Qwen/Qwen3-8B", "revision": LOCKED_CONTROL_IDENTITIES["Qwen3-8B"]["revision"], "precision": "bfloat16", "quantization": None}
    ans = a["answers"]["5"]
    assert [ans[k] for k in ("model_weights_change", "revision_change", "precision_change", "quantization_change")] == ["NO"] * 4
    assert ans["serving_runtime_change"].startswith("NO") and ans["only_chat_template_request_behavior"].startswith("YES")
    assert a["model_identity"]["identical"] is True and a["is_new_runtime_configuration_requiring_fresh_qualification"]["answer"] == "YES"
    assert a["decision"].startswith("A.") and a["candidate_configuration"]["request_setting"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert a["qwen3_8b_status_unchanged"]["runtime_qualification_status"] == "FAILED"
    assert "not authorized" in json.dumps(a["future_attempt_proposal_NOT_IMPLEMENTED_NOT_AUTHORIZED"]).lower() or "NOT_AUTHORIZED" in json.dumps(a)


def test_qwen_configuration_analysis_keeps_the_locked_smoke_prompts_and_only_appends_an_empty_think_block():
    a = json.loads(QWEN_ANALYSIS.read_text())
    persisted = {p["smoke_id"]: p["messages"] for p in _attempt4_record()["smoke_prompts"]}     # the earlier analysis rendered what attempt 4 sent
    for sid, r in a["rendered_locked_requests"].items():
        assert r["messages_unchanged"] == persisted[sid]                                   # the locked prompts are not rewritten
        assert r["candidate_enable_thinking_false"] == r["current_thinking_default"] + "<think>\n\n</think>\n\n"
        assert r["current_thinking_default"].endswith("<|im_start|>assistant\n")


def test_qwen_configuration_analysis_facts_are_proven_from_hashed_pinned_sources():
    a = json.loads(QWEN_ANALYSIS.read_text())
    assert a["chat_template"]["supports_enable_thinking"] and a["chat_template"]["template_contains_no_think_soft_switch_logic"]
    assert a["sources"]["tokenizer_config.json"]["url"].split("/resolve/")[1].startswith(LOCKED_CONTROL_IDENTITIES["Qwen3-8B"]["revision"])
    assert all(len(s["sha256"]) == 64 for s in a["sources"].values()) and a["vllm"]["commit"] in a["sources"]["vllm/parser/qwen3.py"]["url"]
    path = a["vllm_0_29_0_path"]
    assert "chat_kwargs.get(\"enable_thinking\", True)" in path["qwen3_parser_reads_enable_thinking"]["text"]
    assert "ParserState.CONTENT" in path["qwen3_parser_initial_state"]["text"]
    assert "chat_template_kwargs" in path["same_kwargs_given_to_parser"]["text"] and "_engine_chat_template_kwargs" in path["same_kwargs_given_to_engine_template"]["anchor"]
    assert a["current_configuration"]["server_argv"][-2:] == ["--reasoning-parser", "qwen3"] and "UNCHANGED" in a["candidate_configuration"]["server_argv"]


def test_qwen_configuration_analysis_script_is_cpu_only_and_executes_nothing():
    text = (REPO_ROOT / "scripts/phase21b_4_20_qwen_config_analysis.py").read_text()
    for banned in ("import modal", "import torch", "import vllm", "subprocess", "os.system", "eval(", "exec(", "shell=True"):
        assert banned not in text, banned
    assert "ImmutableSandboxedEnvironment" in text


# ══ canonical LOCKED smoke protocol: ONE source of truth (governance drift fix) ═══════════════════════
LOCKED_PROTOCOL_FILE = REPO_ROOT / "orca/eval/locked_smoke_protocol.py"
CANONICAL_PROTOCOL_SHA256 = "d462103b607e9741786ef86afc0b1769d5857d6e7feef36de516dac87a2b25c1"
CANONICAL_USER_TEXT = {"A": "Reply exactly:\nREADY", "B": "2 + 3", "C": 'Return valid JSON:\n{"status":"ready"}'}       # written independently of the module on purpose
DRIFTED_USER_TEXT = ("Reply with exactly:\nREADY", "Return the single integer result of:\n2 + 3", 'Return valid JSON with one field:\n{"status":"ready"}')
ATTEMPT_4_PROMPTS_SHA256 = "afcdec5f49964d38d47d0e35e0f408b92c8ef3401e5393475ad6498b3c065c80"


def test_canonical_smoke_texts_are_exactly_the_owner_locked_wording():
    assert locked_protocol.smoke_ids() == ("A", "B", "C")
    for sid, text in CANONICAL_USER_TEXT.items():
        assert locked_protocol.messages(sid) == [{"role": "user", "content": text}]
        assert locked_protocol.prompt_utf8(sid) == text.encode("utf-8")
        assert locked_protocol.prompt_sha256(sid) == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert locked_protocol.messages("A")[0]["content"] == "Reply exactly:\nREADY"
    assert locked_protocol.messages("B")[0]["content"] == "2 + 3"
    assert locked_protocol.messages("C")[0]["content"] == 'Return valid JSON:\n{"status":"ready"}'
    assert [d["stream"] for d in locked_protocol.SMOKE_DEFINITIONS] == [True, False, False]
    assert locked_protocol.protocol_sha256() == locked_protocol.PINNED_PROTOCOL_SHA256 == CANONICAL_PROTOCOL_SHA256
    assert locked_protocol.canonical_protocol_bytes().decode("utf-8").count("Reply exactly") == 1
    for drifted in DRIFTED_USER_TEXT:
        assert drifted.encode() not in locked_protocol.canonical_protocol_bytes().replace(b"\\n", b"\n") and drifted not in CANONICAL_USER_TEXT.values()


def _mutations():
    for sid, text in CANONICAL_USER_TEXT.items():
        for name, changed in filter(lambda nc: nc[1] != text, (("append_char", text + "."), ("drop_last_char", text[:-1]), ("case_change", text.swapcase()), ("trailing_newline", text + "\n"),
                              ("leading_space", " " + text), ("replace_first_char", "X" + text[1:]), ("nbsp", text.replace(" ", "\u00a0") if " " in text else text + "\u00a0"))):
            yield sid, name, changed


@pytest.mark.parametrize("sid,name,changed", list(_mutations()))
def test_any_one_character_change_to_a_locked_prompt_changes_the_fingerprint_and_fails_closed(sid, name, changed):
    defs = copy.deepcopy(locked_protocol.SMOKE_DEFINITIONS)
    for d in defs:
        if d["smoke_id"] == sid:
            d["user"] = changed
    assert locked_protocol.protocol_sha256(defs) != CANONICAL_PROTOCOL_SHA256
    assert locked_protocol.prompt_sha256(sid, defs) != locked_protocol.prompt_sha256(sid)
    with pytest.raises(RuntimeError, match="drift"):
        locked_protocol.verify_protocol_integrity(defs)
    # the same edit made to the module source stops every consumer at import time
    original = LOCKED_PROTOCOL_FILE.read_text()
    node = next(n for n in ast.walk(ast.parse(original)) if isinstance(n, ast.Constant) and n.value == CANONICAL_USER_TEXT[sid])
    lines = original.splitlines(keepends=True)
    assert node.lineno == node.end_lineno
    line = lines[node.lineno - 1]
    lines[node.lineno - 1] = line[:node.col_offset] + repr(changed) + line[node.end_col_offset:]
    src = "".join(lines)
    assert src != original
    ns: dict = {"__name__": "drift_probe"}
    with pytest.raises(RuntimeError, match="drift"):
        exec(compile(src, "drift_probe", "exec"), ns)          # test-only probe of the module's own import-time integrity check


@pytest.mark.parametrize("field,value", [("expected", "READY."), ("stream", False)])
def test_changing_expected_acceptance_or_request_mode_also_changes_the_fingerprint(field, value):
    defs = copy.deepcopy(locked_protocol.SMOKE_DEFINITIONS)
    if field == "expected":
        defs[0]["acceptance"]["expected"] = value
    else:
        defs[0]["stream"] = value
    assert locked_protocol.protocol_sha256(defs) != CANONICAL_PROTOCOL_SHA256
    defs = copy.deepcopy(locked_protocol.SMOKE_DEFINITIONS)
    defs[2]["acceptance"] = {"kind": "exact_text", "expected": '{"status":"ready"}'}
    assert locked_protocol.protocol_sha256(defs) != CANONICAL_PROTOCOL_SHA256


def test_the_protocol_document_persists_messages_bytes_and_hashes():
    doc = locked_protocol.protocol_document()
    assert doc["protocol_sha256"] == CANONICAL_PROTOCOL_SHA256 == hashlib.sha256(locked_protocol.canonical_protocol_bytes()).hexdigest()
    for p in doc["prompts"]:
        text = CANONICAL_USER_TEXT[p["smoke_id"]]
        assert p["messages"] == [{"role": "user", "content": text}] and bytes.fromhex(p["utf8_hex"]) == text.encode("utf-8")
        assert p["sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    persisted = json.loads((EVIDENCE_DIR / "GENESIS_LOCKED_SMOKE_PROTOCOL_2026-09-25.json").read_text())
    assert persisted["protocol"] == doc and persisted["protocol_sha256"] == CANONICAL_PROTOCOL_SHA256 == persisted["pinned_in_module"]
    drift = persisted["wording_history"]["earlier_runner_wording_drift"]
    assert tuple(drift["messages"].values()) == DRIFTED_USER_TEXT and drift["protocol_sha256_as_run"] != CANONICAL_PROTOCOL_SHA256


def test_runner_both_modal_harnesses_validator_and_record_builder_consume_the_same_definitions(monkeypatch):
    canonical = locked_protocol.runner_smokes()
    runner = _runner_module()
    assert runner.SMOKES == canonical and runner.LOCKED_PROTOCOL.protocol_sha256() == CANONICAL_PROTOCOL_SHA256
    legacy = importlib.util.spec_from_file_location("p21b420_legacy_consts", HARNESS_PATH)
    stub = types.ModuleType("modal")
    stub.Image = type("Image", (), {"from_registry": classmethod(lambda cls, *a, **k: cls()), "entrypoint": lambda self, _c: self})
    stub.App = lambda n: types.SimpleNamespace(name=n, function=lambda **k: (lambda f: f))
    stub.exception = types.SimpleNamespace(TimeoutError=TimeoutError)
    monkeypatch.setitem(sys.modules, "modal", stub)
    mod = importlib.util.module_from_spec(legacy)
    legacy.loader.exec_module(mod)
    assert mod.SMOKES == canonical and mod.LOCKED_PROTOCOL.protocol_sha256() == CANONICAL_PROTOCOL_SHA256
    h100, calls = _load_modal_h100(monkeypatch)
    assert h100.PROTOCOL_FILE == LOCKED_PROTOCOL_FILE and (str(LOCKED_PROTOCOL_FILE), "/root/locked_smoke_protocol.py") in [tuple(c) for c in calls["local_files"]]
    assert h100.locked_protocol.protocol_sha256() == CANONICAL_PROTOCOL_SHA256
    lc_spec = importlib.util.spec_from_file_location("p21b420_lc_for_protocol", LIGHTNING_CONTROL)
    lc = importlib.util.module_from_spec(lc_spec)
    lc_spec.loader.exec_module(lc)
    assert lc.CONSTS.SMOKES == canonical and lc.LOCKED_PROTOCOL.protocol_document() == locked_protocol.protocol_document()
    import orca.eval.control_runtime_qualification as v
    assert v.REQUIRED_SMOKE_IDS == locked_protocol.smoke_ids() and v._locked is locked_protocol
    assert v.LOCKED_SMOKE_EXPECTATIONS == {d["smoke_id"]: d["acceptance"]["expected"] for d in locked_protocol.SMOKE_DEFINITIONS}


_ACCEPTANCE_PROBES = ["READY", "\n\nREADY\n", "Ready", "READY.", "5", " 5 ", "5.", "The answer is 5", "", "  ", '{"status":"ready"}', '\n{ "status" : "ready" }\n',
                      '{"status":"ready","x":1}', '{"status":"READY"}', "not json", '["status","ready"]', '```json\n{"status":"ready"}\n```', "null", "1"]


@pytest.mark.parametrize("probe", _ACCEPTANCE_PROBES)
def test_the_runner_and_legacy_harness_call_the_canonical_acceptance_directly(probe, monkeypatch):
    runner = _runner_module()
    stub = types.ModuleType("modal")
    stub.Image = type("Image", (), {"from_registry": classmethod(lambda cls, *a, **k: cls()), "entrypoint": lambda self, _c: self})
    stub.App = lambda n: types.SimpleNamespace(name=n, function=lambda **k: (lambda f: f))
    stub.exception = types.SimpleNamespace(TimeoutError=TimeoutError)
    monkeypatch.setitem(sys.modules, "modal", stub)
    spec = importlib.util.spec_from_file_location("p21b420_legacy_helper", HARNESS_PATH)
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    assert not hasattr(runner, "_meets_acceptance") and not hasattr(legacy, "_meets_acceptance")          # the duplicate implementation is gone
    for sid in locked_protocol.smoke_ids():
        want = locked_protocol.acceptance(sid, probe)
        assert runner.LOCKED_PROTOCOL.acceptance(sid, probe) == want == legacy.LOCKED_PROTOCOL.acceptance(sid, probe)
        assert smoke_locked_acceptance(sid, probe) == want


def test_the_serving_bodies_call_the_canonical_acceptance_and_share_one_payload_builder():
    for path in (LIGHTNING_RUNNER, HARNESS_PATH):
        body = _fn_source(path, "serve_and_smoke")
        assert 'LOCKED_PROTOCOL.acceptance(smoke["smoke_id"], entry.get("content", ""))[0]' in body and "build_chat_payload(cfg, smoke, gen_cfg)" in body
        assert "_meets_acceptance" not in path.read_text()
    assert _fn_source(LIGHTNING_RUNNER, "build_chat_payload") == _fn_source(HARNESS_PATH, "build_chat_payload")


def test_no_hand_written_smoke_string_exists_outside_the_canonical_module():
    banned = list(CANONICAL_USER_TEXT.values()) + list(DRIFTED_USER_TEXT)
    scanned = sorted(REPO_ROOT.glob("scripts/phase21b_4_20_*.py")) + [REPO_ROOT / "orca/eval/control_runtime_qualification.py"]
    assert len(scanned) >= 6
    for path in scanned:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for b in banned:
                    assert node.value != b, (path.name, b)
                assert not any(k in node.value for k in ("Reply exactly", "Reply with exactly", "single integer result")), (path.name, node.value[:60])


def test_qwen_configuration_analysis_uses_the_canonical_protocol_and_cannot_substitute_prompts():
    v2 = json.loads((EVIDENCE_DIR / "GENESIS_QWEN3_8B_RUNTIME_CONFIGURATION_ANALYSIS_V2_CANONICAL_PROMPTS_2026-09-25.json").read_text())
    assert v2["locked_smoke_protocol_sha256"] == CANONICAL_PROTOCOL_SHA256 and v2["decision"].startswith("A.")
    for sid, r in v2["rendered_locked_requests"].items():
        text = CANONICAL_USER_TEXT[sid]
        assert r["messages_unchanged"] == [{"role": "user", "content": text}]
        assert r["current_thinking_default"] == f"<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n"
        assert r["candidate_enable_thinking_false"] == r["current_thinking_default"] + "<think>\n\n</think>\n\n"
        assert locked_protocol.prompt_sha256(sid) == v2["locked_smoke_prompt_sha256"][sid]
    text = (REPO_ROOT / "scripts/phase21b_4_20_qwen_config_analysis.py").read_text()
    assert "locked_protocol.messages(sid)" in text and not any(b in text for b in DRIFTED_USER_TEXT + tuple(CANONICAL_USER_TEXT.values()))
    earlier = json.loads(QWEN_ANALYSIS.read_text())
    assert earlier["rendering_status"] == "SUPERSEDED_DRIFTED_PROMPTS" and earlier["superseded_by"]["artifact"].startswith("GENESIS_QWEN3_8B_RUNTIME_CONFIGURATION_ANALYSIS_V2")
    assert v2["supersedes"]["artifact"] == QWEN_ANALYSIS.name and len(v2["supersedes"]["original_sha256"]) == 64
    assert earlier["rendered_locked_requests"]["B"]["messages_unchanged"][0]["content"] == DRIFTED_USER_TEXT[1]      # earlier history preserved, not hidden


def test_a_qualified_record_must_use_the_canonical_prompts_and_protocol_fingerprint(tmp_path):
    validate_control_runtime_record(_qualified_record(tmp_path), evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["smoke_prompts"][1]["messages"] = [{"role": "user", "content": DRIFTED_USER_TEXT[1]}]
    with pytest.raises(ControlRuntimeError, match="canonical LOCKED protocol"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    del rec["smoke_protocol"]
    with pytest.raises(ControlRuntimeError, match="smoke_protocol"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["smoke_protocol"]["protocol_sha256"] = "0" * 64
    with pytest.raises(ControlRuntimeError, match="smoke_protocol"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["smoke_protocol"]["prompts"][0]["sha256"] = "0" * 64
    with pytest.raises(ControlRuntimeError, match="per-prompt sha256"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


def test_historical_attempt_4_is_untouched_qwen_is_failed_and_mistral_phi_are_not_tested():
    q = _attempt4_record()
    assert hashlib.sha256(json.dumps(q["smoke_prompts"], sort_keys=True).encode()).hexdigest() == ATTEMPT_4_PROMPTS_SHA256           # prompts as actually sent
    assert tuple(p["messages"][0]["content"] for p in q["smoke_prompts"]) == DRIFTED_USER_TEXT
    assert hashlib.sha256(json.dumps(q["smoke_outputs"], sort_keys=True).encode()).hexdigest() == PERSISTED_QWEN_SMOKE_OUTPUTS_SHA256
    assert q["technical_serving_status"] == "FAILED" and q["runtime_qualification_status"] == "FAILED" and q["capability_status"] == "UNPROVEN"
    assert "smoke_protocol" not in q                                                                                                   # the record was not rewritten
    validate_control_runtime_record(q, evidence_root=EVIDENCE_DIR)
    for tag in ("MISTRAL_NEMO", "PHI4"):
        r = json.loads((EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
        assert r["runtime_qualification_status"] == "NOT_TESTED" and r["technical_serving_status"] == "NOT_TESTED" and r["attempts"] == [] and r["smoke_outputs"] == []
        assert tuple(p["messages"][0]["content"] for p in r["smoke_prompts"]) == tuple(CANONICAL_USER_TEXT.values())
        assert r["smoke_protocol"]["protocol_sha256"] == CANONICAL_PROTOCOL_SHA256
        note = r["smoke_prompts_canonicalization"]
        assert note["superseded_planned_prompts_sha256"] == ATTEMPT_4_PROMPTS_SHA256 and note["canonical_protocol_sha256"] == CANONICAL_PROTOCOL_SHA256
        validate_control_runtime_record(r, evidence_root=EVIDENCE_DIR)


def test_a_drifted_wording_record_cannot_qualify_even_with_perfect_outputs(tmp_path):
    rec = _qualified_record(tmp_path)
    for p, d in zip(rec["smoke_prompts"], DRIFTED_USER_TEXT):
        p["messages"] = [{"role": "user", "content": d}]
    rec["smoke_protocol"]["protocol_sha256"] = "303f55ca0389142253619b2875a61fad0f06560cbb15022a830454a203e54829"
    with pytest.raises(ControlRuntimeError, match="canonical LOCKED protocol"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


def test_the_modal_harness_proves_the_canonical_protocol_from_inside_the_container_and_fails_closed():
    text = MODAL_H100.read_text()
    tree = ast.parse(text)
    proof = ast.unparse(next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_container_proof"))
    serve = ast.unparse(next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "serve_and_smoke"))
    assert "runtime_configuration_proof" in serve and "_container_proof(runner, cfg, result)" in serve and "runner.serving_config(control" in serve
    for key in ("runtime_configuration_id", "chat_template_kwargs_sent", "smoke_protocol_sha256", "prompt_sha256_sent", "model_id", "revision", "precision", "quantization"):
        assert f"'{key}'" in proof
    run = ast.unparse(next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "cmd_run"))
    assert "container_proof_problems" in run and "proof_problems" in run and "HARNESS_FAILURE" in run


# ══ Qwen3-8B runtime configuration `qwen3_8b_non_thinking_v1` (CPU-only wiring; nothing here launches, serves or infers) ═══════════
import contextlib  # noqa: E402
import shutil  # noqa: E402

from orca.eval import control_runtime_configuration as runtime_cfg  # noqa: E402

QWEN_CFG_ID = "qwen3_8b_non_thinking_v1"
ATTEMPT_4_SNAPSHOT = EVIDENCE_DIR / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_ATTEMPT4_SNAPSHOT_2026-09-24.json"
BASE_PAYLOAD_KEYS = {"model", "messages", "temperature", "top_p", "seed", "max_tokens"}


def test_the_approved_qwen_configuration_is_exactly_the_authorized_one():
    cfg = runtime_cfg.configuration_for_model("Qwen/Qwen3-8B")
    assert runtime_cfg.QWEN_CONFIGURATION_ID == QWEN_CFG_ID == cfg["id"]
    assert cfg["chat_template_kwargs"] == {"enable_thinking": False} and cfg["chat_template_kwargs"]["enable_thinking"] is False
    assert (cfg["model_id"], cfg["revision"], cfg["precision"], cfg["quantization"], cfg["reasoning_parser"]) == (
        "Qwen/Qwen3-8B", LOCKED_CONTROL_IDENTITIES["Qwen3-8B"]["revision"], "bfloat16", None, "qwen3")
    assert set(runtime_cfg.RUNTIME_CONFIGURATIONS) == {"Qwen/Qwen3-8B"} and runtime_cfg.REQUIRED_FROM_ATTEMPT == {"Qwen/Qwen3-8B": 5}
    assert runtime_cfg.configuration_for_model("mistralai/Mistral-Nemo-Instruct-2407") is None and runtime_cfg.configuration_for_model("microsoft/phi-4") is None
    assert runtime_cfg.chat_template_kwargs_for_model("microsoft/phi-4") is None
    copy_ = runtime_cfg.configuration_for_model("Qwen/Qwen3-8B")
    copy_["chat_template_kwargs"]["enable_thinking"] = True                    # callers cannot mutate the canonical data
    assert runtime_cfg.RUNTIME_CONFIGURATIONS["Qwen/Qwen3-8B"]["chat_template_kwargs"]["enable_thinking"] is False


@pytest.mark.parametrize("key,expect_kwargs", [("qwen3_8b", True), ("mistral_nemo", False), ("phi4", False)])
def test_only_qwen_requests_carry_enable_thinking_false_and_every_smoke_carries_it(key, expect_kwargs):
    runner = _runner_module()
    cfg = runner.serving_config(key)
    gen = {"temperature": 0, "top_p": 1, "seed": 0, "max_tokens": cfg["smoke_max_tokens"]}
    for smoke in cfg["smokes"]:
        payload = runner.build_chat_payload(cfg, smoke, gen)
        assert payload["messages"] == locked_protocol.messages(smoke["smoke_id"])                    # canonical prompts, untouched
        if expect_kwargs:
            assert payload["chat_template_kwargs"] == {"enable_thinking": False} and payload["chat_template_kwargs"]["enable_thinking"] is False
            assert set(payload) == BASE_PAYLOAD_KEYS | {"chat_template_kwargs"}
        else:
            assert "chat_template_kwargs" not in payload and set(payload) == BASE_PAYLOAD_KEYS       # NO Qwen-specific setting
    assert (cfg["runtime_configuration"] or {}).get("id") == (QWEN_CFG_ID if expect_kwargs else None)


def test_the_qwen_payload_differs_from_the_thinking_default_only_by_that_one_field():
    runner = _runner_module()
    cfg = runner.serving_config("qwen3_8b")
    gen = {"temperature": 0, "top_p": 1, "seed": 0, "max_tokens": 1024}
    for smoke in cfg["smokes"]:
        after = runner.build_chat_payload(cfg, smoke, gen)
        before = runner.build_chat_payload(dict(cfg, runtime_configuration=None), smoke, gen)
        assert {k: v for k, v in after.items() if k != "chat_template_kwargs"} == before and "chat_template_kwargs" not in before
    assert (cfg["model_id"], cfg["revision"], cfg["extra_args"], cfg["max_model_len"], cfg["smoke_max_tokens"]) == (
        "Qwen/Qwen3-8B", "b968826d9c46dd6066d109eabc6255188de91218", ["--reasoning-parser", "qwen3"], 4096, 1024)


def test_the_runner_cli_and_the_modal_harness_assemble_the_serving_config_in_one_place():
    modal_src = ast.unparse(next(n for n in ast.walk(ast.parse(MODAL_H100.read_text())) if isinstance(n, ast.FunctionDef) and n.name == "serve_and_smoke"))
    assert "runner.serving_config(control" in modal_src and '"smokes"' not in modal_src            # no second cfg assembly in the harness
    cmd = ast.unparse(next(n for n in ast.walk(ast.parse(LIGHTNING_RUNNER.read_text())) if isinstance(n, ast.FunctionDef) and n.name == "cmd_serve"))
    assert "serving_config(control" in cmd and '"smokes"' not in cmd


def test_the_canonical_acceptance_is_the_only_smoke_acceptance_implementation():
    allowed = REPO_ROOT / "orca/eval/locked_smoke_protocol.py"
    files = [p for p in sorted(REPO_ROOT.glob("scripts/phase21b_4_20_*.py")) + sorted((REPO_ROOT / "orca/eval").glob("*.py")) if p != allowed]
    assert len(files) >= 8
    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                assert node.name not in {"_meets_acceptance", "acceptance", "meets_acceptance"} or "smoke_locked_acceptance" == node.name, (path.name, node.name)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in {"exact_text", "json_equal"}, (path.name, node.value)
    # the validator's function delegates; it does not re-implement
    body = ast.unparse(next(n for n in ast.walk(ast.parse((REPO_ROOT / "orca/eval/control_runtime_qualification.py").read_text()))
                            if isinstance(n, ast.FunctionDef) and n.name == "smoke_locked_acceptance"))
    assert body.count("return") == 1 and "_locked.acceptance(smoke_id, content)" in body


def test_modal_harness_ships_the_configuration_module_beside_the_runner(monkeypatch):
    mod, calls = _load_modal_h100(monkeypatch)
    shipped = [tuple(c) for c in calls["local_files"]]
    assert (str(REPO_ROOT / "orca/eval/control_runtime_configuration.py"), "/root/control_runtime_configuration.py") in shipped
    assert shipped[0][1] == "/root/runner.py" and mod.CONFIG_FILE == REPO_ROOT / "orca/eval/control_runtime_configuration.py"


# ── validator: the NEW Qwen attempt must carry and prove the configuration; attempts 1-4 are never retro-fitted ──
def _qwen_history(n_last: int):
    hist = [{"attempt_number": 1, "outcome": "HARNESS_FAILURE", "status": "HARNESS_FAILURE", "failure_domain": "HARNESS", "valid_runtime_attempt": False, "reason": "h",
             "resource_type": "x", "duration_seconds": 34.6, "owner_billed_delta_usd": "0E-8", "cleanup_result": "PASS"},
            {"attempt_number": 2, "provider": "Lightning AI", "outcome": "BLOCKED_NO_GPU", "valid_runtime_attempt": False, "reason": "x", "resource_type": "x",
             "duration_seconds": 0, "owner_billed_delta_usd": "0", "cleanup_result": "NOT_APPLICABLE"},
            {"attempt_number": 3, "provider": "razorBridge", "outcome": "BLOCKED_NO_GPU", "valid_runtime_attempt": False, "reason": "x", "resource_type": "x",
             "duration_seconds": 0, "owner_billed_delta_usd": "0", "cleanup_result": "NOT_APPLICABLE"},
            {"attempt_number": 4, "provider": "Modal", "outcome": "TECHNICAL_FAILURE", "failure_domain": "MODEL_RUNTIME", "valid_runtime_attempt": True, "reason": "smoke B",
             "resource_type": "x", "duration_seconds": 196.5, "owner_billed_delta_usd": "0E-8", "cleanup_result": "PASS"}]
    if n_last == 5:
        hist.append({"attempt_number": 5, "provider": "Modal", "outcome": "TECHNICAL_SUCCESS", "failure_domain": "NONE", "valid_runtime_attempt": True, "reason": "ok",
                     "resource_type": "x", "duration_seconds": 190.0, "owner_billed_delta_usd": "0E-8", "cleanup_result": "PASS"})
    return hist[:n_last] if n_last <= 4 else hist


def _qwen_proof(**over):
    proof = {"runtime_configuration_id": QWEN_CFG_ID, "runtime_configuration_id_applied": QWEN_CFG_ID,
             "runtime_configuration_sha256": runtime_cfg.configuration_sha256("Qwen/Qwen3-8B"), "runtime_policy_sha256": runtime_cfg.PINNED_RUNTIME_POLICY_SHA256,
             "chat_template_kwargs_sent": {sid: {"enable_thinking": False} for sid in "ABC"},
             "smoke_protocol_sha256": CANONICAL_PROTOCOL_SHA256, "prompt_sha256_sent": {sid: locked_protocol.prompt_sha256(sid) for sid in "ABC"},
             "model_id": "Qwen/Qwen3-8B", "served_model_id": "Qwen/Qwen3-8B", "revision": LOCKED_CONTROL_IDENTITIES["Qwen3-8B"]["revision"],
             "precision": "bfloat16", "quantization": None, "reasoning_parser": "qwen3"}
    proof.update(over)
    return proof


def _qwen5(tmp_path, **rc_over):
    rec = _qualified_record(tmp_path, "Qwen3-8B")
    rec["attempts"] = _qwen_history(5)
    rec["gpu_provider"] = "Modal"
    for o in rec["smoke_outputs"]:
        o["chat_template_kwargs_sent"] = {"enable_thinking": False}
    rec["runtime_configuration"] = {"id": QWEN_CFG_ID, "chat_template_kwargs": {"enable_thinking": False},
                                    "configuration_sha256": runtime_cfg.configuration_sha256("Qwen/Qwen3-8B"),
                                    "runtime_policy_sha256": runtime_cfg.PINNED_RUNTIME_POLICY_SHA256, "container_proof": _qwen_proof()}
    rec["runtime_configuration"].update(rc_over)
    return rec


def test_a_consistent_attempt_5_qwen_record_with_the_configuration_and_proof_validates(tmp_path):
    validate_control_runtime_record(_qwen5(tmp_path), evidence_root=tmp_path)


def test_attempt_4_style_qwen_records_need_no_configuration_and_the_field_is_not_retro_fitted(tmp_path):
    rec = _qualified_record(tmp_path, "Qwen3-8B")
    rec["attempts"] = _qwen_history(4)
    rec["technical_serving_status"], rec["runtime_qualification_status"] = "FAILED", "FAILED"
    validate_control_runtime_record(rec, evidence_root=tmp_path)                          # no runtime_configuration: allowed below attempt 5
    assert "runtime_configuration" not in _attempt4_record()                              # and the persisted attempt-4 record has none
    rec5 = _qwen5(tmp_path)
    del rec5["runtime_configuration"]
    with pytest.raises(ControlRuntimeError, match="requires runtime_configuration"):
        validate_control_runtime_record(rec5, evidence_root=tmp_path)


@pytest.mark.parametrize("label,mutate,match", [
    ("missing_id", lambda rc: rc.pop("id"), "runtime_configuration.id"),
    ("wrong_id", lambda rc: rc.update(id="qwen3_8b_thinking_v0"), "runtime_configuration.id"),
    ("thinking_true", lambda rc: rc.update(chat_template_kwargs={"enable_thinking": True}), "must be false"),
    ("thinking_int_zero", lambda rc: rc.update(chat_template_kwargs={"enable_thinking": 0}), "must be false"),
    ("thinking_absent", lambda rc: rc.update(chat_template_kwargs={}), "enable_thinking"),
    ("kwargs_missing", lambda rc: rc.pop("chat_template_kwargs"), "enable_thinking"),
    ("extra_kwarg", lambda rc: rc.update(chat_template_kwargs={"enable_thinking": False, "reasoning_effort": "none"}), "unapproved chat_template_kwargs"),
    ("wrong_config_fingerprint", lambda rc: rc.update(configuration_sha256="0" * 64), "configuration_sha256"),
    ("no_proof", lambda rc: rc.pop("container_proof"), "container proof"),
    ("proof_id_disagrees", lambda rc: rc["container_proof"].update(runtime_configuration_id="qwen3_8b_thinking_v0"), "runtime_configuration_id"),
    ("proof_applied_id_disagrees", lambda rc: rc["container_proof"].update(runtime_configuration_id_applied=None), "runtime_configuration_id"),
    ("proof_kwargs_true_for_one_smoke", lambda rc: rc["container_proof"]["chat_template_kwargs_sent"].update(B={"enable_thinking": True}), "every locked smoke"),
    ("proof_kwargs_missing_for_one_smoke", lambda rc: rc["container_proof"]["chat_template_kwargs_sent"].update(C=None), "every locked smoke"),
    ("proof_wrong_protocol_fingerprint", lambda rc: rc["container_proof"].update(smoke_protocol_sha256="0" * 64), "protocol fingerprint"),
    ("proof_wrong_prompt_hash", lambda rc: rc["container_proof"]["prompt_sha256_sent"].update(B=locked_protocol.prompt_sha256("A")), "per-prompt sha256"),
    ("proof_wrong_model", lambda rc: rc["container_proof"].update(model_id="Qwen/Qwen3-4B"), "model id"),
    ("proof_wrong_served_model", lambda rc: rc["container_proof"].update(served_model_id="other"), "model id"),
    ("proof_wrong_revision", lambda rc: rc["container_proof"].update(revision="0" * 40), "revision"),
    ("proof_wrong_precision", lambda rc: rc["container_proof"].update(precision="float16"), "precision"),
    ("proof_quantized", lambda rc: rc["container_proof"].update(quantization="fp8"), "precision"),
    ("proof_wrong_parser", lambda rc: rc["container_proof"].update(reasoning_parser=None), "reasoning parser"),
    ("proof_wrong_config_fingerprint", lambda rc: rc["container_proof"].update(runtime_configuration_sha256="0" * 64), "fingerprint"),
])
def test_the_validator_rejects_every_qwen_configuration_defect(tmp_path, label, mutate, match):
    rec = _qwen5(tmp_path)
    mutate(rec["runtime_configuration"])
    with pytest.raises(ControlRuntimeError, match=match):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


def test_an_output_that_records_different_kwargs_than_the_configuration_is_rejected(tmp_path):
    rec = _qwen5(tmp_path)
    rec["smoke_outputs"][1]["chat_template_kwargs_sent"] = {"enable_thinking": True}
    with pytest.raises(ControlRuntimeError, match="disagree"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


def test_a_qualified_attempt_5_still_needs_the_canonical_prompts_and_fingerprint(tmp_path):
    rec = _qwen5(tmp_path)
    rec["smoke_protocol"]["protocol_sha256"] = "0" * 64
    with pytest.raises(ControlRuntimeError, match="smoke_protocol"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


@pytest.mark.parametrize("control", ["Mistral-Nemo-Instruct-2407", "Phi-4"])
def test_controls_without_an_approved_configuration_may_not_carry_the_qwen_setting(tmp_path, control):
    rec = _qualified_record(tmp_path, control)
    validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec["runtime_configuration"] = {"id": QWEN_CFG_ID, "chat_template_kwargs": {"enable_thinking": False}}
    with pytest.raises(ControlRuntimeError, match="no approved runtime configuration"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


# ── harness: container proof is verified locally and fails closed; the next attempt is 5; prior evidence is preserved ──
def _proof_for(mod, model_key="Qwen3-8B", **over):
    locked = LOCKED_CONTROL_IDENTITIES[model_key]
    approved = runtime_cfg.configuration_for_model(locked["model_id"])
    proof = _qwen_proof() if approved else {
        "runtime_configuration_id": None, "runtime_configuration_id_applied": None, "runtime_configuration_sha256": None,
        "runtime_policy_sha256": runtime_cfg.PINNED_RUNTIME_POLICY_SHA256,
        "chat_template_kwargs_sent": {sid: None for sid in "ABC"}, "smoke_protocol_sha256": CANONICAL_PROTOCOL_SHA256,
        "prompt_sha256_sent": {sid: locked_protocol.prompt_sha256(sid) for sid in "ABC"}, "model_id": locked["model_id"], "served_model_id": locked["model_id"],
        "revision": locked["revision"], "precision": "bfloat16", "quantization": None, "reasoning_parser": None}
    proof.update(over)
    return {"runtime_configuration_proof": proof}


def test_the_harness_accepts_only_a_complete_matching_container_proof(monkeypatch):
    mod, _ = _load_modal_h100(monkeypatch)
    q = LOCKED_CONTROL_IDENTITIES["Qwen3-8B"]
    assert mod.container_proof_problems(_proof_for(mod), q["model_id"], q["revision"]) == []
    assert mod.container_proof_problems(None, q["model_id"], q["revision"]) and mod.container_proof_problems({}, q["model_id"], q["revision"])
    bad = [dict(runtime_configuration_id=None), dict(runtime_configuration_id="qwen3_8b_thinking_v0"), dict(runtime_configuration_id_applied="x"),
           dict(chat_template_kwargs_sent={"A": {"enable_thinking": False}, "B": {"enable_thinking": True}, "C": {"enable_thinking": False}}),
           dict(chat_template_kwargs_sent={"A": {"enable_thinking": 0}, "B": {"enable_thinking": False}, "C": {"enable_thinking": False}}),
           dict(chat_template_kwargs_sent={"A": {"enable_thinking": False}}), dict(chat_template_kwargs_sent={sid: {} for sid in "ABC"}),
           dict(smoke_protocol_sha256="0" * 64), dict(prompt_sha256_sent={"A": "0" * 64, "B": "0" * 64, "C": "0" * 64}), dict(model_id="x"), dict(served_model_id="x"),
           dict(revision="0" * 40), dict(precision="float16"), dict(quantization="fp8"), dict(reasoning_parser=None), dict(runtime_configuration_sha256="0" * 64)]
    for over in bad:
        assert mod.container_proof_problems(_proof_for(mod, **over), q["model_id"], q["revision"]), over
    for key in ("Mistral-Nemo-Instruct-2407", "Phi-4"):
        m = LOCKED_CONTROL_IDENTITIES[key]
        assert mod.container_proof_problems(_proof_for(mod, key), m["model_id"], m["revision"]) == []              # proves NO extra setting was sent
        leaked = _proof_for(mod, key, chat_template_kwargs_sent={sid: {"enable_thinking": False} for sid in "ABC"})
        assert mod.container_proof_problems(leaked, m["model_id"], m["revision"])                                 # a leaked Qwen setting is refused


def test_the_real_qwen_history_is_1_to_5_attempts_1_to_4_are_unchanged_and_attempt_5_is_the_only_new_one(monkeypatch):
    mod, _ = _load_modal_h100(monkeypatch)
    attempts = mod._load_attempts("QWEN3_8B")
    assert [a["attempt_number"] for a in attempts] == [1, 2, 3, 4, 5]
    assert attempts[:4] == _attempt4_record()["attempts"]                                # attempts 1-4 exactly as preserved in the attempt-4 snapshot
    assert attempts[3]["outcome"] == "TECHNICAL_FAILURE" and attempts[3]["original_classification"]["outcome"] == "TECHNICAL_SUCCESS"
    assert not any("runtime_configuration" in a for a in attempts[:4])                   # attempts 1-4 carry no configuration
    assert mod._load_attempts("MISTRAL_NEMO") == [] and mod._load_attempts("PHI4") == []

ATTEMPT_4_SNAPSHOT_SHA256 = "008b945e7fc0f10eec2a04104f5627260a4187d512d14294b0da41b0a0e217fd"


def test_attempt_4_evidence_snapshot_is_byte_identical_to_what_was_preserved_and_still_failed():
    assert hashlib.sha256(ATTEMPT_4_SNAPSHOT.read_bytes()).hexdigest() == ATTEMPT_4_SNAPSHOT_SHA256                  # pinned: unchanged since the readiness artifact
    q = json.loads(ATTEMPT_4_SNAPSHOT.read_text())
    assert q["technical_serving_status"] == "FAILED" and q["runtime_qualification_status"] == "FAILED" and q["attempts"][-1]["attempt_number"] == 4
    assert hashlib.sha256(json.dumps(q["smoke_outputs"], sort_keys=True).encode()).hexdigest() == PERSISTED_QWEN_SMOKE_OUTPUTS_SHA256
    assert q["raw_log_sha256"] == "068332b340ddcf73d1d61e326c1e95646a610ac6864b2a47848cf218355d5bbd"
    assert hashlib.sha256((EVIDENCE_DIR / q["raw_log_artifact"]).read_bytes()).hexdigest() == q["raw_log_sha256"]
    assert hashlib.sha256(json.dumps(q["smoke_prompts"], sort_keys=True).encode()).hexdigest() == ATTEMPT_4_PROMPTS_SHA256
    readiness = json.loads((EVIDENCE_DIR / "GENESIS_QWEN3_8B_NON_THINKING_V1_IMPLEMENTATION_READINESS_2026-09-25.json").read_text())
    assert readiness["historical_attempt_4"]["snapshot_sha256"] == ATTEMPT_4_SNAPSHOT_SHA256

def test_the_existing_financial_gates_are_untouched_and_the_settlement_waiver_stays_attempt_1_only(monkeypatch):
    mod, _ = _load_modal_h100(monkeypatch)
    from orca.eval.control_runtime_qualification import MAX_AUTHORIZED_RUN_COST_USD, financial_gate_decision
    assert MAX_AUTHORIZED_RUN_COST_USD == Decimal("1.25") and mod.RESERVE_USD == "5.00" and mod.HARD_TIMEOUT_SECONDS == 900
    worst = mod.worst_case_cost({"h100": Decimal("3.95"), "cpu": Decimal("0.0473"), "mem": Decimal("0.008")}, gpu=True, cores=mod.CPU_CORES,
                                memory_mib=mod.GPU_MEMORY_MIB, seconds=mod.HARD_TIMEOUT_SECONDS)
    assert worst <= Decimal("1.25")
    summary = {"billed_cost": "0", "metered_cost": "20.31", "adjustments": {"credits": "-20.31"}}
    assert financial_gate_decision(summary, worst_case_job_cost_usd="1.26", credit_pool_usd="30.00", reserve_usd="5.00",
                                   prior_positive_billing_seen=False, prior_settlement_unresolved=False)["allowed"] is False
    assert financial_gate_decision(dict(summary, billed_cost="0.01"), worst_case_job_cost_usd=str(worst), credit_pool_usd="30.00", reserve_usd="5.00",
                                   prior_positive_billing_seen=False, prior_settlement_unresolved=False)["allowed"] is False
    assert financial_gate_decision(summary, worst_case_job_cost_usd=str(worst), credit_pool_usd="30.00", reserve_usd="5.00",
                                   prior_positive_billing_seen=False, prior_settlement_unresolved=True)["allowed"] is False
    pre = ast.unparse(next(n for n in ast.walk(ast.parse(MODAL_H100.read_text())) if isinstance(n, ast.FunctionDef) and n.name == "_preflight"))
    assert "financial_gate_decision" in pre and "prior_settlement_unresolved=unresolved" in pre and "live Modal resource" in pre
    attempts = dict(((t, a["attempt_number"]), a) for t, a in mod._modal_attempts())
    assert mod.validate_owner_settlement_waiver("QWEN3_8B", attempts[("QWEN3_8B", 4)])[0] == "WAIVER_ABSENT"      # the waiver never applies to attempt 4
    assert mod.validate_owner_settlement_waiver("QWEN3_8B", attempts[("QWEN3_8B", 1)])[0] == "WAIVER_ACCEPTED"
    assert all(mod.settlement_resolved(t, a) for t, a in mod._modal_attempts())                                    # attempt 1 by waiver, attempt 4 by OBSERVED reconciliation
    assert mod.unresolved_settlement_upper_bound_usd() > 0                                                        # attempt 1's conservative exposure stays deducted


def _fake_container_result(mod, runner, *, kwargs_for_b=None):
    cfg = runner.serving_config("qwen3_8b", 420)
    good = {"A": "READY", "B": "5", "C": '{"status":"ready"}'}
    smokes = []
    for sid in "ABC":
        text = good[sid]
        smokes.append({"smoke_id": sid, "http_status": 200, "raw_response": json.dumps({"choices": [{"message": {"content": text}}]}), "content": text, "finish_reason": "stop",
                       "usage": {"completion_tokens": 2}, "latency_seconds": 0.5, "ttft_seconds": None, "matches_expected_exactly": True,
                       "chat_template_kwargs_sent": kwargs_for_b if (sid == "B" and kwargs_for_b is not None) else {"enable_thinking": False},
                       "prompt_sha256_sent": locked_protocol.prompt_sha256(sid)})
    argv = ["/usr/local/bin/python", "-m", "vllm.entrypoints.openai.api_server", "--model", "<local pinned-revision snapshot dir>", "--served-model-name", "Qwen/Qwen3-8B",
            "--dtype", "bfloat16", "--max-model-len", "4096", "--gpu-memory-utilization", "0.9", "--host", "127.0.0.1", "--port", "8000", "--seed", "0", "--reasoning-parser", "qwen3"]
    result = {"server_ready": True, "error": None, "server_argv_sanitized": argv, "orphan_vllm_processes_after_shutdown": 0, "server_exit_code": 0,
              "snapshot_dir_name": LOCKED_CONTROL_IDENTITIES["Qwen3-8B"]["revision"], "snapshot_dir_names": [LOCKED_CONTROL_IDENTITIES["Qwen3-8B"]["revision"]],
              "weight_bytes_observed": LOCKED_CONTROL_IDENTITIES["Qwen3-8B"]["expected_weight_bytes"], "weight_shard_files": ["model-00001-of-00005.safetensors"],
              "models_endpoint": {"data": [{"id": "Qwen/Qwen3-8B"}]}, "versions": {"vllm": "0.29.0"}, "server_log": "", "events": ["synthetic"],
              "cold_start_seconds": 100.0, "peak_gpu_memory_used_mib": 70000, "steady_gpu_memory_used_mib": 60000, "smoke_results": smokes,
              "runtime_configuration_id_applied": cfg["runtime_configuration"]["id"], "generation_config_sent": {"temperature": 0, "top_p": 1, "seed": 0, "max_tokens": 1024},
              "stage_manifest": {"all_lfs_sha256_match": True}}
    result["runtime_configuration_proof"] = mod._container_proof(runner, cfg, result)
    return result


def _run_env(monkeypatch, tmp_path, result_builder):
    mod, _ = _load_modal_h100(monkeypatch)
    ev = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_DIR, ev)
    # simulate the state BEFORE the authorized attempt 5 (attempts 1-4, main record == attempt-4 snapshot); the real evidence is never touched
    (ev / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json").write_bytes(ATTEMPT_4_SNAPSHOT.read_bytes())
    attempts_path = ev / "GENESIS_CONTROL_QWEN3_8B_ATTEMPTS_2026-09-24.json"
    doc = json.loads(attempts_path.read_text())
    doc["attempts"] = doc["attempts"][:4]
    attempts_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    monkeypatch.setattr(mod, "EVIDENCE_DIR", ev)
    lc = mod._load_lightning_control()
    baseline = {"billed_cost": "0E-8", "metered_cost": "20.31000000", "adjustments": {"credits": "-20.31000000", "plan_cost": "0E-8"},
                "metered_cost_breakdown": {"ephemeral_apps": "20.30462160", "deployed_apps": "0.00101405"}}
    decision = {"allowed": True, "reasons": [], "remaining_credit_usd": "9.65"}
    monkeypatch.setattr(mod, "_preflight", lambda kind, key, gpu: (lc.CONTROLS[key], {"h100": Decimal("3.95"), "cpu": Decimal("0.0473"), "mem": Decimal("0.008")},
                                                                    Decimal("1.0828"), baseline, {"live_resources": 0}, Decimal("0.0380"), decision))
    monkeypatch.setattr(mod, "billing_summary", lambda: baseline)
    monkeypatch.setattr(mod, "cleanup_snapshot", lambda: {"live_resources": 0, "containers": [], "apps": [], "volumes": []})
    monkeypatch.setattr(mod, "_app_row", lambda name, app_id: {"app_id": "ap-TEST", "state": "stopped", "tasks": "0"})
    monkeypatch.setattr(mod, "_cli_json", lambda *a: [])
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    remote_calls = []
    runner = _runner_module()

    def fake_remote(control):
        remote_calls.append(control)
        return result_builder(mod, runner)

    monkeypatch.setattr(mod, "serve_and_smoke", types.SimpleNamespace(remote=fake_remote))         # NOTHING real runs: no GPU, no Modal, no network
    monkeypatch.setattr(mod, "app", types.SimpleNamespace(run=lambda: contextlib.nullcontext(), app_id="ap-TEST", name="orneur-p21b420-h100-control-runtime"))
    return mod, ev, remote_calls


def test_a_future_qwen_run_becomes_attempt_5_preserves_attempt_4_and_records_the_verified_configuration(monkeypatch, tmp_path):
    mod, ev, remote_calls = _run_env(monkeypatch, tmp_path, lambda m, r: _fake_container_result(m, r))
    before = {p.name: p.read_bytes() for p in ev.iterdir() if "ATTEMPT4" in p.name or "ATTEMPT1" in p.name or "ATTEMPTS" in p.name}
    assert mod.cmd_run(types.SimpleNamespace(control="qwen3_8b")) == 1 and remote_calls == ["qwen3_8b"]           # 1 == settlement still pending (flat metering in this stand-in)
    attempts = json.loads((ev / "GENESIS_CONTROL_QWEN3_8B_ATTEMPTS_2026-09-24.json").read_text())["attempts"]
    assert [a["attempt_number"] for a in attempts] == [1, 2, 3, 4, 5] and attempts[:4] == json.loads(before["GENESIS_CONTROL_QWEN3_8B_ATTEMPTS_2026-09-24.json"])["attempts"]
    assert attempts[4]["outcome"] == "TECHNICAL_SUCCESS" and attempts[4]["valid_runtime_attempt"] is True
    snap = ev / ATTEMPT_4_SNAPSHOT.name
    assert snap.read_bytes() == ATTEMPT_4_SNAPSHOT.read_bytes()                                                    # attempt-4 record preserved byte-identically
    rec = json.loads((ev / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
    assert rec["runtime_configuration"]["id"] == QWEN_CFG_ID and rec["runtime_configuration"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert rec["runtime_configuration"]["container_proof"]["smoke_protocol_sha256"] == CANONICAL_PROTOCOL_SHA256 and rec["smoke_protocol"]["protocol_sha256"] == CANONICAL_PROTOCOL_SHA256
    assert rec["runtime_qualification_status"] == "PENDING_SETTLEMENT_OBSERVATION" and rec["capability_status"] == "UNPROVEN" and "validator_note" not in rec
    validate_control_runtime_record(rec, evidence_root=ev)
    for name, data in before.items():
        if "ATTEMPTS" not in name:
            assert (ev / name).read_bytes() == data                                                                # every per-attempt attempt-1/attempt-4 file untouched


@pytest.mark.parametrize("label,builder", [
    ("thinking_true_sent", lambda m, r: _fake_container_result(m, r, kwargs_for_b={"enable_thinking": True})),
    ("no_proof", lambda m, r: {k: v for k, v in _fake_container_result(m, r).items() if k != "runtime_configuration_proof"}),
])
def test_a_missing_or_disagreeing_container_proof_is_a_harness_failure_never_a_model_result(monkeypatch, tmp_path, label, builder):
    mod, ev, remote_calls = _run_env(monkeypatch, tmp_path, builder)
    mod.cmd_run(types.SimpleNamespace(control="qwen3_8b"))
    a5 = json.loads((ev / "GENESIS_CONTROL_QWEN3_8B_ATTEMPTS_2026-09-24.json").read_text())["attempts"][4]
    assert a5["attempt_number"] == 5 and a5["outcome"] == "HARNESS_FAILURE" and a5["failure_domain"] == "HARNESS" and a5["valid_runtime_attempt"] is False
    assert "did not prove" in a5["reason"]
    rec = json.loads((ev / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
    assert rec["technical_serving_status"] == "NOT_PROVEN" and rec["runtime_qualification_status"] == "NOT_COMPLETED"


def test_a_changed_prior_attempt_snapshot_refuses_the_launch_before_any_remote_call(monkeypatch, tmp_path):
    mod, ev, remote_calls = _run_env(monkeypatch, tmp_path, lambda m, r: _fake_container_result(m, r))
    (ev / ATTEMPT_4_SNAPSHOT.name).write_text("{}")
    assert mod.cmd_run(types.SimpleNamespace(control="qwen3_8b")) == 2 and remote_calls == []


def test_this_test_module_never_calls_a_gpu_or_provider_function_for_real():
    # every harness test above replaces serve_and_smoke/app with inert stand-ins; there is no live call, and generated text is data only
    for path in (LIGHTNING_RUNNER, MODAL_H100):
        text = path.read_text()
        for banned in ("eval(", "exec(", "compile(", "os.system", "shell=True"):
            assert banned not in ast.unparse(ast.parse(text)).replace("re.compile(", ""), (path.name, banned)


def test_the_implementation_readiness_artifact_is_cpu_only_and_consistent_with_the_code():
    a = json.loads((EVIDENCE_DIR / "GENESIS_QWEN3_8B_NON_THINKING_V1_IMPLEMENTATION_READINESS_2026-09-25.json").read_text())
    assert a["no_gpu_used"] and a["no_modal_function_called"] and a["no_inference_performed"] and a["owner_cash_spent_usd"] == "0" and a["generated_output_executed"] is False
    assert a["approved_configuration"]["runtime_configuration_id"] == QWEN_CFG_ID and a["approved_configuration"]["configuration_sha256"] == runtime_cfg.configuration_sha256("Qwen/Qwen3-8B")
    d = a["request_payload_delta"]
    assert d["after_qwen_non_thinking_v1"]["chat_template_kwargs"] == {"enable_thinking": False} and "chat_template_kwargs" not in d["before_qwen_thinking_default"]
    assert d["mistral_nemo_payload_has_chat_template_kwargs"] is False and d["phi4_payload_has_chat_template_kwargs"] is False
    assert a["canonical_smoke_protocol"]["protocol_sha256"] == CANONICAL_PROTOCOL_SHA256 and a["acceptance_logic"]["runner_duplicate_removed"] is True
    assert a["attempt_5_readiness"]["next_attempt_number"] == 5 and a["attempt_5_readiness"]["execution_authorized"] is False and a["attempt_5_readiness"]["financial_gates_evaluated_here"] is False
    h = a["historical_attempt_4"]
    assert h["record_equals_snapshot"] is True and h["status"] == {"technical_serving_status": "FAILED", "runtime_qualification_status": "FAILED"}
    assert h["snapshot_sha256"] == hashlib.sha256(ATTEMPT_4_SNAPSHOT.read_bytes()).hexdigest()
    assert a["status_unchanged"] == {"qwen3_8b": "FAILED", "mistral_nemo": "NOT_TESTED", "phi4": "NOT_TESTED", "capability": "UNPROVEN"}


# ══ pinned runtime-configuration POLICY fingerprint (fail-closed on import; over the policy DATA, not the source-file hash) ═══════════
RUNTIME_CONFIG_FILE = REPO_ROOT / "orca/eval/control_runtime_configuration.py"
PINNED_POLICY_SHA256 = "50c0b455e710aa53d0ec4d5515c9f9835b51ebac14391242813ceef961b6c62e"
PINNED_QWEN_CONFIG_SHA256 = "c88e0e140797d25ea9c86bc642d23706d9b6e76c241c49d2b6b354a40b83bab1"
EXPECTED_POLICY_DOCUMENT = {                                   # written independently of the module on purpose
    "policy_id": "GENESIS_CONTROL_RUNTIME_CONFIGURATION_POLICY",
    "policies": [{"runtime_configuration_id": "qwen3_8b_non_thinking_v1", "model_id": "Qwen/Qwen3-8B", "revision": "b968826d9c46dd6066d109eabc6255188de91218",
                  "precision": "bfloat16", "quantization": None, "reasoning_parser": "qwen3", "chat_template_kwargs": {"enable_thinking": False},
                  "required_from_attempt": 5}]}


def test_the_canonical_runtime_policy_passes_and_is_exactly_the_protected_document():
    runtime_cfg.verify_runtime_configuration_integrity()
    assert runtime_cfg.PINNED_RUNTIME_POLICY_SHA256 == PINNED_POLICY_SHA256 == runtime_cfg.runtime_policy_sha256()
    assert runtime_cfg.runtime_policy_document() == EXPECTED_POLICY_DOCUMENT
    assert hashlib.sha256(json.dumps(EXPECTED_POLICY_DOCUMENT, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest() == PINNED_POLICY_SHA256
    assert runtime_cfg.PINNED_QWEN_CONFIGURATION_SHA256 == PINNED_QWEN_CONFIG_SHA256 == runtime_cfg.configuration_sha256("Qwen/Qwen3-8B")


def _policy_inputs():
    return copy.deepcopy(runtime_cfg.RUNTIME_CONFIGURATIONS), copy.deepcopy(runtime_cfg.REQUIRED_FROM_ATTEMPT)


_PROTECTED_MUTATIONS = {
    "configuration_id": lambda c, r: c["Qwen/Qwen3-8B"].update(id="qwen3_8b_non_thinking_v2"),
    "model_id": lambda c, r: c["Qwen/Qwen3-8B"].update(model_id="Qwen/Qwen3-4B"),
    "revision": lambda c, r: c["Qwen/Qwen3-8B"].update(revision="0" * 40),
    "precision": lambda c, r: c["Qwen/Qwen3-8B"].update(precision="float16"),
    "quantization": lambda c, r: c["Qwen/Qwen3-8B"].update(quantization="fp8"),
    "reasoning_parser": lambda c, r: c["Qwen/Qwen3-8B"].update(reasoning_parser="deepseek_r1"),
    "reasoning_parser_removed": lambda c, r: c["Qwen/Qwen3-8B"].update(reasoning_parser=None),
    "enable_thinking": lambda c, r: c["Qwen/Qwen3-8B"]["chat_template_kwargs"].update(enable_thinking=True),
    "enable_thinking_removed": lambda c, r: c["Qwen/Qwen3-8B"].update(chat_template_kwargs={}),
    "extra_kwarg": lambda c, r: c["Qwen/Qwen3-8B"]["chat_template_kwargs"].update(reasoning_effort="none"),
    "required_from_attempt_earlier": lambda c, r: r.update({"Qwen/Qwen3-8B": 4}),
    "required_from_attempt_later": lambda c, r: r.update({"Qwen/Qwen3-8B": 6}),
    "required_from_attempt_removed": lambda c, r: r.pop("Qwen/Qwen3-8B"),
}


@pytest.mark.parametrize("field", sorted(_PROTECTED_MUTATIONS))
def test_a_one_field_mutation_of_every_protected_policy_field_fails_integrity_verification(field):
    configs, required = _policy_inputs()
    _PROTECTED_MUTATIONS[field](configs, required)
    assert runtime_cfg.runtime_policy_sha256(configs, required) != PINNED_POLICY_SHA256
    with pytest.raises(RuntimeError, match="policy drift"):
        runtime_cfg.verify_runtime_configuration_integrity(configs, required)


def test_a_new_unapproved_control_entry_or_a_removed_qwen_entry_also_fails():
    configs, required = _policy_inputs()
    configs["microsoft/phi-4"] = {"id": "phi4_x", "model_id": "microsoft/phi-4", "revision": "r", "precision": "bfloat16", "quantization": None,
                                  "reasoning_parser": None, "chat_template_kwargs": {"enable_thinking": False}}
    with pytest.raises(RuntimeError, match="policy drift"):
        runtime_cfg.verify_runtime_configuration_integrity(configs, required)
    with pytest.raises(RuntimeError, match="policy drift"):
        runtime_cfg.verify_runtime_configuration_integrity({}, {})
    configs, required = _policy_inputs()
    configs["Qwen/Qwen3-8B"]["note"] = "an unprotected extra key"                     # not in the policy document, but the pinned configuration hash catches it
    with pytest.raises(RuntimeError, match="policy drift"):
        runtime_cfg.verify_runtime_configuration_integrity(configs, required)


_SOURCE_EDITS = {
    "id": ('QWEN_CONFIGURATION_ID = "qwen3_8b_non_thinking_v1"', 'QWEN_CONFIGURATION_ID = "qwen3_8b_non_thinking_v2"'),
    "revision": ('"revision": "b968826d9c46dd6066d109eabc6255188de91218",', '"revision": "c968826d9c46dd6066d109eabc6255188de91218",'),
    "precision": ('"precision": "bfloat16",', '"precision": "float16",'),
    "quantization": ('"quantization": None,', '"quantization": "fp8",'),
    "reasoning_parser": ('"reasoning_parser": "qwen3",', '"reasoning_parser": "deepseek_r1",'),
    "enable_thinking": ('"chat_template_kwargs": {"enable_thinking": False},', '"chat_template_kwargs": {"enable_thinking": True},'),
    "extra_kwarg": ('"chat_template_kwargs": {"enable_thinking": False},', '"chat_template_kwargs": {"enable_thinking": False, "reasoning_effort": "none"},'),
    "required_from_attempt": ('REQUIRED_FROM_ATTEMPT: dict[str, int] = {"Qwen/Qwen3-8B": 5}', 'REQUIRED_FROM_ATTEMPT: dict[str, int] = {"Qwen/Qwen3-8B": 4}'),
}


@pytest.mark.parametrize("field", sorted(_SOURCE_EDITS))
def test_editing_the_canonical_module_data_stops_every_importer_at_import_time(field):
    old, new = _SOURCE_EDITS[field]
    original = RUNTIME_CONFIG_FILE.read_text()
    assert original.count(old) == 1 and old != new
    with pytest.raises(RuntimeError, match="policy drift"):
        exec(compile(original.replace(old, new), "policy_drift_probe", "exec"), {"__name__": "policy_drift_probe"})     # test-only probe of the import-time check


def test_the_pin_covers_the_policy_data_not_the_source_file_bytes():
    original = RUNTIME_CONFIG_FILE.read_text()
    exec(compile(original + "\n# a comment and   extra   whitespace change nothing about the approved policy\n", "neutral_edit", "exec"), {"__name__": "neutral_edit"})
    assert hashlib.sha256(original.encode()).hexdigest() != PINNED_POLICY_SHA256                 # the source-file hash is not what is pinned


def test_the_container_and_the_runner_load_the_same_pinned_policy(monkeypatch):
    runner = _runner_module()
    assert runner.RUNTIME_CONFIGS.PINNED_RUNTIME_POLICY_SHA256 == PINNED_POLICY_SHA256 == runner.RUNTIME_CONFIGS.runtime_policy_sha256()
    mod, _ = _load_modal_h100(monkeypatch)
    assert mod.runtime_config.PINNED_RUNTIME_POLICY_SHA256 == PINNED_POLICY_SHA256
    proof = mod._container_proof(runner, runner.serving_config("qwen3_8b"), {"smoke_results": []})
    assert proof["runtime_policy_sha256"] == PINNED_POLICY_SHA256


@pytest.mark.parametrize("label,mutate", [
    ("record_missing", lambda rc: rc.pop("runtime_policy_sha256")),
    ("record_wrong", lambda rc: rc.update(runtime_policy_sha256="0" * 64)),
    ("proof_missing", lambda rc: rc["container_proof"].pop("runtime_policy_sha256")),
    ("proof_wrong", lambda rc: rc["container_proof"].update(runtime_policy_sha256="0" * 64)),
    ("record_and_proof_agree_on_a_drifted_value", lambda rc: (rc.update(runtime_policy_sha256="1" * 64), rc["container_proof"].update(runtime_policy_sha256="1" * 64))),
    ("proof_equals_record_but_not_pinned_config_hash_reused", lambda rc: (rc.update(runtime_policy_sha256=PINNED_QWEN_CONFIG_SHA256), rc["container_proof"].update(runtime_policy_sha256=PINNED_QWEN_CONFIG_SHA256))),
])
def test_record_container_and_pinned_policy_hashes_must_all_be_equal_or_validation_fails(tmp_path, label, mutate):
    rec = _qwen5(tmp_path)
    validate_control_runtime_record(rec, evidence_root=tmp_path)
    mutate(rec["runtime_configuration"])
    with pytest.raises(ControlRuntimeError, match="runtime-policy sha256|runtime_policy_sha256"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


def test_the_harness_refuses_a_container_policy_hash_that_differs_from_the_locally_pinned_one(monkeypatch):
    mod, _ = _load_modal_h100(monkeypatch)
    q = LOCKED_CONTROL_IDENTITIES["Qwen3-8B"]
    assert mod.container_proof_problems(_proof_for(mod), q["model_id"], q["revision"]) == []
    for bad in ("0" * 64, None):
        problems = mod.container_proof_problems(_proof_for(mod, runtime_policy_sha256=bad), q["model_id"], q["revision"])
        assert any("runtime-policy sha256" in p for p in problems)
    for key in ("Mistral-Nemo-Instruct-2407", "Phi-4"):                                            # the policy hash is global: every control proves it
        m = LOCKED_CONTROL_IDENTITIES[key]
        assert any("runtime-policy sha256" in p for p in mod.container_proof_problems(_proof_for(mod, key, runtime_policy_sha256="0" * 64), m["model_id"], m["revision"]))


def test_a_drifted_container_policy_hash_is_a_harness_failure_never_a_model_result(monkeypatch, tmp_path):
    def builder(m, r):
        result = _fake_container_result(m, r)
        result["runtime_configuration_proof"]["runtime_policy_sha256"] = "2" * 64
        return result

    mod, ev, remote_calls = _run_env(monkeypatch, tmp_path, builder)
    mod.cmd_run(types.SimpleNamespace(control="qwen3_8b"))
    a5 = json.loads((ev / "GENESIS_CONTROL_QWEN3_8B_ATTEMPTS_2026-09-24.json").read_text())["attempts"][4]
    assert a5["attempt_number"] == 5 and a5["outcome"] == "HARNESS_FAILURE" and a5["failure_domain"] == "HARNESS" and a5["valid_runtime_attempt"] is False
    assert "runtime-policy sha256" in a5["reason"]


def test_the_policy_pin_leaves_attempt_4_byte_identical_and_mistral_phi_not_tested(monkeypatch):
    assert hashlib.sha256(ATTEMPT_4_SNAPSHOT.read_bytes()).hexdigest() == ATTEMPT_4_SNAPSHOT_SHA256
    q = _attempt4_record()
    assert q["runtime_qualification_status"] == "FAILED" and q["technical_serving_status"] == "FAILED" and "runtime_configuration" not in q
    assert hashlib.sha256(json.dumps(q["smoke_outputs"], sort_keys=True).encode()).hexdigest() == PERSISTED_QWEN_SMOKE_OUTPUTS_SHA256
    mod, _ = _load_modal_h100(monkeypatch)
    assert mod._load_attempts("MISTRAL_NEMO") == [] and mod._load_attempts("PHI4") == []
    for tag in ("MISTRAL_NEMO", "PHI4"):
        r = json.loads((EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
        assert r["runtime_qualification_status"] == "NOT_TESTED"

def test_the_policy_module_never_executes_generated_text_and_makes_no_gpu_or_provider_call():
    tree = ast.parse(RUNTIME_CONFIG_FILE.read_text())
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported <= {"__future__", "copy", "hashlib", "json"}                                   # stdlib data handling only: no modal, no network, no subprocess
    body = ast.unparse(tree)
    for banned in ("eval(", "exec(", "compile(", "subprocess", "os.system", "modal", "urllib", "requests"):
        assert banned not in body, banned


def test_the_readiness_artifact_records_the_pinned_policy_and_its_document():
    a = json.loads((EVIDENCE_DIR / "GENESIS_QWEN3_8B_NON_THINKING_V1_IMPLEMENTATION_READINESS_2026-09-25.json").read_text())["approved_configuration"]
    assert a["pinned_runtime_policy_sha256"] == PINNED_POLICY_SHA256 and a["protected_policy_document"] == EXPECTED_POLICY_DOCUMENT
    assert a["policy_fingerprint_verified_on_import"] is True and a["pinned_configuration_sha256"] == PINNED_QWEN_CONFIG_SHA256


# ══ Qwen3-8B attempt 5 (owner-authorized, executed once under qwen3_8b_non_thinking_v1): the persisted, honest result ═══════════════════
ATTEMPT_5_SMOKE_OUTPUTS_SHA256 = "9fcf1402ab27f2d089a26fbdfd12e7ca6a3c4b8d072e769e546b690371536bef"
ATTEMPT_5_RAW_LOG_SHA256 = "3596fbd908ea8c92a2553a3d6c10e230b4b3a1bcb47f6127ece5a661f743abeb"
APPROVED_POLICY_SHA256 = "50c0b455e710aa53d0ec4d5515c9f9835b51ebac14391242813ceef961b6c62e"


def test_attempt_5_is_a_valid_runtime_attempt_whose_locked_smoke_b_did_not_return_exactly_5():
    q = _persisted_qwen()
    a5 = q["attempts"][-1]
    assert a5["attempt_number"] == 5 and a5["provider"] == "Modal" and a5["outcome"] == "TECHNICAL_FAILURE" and a5["failure_domain"] == "MODEL_RUNTIME"
    assert a5["valid_runtime_attempt"] is True and "B: content is not exactly '5'" in a5["reason"] and a5["cleanup_result"] == "PASS"
    assert a5["owner_billed_delta_usd"] == "0E-8" and a5["billing_settlement_status"] == "OBSERVED" and a5["duration_seconds"] < 900
    assert q["technical_serving_status"] == "FAILED" and q["runtime_qualification_status"] == "FAILED" and q["capability_status"] == "UNPROVEN"
    out = {o["smoke_id"]: o for o in q["smoke_outputs"]}
    assert (out["A"]["content"], out["B"]["content"], out["C"]["content"]) == ("READY", "2 + 3 = 5", '{"status": "ready"}')          # raw contents, as returned
    assert [(x["smoke_id"], x["accepted"]) for x in q["smoke_acceptance"]] == [("A", True), ("B", False), ("C", True)]
    assert all(o["executed"] is False and o["http_status"] == 200 and o["finish_reason"] == "stop" for o in out.values()) and q["generated_output_executed"] is False
    assert all((o["usage"]["completion_tokens_details"] or {}).get("reasoning_tokens") == 0 for o in out.values())                    # thinking really was off
    assert hashlib.sha256(json.dumps(q["smoke_outputs"], sort_keys=True).encode()).hexdigest() == ATTEMPT_5_SMOKE_OUTPUTS_SHA256
    validate_control_runtime_record(q, evidence_root=EVIDENCE_DIR)


def test_attempt_5_can_never_be_relabelled_qualified_with_its_smoke_b_output():
    forced = copy.deepcopy(_persisted_qwen())
    forced.update(technical_serving_status="QUALIFIED", runtime_qualification_status="RUNTIME_QUALIFIED")
    with pytest.raises(ControlRuntimeError, match="LOCKED (smoke|protocol)"):
        validate_control_runtime_record(forced, evidence_root=EVIDENCE_DIR)
    assert {a["smoke_id"]: a["accepted"] for a in compute_smoke_acceptance(_persisted_qwen())} == {"A": True, "B": False, "C": True}


def test_attempt_5_proved_the_approved_configuration_the_pinned_policy_and_the_canonical_protocol_from_inside_the_container():
    q = _persisted_qwen()
    rc = q["runtime_configuration"]
    assert rc["id"] == QWEN_CFG_ID and rc["chat_template_kwargs"] == {"enable_thinking": False} and rc["chat_template_kwargs"]["enable_thinking"] is False
    proof = rc["container_proof"]
    assert proof["runtime_policy_sha256"] == rc["runtime_policy_sha256"] == runtime_cfg.PINNED_RUNTIME_POLICY_SHA256 == APPROVED_POLICY_SHA256
    assert proof["runtime_configuration_sha256"] == PINNED_QWEN_CONFIG_SHA256 == rc["configuration_sha256"]
    assert proof["runtime_configuration_id"] == proof["runtime_configuration_id_applied"] == QWEN_CFG_ID
    assert proof["chat_template_kwargs_sent"] == {sid: {"enable_thinking": False} for sid in "ABC"}
    assert all(o["chat_template_kwargs_sent"] == {"enable_thinking": False} for o in q["smoke_outputs"])
    assert proof["smoke_protocol_sha256"] == q["smoke_protocol"]["protocol_sha256"] == CANONICAL_PROTOCOL_SHA256
    assert proof["prompt_sha256_sent"] == {sid: locked_protocol.prompt_sha256(sid) for sid in "ABC"}
    assert [p["messages"] for p in q["smoke_prompts"]] == [locked_protocol.messages(sid) for sid in "ABC"]                             # canonical prompts, not the drifted ones
    assert (proof["model_id"], proof["served_model_id"], proof["revision"], proof["precision"], proof["quantization"], proof["reasoning_parser"]) == (
        "Qwen/Qwen3-8B", "Qwen/Qwen3-8B", LOCKED_CONTROL_IDENTITIES["Qwen3-8B"]["revision"], "bfloat16", None, "qwen3")
    ident = q["identity_verification"]
    assert ident["pinned_revision_matches_runtime_artifact"] is True and ident["runtime_served_model_matches_pinned_id"] is True and ident["no_silent_model_fallback"] is True
    assert ident["weight_bytes_observed"] == LOCKED_CONTROL_IDENTITIES["Qwen3-8B"]["expected_weight_bytes"] and q["precision"].lower().startswith("bfloat16")


def test_attempt_5_financials_settlement_cleanup_and_raw_log_are_consistent_and_zero_owner_cash():
    q = _persisted_qwen()
    assert q["financial_acceptance_status"] == "PASS" and q["owner_billed_delta_usd"] == "0E-8" and q["cleanup_status"] == "PASS" and q["live_resources_after_cleanup"] == 0
    assert q["billing_settlement"]["status"] == "OBSERVED" and q["financial_reconciliation"]["billing_delta_usd"] in ("0E-8", "0")
    fin = q["financial_evidence"]
    for art, sha in (("preflight_artifact", "preflight_sha256"), ("billing_before_artifact", "billing_before_sha256"), ("billing_after_artifact", "billing_after_sha256")):
        assert "ATTEMPT5" in fin[art] and hashlib.sha256((EVIDENCE_DIR / fin[art]).read_bytes()).hexdigest() == fin[sha]
    after = json.loads((EVIDENCE_DIR / fin["billing_after_artifact"]).read_text())
    assert after["owner_billed_delta_usd"] == "0E-8" and after["peak_observed_billed_usd"] == "0E-8" and all(r["billed"] == "0E-8" for r in after["post_run_readings"])
    assert [r["cost"] for r in after["itemized_rows_for_app"]] == ["0.18768559"] and after["cleanup_snapshot"]["live_resources"] == 0
    assert after["app_row"]["state"] == "stopped" and after["app_row"]["tasks"] == "0" and after["cleanup_snapshot"]["containers"] == []
    pre = json.loads((EVIDENCE_DIR / fin["preflight_artifact"]).read_text())
    assert pre["gate_decision"]["allowed"] is True and Decimal(pre["worst_case_cost_usd"]) <= Decimal("1.25") and pre["reserve_usd"] == "5.00"
    assert q["raw_log_sha256"] == ATTEMPT_5_RAW_LOG_SHA256 and hashlib.sha256((EVIDENCE_DIR / q["raw_log_artifact"]).read_bytes()).hexdigest() == ATTEMPT_5_RAW_LOG_SHA256


def test_attempt_5_left_attempts_1_to_4_and_the_attempt_4_snapshot_untouched_and_ran_no_other_control():
    q = _persisted_qwen()
    assert q["attempts"][:4] == _attempt4_record()["attempts"] and [a["attempt_number"] for a in q["attempts"]] == [1, 2, 3, 4, 5]
    assert hashlib.sha256(ATTEMPT_4_SNAPSHOT.read_bytes()).hexdigest() == ATTEMPT_4_SNAPSHOT_SHA256
    for tag in ("MISTRAL_NEMO", "PHI4"):
        r = json.loads((EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
        assert r["runtime_qualification_status"] == "NOT_TESTED" and r["attempts"] == [] and r["smoke_outputs"] == []
    raw_attempts = json.loads((EVIDENCE_DIR / "GENESIS_CONTROL_QWEN3_8B_ATTEMPTS_2026-09-24.json").read_text())["attempts"]
    assert raw_attempts == q["attempts"] and len(raw_attempts) == 5
