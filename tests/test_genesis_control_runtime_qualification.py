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
    (_summary(metered="25.00", credits="-20.03"), {}, "does not reconcile"),
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
    assert roots <= {"__future__", "argparse", "hashlib", "json", "re", "subprocess", "sys", "time", "datetime", "decimal", "pathlib", "modal", "urllib"}


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
    for key, doc in (("preflight", pre), ("billing_before", {"billing_summary": baseline}),
                     ("billing_after", {"peak_observed_billed_usd": "0E-8", "app_row": {"app_id": _RECON_APP_ID, "state": "stopped", "tasks": "0"}})):
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
    strip = lambda xs: [{k: v for k, v in a.items() if k not in ("billing_settlement_status", "original_in_run_billing_settlement_status", "settlement_reconciliation_artifact")} for a in xs]
    assert strip(rec["attempts"]) == strip(before["attempts"]) and rec["smoke_outputs"] == before["smoke_outputs"] and rec["raw_log_sha256"] == before["raw_log_sha256"]
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
        call = _fn_source(path, "run_smoke_call")
        assert 'LOCKED_PROTOCOL.acceptance(smoke["smoke_id"], entry.get("content", ""))[0]' in call and "build_chat_payload(cfg, smoke, gen_cfg)" in call
        assert "run_smoke_call(cfg, smoke, gen_cfg, http)" in _fn_source(path, "serve_and_smoke")
        assert "_meets_acceptance" not in path.read_text()
    for name in ("build_chat_payload", "capture_http_error", "run_smoke_call"):
        assert _fn_source(LIGHTNING_RUNNER, name) == _fn_source(HARNESS_PATH, name), name


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
    for tag in ("PHI4",):                                                           # Mistral-Nemo has since had its one authorized attempt
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
    rec["reasoning_mode"] = runtime_cfg.effective_reasoning_mode("ENABLED (default template capability)", runtime_cfg.configuration_for_model("Qwen/Qwen3-8B"))
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
    assert len(mod._load_attempts("MISTRAL_NEMO")) == 2 and mod._load_attempts("PHI4") == []

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
    assert all(mod.settlement_resolved(t, a) for t, a in mod._modal_attempts() if t == "QWEN3_8B")                    # Qwen attempt 1 by waiver, 4 and 5 by OBSERVED settlement
    mistral = [(a["attempt_number"], mod.settlement_resolved(t, a)) for t, a in mod._modal_attempts() if t == "MISTRAL_NEMO"]
    assert mistral == [(1, True), (2, False)]                                                                         # attempt 1 OBSERVED by reconciliation; attempt 2 delayed => any further launch stays blocked
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
    assert len(mod._load_attempts("MISTRAL_NEMO")) == 2 and mod._load_attempts("PHI4") == []
    for tag in ("PHI4",):                                                           # Mistral-Nemo has since had its one authorized attempt
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
    for tag in ("PHI4",):                                                           # Mistral-Nemo has since had its one authorized attempt
        r = json.loads((EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
        assert r["runtime_qualification_status"] == "NOT_TESTED" and r["attempts"] == [] and r["smoke_outputs"] == []
    raw_attempts = json.loads((EVIDENCE_DIR / "GENESIS_CONTROL_QWEN3_8B_ATTEMPTS_2026-09-24.json").read_text())["attempts"]
    assert raw_attempts == q["attempts"] and len(raw_attempts) == 5


# ══ attempt-5 descriptive-metadata correction: reasoning_mode derives from the EFFECTIVE configuration, not the template capability ═══════
ATTEMPT_5_SNAPSHOT = EVIDENCE_DIR / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_ATTEMPT5_SNAPSHOT_2026-09-24.json"
ATTEMPT_5_SNAPSHOT_SHA256 = "85d3fec9ae744c553ce668fa693fb19f329e6a14414051b082a23be6202213c5"
STALE_REASONING_MODE = "ENABLED (Qwen3 hybrid-thinking template default; canonical control spec launches with --reasoning-parser qwen3)"


def _attempt5_snapshot():
    return json.loads(ATTEMPT_5_SNAPSHOT.read_text())


def test_qwen_records_from_attempt_5_with_enable_thinking_false_describe_a_non_thinking_mode():
    mode = runtime_cfg.effective_reasoning_mode(STALE_REASONING_MODE, runtime_cfg.configuration_for_model("Qwen/Qwen3-8B"))
    assert mode.startswith("NON_THINKING") and "enable_thinking=false" in mode and QWEN_CFG_ID in mode and "ENABLED" not in mode
    assert "--reasoning-parser qwen3 is loaded but thinking is not enabled" in mode                    # the parser being loaded does not imply thinking
    # any other configuration (or none) leaves the descriptive default untouched: nothing is invented
    for other in (None, {}, {"chat_template_kwargs": None}, {"chat_template_kwargs": {"enable_thinking": True}}, {"chat_template_kwargs": {}}):
        assert runtime_cfg.effective_reasoning_mode(STALE_REASONING_MODE, other) == STALE_REASONING_MODE
    assert runtime_cfg.effective_reasoning_mode("NOT_APPLICABLE (non-reasoning instruct model)", None) == "NOT_APPLICABLE (non-reasoning instruct model)"


def test_the_validator_requires_reasoning_mode_to_match_the_effective_non_thinking_configuration(tmp_path):
    validate_control_runtime_record(_qwen5(tmp_path), evidence_root=tmp_path)
    for bad in (STALE_REASONING_MODE, None, "", "NON_THINKING", "ENABLED", "NON_THINKING but ENABLED (enable_thinking=false)", 7):
        rec = _qwen5(tmp_path)
        rec["reasoning_mode"] = bad
        with pytest.raises(ControlRuntimeError, match="reasoning_mode must describe the effective configuration"):
            validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qwen5(tmp_path)
    del rec["reasoning_mode"]
    with pytest.raises(ControlRuntimeError, match="reasoning_mode"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


def test_a_new_harness_record_derives_reasoning_mode_from_the_effective_configuration(monkeypatch, tmp_path):
    mod, ev, remote_calls = _run_env(monkeypatch, tmp_path, lambda m, r: _fake_container_result(m, r))
    mod.cmd_run(types.SimpleNamespace(control="qwen3_8b"))
    rec = json.loads((ev / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
    assert rec["reasoning_mode"].startswith("NON_THINKING") and "enable_thinking=false" in rec["reasoning_mode"] and rec["reasoning_parser"] == "qwen3"
    assert "ENABLED" not in rec["reasoning_mode"] and "metadata_correction" not in rec                     # correct at creation time; nothing to patch later
    validate_control_runtime_record(rec, evidence_root=ev)


def test_historical_attempt_4_stays_recorded_as_thinking_default_and_untouched():
    q4 = _attempt4_record()
    assert q4["reasoning_mode"] == STALE_REASONING_MODE and q4["reasoning_parser"] == "qwen3" and "runtime_configuration" not in q4 and "metadata_correction" not in q4
    assert hashlib.sha256(ATTEMPT_4_SNAPSHOT.read_bytes()).hexdigest() == ATTEMPT_4_SNAPSHOT_SHA256
    assert hashlib.sha256(json.dumps(q4["smoke_outputs"], sort_keys=True).encode()).hexdigest() == PERSISTED_QWEN_SMOKE_OUTPUTS_SHA256
    assert q4["attempts"][-1]["outcome"] == "TECHNICAL_FAILURE" and q4["attempts"][-1]["attempt_number"] == 4                # attempt 4 really ran with thinking on


def test_the_persisted_attempt_5_record_was_corrected_in_descriptive_metadata_only():
    snap, cur = _attempt5_snapshot(), _persisted_qwen()
    assert hashlib.sha256(ATTEMPT_5_SNAPSHOT.read_bytes()).hexdigest() == ATTEMPT_5_SNAPSHOT_SHA256
    assert snap["reasoning_mode"] == STALE_REASONING_MODE and "metadata_correction" not in snap             # the pre-correction record, preserved immutably
    assert cur["reasoning_mode"].startswith("NON_THINKING") and "enable_thinking=false" in cur["reasoning_mode"] and cur["reasoning_parser"] == "qwen3"
    note = cur["metadata_correction"]
    assert note["field"] == "reasoning_mode" and note["from"] == STALE_REASONING_MODE and note["to"] == cur["reasoning_mode"] and note["reclassifies_attempt"] is False
    assert note["snapshot_sha256"] == ATTEMPT_5_SNAPSHOT_SHA256 and note["snapshot_artifact"] == ATTEMPT_5_SNAPSHOT.name and "DESCRIPTIVE METADATA ONLY" in note["kind"]
    differing = {k for k in set(snap) | set(cur) if snap.get(k) != cur.get(k)}
    assert differing == {"reasoning_mode", "metadata_correction"}                                             # NOTHING else changed: outputs, log, financials, proof, attempts, status
    for key in ("smoke_outputs", "raw_log_sha256", "financial_evidence", "financial_reconciliation", "billing_settlement", "runtime_configuration", "attempts",
                "technical_serving_status", "runtime_qualification_status", "smoke_acceptance", "owner_billed_delta_usd"):
        assert cur[key] == snap[key], key
    validate_control_runtime_record(cur, evidence_root=EVIDENCE_DIR)


def test_attempt_5_is_not_reclassified_by_the_metadata_correction():
    cur = _persisted_qwen()
    a5 = cur["attempts"][-1]
    assert a5["attempt_number"] == 5 and a5["outcome"] == "TECHNICAL_FAILURE" and a5["failure_domain"] == "MODEL_RUNTIME" and a5["valid_runtime_attempt"] is True
    assert cur["technical_serving_status"] == "FAILED" and cur["runtime_qualification_status"] == "FAILED" and cur["capability_status"] == "UNPROVEN"
    assert {a["smoke_id"]: a["accepted"] for a in cur["smoke_acceptance"]} == {"A": True, "B": False, "C": True}
    assert next(o["content"] for o in cur["smoke_outputs"] if o["smoke_id"] == "B") == "2 + 3 = 5"
    assert hashlib.sha256(json.dumps(cur["smoke_outputs"], sort_keys=True).encode()).hexdigest() == ATTEMPT_5_SMOKE_OUTPUTS_SHA256
    assert cur["raw_log_sha256"] == ATTEMPT_5_RAW_LOG_SHA256 and all(o["usage"]["completion_tokens_details"]["reasoning_tokens"] == 0 for o in cur["smoke_outputs"])
    forced = copy.deepcopy(cur)
    forced.update(technical_serving_status="QUALIFIED", runtime_qualification_status="RUNTIME_QUALIFIED")
    with pytest.raises(ControlRuntimeError, match="LOCKED (smoke|protocol)"):
        validate_control_runtime_record(forced, evidence_root=EVIDENCE_DIR)


def _correction_env(monkeypatch, tmp_path, *, drop_snapshot=True):
    mod, _ = _load_modal_h100(monkeypatch)
    ev = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_DIR, ev)
    (ev / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json").write_bytes(ATTEMPT_5_SNAPSHOT.read_bytes())          # the pre-correction record
    if drop_snapshot:
        (ev / ATTEMPT_5_SNAPSHOT.name).unlink()
    monkeypatch.setattr(mod, "EVIDENCE_DIR", ev)
    boom = types.SimpleNamespace(remote=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no GPU / provider function may be called")))
    monkeypatch.setattr(mod, "serve_and_smoke", boom)
    monkeypatch.setattr(mod, "app", types.SimpleNamespace(run=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no Modal app run"))))
    monkeypatch.setattr(mod, "_cli_json", lambda *a: (_ for _ in ()).throw(AssertionError("no Modal CLI / billing call")))
    return mod, ev


def test_the_correction_mode_snapshots_first_changes_only_descriptive_metadata_and_calls_no_provider(monkeypatch, tmp_path):
    mod, ev = _correction_env(monkeypatch, tmp_path)
    args = types.SimpleNamespace(control="qwen3_8b", attempt=5)
    assert mod.cmd_correct_reasoning_mode(args) == 0
    snap = ev / ATTEMPT_5_SNAPSHOT.name
    assert snap.read_bytes() == ATTEMPT_5_SNAPSHOT.read_bytes()                                                                   # byte-identical pre-correction copy
    cur = json.loads((ev / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
    assert {k for k in set(cur) | set(_attempt5_snapshot()) if cur.get(k) != _attempt5_snapshot().get(k)} == {"reasoning_mode", "metadata_correction"}
    assert cur["reasoning_mode"].startswith("NON_THINKING") and cur["metadata_correction"]["snapshot_sha256"] == ATTEMPT_5_SNAPSHOT_SHA256
    first = (ev / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json").read_bytes()
    assert mod.cmd_correct_reasoning_mode(args) == 0                                                                              # idempotent
    assert (ev / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json").read_bytes() == first
    assert mod.cmd_correct_reasoning_mode(types.SimpleNamespace(control="qwen3_8b", attempt=4)) == 2                              # only the record's final attempt
    body = ast.unparse(next(n for n in ast.walk(ast.parse(MODAL_H100.read_text())) if isinstance(n, ast.FunctionDef) and n.name == "cmd_correct_reasoning_mode"))
    for banned in ("serve_and_smoke", ".remote(", "app.run", "billing_summary", "_cli_json", "subprocess", "eval(", "exec("):
        assert banned not in body, banned


def test_a_documented_metadata_correction_does_not_block_a_later_launch_but_other_drift_does(monkeypatch, tmp_path):
    mod, ev = _correction_env(monkeypatch, tmp_path, drop_snapshot=False)
    assert mod.cmd_correct_reasoning_mode(types.SimpleNamespace(control="qwen3_8b", attempt=5)) == 0
    assert mod.archive_prior_record("QWEN3_8B") == ATTEMPT_5_SNAPSHOT.name                                                       # corrected record vs its snapshot: accepted
    rec_path = ev / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json"
    tampered = json.loads(rec_path.read_text())
    tampered["smoke_outputs"][1]["content"] = "5"                                                                                # any change beyond the documented metadata
    rec_path.write_text(json.dumps(tampered))
    with pytest.raises(RuntimeError, match="refusing to overwrite prior-attempt evidence"):
        mod.archive_prior_record("QWEN3_8B")
    undocumented = json.loads(ATTEMPT_5_SNAPSHOT.read_text())
    undocumented["reasoning_mode"] = "NON_THINKING (undocumented edit)"
    rec_path.write_text(json.dumps(undocumented))
    with pytest.raises(RuntimeError, match="refusing to overwrite prior-attempt evidence"):
        mod.archive_prior_record("QWEN3_8B")


def test_only_the_qwen_non_thinking_configuration_changes_a_reasoning_mode_other_controls_are_unaffected():
    for control_default in ("NOT_APPLICABLE (non-reasoning instruct model)", "NOT_APPLICABLE (base phi-4 instruct, no thinking tags)"):
        assert runtime_cfg.effective_reasoning_mode(control_default, runtime_cfg.configuration_for_model("microsoft/phi-4")) == control_default
        assert runtime_cfg.effective_reasoning_mode(control_default, runtime_cfg.configuration_for_model("mistralai/Mistral-Nemo-Instruct-2407")) == control_default
    for tag in ("PHI4",):                                                           # Mistral-Nemo has since had its one authorized attempt
        r = json.loads((EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
        assert r["runtime_qualification_status"] == "NOT_TESTED" and r["reasoning_mode"].startswith("NOT_APPLICABLE")


# ── Mistral-Nemo: exact locked server flags proven from the container; no Qwen setting or parser may leak ──
MISTRAL_ARGS = ["--tokenizer-mode", "hf", "--config-format", "hf", "--load-format", "safetensors"]


def _mistral_proof(**over):
    m = LOCKED_CONTROL_IDENTITIES["Mistral-Nemo-Instruct-2407"]
    proof = {"runtime_configuration_id": None, "runtime_configuration_id_applied": None, "runtime_configuration_sha256": None, "runtime_policy_sha256": runtime_cfg.PINNED_RUNTIME_POLICY_SHA256,
             "chat_template_kwargs_sent": {sid: None for sid in "ABC"}, "smoke_protocol_sha256": CANONICAL_PROTOCOL_SHA256,
             "prompt_sha256_sent": {sid: locked_protocol.prompt_sha256(sid) for sid in "ABC"}, "model_id": m["model_id"], "served_model_id": m["model_id"],
             "revision": m["revision"], "precision": "bfloat16", "quantization": None, "reasoning_parser": None,
             "tokenizer_mode": "hf", "config_format": "hf", "load_format": "safetensors"}
    proof.update(over)
    return {"runtime_configuration_proof": proof}


def test_the_mistral_container_proof_requires_exactly_the_locked_flags_and_no_qwen_leakage(monkeypatch):
    mod, _ = _load_modal_h100(monkeypatch)
    m = LOCKED_CONTROL_IDENTITIES["Mistral-Nemo-Instruct-2407"]
    assert mod.container_proof_problems(_mistral_proof(), m["model_id"], m["revision"], MISTRAL_ARGS) == []
    assert _runner_module().LOCKED["mistral_nemo"]["extra_args"] == MISTRAL_ARGS
    for over in (dict(tokenizer_mode=None), dict(tokenizer_mode="mistral"), dict(config_format=None), dict(config_format="mistral"), dict(load_format="auto"), dict(load_format=None),
                 dict(reasoning_parser="qwen3"), dict(runtime_configuration_id="qwen3_8b_non_thinking_v1"), dict(runtime_configuration_id_applied="qwen3_8b_non_thinking_v1"),
                 dict(chat_template_kwargs_sent={sid: {"enable_thinking": False} for sid in "ABC"}), dict(chat_template_kwargs_sent={"A": None, "B": {"enable_thinking": False}, "C": None}),
                 dict(runtime_configuration_sha256=runtime_cfg.configuration_sha256("Qwen/Qwen3-8B")), dict(quantization="fp8"), dict(precision="float16"),
                 dict(smoke_protocol_sha256="0" * 64), dict(prompt_sha256_sent={"A": "0" * 64, "B": "0" * 64, "C": "0" * 64}), dict(revision="0" * 40), dict(served_model_id="other")):
        assert mod.container_proof_problems(_mistral_proof(**over), m["model_id"], m["revision"], MISTRAL_ARGS), over
    q = LOCKED_CONTROL_IDENTITIES["Qwen3-8B"]                                            # and the Qwen control still proves its parser
    assert any("--reasoning-parser" in p for p in mod.container_proof_problems(_proof_for(mod, reasoning_parser=None), q["model_id"], q["revision"], ["--reasoning-parser", "qwen3"]))


def test_the_container_proof_reads_the_server_flags_from_the_real_argv(monkeypatch):
    mod, _ = _load_modal_h100(monkeypatch)
    runner = _runner_module()
    cfg = runner.serving_config("mistral_nemo")
    assert cfg["runtime_configuration"] is None and cfg["extra_args"] == MISTRAL_ARGS
    argv = ["python", "-m", "vllm.entrypoints.openai.api_server", "--model", "<snap>", "--dtype", "bfloat16", *MISTRAL_ARGS, "--seed", "0"]
    proof = mod._container_proof(runner, cfg, {"server_argv_sanitized": argv, "smoke_results": [], "models_endpoint": {"data": [{"id": cfg["model_id"]}]}, "snapshot_dir_name": cfg["revision"]})
    assert (proof["tokenizer_mode"], proof["config_format"], proof["load_format"], proof["reasoning_parser"], proof["quantization"], proof["precision"]) == ("hf", "hf", "safetensors", None, None, "bfloat16")
    assert proof["runtime_configuration_id"] is None and proof["runtime_policy_sha256"] == PINNED_POLICY_SHA256


# ══ Mistral-Nemo-Instruct-2407 attempt 1 (owner-authorized, executed once): the persisted, honest result ═══════════════════════════════
MISTRAL_SMOKE_OUTPUTS_SHA256 = "fc6d67603f3dfb6981bd4fd95955c5f8923cb5bcdd08984ff1f11d5c1561a00a"
MISTRAL_RAW_LOG_SHA256 = "c4986233bce379dd1ff374ac856cee41235425e47886d455379f29852aed8aa3"


MISTRAL_A1_FINALIZED = EVIDENCE_DIR / "GENESIS_CONTROL_MISTRAL_NEMO_RUNTIME_QUALIFICATION_ATTEMPT1_FINALIZED_SNAPSHOT_2026-09-25.json"
MISTRAL_A1_FINALIZED_SHA256 = "bbde9921df216a253cf5f0f01a3210530e776794dd0bcad5e0f110e31e2d9464"


def _mistral():
    """The finalized ATTEMPT-1 record (byte-identical to the live record as it stood before attempt 2 overwrote it)."""
    return json.loads(MISTRAL_A1_FINALIZED.read_text())


def _mistral_live():
    return json.loads((EVIDENCE_DIR / "GENESIS_CONTROL_MISTRAL_NEMO_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())


MISTRAL_SNAPSHOT = EVIDENCE_DIR / "GENESIS_CONTROL_MISTRAL_NEMO_RUNTIME_QUALIFICATION_ATTEMPT1_SNAPSHOT_2026-09-24.json"
MISTRAL_SNAPSHOT_SHA256 = "5bcf5aa8423ea22082a554c39edf414dea27b45511dca1f3c18136e4fe9fd5df"


def test_mistral_attempt_1_served_the_exact_model_but_the_http_400_rejection_is_unattributed():
    m = _mistral()
    a = m["attempts"][-1]
    assert a["attempt_number"] == 1 and len(m["attempts"]) == 1 and a["provider"] == "Modal" and a["outcome"] == "UNATTRIBUTED_REQUEST_REJECTION" and a["failure_domain"] == "UNATTRIBUTED"
    assert m["technical_serving_status"] == "NOT_PROVEN" and m["runtime_qualification_status"] == "NOT_COMPLETED" and m["capability_status"] == "UNPROVEN"
    assert "NOT captured" in a["reason"] and "not a pass" in a["reason"] and "not evidence that the model is incompatible" in a["reason"]
    assert all(o["http_status"] is None and o["raw_response"] == "" and o["content"] is None and o["executed"] is False for o in m["smoke_outputs"])     # raw fields preserved exactly
    assert hashlib.sha256(json.dumps(m["smoke_outputs"], sort_keys=True).encode()).hexdigest() == MISTRAL_SMOKE_OUTPUTS_SHA256
    log = (EVIDENCE_DIR / m["raw_log_artifact"]).read_text()
    assert log.count('"POST /v1/chat/completions HTTP/1.1" 400 Bad Request') == 3 and "server ready" in log                                      # the immutable log proves three HTTP 400s
    assert hashlib.sha256((EVIDENCE_DIR / m["raw_log_artifact"]).read_bytes()).hexdigest() == m["raw_log_sha256"] == MISTRAL_RAW_LOG_SHA256
    gap = m["http_error_evidence_gap"]
    assert gap["api_error_bodies_captured"] is False and gap["proven_by_immutable_raw_server_log"]["post_chat_completions_statuses"] == [400, 400, 400]
    assert gap["preserved_unchanged"] == {"http_status": [None, None, None], "raw_response": ["", "", ""]} and "not reconstructed" in gap["statement"]
    validate_control_runtime_record(m, evidence_root=EVIDENCE_DIR)


def test_mistral_original_classification_and_the_pre_correction_record_are_preserved():
    assert hashlib.sha256(MISTRAL_SNAPSHOT.read_bytes()).hexdigest() == MISTRAL_SNAPSHOT_SHA256
    snap, cur = json.loads(MISTRAL_SNAPSHOT.read_text()), _mistral()
    assert snap["technical_serving_status"] == "FAILED" and snap["runtime_qualification_status"] == "FAILED" and snap["attempts"][-1]["outcome"] == "TECHNICAL_FAILURE"
    assert snap["attempts"][-1]["failure_domain"] == "MODEL_RUNTIME" and snap["attempts"][-1]["billing_settlement_status"] == "OBSERVED"       # the contradictory pre-correction state, kept as history
    oc = cur["attempts"][-1]["original_classification"]
    assert (oc["outcome"], oc["status"], oc["failure_domain"], oc["valid_runtime_attempt"]) == ("TECHNICAL_FAILURE", "TECHNICAL_FAILURE", "MODEL_RUNTIME", True)
    cc = cur["classification_correction"]
    assert cc["snapshot_sha256"] == MISTRAL_SNAPSHOT_SHA256 and cc["from"]["outcome"] == "TECHNICAL_FAILURE" and cc["to"]["outcome"] == "UNATTRIBUTED_REQUEST_REJECTION"
    assert "chat-completions qualification" in cc["not_established"] and "any model incompatibility" in cc["not_established"] and "server ready" in cc["established"]
    changed = {k for k in set(snap) | set(cur) if snap.get(k) != cur.get(k)}
    assert set(cc["changed_fields"]) | {"classification_correction"} == {"attempts", "technical_serving_status", "runtime_qualification_status", "container_execution_proof",
                                                                          "http_error_evidence_gap", "classification_correction"}
    # the later, hash-verified OBSERVED settlement reconciliation additionally finalized ONLY the settlement fields
    assert changed == set(cc["changed_fields"]) | {"classification_correction", "billing_settlement", "financial_reconciliation", "original_in_run_financial_reconciliation", "settlement_reconciliation"}
    for key in ("smoke_outputs", "raw_log_sha256", "raw_log_artifact", "financial_evidence", "original_in_run_billing_settlement",
                "settlement_correction", "identity_verification", "server_argv_sanitized", "started_at_utc", "finished_at_utc", "cold_start_seconds", "load_seconds",
                "latency_seconds", "peak_gpu_memory_bytes", "owner_billed_delta_usd", "smoke_prompts", "smoke_protocol"):
        assert cur[key] == snap[key], key
    strip = lambda a: {k: v for k, v in a.items() if k not in ("outcome", "status", "failure_domain", "reason", "original_classification", "billing_settlement_status",
                                                                 "original_in_run_billing_settlement_status", "settlement_reconciliation_artifact")}
    assert strip(cur["attempts"][-1]) == strip(snap["attempts"][-1])                                                                            # timings, ids, log hash untouched


def test_mistral_attempt_1_identity_flags_prompts_and_no_qwen_leakage_are_evidenced():
    m = _mistral()
    locked = LOCKED_CONTROL_IDENTITIES["Mistral-Nemo-Instruct-2407"]
    ident = m["identity_verification"]
    assert ident["pinned_revision_matches_runtime_artifact"] is True and ident["runtime_served_model_matches_pinned_id"] is True and ident["no_silent_model_fallback"] is True
    assert ident["weight_bytes_observed"] == locked["expected_weight_bytes"] and m["model_id"] == locked["model_id"] and m["model_revision"] == locked["revision"]
    argv = m["server_argv_sanitized"]
    assert argv[argv.index("--dtype") + 1] == "bfloat16" and "--quantization" not in argv and "--reasoning-parser" not in argv
    assert argv[argv.index("--tokenizer-mode") + 1] == "hf" and argv[argv.index("--config-format") + 1] == "hf" and argv[argv.index("--load-format") + 1] == "safetensors"
    assert m.get("runtime_configuration") is None and m["reasoning_parser"] is None and m["reasoning_mode"].startswith("NOT_APPLICABLE")
    assert all(o["chat_template_kwargs_sent"] is None for o in m["smoke_outputs"])                                                                  # NO Qwen-specific request setting
    assert [o["prompt_sha256_sent"] for o in m["smoke_outputs"]] == [locked_protocol.prompt_sha256(sid) for sid in "ABC"]
    assert [p["messages"] for p in m["smoke_prompts"]] == [locked_protocol.messages(sid) for sid in "ABC"] and m["smoke_protocol"]["protocol_sha256"] == CANONICAL_PROTOCOL_SHA256


def test_mistral_attempt_1_financials_cleanup_and_owner_cash_are_zero_and_the_settlement_claim_was_honestly_corrected():
    m = _mistral()
    assert m["financial_acceptance_status"] == "PASS" and m["owner_billed_delta_usd"] == "0E-8" and m["cleanup_status"] == "PASS" and m["live_resources_after_cleanup"] == 0
    fin = m["financial_evidence"]
    after = json.loads((EVIDENCE_DIR / fin["billing_after_artifact"]).read_text())
    assert after["owner_billed_delta_usd"] == "0E-8" and all(r["billed"] == "0E-8" for r in after["post_run_readings"]) and after["cleanup_snapshot"]["live_resources"] == 0
    assert after["app_row"]["state"] == "stopped" and after["app_row"]["tasks"] == "0"
    pre = json.loads((EVIDENCE_DIR / fin["preflight_artifact"]).read_text())
    assert pre["gate_decision"]["allowed"] is True and Decimal(pre["worst_case_cost_usd"]) <= Decimal("1.25")
    # the in-run OBSERVED matched itemized rows by the shared app description and so included Qwen attempt 5's app; corrected, original preserved
    assert m["original_in_run_billing_settlement"]["status"] == "OBSERVED"                              # the contaminated original determination is preserved as history
    assert m["billing_settlement"]["status"] == "OBSERVED" and m["settlement_reconciliation"]["artifact"].endswith("20260925T120607Z.json")     # finally OBSERVED by exact-attribution reconciliation
    corr = m["settlement_correction"]
    assert corr["reclassifies_attempt"] is False and [r["object_id"] for r in corr["foreign_rows_in_original_itemization"]] == ["ap-b6PkVuAdoik7AvUELDwNuQ"]
    assert hashlib.sha256((EVIDENCE_DIR / corr["reconciliation_artifact"]).read_bytes()).hexdigest() == corr["reconciliation_sha256"]
    att = json.loads((EVIDENCE_DIR / "GENESIS_CONTROL_MISTRAL_NEMO_ATTEMPTS_2026-09-24.json").read_text())["attempts"][0]
    assert att["billing_settlement_status"] == "OBSERVED" and att["original_in_run_billing_settlement_status"] == "OBSERVED" and att["outcome"] == "UNATTRIBUTED_REQUEST_REJECTION"
    assert m["attempts"][-1] == att and m["attempts"][-1]["billing_settlement_status"] == m["billing_settlement"]["status"]       # embedded == top-level == attempts file


def test_the_observed_mistral_settlement_is_resolved_by_evidence_never_by_a_waiver(monkeypatch):
    mod, _ = _load_modal_h100(monkeypatch)
    attempts = {(tag, a["attempt_number"]): a for tag, a in mod._modal_attempts()}
    assert mod.settlement_resolved("QWEN3_8B", attempts[("QWEN3_8B", 5)]) is True and mod.settlement_resolved("QWEN3_8B", attempts[("QWEN3_8B", 4)]) is True
    assert mod.settlement_resolved("MISTRAL_NEMO", attempts[("MISTRAL_NEMO", 1)]) is True                  # observed by the exact-attribution reconciliation
    assert mod.validate_owner_settlement_waiver("MISTRAL_NEMO", attempts[("MISTRAL_NEMO", 1)])[0] == "WAIVER_ABSENT"      # ... and NOT by a waiver
    assert not any(p.name.startswith("GENESIS_OWNER_SETTLEMENT_WAIVER_MISTRAL") for p in EVIDENCE_DIR.iterdir())
    assert mod.unresolved_settlement_upper_bound_usd() > 0                                                  # Qwen attempt 1's exposure is still deducted

def test_mistral_and_qwen_records_are_unchanged_by_the_mistral_run_and_phi4_is_untested():
    assert hashlib.sha256(ATTEMPT_4_SNAPSHOT.read_bytes()).hexdigest() == ATTEMPT_4_SNAPSHOT_SHA256 and hashlib.sha256(ATTEMPT_5_SNAPSHOT.read_bytes()).hexdigest() == ATTEMPT_5_SNAPSHOT_SHA256
    q = _persisted_qwen()
    assert q["runtime_qualification_status"] == "FAILED" and q["attempts"][-1]["attempt_number"] == 5 and hashlib.sha256(json.dumps(q["smoke_outputs"], sort_keys=True).encode()).hexdigest() == ATTEMPT_5_SMOKE_OUTPUTS_SHA256
    phi = json.loads((EVIDENCE_DIR / "GENESIS_CONTROL_PHI4_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
    assert phi["runtime_qualification_status"] == "NOT_TESTED" and phi["attempts"] == [] and phi["smoke_outputs"] == []


def test_a_run_matches_itemized_billing_rows_by_object_id_not_by_the_shared_app_description(monkeypatch, tmp_path):
    mod, ev, remote_calls = _run_env(monkeypatch, tmp_path, lambda m, r: _fake_container_result(m, r))
    rows = [{"object_id": "ap-TEST", "description": "orneur-p21b420-h100-control-runtime", "cost": "0.2", "interval_start": "2026-09-25T09:00:00"},
            {"object_id": "ap-EARLIER-ATTEMPT", "description": "orneur-p21b420-h100-control-runtime", "cost": "0.19", "interval_start": "2026-09-25T08:00:00"}]
    monkeypatch.setattr(mod, "_cli_json", lambda *a: rows)
    mod.cmd_run(types.SimpleNamespace(control="qwen3_8b"))
    after = json.loads((ev / "GENESIS_CONTROL_QWEN3_8B_MODAL_H100_ATTEMPT5_BILLING_AFTER_2026-09-24.json").read_text())
    assert [r["object_id"] for r in after["itemized_rows_for_app"]] == ["ap-TEST"]
    assert 'x.get("object_id") == app_id' in MODAL_H100.read_text() and 'x.get("description") == app.name' not in MODAL_H100.read_text()


def test_a_contaminated_in_run_settlement_is_corrected_honestly_and_the_gate_stays_closed(monkeypatch, tmp_path):
    mod, before = _reconcile_env(monkeypatch, tmp_path, metered_now="20.50000000", credits_now="-20.50000000", eph_before="20.07689253", eph_now="20.49230719", run_cost="0.20000000")
    rec_path = tmp_path / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json"
    rec = json.loads(rec_path.read_text())
    rec.update(technical_serving_status="FAILED", runtime_qualification_status="FAILED", billing_settlement={"status": "OBSERVED", "reasons": [], "stop_before_next_control": False})
    rec["attempts"][-1].update(outcome="TECHNICAL_FAILURE", status="TECHNICAL_FAILURE", failure_domain="MODEL_RUNTIME", billing_settlement_status="OBSERVED")
    after_doc = json.loads((tmp_path / rec["financial_evidence"]["billing_after_artifact"]).read_text())
    after_doc["itemized_rows_for_app"] = [{"object_id": "ap-OTHER-ATTEMPT", "cost": "0.19"}, {"object_id": "ap-SYNTHETICATTEMPT4", "cost": "0.2"}]
    (tmp_path / rec["financial_evidence"]["billing_after_artifact"]).write_text(json.dumps(after_doc))
    rec["financial_evidence"]["billing_after_sha256"] = hashlib.sha256((tmp_path / rec["financial_evidence"]["billing_after_artifact"]).read_bytes()).hexdigest()
    rec_path.write_text(json.dumps(rec))
    attempts_path = tmp_path / f"GENESIS_CONTROL_QWEN3_8B_ATTEMPTS_{mod.DATE_TAG}.json"
    doc = json.loads(attempts_path.read_text())
    doc["attempts"][-1].update(outcome="TECHNICAL_FAILURE", billing_settlement_status="OBSERVED")
    attempts_path.write_text(json.dumps(doc))
    assert mod.settlement_resolved("QWEN3_8B", doc["attempts"][-1]) is True                                # the contaminated claim would have unlocked the next control
    assert mod.cmd_reconcile(_rc_args(mod)) == 5                                                            # growth 0.4123 vs own row 0.2: not observable
    out = json.loads(rec_path.read_text())
    assert out["billing_settlement"]["status"] == "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE" and out["original_in_run_billing_settlement"]["status"] == "OBSERVED"
    assert out["settlement_correction"]["reclassifies_attempt"] is False and out["technical_serving_status"] == "FAILED" and out["runtime_qualification_status"] == "FAILED"
    assert out["smoke_outputs"] == rec["smoke_outputs"] and out["raw_log_sha256"] == rec["raw_log_sha256"] and out["financial_evidence"] == rec["financial_evidence"]
    corrected = json.loads(attempts_path.read_text())["attempts"][-1]
    assert corrected["billing_settlement_status"] == "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE" and corrected["original_in_run_billing_settlement_status"] == "OBSERVED"
    assert mod.settlement_resolved("QWEN3_8B", corrected) is False                                          # the gate is closed again until a reconciliation observes it


# ══ audit remediation: HTTPError capture, conservative Mistral classification, settlement consistency, container execution proof for EVERY control ═══
import http.server  # noqa: E402
import threading  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

_ERROR_JSON = '{"object": "error", "message": "synthetic bad request", "type": "BadRequestError", "code": 400}'
_HOSTILE_BODY = "__import__('os').system('touch {marker}')"        # response text is DATA: it must never be executed


class _FakeVllm(http.server.BaseHTTPRequestHandler):
    mode = "error_json"
    marker = ""

    def log_message(self, *a):  # noqa: D401
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        mode = type(self).mode
        if mode in ("error_json", "error_text", "error_hostile"):
            body = {"error_json": _ERROR_JSON, "error_text": "plain text error", "error_hostile": _HOSTILE_BODY.format(marker=type(self).marker)}[mode].encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json" if mode == "error_json" else "text/plain")
            self.send_header("Set-Cookie", "secret=1")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif mode == "ok_stream":
            body = b'data: {"choices":[{"delta":{"content":"READY"},"finish_reason":"stop"}],"usage":{"completion_tokens":2}}\n\ndata: [DONE]\n\n'
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = b'{"choices":[{"message":{"content":"5"},"finish_reason":"stop"}],"usage":{"completion_tokens":1}}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


@contextlib.contextmanager
def _fake_server(mode, marker=""):
    _FakeVllm.mode, _FakeVllm.marker = mode, marker
    srv = http.server.HTTPServer(("127.0.0.1", 0), _FakeVllm)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()

    def http_call(method, path, body=None, timeout=10.0):
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}{path}", method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=timeout)

    try:
        yield http_call
    finally:
        srv.shutdown()
        srv.server_close()


def _call_modules(monkeypatch):
    runner = _runner_module()
    stub = types.ModuleType("modal")
    stub.Image = type("Image", (), {"from_registry": classmethod(lambda cls, *a, **k: cls()), "entrypoint": lambda self, _c: self})
    stub.App = lambda n: types.SimpleNamespace(name=n, function=lambda **k: (lambda f: f))
    stub.exception = types.SimpleNamespace(TimeoutError=TimeoutError)
    monkeypatch.setitem(sys.modules, "modal", stub)
    spec = importlib.util.spec_from_file_location("p21b420_legacy_for_http", HARNESS_PATH)
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    return runner, legacy


@pytest.mark.parametrize("sid,stream", [("A", True), ("B", False), ("C", False)])
@pytest.mark.parametrize("mode,structured", [("error_json", True), ("error_text", False)])
def test_an_http_400_body_is_captured_for_streamed_and_non_streamed_requests(monkeypatch, sid, stream, mode, structured):
    for module in _call_modules(monkeypatch):                                                  # the shared runner AND the legacy harness carry the identical code
        cfg = module.serving_config("mistral_nemo") if hasattr(module, "serving_config") else {"model_id": "mistralai/Mistral-Nemo-Instruct-2407", "smoke_max_tokens": 64}
        smoke = next(x for x in module.SMOKES if x["smoke_id"] == sid)
        assert smoke["stream"] is stream
        with _fake_server(mode) as call:
            entry = module.run_smoke_call(cfg, smoke, {"temperature": 0, "top_p": 1, "seed": 0, "max_tokens": 64}, call)
        body = _ERROR_JSON if mode == "error_json" else "plain text error"
        assert entry["http_status"] == 400 and entry["raw_response"] == body and entry["smoke_id"] == sid
        err = entry["http_error"]
        assert err["status"] == 400 and err["error_class"] == "HTTPError" and err["smoke_id"] == sid and err["body_bytes"] == len(body.encode())
        assert err["body_sha256"] == hashlib.sha256(body.encode()).hexdigest()                                     # sha256 of the captured body
        assert (err["structured_error"] == json.loads(_ERROR_JSON)) if structured else err["structured_error"] is None
        assert "content-type" in {k.lower() for k in err["headers"]} and "set-cookie" not in {k.lower() for k in err["headers"]}     # safe headers only
        assert entry["error"].startswith("HTTPError: HTTP Error 400") and entry["matches_expected_exactly"] is False and "content" not in entry
        assert entry["prompt_sha256_sent"] == locked_protocol.prompt_sha256(sid) and entry["chat_template_kwargs_sent"] is None


def test_the_refactored_smoke_call_still_records_successful_streamed_and_non_streamed_responses(monkeypatch):
    for module in _call_modules(monkeypatch):
        cfg = {"model_id": "m", "smoke_max_tokens": 8, "runtime_configuration": None}
        gen = {"temperature": 0, "top_p": 1, "seed": 0, "max_tokens": 8}
        with _fake_server("ok_stream") as call:
            a = module.run_smoke_call(cfg, next(x for x in module.SMOKES if x["smoke_id"] == "A"), gen, call)
        with _fake_server("ok") as call:
            b = module.run_smoke_call(cfg, next(x for x in module.SMOKES if x["smoke_id"] == "B"), gen, call)
        assert (a["http_status"], a["content"], a["matches_expected_exactly"]) == (200, "READY", True) and "http_error" not in a
        assert (b["http_status"], b["content"], b["matches_expected_exactly"]) == (200, "5", True) and "http_error" not in b


def test_an_http_error_body_is_data_only_and_never_executed(monkeypatch, tmp_path):
    marker = tmp_path / "PWNED"
    runner, _ = _call_modules(monkeypatch)
    cfg = {"model_id": "m", "smoke_max_tokens": 8, "runtime_configuration": None}
    with _fake_server("error_hostile", marker=str(marker)) as call:
        entry = runner.run_smoke_call(cfg, next(x for x in runner.SMOKES if x["smoke_id"] == "B"), {"temperature": 0, "top_p": 1, "seed": 0, "max_tokens": 8}, call)
    assert entry["raw_response"] == _HOSTILE_BODY.format(marker=marker) and not marker.exists()                # stored verbatim, nothing ran
    for path in (LIGHTNING_RUNNER, HARNESS_PATH):
        for name in ("capture_http_error", "run_smoke_call"):
            src = _fn_source(path, name)
            assert not any(b in src for b in ("eval(", "exec(", "compile(", "subprocess", "os.system", "__import__("))


def test_the_record_builder_persists_the_captured_http_error_fields():
    text = LIGHTNING_CONTROL.read_text()
    assert '"error": s.get("error"), "http_error": s.get("http_error")' in text


# ── validator: conservative attribution, settlement consistency, container execution proof ──
def _mistral_record(tmp_path, *, outcome="UNATTRIBUTED_REQUEST_REJECTION", technical="NOT_PROVEN", runtime="NOT_COMPLETED", statuses=None, proof="ok"):
    rec = _qualified_record(tmp_path, "Mistral-Nemo-Instruct-2407")
    rec.update(gpu_type="NVIDIA H100 80GB (Modal H100)", technical_serving_status=technical, runtime_qualification_status=runtime, reasoning_parser=None)
    rec["attempts"] = [{"attempt_number": 1, "provider": "Modal", "outcome": outcome, "valid_runtime_attempt": True, "reason": "synthetic", "resource_type": "x",
                        "duration_seconds": 176.2, "owner_billed_delta_usd": "0E-8", "cleanup_result": "PASS", "billing_settlement_status": "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE"}]
    rec["billing_settlement"] = {"status": "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE", "reasons": ["x"], "stop_before_next_control": True}
    for o, st in zip(rec["smoke_outputs"], statuses or [None, None, None]):
        o["http_status"] = st
        if st is None:
            o["raw_response"] = ""
            o["raw_response_sha256"] = hashlib.sha256(b"").hexdigest()
    if proof == "ok":
        rec["container_execution_proof"] = dict(_mistral_proof()["runtime_configuration_proof"], provenance="CONTAINER_RETURNED")
    return rec


def test_a_missing_http_error_body_prevents_a_model_runtime_attribution(tmp_path):
    from orca.eval.control_runtime_qualification import ATTEMPT_OUTCOMES, FAILURE_DOMAIN_BY_OUTCOME
    validate_control_runtime_record(_mistral_record(tmp_path), evidence_root=tmp_path)                       # UNATTRIBUTED + NOT_PROVEN / NOT_COMPLETED is accepted
    with pytest.raises(ControlRuntimeError, match="MODEL_RUNTIME attribution requires a captured HTTP 200"):
        validate_control_runtime_record(_mistral_record(tmp_path, outcome="TECHNICAL_FAILURE", technical="FAILED", runtime="FAILED"), evidence_root=tmp_path)
    with pytest.raises(ControlRuntimeError, match="MODEL_RUNTIME attribution requires a captured HTTP 200"):
        validate_control_runtime_record(_mistral_record(tmp_path, outcome="TECHNICAL_FAILURE", technical="FAILED", runtime="FAILED", statuses=[400, 400, 400]), evidence_root=tmp_path)
    with pytest.raises(ControlRuntimeError, match="requires a valid model-runtime attempt"):                   # an unattributed rejection can never be a model-runtime FAILED
        validate_control_runtime_record(_mistral_record(tmp_path, technical="FAILED", runtime="FAILED"), evidence_root=tmp_path)
    assert FAILURE_DOMAIN_BY_OUTCOME["UNATTRIBUTED_REQUEST_REJECTION"] == "UNATTRIBUTED" and "UNATTRIBUTED_REQUEST_REJECTION" in ATTEMPT_OUTCOMES
    assert derive_runtime_status(technical="NOT_PROVEN", financial_acceptance="PASS", cleanup="PASS", owner_billed_delta_usd="0", live_resources_after_cleanup=0) == "NOT_COMPLETED"


def test_the_embedded_attempt_settlement_must_equal_the_top_level_settlement_after_a_correction(tmp_path):
    rec = _mistral_record(tmp_path)
    rec["original_in_run_billing_settlement"] = {"status": "OBSERVED", "reasons": []}
    rec["settlement_correction"] = {"reason": "x"}
    validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec["attempts"][-1]["billing_settlement_status"] = "OBSERVED"                                             # the audit's contradiction
    with pytest.raises(ControlRuntimeError, match="contradicts the corrected top-level"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _mistral_record(tmp_path)
    rec["original_in_run_billing_settlement"] = {"status": "OBSERVED", "reasons": []}
    rec["attempts"][-1]["billing_settlement_status"] = "SOMETHING_ELSE"
    with pytest.raises(ControlRuntimeError, match="neither the current settlement nor the preserved"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)
    qwen4 = _attempt4_record()                                                                                   # historical finalization: in-run value kept as history, top-level OBSERVED
    assert qwen4["attempts"][-1]["billing_settlement_status"] == "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE" and qwen4["billing_settlement"]["status"] == "OBSERVED"
    validate_control_runtime_record(qwen4, evidence_root=EVIDENCE_DIR)


@pytest.mark.parametrize("label,mutate,match", [
    ("missing_proof", lambda r: r.pop("container_execution_proof"), "requires container_execution_proof"),
    ("qwen_configuration_leaked", lambda r: r["container_execution_proof"].update(runtime_configuration_id="qwen3_8b_non_thinking_v1"), "no other control's configuration"),
    ("qwen_applied_leaked", lambda r: r["container_execution_proof"].update(runtime_configuration_id_applied="qwen3_8b_non_thinking_v1"), "no other control's configuration"),
    ("qwen_kwargs_leaked", lambda r: r["container_execution_proof"]["chat_template_kwargs_sent"].update(B={"enable_thinking": False}), "chat_template_kwargs sent must be None"),
    ("kwargs_key_missing", lambda r: r["container_execution_proof"]["chat_template_kwargs_sent"].pop("C"), "chat_template_kwargs sent"),
    ("reasoning_parser_leaked", lambda r: r["container_execution_proof"].update(reasoning_parser="qwen3"), "reasoning_parser proven as 'qwen3'"),
    ("tokenizer_mode_wrong", lambda r: r["container_execution_proof"].update(tokenizer_mode="mistral"), "tokenizer_mode proven as 'mistral'"),
    ("tokenizer_mode_missing", lambda r: r["container_execution_proof"].update(tokenizer_mode=None), "tokenizer_mode"),
    ("config_format_wrong", lambda r: r["container_execution_proof"].update(config_format="mistral"), "config_format"),
    ("load_format_wrong", lambda r: r["container_execution_proof"].update(load_format="auto"), "load_format"),
    ("wrong_protocol", lambda r: r["container_execution_proof"].update(smoke_protocol_sha256="0" * 64), "canonical smoke protocol"),
    ("wrong_prompt_hash", lambda r: r["container_execution_proof"]["prompt_sha256_sent"].update(A="0" * 64), "canonical smoke protocol"),
    ("wrong_model", lambda r: r["container_execution_proof"].update(model_id="mistralai/Mistral-Nemo-Base-2407"), "model id"),
    ("wrong_served_model", lambda r: r["container_execution_proof"].update(served_model_id="other"), "model id"),
    ("wrong_revision", lambda r: r["container_execution_proof"].update(revision="0" * 40), "revision"),
    ("wrong_precision", lambda r: r["container_execution_proof"].update(precision="float16"), "bfloat16"),
    ("quantized", lambda r: r["container_execution_proof"].update(quantization="fp8"), "bfloat16"),
    ("bad_provenance", lambda r: r["container_execution_proof"].update(provenance="TRUST_ME"), "provenance"),
    ("returned_proof_wrong_policy_hash", lambda r: r["container_execution_proof"].update(runtime_policy_sha256="0" * 64), "runtime-policy sha256"),
    ("returned_proof_missing_policy_hash", lambda r: r["container_execution_proof"].update(runtime_policy_sha256=None), "runtime-policy sha256"),
    ("reconstructed_claims_a_policy_hash", lambda r: r["container_execution_proof"].update(provenance="RECONSTRUCTED_FROM_PERSISTED_EVIDENCE", reconstruction_note="x"), "grandfathered exception|correction markers"),
    ("reconstructed_without_a_note", lambda r: r["container_execution_proof"].update(provenance="RECONSTRUCTED_FROM_PERSISTED_EVIDENCE", runtime_policy_sha256=None), "grandfathered exception|correction markers"),
    ("top_level_proof_without_explicit_provenance", lambda r: r["container_execution_proof"].pop("provenance"), "provenance must be one of"),
])
def test_a_valid_runtime_attempt_requires_the_full_container_execution_proof_with_null_qwen_settings_and_exact_mistral_flags(tmp_path, label, mutate, match):
    rec = _mistral_record(tmp_path)
    validate_control_runtime_record(rec, evidence_root=tmp_path)
    mutate(rec)
    with pytest.raises(ControlRuntimeError, match=match):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


def test_the_grandfathered_historical_mistral_attempt_1_reconstructed_proof_is_accepted():
    m = _mistral()
    assert m["container_execution_proof"]["provenance"] == "RECONSTRUCTED_FROM_PERSISTED_EVIDENCE" and m["container_execution_proof"]["runtime_policy_sha256"] is None
    validate_control_runtime_record(m, evidence_root=EVIDENCE_DIR)


def test_the_locked_server_flags_in_the_validator_mirror_the_runner_lock():
    from orca.eval.control_runtime_qualification import LOCKED_SERVER_FLAGS
    runner = _runner_module()
    for key, name in (("qwen3_8b", "Qwen3-8B"), ("mistral_nemo", "Mistral-Nemo-Instruct-2407"), ("phi4", "Phi-4")):
        args = runner.LOCKED[key]["extra_args"]
        want = dict(zip(args[0::2], args[1::2]))
        assert LOCKED_SERVER_FLAGS[name] == {"reasoning_parser": want.get("--reasoning-parser"), "tokenizer_mode": want.get("--tokenizer-mode"),
                                             "config_format": want.get("--config-format"), "load_format": want.get("--load-format")}


def test_the_qwen_proof_stays_cross_bound_and_historical_qwen_attempts_are_exempt(tmp_path):
    validate_control_runtime_record(_attempt4_record(), evidence_root=EVIDENCE_DIR)                            # attempt 4 predates the proof: never retro-fitted
    validate_control_runtime_record(_persisted_qwen(), evidence_root=EVIDENCE_DIR)                             # attempt 5: proof lives in runtime_configuration.container_proof
    rec = _qwen5(tmp_path)
    rec["gpu_type"] = "NVIDIA H100 80GB (Modal H100)"
    rec["container_execution_proof"] = dict(copy.deepcopy(rec["runtime_configuration"]["container_proof"]), provenance="CONTAINER_RETURNED")
    validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec["container_execution_proof"]["chat_template_kwargs_sent"]["B"] = {"enable_thinking": True}
    with pytest.raises(ControlRuntimeError, match="container_execution_proof disagrees"):
        validate_control_runtime_record(rec, evidence_root=tmp_path)


def test_the_persisted_mistral_proof_is_reconstructed_binds_the_exact_flags_and_null_qwen_settings():
    m = _mistral()
    p = m["container_execution_proof"]
    locked = LOCKED_CONTROL_IDENTITIES["Mistral-Nemo-Instruct-2407"]
    assert p["provenance"] == "RECONSTRUCTED_FROM_PERSISTED_EVIDENCE" and p["runtime_policy_sha256"] is None and "not reconstructable" in p["reconstruction_note"]
    assert (p["model_id"], p["served_model_id"], p["revision"], p["precision"], p["quantization"]) == (locked["model_id"], locked["model_id"], locked["revision"], "bfloat16", None)
    assert (p["tokenizer_mode"], p["config_format"], p["load_format"], p["reasoning_parser"]) == ("hf", "hf", "safetensors", None)
    assert p["runtime_configuration_id"] is None and p["runtime_configuration_id_applied"] is None and p["chat_template_kwargs_sent"] == {"A": None, "B": None, "C": None}
    assert p["smoke_protocol_sha256"] == CANONICAL_PROTOCOL_SHA256 and p["prompt_sha256_sent"] == {sid: locked_protocol.prompt_sha256(sid) for sid in "ABC"}


def test_a_new_harness_record_persists_the_container_execution_proof_for_every_control(monkeypatch, tmp_path):
    mod, ev, remote_calls = _run_env(monkeypatch, tmp_path, lambda m, r: _fake_container_result(m, r))
    mod.cmd_run(types.SimpleNamespace(control="qwen3_8b"))
    rec = json.loads((ev / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
    assert rec["container_execution_proof"]["provenance"] == "CONTAINER_RETURNED" and rec["container_execution_proof"]["runtime_policy_sha256"] == PINNED_POLICY_SHA256
    assert {k: v for k, v in rec["container_execution_proof"].items() if k != "provenance"} == rec["runtime_configuration"]["container_proof"]
    assert "container_execution_proof" in ast.unparse(next(n for n in ast.walk(ast.parse(MODAL_H100.read_text())) if isinstance(n, ast.FunctionDef) and n.name == "cmd_run"))
    validate_control_runtime_record(rec, evidence_root=ev)


def test_an_http_rejection_in_a_future_run_is_classified_unattributed_never_model_runtime(monkeypatch, tmp_path):
    def builder(m, r):
        result = _fake_container_result(m, r)
        for x in result["smoke_results"]:
            x.update(http_status=400, content=None, raw_response='{"error": "synthetic"}', matches_expected_exactly=False, error="HTTPError: HTTP Error 400: Bad Request",
                     http_error={"status": 400, "body_sha256": hashlib.sha256(b'{"error": "synthetic"}').hexdigest()})
        return result

    mod, ev, remote_calls = _run_env(monkeypatch, tmp_path, builder)
    mod.cmd_run(types.SimpleNamespace(control="qwen3_8b"))
    a5 = json.loads((ev / "GENESIS_CONTROL_QWEN3_8B_ATTEMPTS_2026-09-24.json").read_text())["attempts"][4]
    assert a5["outcome"] == "UNATTRIBUTED_REQUEST_REJECTION" and a5["failure_domain"] == "UNATTRIBUTED" and "not attributable to the model" in a5["reason"]
    rec = json.loads((ev / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
    assert rec["technical_serving_status"] == "NOT_PROVEN" and rec["runtime_qualification_status"] == "NOT_COMPLETED"
    assert all(o["http_status"] == 400 and o["http_error"]["status"] == 400 for o in rec["smoke_outputs"])


def _reclass_env(monkeypatch, tmp_path):
    mod, _ = _load_modal_h100(monkeypatch)
    ev = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_DIR, ev)
    (ev / "GENESIS_CONTROL_MISTRAL_NEMO_RUNTIME_QUALIFICATION_2026-09-24.json").write_bytes(MISTRAL_SNAPSHOT.read_bytes())          # the pre-correction record
    (ev / MISTRAL_SNAPSHOT.name).unlink()
    attempts_path = ev / "GENESIS_CONTROL_MISTRAL_NEMO_ATTEMPTS_2026-09-24.json"
    doc = json.loads(attempts_path.read_text())
    doc["attempts"] = json.loads(MISTRAL_SNAPSHOT.read_text())["attempts"]
    attempts_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    monkeypatch.setattr(mod, "EVIDENCE_DIR", ev)
    boom = types.SimpleNamespace(remote=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no GPU / provider function may be called")))
    monkeypatch.setattr(mod, "serve_and_smoke", boom)
    monkeypatch.setattr(mod, "app", types.SimpleNamespace(run=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no Modal app run"))))
    monkeypatch.setattr(mod, "_cli_json", lambda *a: (_ for _ in ()).throw(AssertionError("no Modal CLI / billing call")))
    return mod, ev


def test_the_cpu_only_reclassification_reproduces_the_persisted_mistral_record_and_calls_no_provider(monkeypatch, tmp_path):
    mod, ev = _reclass_env(monkeypatch, tmp_path)
    args = types.SimpleNamespace(control="mistral_nemo", attempt=1)
    assert mod.cmd_reclassify_unattributed(args) == 0
    assert (ev / MISTRAL_SNAPSHOT.name).read_bytes() == MISTRAL_SNAPSHOT.read_bytes()                       # snapshot taken first, byte-identical
    out = json.loads((ev / "GENESIS_CONTROL_MISTRAL_NEMO_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
    persisted = _mistral()
    strip = lambda xs: [{k: v for k, v in a.items() if k not in ("billing_settlement_status", "settlement_reconciliation_artifact")} for a in xs]
    for key in ("technical_serving_status", "container_execution_proof", "http_error_evidence_gap"):
        assert out[key] == persisted[key], key
    assert strip(out["attempts"]) == strip(persisted["attempts"]) and out["runtime_qualification_status"] == persisted["runtime_qualification_status"] == "NOT_COMPLETED"
    first = (ev / "GENESIS_CONTROL_MISTRAL_NEMO_RUNTIME_QUALIFICATION_2026-09-24.json").read_bytes()
    assert mod.cmd_reclassify_unattributed(args) == 0 and (ev / "GENESIS_CONTROL_MISTRAL_NEMO_RUNTIME_QUALIFICATION_2026-09-24.json").read_bytes() == first    # idempotent
    body = ast.unparse(next(n for n in ast.walk(ast.parse(MODAL_H100.read_text())) if isinstance(n, ast.FunctionDef) and n.name == "cmd_reclassify_unattributed"))
    for banned in ("serve_and_smoke", ".remote(", "app.run", "billing_summary", "_cli_json", "subprocess", "eval(", "exec("):
        assert banned not in body, banned
    rec_path = ev / "GENESIS_CONTROL_MISTRAL_NEMO_RUNTIME_QUALIFICATION_2026-09-24.json"
    assert mod.archive_prior_record("MISTRAL_NEMO") == MISTRAL_SNAPSHOT.name                                  # a later launch accepts exactly this documented correction
    tampered = json.loads(rec_path.read_text())
    tampered["smoke_outputs"][0]["http_status"] = 400                                                        # fabricating a status would be refused
    rec_path.write_text(json.dumps(tampered))
    with pytest.raises(RuntimeError, match="refusing to overwrite prior-attempt evidence"):
        mod.archive_prior_record("MISTRAL_NEMO")


def test_the_reclassification_refuses_when_the_raw_log_does_not_prove_the_rejection(monkeypatch, tmp_path):
    mod, ev = _reclass_env(monkeypatch, tmp_path)
    args = types.SimpleNamespace(control="mistral_nemo", attempt=1)
    assert mod.cmd_reclassify_unattributed(types.SimpleNamespace(control="mistral_nemo", attempt=2)) == 2
    log = ev / json.loads(MISTRAL_SNAPSHOT.read_text())["raw_log_artifact"]
    log.write_text(log.read_text().replace(" 400 Bad Request", " 200 OK"))                                      # a log that no longer proves the rejection (and no longer matches its hash)
    assert mod.cmd_reclassify_unattributed(args) == 2
    assert json.loads((ev / "GENESIS_CONTROL_MISTRAL_NEMO_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())["technical_serving_status"] == "FAILED"


def test_mistral_final_state_settlement_gate_and_neighbours_after_the_remediation(monkeypatch):
    m = _mistral()
    assert m["technical_serving_status"] == "NOT_PROVEN" and m["runtime_qualification_status"] == "NOT_COMPLETED" and m["capability_status"] == "UNPROVEN"
    assert m["owner_billed_delta_usd"] == "0E-8" and m["billing_settlement"]["status"] == "OBSERVED"
    art = json.loads((EVIDENCE_DIR / m["settlement_reconciliation"]["artifact"]).read_text())
    assert art["itemized_run_cost_usd"] == "0.20532158" and art["owner_billed_delta_usd"] == "0E-8" and art["settlement"]["status"] == "OBSERVED" and art["app_listing"] == "ABSENT_FROM_LISTING_RUNTIME_EVIDENCE_STOPPED"
    earlier = json.loads((EVIDENCE_DIR / m["settlement_correction"]["reconciliation_artifact"]).read_text())
    assert earlier["settlement"]["status"] == "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE"                       # the earlier downgrade evidence is preserved
    mod, _ = _load_modal_h100(monkeypatch)
    attempts = {(t, a["attempt_number"]): a for t, a in mod._modal_attempts()}
    assert mod.settlement_resolved("MISTRAL_NEMO", attempts[("MISTRAL_NEMO", 1)]) is True and mod.validate_owner_settlement_waiver("MISTRAL_NEMO", attempts[("MISTRAL_NEMO", 1)])[0] == "WAIVER_ABSENT"
    assert not any(p.name.startswith("GENESIS_OWNER_SETTLEMENT_WAIVER_MISTRAL") for p in EVIDENCE_DIR.iterdir())
    q = _persisted_qwen()
    assert q["runtime_qualification_status"] == "FAILED" and hashlib.sha256(json.dumps(q["smoke_outputs"], sort_keys=True).encode()).hexdigest() == ATTEMPT_5_SMOKE_OUTPUTS_SHA256
    assert hashlib.sha256(ATTEMPT_5_SNAPSHOT.read_bytes()).hexdigest() == ATTEMPT_5_SNAPSHOT_SHA256 and hashlib.sha256(ATTEMPT_4_SNAPSHOT.read_bytes()).hexdigest() == ATTEMPT_4_SNAPSHOT_SHA256
    phi = json.loads((EVIDENCE_DIR / "GENESIS_CONTROL_PHI4_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
    assert phi["runtime_qualification_status"] == "NOT_TESTED" and phi["attempts"] == []


# ══ proof-provenance hardening: RECONSTRUCTED is grandfathered for Mistral-Nemo attempt 1 ONLY ═══════════════════════════════════════════════
from orca.eval.control_runtime_qualification import GRANDFATHERED_RECONSTRUCTED_PROOFS  # noqa: E402


def test_the_grandfather_rule_is_exactly_mistral_attempt_1_with_the_pinned_snapshot_and_raw_log():
    assert GRANDFATHERED_RECONSTRUCTED_PROOFS == {("Mistral-Nemo-Instruct-2407", 1): {
        "snapshot_artifact": "GENESIS_CONTROL_MISTRAL_NEMO_RUNTIME_QUALIFICATION_ATTEMPT1_SNAPSHOT_2026-09-24.json", "snapshot_sha256": MISTRAL_SNAPSHOT_SHA256,
        "raw_log_sha256": MISTRAL_RAW_LOG_SHA256, "outcome": "UNATTRIBUTED_REQUEST_REJECTION"}}
    m = _mistral()
    assert m["classification_correction"]["snapshot_sha256"] == MISTRAL_SNAPSHOT_SHA256 and m["raw_log_sha256"] == MISTRAL_RAW_LOG_SHA256


def _reconstructed_variant(**over):
    m = copy.deepcopy(_mistral())
    m.update(over)
    return m


def test_reconstructed_provenance_fails_for_mistral_attempt_2():
    m = _mistral()
    a2 = copy.deepcopy(m["attempts"][0])
    a2.update(attempt_number=2)
    a2.pop("original_classification", None)
    rec = _reconstructed_variant(attempts=[m["attempts"][0], a2])
    with pytest.raises(ControlRuntimeError, match="grandfathered exception for Mistral-Nemo attempt 1 ONLY"):
        validate_control_runtime_record(rec, evidence_root=EVIDENCE_DIR)


def test_reconstructed_provenance_fails_for_phi4_attempt_1_and_for_any_new_qwen_attempt(tmp_path):
    phi = _mistral_record(tmp_path)
    phi.update(control_name="Phi-4", model_id=LOCKED_CONTROL_IDENTITIES["Phi-4"]["model_id"], model_revision=LOCKED_CONTROL_IDENTITIES["Phi-4"]["revision"])
    phi["container_execution_proof"].update(provenance="RECONSTRUCTED_FROM_PERSISTED_EVIDENCE", runtime_policy_sha256=None, reconstruction_note="x")
    with pytest.raises(ControlRuntimeError, match="grandfathered exception for Mistral-Nemo attempt 1 ONLY"):
        validate_control_runtime_record(phi, evidence_root=tmp_path)
    q = _qwen5(tmp_path)                                                                                      # a NEW Qwen attempt (5) cannot use a reconstructed proof
    q["gpu_type"] = "NVIDIA H100 80GB (Modal H100)"
    q["container_execution_proof"] = dict(copy.deepcopy(q["runtime_configuration"]["container_proof"]), provenance="RECONSTRUCTED_FROM_PERSISTED_EVIDENCE")
    with pytest.raises(ControlRuntimeError, match="grandfathered exception for Mistral-Nemo attempt 1 ONLY"):
        validate_control_runtime_record(q, evidence_root=tmp_path)
    q6 = _qwen5(tmp_path)                                                                                     # ... nor any later one
    q6["gpu_type"] = "NVIDIA H100 80GB (Modal H100)"
    extra = dict(q6["attempts"][-1], attempt_number=6)
    q6["attempts"] = q6["attempts"] + [extra]
    q6["container_execution_proof"] = dict(copy.deepcopy(q6["runtime_configuration"]["container_proof"]), provenance="RECONSTRUCTED_FROM_PERSISTED_EVIDENCE")
    with pytest.raises(ControlRuntimeError, match="grandfathered exception for Mistral-Nemo attempt 1 ONLY"):
        validate_control_runtime_record(q6, evidence_root=tmp_path)


@pytest.mark.parametrize("label,mutate", [
    ("outcome_differs", lambda r: r["attempts"][-1].update(outcome="TECHNICAL_FAILURE", failure_domain="MODEL_RUNTIME")),
    ("correction_snapshot_sha_differs", lambda r: r["classification_correction"].update(snapshot_sha256="0" * 64)),
    ("correction_snapshot_name_differs", lambda r: r["classification_correction"].update(snapshot_artifact="OTHER_SNAPSHOT.json")),
    ("correction_block_missing", lambda r: r.pop("classification_correction")),
    ("record_raw_log_sha_differs", lambda r: r.update(raw_log_sha256="0" * 64)),
    ("gap_raw_log_sha_differs", lambda r: r["http_error_evidence_gap"]["proven_by_immutable_raw_server_log"].update(sha256="0" * 64)),
    ("gap_block_missing", lambda r: r.pop("http_error_evidence_gap")),
])
def test_every_historical_correction_marker_must_agree_for_the_grandfathered_exception(label, mutate):
    rec = _reconstructed_variant()
    mutate(rec)
    with pytest.raises(ControlRuntimeError):
        validate_control_runtime_record(rec, evidence_root=EVIDENCE_DIR)


def test_a_tampered_grandfathered_snapshot_file_is_refused(tmp_path):
    ev = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_DIR, ev)
    (ev / MISTRAL_SNAPSHOT.name).write_text("{}")
    with pytest.raises(ControlRuntimeError):
        validate_control_runtime_record(_mistral(), evidence_root=ev)


def test_an_otherwise_identical_future_attempt_with_reconstructed_provenance_fails_but_container_returned_passes(tmp_path):
    ok = _mistral_record(tmp_path)                                            # a future-style Mistral record: CONTAINER_RETURNED
    validate_control_runtime_record(ok, evidence_root=tmp_path)
    bad = _mistral_record(tmp_path)
    bad["attempts"] = [dict(bad["attempts"][0], attempt_number=1), dict(bad["attempts"][0], attempt_number=2)]
    bad["container_execution_proof"].update(provenance="RECONSTRUCTED_FROM_PERSISTED_EVIDENCE", runtime_policy_sha256=None, reconstruction_note="manufactured after execution")
    with pytest.raises(ControlRuntimeError, match="grandfathered exception"):
        validate_control_runtime_record(bad, evidence_root=tmp_path)


def test_the_harness_can_only_record_a_container_returned_proof_and_a_missing_one_is_a_harness_failure(monkeypatch, tmp_path):
    text = MODAL_H100.read_text()
    run = ast.unparse(next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and n.name == "cmd_run"))
    assert "RECONSTRUCTED" not in run and "provenance='CONTAINER_RETURNED'" in run.replace('"', "'")            # the run path can only stamp CONTAINER_RETURNED
    mod, ev, remote_calls = _run_env(monkeypatch, tmp_path, lambda m, r: {k: v for k, v in _fake_container_result(m, r).items() if k != "runtime_configuration_proof"})
    mod.cmd_run(types.SimpleNamespace(control="qwen3_8b"))
    a5 = json.loads((ev / "GENESIS_CONTROL_QWEN3_8B_ATTEMPTS_2026-09-24.json").read_text())["attempts"][4]
    assert a5["outcome"] == "HARNESS_FAILURE" and a5["failure_domain"] == "HARNESS" and a5["valid_runtime_attempt"] is False and "no runtime_configuration_proof" in a5["reason"]
    rec = json.loads((ev / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
    assert rec["technical_serving_status"] == "NOT_PROVEN" and rec.get("container_execution_proof") is None


def test_the_reclassification_mode_is_refused_for_anything_but_the_grandfathered_attempt(monkeypatch):
    mod, _ = _load_modal_h100(monkeypatch)
    assert mod.cmd_reclassify_unattributed(types.SimpleNamespace(control="qwen3_8b", attempt=5)) == 2
    assert mod.cmd_reclassify_unattributed(types.SimpleNamespace(control="phi4", attempt=1)) == 2
    assert mod.cmd_reclassify_unattributed(types.SimpleNamespace(control="mistral_nemo", attempt=2)) == 2


# ── reconcile: an app that has aged out of Modal's listing is not a live app; a NOT_COMPLETED record is never relabelled PENDING ──
def test_reconcile_treats_an_app_that_aged_out_of_the_listing_as_not_live_only_with_run_time_stopped_evidence(monkeypatch, tmp_path):
    mod, before = _reconcile_env(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "_app_row", lambda name, app_id: None)                                          # the stopped ephemeral app is no longer listed
    assert mod.cmd_reconcile(_rc_args(mod)) == 0
    art = json.loads(_rc_artifacts(tmp_path)[0].read_text())
    assert art["app_listing"] == "ABSENT_FROM_LISTING_RUNTIME_EVIDENCE_STOPPED" and art["app_stopped_with_zero_tasks"] is True and art["settlement"]["status"] == "OBSERVED"
    for f in tmp_path.glob("GENESIS_CONTROL_QWEN3_8B_ATTEMPT4_SETTLEMENT_RECONCILIATION_*.json"):
        f.unlink()


def test_an_absent_app_without_run_time_stopped_evidence_or_with_live_resources_is_not_accepted(monkeypatch, tmp_path):
    mod, _ = _reconcile_env(monkeypatch, tmp_path, live=1)
    monkeypatch.setattr(mod, "_app_row", lambda name, app_id: None)
    assert mod.cmd_reconcile(_rc_args(mod)) == 5
    assert json.loads(_rc_artifacts(tmp_path)[0].read_text())["app_listing"] == "ABSENT_FROM_LISTING_NO_STOPPED_EVIDENCE"
    (tmp_path / "second").mkdir()
    mod2, _ = _reconcile_env(monkeypatch, tmp_path / "second")
    (tmp_path / "second" / "synthetic_billing_after.json").write_text(json.dumps({"peak_observed_billed_usd": "0E-8"}))         # no run-time stopped evidence
    rec = json.loads((tmp_path / "second" / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
    rec["financial_evidence"]["billing_after_sha256"] = hashlib.sha256((tmp_path / "second" / "synthetic_billing_after.json").read_bytes()).hexdigest()
    (tmp_path / "second" / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json").write_text(json.dumps(rec))
    monkeypatch.setattr(mod2, "_app_row", lambda name, app_id: None)
    assert mod2.cmd_reconcile(_rc_args(mod2)) == 5


def test_a_not_completed_record_is_never_relabelled_pending_and_the_pending_step_does_not_raise(monkeypatch, tmp_path):
    mod, before = _reconcile_env(monkeypatch, tmp_path, metered_now="20.08000000", credits_now="-20.08000000", rows=[])
    rec_path = tmp_path / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json"
    rec = json.loads(rec_path.read_text())
    rec.update(technical_serving_status="NOT_PROVEN", runtime_qualification_status="NOT_COMPLETED")
    rec["attempts"][-1].update(outcome="UNATTRIBUTED_REQUEST_REJECTION", status="UNATTRIBUTED_REQUEST_REJECTION", failure_domain="UNATTRIBUTED")
    rec_path.write_text(json.dumps(rec))
    for x in rec["smoke_outputs"]:
        pass
    before_bytes = rec_path.read_bytes()
    assert mod.cmd_reconcile(_rc_args(mod)) == 5                                                            # no traceback
    assert rec_path.read_bytes() == before_bytes                                                            # the record stands as recorded


# ══ CPU-only Mistral HTTP 400 root-cause analysis + the third read-only reconciliation ═══════════════════════════════════════════════════════
MISTRAL_ANALYSIS = EVIDENCE_DIR / "GENESIS_MISTRAL_NEMO_HTTP400_CPU_ROOT_CAUSE_ANALYSIS_2026-09-25.json"
MISTRAL_RECON_3 = EVIDENCE_DIR / "GENESIS_CONTROL_MISTRAL_NEMO_ATTEMPT1_SETTLEMENT_RECONCILIATION_20260925T114303Z.json"


def test_the_mistral_http400_analysis_is_cpu_only_and_states_that_the_root_cause_is_not_established():
    a = json.loads(MISTRAL_ANALYSIS.read_text())
    assert a["no_gpu_used"] and a["no_modal_used"] and a["no_model_weights_loaded"] and a["no_generation"] and a["generated_output_executed"] is False and a["mistral_rerun"] is False
    d = a["decision"]
    assert d["answer"] == "B. ROOT CAUSE NOT ESTABLISHED CPU-ONLY" and "no fix is proposed" in d["not_invented"] and d["classification_of_the_issue"].startswith("UNATTRIBUTED")
    assert d["correction_changes_model_identity"].startswith("n/a") and "would require its own owner authorization" in d["what_would_establish_it"]
    assert a["status_unchanged"] == {"mistral_nemo": "NOT_PROVEN / NOT_COMPLETED", "qwen3_8b": "FAILED", "phi4": "NOT_TESTED", "capability": "UNPROVEN"}


def test_the_mistral_analysis_uses_the_exact_orneur_payloads_and_the_runs_own_library_versions():
    a = json.loads(MISTRAL_ANALYSIS.read_text())
    runner = _runner_module()
    cfg = runner.serving_config("mistral_nemo")
    gen = {"temperature": 0, "top_p": 1, "seed": 0, "max_tokens": cfg["smoke_max_tokens"]}
    assert (a["subject"]["revision"], a["subject"]["server_flags"], a["subject"]["canonical_protocol_sha256"]) == (
        LOCKED_CONTROL_IDENTITIES["Mistral-Nemo-Instruct-2407"]["revision"], MISTRAL_ARGS, CANONICAL_PROTOCOL_SHA256)
    for smoke in cfg["smokes"]:
        want = runner.build_chat_payload(cfg, smoke, gen)
        if smoke["stream"]:
            want = dict(want, stream=True, stream_options={"include_usage": True})
        t = a["request_by_request_trace"][smoke["smoke_id"]]
        assert t["exact_payload"] == want and t["prompt_is_canonical"] is True and "chat_template_kwargs" not in t["exact_payload"]
        assert t["payload_prompt_sha256"] == locked_protocol.prompt_sha256(smoke["smoke_id"])
        assert ("stream" in t["exact_payload"]) is (smoke["smoke_id"] == "A")                                   # only A carries the streaming fields
        assert {k: v["result"] for k, v in t["stages"].items()} == {"chat_template_render_and_tokenize_cpu": "PASS", "prompt_plus_max_tokens_within_max_model_len": "PASS"}
        assert t["stages"]["chat_template_render_and_tokenize_cpu"]["rendered_text"].startswith("<s>[INST]") and t["stages"]["chat_template_render_and_tokenize_cpu"]["bos_count"] == 1
    v = a["cpu_library_versions_used"]
    assert v["transformers"] == "5.16.1" and v["tokenizers"] == "0.23.2" and "'transformers': '5.16.1'" in v["in_run_log"] and "'tokenizers': '0.23.2'" in v["in_run_log"]
    assert a["pinned_files_facts"]["chat_template_present"] is True and a["pinned_files_facts"]["config_json_architectures"] == ["MistralForCausalLM"]


def test_the_mistral_analysis_reads_the_immutable_raw_log_and_is_consistent_with_it():
    a = json.loads(MISTRAL_ANALYSIS.read_text())
    f = a["raw_server_log_facts"]
    assert f["raw_log_sha256"] == MISTRAL_RAW_LOG_SHA256 and f["statuses"] == ["400", "400", "400"] and len(f["post_chat_completions_lines"]) == 3
    assert f["traceback_in_log"] is False and f["transformers_chat_template_exception_logged"] is False and f["error_with_model_logged"] is False and f["error_level_lines_before_the_400s"] == []
    log = (EVIDENCE_DIR / _mistral()["raw_log_artifact"]).read_text()
    assert log.count('"POST /v1/chat/completions HTTP/1.1" 400 Bad Request') == 3 and "Traceback" not in log and "An error occurred in `transformers`" not in log
    ev = a["vllm_source_evidence"]
    assert "raise ValueError(str(e)) from e" in ev["template_failure_is_logged_and_wrapped_as_ValueError_400"]["text"] and "logger.exception" in ev["template_failure_is_logged_and_wrapped_as_ValueError_400"]["text"]
    assert "log_error_stack" in ev["pydantic_request_validation_errors_are_logged_only_with_log_error_stack"]["text"]
    assert "HTTPStatus.BAD_REQUEST" in ev["create_error_response_default_is_400"]["text"]
    assert a["vllm_source_evidence"]["stream_options_requires_stream"]["text"].count("stream") >= 2
    assert all(len(x["sha256"]) == 64 for group in a["sources"].values() for x in group.values()) and a["sources"]["vllm_v0_29_0"]["renderers/hf.py"]["url"].find("98dff2a81d747d1dba01a47f939f48c3526d4206") > 0


def test_the_mistral_analysis_script_is_cpu_only_executes_nothing_and_loads_no_model():
    text = (REPO_ROOT / "scripts/phase21b_4_20_mistral_http400_analysis.py").read_text()
    for banned in ("import modal", "import torch", "import vllm", "subprocess", "os.system", "eval(", "exec(", "from_pretrained(\"mistralai", ".generate(", "safetensors.torch"):
        assert banned not in text, banned
    assert "AutoTokenizer" in text and "apply_chat_template" in text                                            # tokenizer/config only


def test_the_third_read_only_reconciliation_left_mistral_unresolved_owner_cash_zero_and_the_record_untouched():
    r = json.loads(MISTRAL_RECON_3.read_text())
    assert r["no_gpu_started"] is True and r["no_modal_function_called"] is True and r["waiver_applies"] is False
    assert r["verdict"] == "SETTLEMENT_STILL_NOT_OBSERVABLE" and r["settlement"]["status"] == "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE" and r["settlement"]["stop_before_next_control"] is True
    assert r["owner_billed_delta_usd"] == "0E-8" and r["live_resources"] == 0 and r["itemized_run_cost_usd"] == "0.20532158" and r["modal_app_id"] == "ap-LEwLRsdDZiLhSvTgwIPn7g"
    assert r["metered_delta_precise_usd"] == "0.20532159" and r["metered_unattributed_usd"] == "1E-8"                # the exact growth now equals the run's own row (1e-8 rounding)
    assert any("not in state 'stopped'" in x for x in r["settlement"]["reasons"]) and r["app_row"] is None       # unresolved only because the aged-out app was judged by the listing (harness fixed since)
    m = _mistral()
    assert m["technical_serving_status"] == "NOT_PROVEN" and m["runtime_qualification_status"] == "NOT_COMPLETED" and m["owner_billed_delta_usd"] == "0E-8"
    assert m["settlement_reconciliation"]["artifact"] != MISTRAL_RECON_3.name                                # the later (fourth) reconciliation, not this one, finalized the settlement


# ══ transactional settlement finalization: record, embedded attempt and attempts file move together; settlement resolution qualifies nothing ═══════════
def _mistral_like_env(monkeypatch, tmp_path, **env):
    """An UNATTRIBUTED (technical NOT_PROVEN) record whose settlement was corrected to NOT_YET_OBSERVABLE, with a later reconciliation that will observe it."""
    mod, before = _reconcile_env(monkeypatch, tmp_path, **env)
    rec_path = tmp_path / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json"
    attempts_path = tmp_path / f"GENESIS_CONTROL_QWEN3_8B_ATTEMPTS_{mod.DATE_TAG}.json"
    rec = json.loads(rec_path.read_text())
    unresolved = {"status": "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE", "reasons": ["excess cannot be attributed"], "stop_before_next_control": True}
    rec.update(technical_serving_status="NOT_PROVEN", runtime_qualification_status="NOT_COMPLETED", billing_settlement=unresolved,
               original_in_run_billing_settlement={"status": "OBSERVED", "reasons": [], "stop_before_next_control": False},
               settlement_correction={"reason": "in-run OBSERVED was contaminated by another attempt's rows", "reclassifies_attempt": False})
    last = rec["attempts"][-1]
    last.update(outcome="UNATTRIBUTED_REQUEST_REJECTION", status="UNATTRIBUTED_REQUEST_REJECTION", failure_domain="UNATTRIBUTED", billing_settlement_status="BILLING_SETTLEMENT_NOT_YET_OBSERVABLE",
                original_in_run_billing_settlement_status="OBSERVED", settlement_correction="see earlier reconciliation")
    rec_path.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    doc = json.loads(attempts_path.read_text())
    doc["attempts"][-1] = dict(last)
    attempts_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    validate_control_runtime_record(rec, evidence_root=tmp_path)                       # the pre-reconciliation state is itself valid and consistent
    return mod, rec_path, attempts_path, rec, doc


def test_an_observed_reconciliation_updates_the_record_the_embedded_attempt_and_the_attempts_file_together(monkeypatch, tmp_path):
    mod, rec_path, attempts_path, before, before_att = _mistral_like_env(monkeypatch, tmp_path)
    assert mod.cmd_reconcile(_rc_args(mod)) == 0
    art_path = _rc_artifacts(tmp_path)[-1]
    art = json.loads(art_path.read_text())
    assert art["settlement"]["status"] == "OBSERVED"
    rec = json.loads(rec_path.read_text())
    file_att = json.loads(attempts_path.read_text())["attempts"][-1]
    emb = rec["attempts"][-1]
    assert rec["billing_settlement"]["status"] == emb["billing_settlement_status"] == file_att["billing_settlement_status"] == "OBSERVED"            # all three agree
    assert emb == file_att                                                                                                                             # identical attempt state
    assert rec["settlement_reconciliation"]["artifact"] == art_path.name and rec["settlement_reconciliation"]["sha256"] == hashlib.sha256(art_path.read_bytes()).hexdigest()
    assert emb["settlement_reconciliation_artifact"] == art_path.name                                                                                  # the final OBSERVED cites the NEW artifact
    assert rec["settlement_reconciliation"]["promotional_credit_used_usd"] == art["itemized_run_cost_usd"]
    validate_control_runtime_record(rec, evidence_root=tmp_path)


def test_the_finalization_preserves_the_contaminated_history_and_changes_nothing_else(monkeypatch, tmp_path):
    mod, rec_path, attempts_path, before, before_att = _mistral_like_env(monkeypatch, tmp_path)
    assert mod.cmd_reconcile(_rc_args(mod)) == 0
    rec = json.loads(rec_path.read_text())
    emb = rec["attempts"][-1]
    assert rec["original_in_run_billing_settlement"] == before["original_in_run_billing_settlement"] and rec["original_in_run_billing_settlement"]["status"] == "OBSERVED"
    assert rec["settlement_correction"] == before["settlement_correction"]                                                                             # the downgrade history survives
    assert emb["original_in_run_billing_settlement_status"] == "OBSERVED" and emb["settlement_correction"] == "see earlier reconciliation"
    assert rec["original_in_run_financial_reconciliation"] == before["financial_reconciliation"]
    for key in ("technical_serving_status", "runtime_qualification_status", "capability_status", "smoke_outputs", "smoke_prompts", "smoke_protocol", "smoke_acceptance",
                "raw_log_sha256", "raw_log_artifact", "identity_verification", "server_argv_sanitized", "financial_evidence", "owner_billed_delta_usd", "cleanup_status",
                "live_resources_after_cleanup", "container_execution_proof", "http_error_evidence_gap", "classification_correction", "model_id", "model_revision"):
        assert rec.get(key) == before.get(key), key
    for key in ("outcome", "status", "failure_domain", "valid_runtime_attempt", "reason", "duration_seconds", "started_at_utc", "finished_at_utc", "modal_app_id", "raw_log_sha256"):
        assert emb.get(key) == before["attempts"][-1].get(key), key
    assert rec["technical_serving_status"] == "NOT_PROVEN" and rec["runtime_qualification_status"] == "NOT_COMPLETED" and rec["capability_status"] == "UNPROVEN"   # settlement qualifies nothing
    assert emb["outcome"] == "UNATTRIBUTED_REQUEST_REJECTION" and emb["failure_domain"] == "UNATTRIBUTED"


def test_an_unobserved_reconciliation_leaves_the_record_and_the_attempts_file_untouched(monkeypatch, tmp_path):
    mod, rec_path, attempts_path, before, before_att = _mistral_like_env(monkeypatch, tmp_path, metered_now="20.50000000", credits_now="-20.50000000",
                                                                         eph_before="20.07689253", eph_now="20.49230719", run_cost="0.20000000")
    rb, ab = rec_path.read_bytes(), attempts_path.read_bytes()
    assert mod.cmd_reconcile(_rc_args(mod)) == 5
    assert rec_path.read_bytes() == rb and attempts_path.read_bytes() == ab


def test_a_failed_validation_persists_nothing_partial(monkeypatch, tmp_path):
    mod, rec_path, attempts_path, before, before_att = _mistral_like_env(monkeypatch, tmp_path)
    rb, ab = rec_path.read_bytes(), attempts_path.read_bytes()
    real = mod.validate_control_runtime_record

    def boom(record, evidence_root=None):
        if record["billing_settlement"]["status"] == "OBSERVED":
            raise ControlRuntimeError("synthetic validation failure")
        return real(record, evidence_root=evidence_root)

    monkeypatch.setattr(mod, "validate_control_runtime_record", boom)
    assert mod.cmd_reconcile(_rc_args(mod)) == 1
    assert rec_path.read_bytes() == rb and attempts_path.read_bytes() == ab                                       # neither file changed
    assert not list(tmp_path.glob("*.tmp-finalize"))
    assert _rc_artifacts(tmp_path), "the timestamped reconciliation artifact may remain as immutable evidence"


def test_a_failure_while_writing_the_pair_leaves_both_original_files_intact(tmp_path):
    mod = types.SimpleNamespace()
    spec = importlib.util.spec_from_file_location("p21b420_atomic_probe", MODAL_H100)
    stub = types.ModuleType("modal")
    stub.Image = type("Image", (), {"from_registry": classmethod(lambda cls, *a, **k: cls()), "entrypoint": lambda self, _c: self, "add_local_file": lambda self, *a, **k: self})
    stub.App = lambda n: types.SimpleNamespace(name=n, function=lambda **k: (lambda f: f))
    stub.Volume = types.SimpleNamespace(from_name=lambda *a, **k: None)
    stub.is_local = lambda: True
    sys.modules["modal"] = stub
    try:
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        sys.modules.pop("modal", None)
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text('{"v": 1}')
    b.write_text('{"v": 2}')
    with pytest.raises(FileNotFoundError):
        m._atomic_write_pair([(a, {"v": 10}), (tmp_path / "missing_dir" / "b.json", {"v": 20})])       # the second file cannot even be prepared
    assert json.loads(a.read_text()) == {"v": 1} and json.loads(b.read_text()) == {"v": 2} and not list(tmp_path.glob("*.tmp-finalize"))
    m._atomic_write_pair([(a, {"v": 10}), (b, {"v": 20})])
    assert json.loads(a.read_text()) == {"v": 10} and json.loads(b.read_text()) == {"v": 20}


def test_the_finalizer_source_is_transactional_and_calls_no_provider():
    text = MODAL_H100.read_text()
    fn = ast.unparse(next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and n.name == "_finalize_record"))
    assert fn.index("validate_control_runtime_record") < fn.index("_atomic_write_pair") and "write_json(" not in fn
    for banned in ("serve_and_smoke", ".remote(", "app.run", "billing_summary", "_cli_json", "subprocess", "eval(", "exec("):
        assert banned not in fn, banned
    assert "_sync_attempt_settlement" in fn and "the record, the embedded attempt and the attempts-file entry do not agree" in fn


def test_the_finalizer_leaves_qwen_and_phi_evidence_as_recorded():
    assert hashlib.sha256(ATTEMPT_4_SNAPSHOT.read_bytes()).hexdigest() == ATTEMPT_4_SNAPSHOT_SHA256 and hashlib.sha256(ATTEMPT_5_SNAPSHOT.read_bytes()).hexdigest() == ATTEMPT_5_SNAPSHOT_SHA256
    q = _persisted_qwen()
    assert q["runtime_qualification_status"] == "FAILED" and hashlib.sha256(json.dumps(q["smoke_outputs"], sort_keys=True).encode()).hexdigest() == ATTEMPT_5_SMOKE_OUTPUTS_SHA256
    phi = json.loads((EVIDENCE_DIR / "GENESIS_CONTROL_PHI4_RUNTIME_QUALIFICATION_2026-09-24.json").read_text())
    assert phi["runtime_qualification_status"] == "NOT_TESTED" and phi["attempts"] == [] and phi["smoke_outputs"] == []


def test_a_later_launch_snapshots_the_attempt_2_record_and_refuses_tampering(monkeypatch, tmp_path):
    mod, _ = _load_modal_h100(monkeypatch)
    ev = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_DIR, ev)                                                                        # NEVER touch the real evidence directory from a test
    monkeypatch.setattr(mod, "EVIDENCE_DIR", ev)
    rec_path = ev / "GENESIS_CONTROL_MISTRAL_NEMO_RUNTIME_QUALIFICATION_2026-09-24.json"
    assert mod.archive_prior_record("MISTRAL_NEMO") == "GENESIS_CONTROL_MISTRAL_NEMO_RUNTIME_QUALIFICATION_ATTEMPT2_SNAPSHOT_2026-09-24.json"
    assert (ev / "GENESIS_CONTROL_MISTRAL_NEMO_RUNTIME_QUALIFICATION_ATTEMPT2_SNAPSHOT_2026-09-24.json").read_bytes() == rec_path.read_bytes()
    tampered = json.loads(rec_path.read_text())
    tampered["attempts"][-1]["duration_seconds"] = 1.0                                                       # anything beyond the documented fields is refused
    rec_path.write_text(json.dumps(tampered))
    with pytest.raises(RuntimeError, match="refusing to overwrite prior-attempt evidence"):
        mod.archive_prior_record("MISTRAL_NEMO")


def test_mistral_attempt_1_finalized_snapshot_is_byte_identical_to_the_pre_attempt_2_record():
    assert hashlib.sha256(MISTRAL_A1_FINALIZED.read_bytes()).hexdigest() == MISTRAL_A1_FINALIZED_SHA256
    live_attempts = json.loads((EVIDENCE_DIR / "GENESIS_CONTROL_MISTRAL_NEMO_ATTEMPTS_2026-09-24.json").read_text())["attempts"]
    assert live_attempts[0] == _mistral()["attempts"][0] and [a["attempt_number"] for a in live_attempts] == [1, 2]   # attempt 1 unchanged; attempt 2 appended


def test_mistral_attempt_2_is_the_honest_unattributed_http400_with_captured_bodies_and_container_proof():
    live = _mistral_live()
    a2 = live["attempts"][-1]
    assert a2["attempt_number"] == 2 and a2["outcome"] == "UNATTRIBUTED_REQUEST_REJECTION" and a2["failure_domain"] == "UNATTRIBUTED"
    assert live["technical_serving_status"] == "NOT_PROVEN" and live["runtime_qualification_status"] == "NOT_COMPLETED" and live["capability_status"] == "UNPROVEN"
    proof = live["container_execution_proof"]
    assert proof["provenance"] == "CONTAINER_RETURNED" and proof["tokenizer_mode"] == "hf" and proof["config_format"] == "hf" and proof["load_format"] == "safetensors"
    assert proof["reasoning_parser"] is None and proof["runtime_configuration_id"] is None and proof["smoke_protocol_sha256"] == "d462103b607e9741786ef86afc0b1769d5857d6e7feef36de516dac87a2b25c1"
    assert all(v is None for v in proof["chat_template_kwargs_sent"].values())
    outs = live["smoke_outputs"]
    assert [o["http_status"] for o in outs] == [400, 400, 400] and all(o["content"] is None for o in outs)
    for o in outs:
        he = o["http_error"]
        assert he["status"] == 400 and he["body_sha256"] == hashlib.sha256(o["raw_response"].encode()).hexdigest() and he["structured_error"]["error"]["type"] == "BadRequestError"
        assert "default chat template is no longer allowed" in he["structured_error"]["error"]["message"] and he["headers"]
    assert a2["owner_billed_delta_usd"] in ("0", "0E-8") and a2["cleanup_result"] == "PASS" and a2["billing_settlement_status"] == "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE"


# ══ Financial-gate correction: provider-adjustment reconciliation vs promotional-credit runway ═════════


def _mixed(metered="20.89627853", billed="0E-8", **adj):
    adjustments = {"credits": "-20.70000000", "free_storage": "-0.19627853"}
    adjustments.update(adj)
    return {"metered_cost": metered, "billed_cost": billed, "adjustments": adjustments}


def test_FG_A_pure_credit_case_still_passes():
    d = _gate(_summary(metered="20.70", credits="-20.70"), worst_case_job_cost_usd="1.0828")
    assert d["allowed"] is True and d["current_owner_payable_covered"] is True and d["non_credit_adjustments_usd"] == "0"


def test_FG_B_real_mixed_adjustment_shape_passes_and_reports_every_field():
    d = _gate(_mixed(), worst_case_job_cost_usd="1.0828")
    assert d["allowed"] is True, d["reasons"]
    assert d["metered_cost_usd"] == "20.89627853" and d["credits_applied_usd"] == "20.70000000"
    assert d["non_credit_adjustments_usd"] == "-0.19627853" and Decimal(d["provider_recomputed_billed_usd"]) == 0
    assert d["current_owner_payable_covered"] is True
    assert Decimal(d["remaining_promotional_credit_usd"]) == Decimal("30.00") - Decimal("20.70000000")
    assert Decimal(d["headroom_usd"]) == Decimal("9.30") - Decimal("5.00") - Decimal("1.0828")


def test_FG_C_free_storage_never_increases_promotional_runway():
    with_free = _gate(_mixed(), worst_case_job_cost_usd="1.25")
    without = _gate(_summary(metered="20.70", credits="-20.70"), worst_case_job_cost_usd="1.25")
    assert Decimal(with_free["remaining_promotional_credit_usd"]) == Decimal(without["remaining_promotional_credit_usd"])
    # big free_storage must not rescue an exhausted credit pool
    d = _gate({"metered_cost": "27.00", "billed_cost": "0", "adjustments": {"credits": "-26.00", "free_storage": "-1.00"}})
    assert d["allowed"] is False and any("credit-coverage gate" in r for r in d["reasons"])


def test_FG_D_positive_billed_cost_always_blocks():
    d = _gate(_mixed(metered="20.99627853", billed="0.10000000"))
    assert d["allowed"] is False and any("billed_cost is already" in r for r in d["reasons"])


def test_FG_E_provider_arithmetic_mismatch_blocks_fail_closed():
    d = _gate(_mixed(metered="20.99627853"))          # 20.996 - 20.70 - 0.196 = 0.10 != billed 0
    assert d["allowed"] is False and any("does not reconcile" in r for r in d["reasons"])


def test_FG_F_unknown_adjustment_keys_reconcile_but_never_count_as_gpu_credit():
    s = _mixed(metered="21.09627853", network_allowance="-0.20000000")
    d = _gate(s, worst_case_job_cost_usd="1.0828")
    assert d["allowed"] is True and d["adjustments_usd"]["network_allowance"] == "-0.20000000"
    assert d["credits_applied_usd"] == "20.70000000" and Decimal(d["remaining_promotional_credit_usd"]) == Decimal(_gate(_mixed())["remaining_promotional_credit_usd"])


@pytest.mark.parametrize("bad", ["abc", None, "NaN", "Infinity", {"x": 1}])
def test_FG_G_malformed_adjustment_values_fail_closed(bad):
    d = _gate(_mixed(free_storage=bad))
    assert d["allowed"] is False and any("unreadable" in r for r in d["reasons"])


def test_FG_G_missing_or_non_mapping_adjustments_fail_closed():
    assert _gate({"metered_cost": "1", "billed_cost": "0", "adjustments": ["x"]})["allowed"] is False
    assert _gate({"metered_cost": "1", "billed_cost": "0", "adjustments": {"free_storage": "-1"}})["allowed"] is False   # no credits key


def test_FG_H_positive_non_credit_adjustment_is_accounted_for():
    # a positive adjustment (a charge) is part of the invoice arithmetic: it makes billed non-zero or breaks reconciliation
    d = _gate(_mixed(surcharge="0.50000000"))
    assert d["allowed"] is False
    ok = _gate({"metered_cost": "20.70", "billed_cost": "0.50", "adjustments": {"credits": "-20.70", "surcharge": "0.50"}})
    assert ok["allowed"] is False and any("billed_cost is already" in r for r in ok["reasons"])


def test_FG_I_insufficient_promotional_credit_blocks_even_when_billed_is_zero():
    d = _gate(_mixed(metered="26.19627853", credits="-26.00000000"), worst_case_job_cost_usd="1.0828")
    assert d["allowed"] is False and Decimal(d["billed_cost_usd"]) == 0
    assert any("credit-coverage gate" in r for r in d["reasons"])


def test_FG_J_K_prior_positive_billing_and_unresolved_settlement_still_block():
    assert _gate(_mixed(), prior_positive_billing_seen=True)["allowed"] is False
    assert _gate(_mixed(), prior_settlement_unresolved=True)["allowed"] is False


def test_FG_L_gate_and_reconciliation_are_pure_no_provider_call(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("provider call")))
    _gate(_mixed())
    from orca.eval.control_runtime_qualification import build_financial_reconciliation, assess_settlement
    r = build_financial_reconciliation(_summary(metered="20.70", credits="-20.70"), _mixed(metered="21.70627853", credits="-21.51000000"),
                                       credit_pool_usd="30.00", reserve_usd="5.00", max_run_cost_usd="1.25")
    assert r["non_credit_adjustments_postrun_usd"] == "-0.19627853" and r["non_credit_adjustments_baseline_usd"] == "0"
    assert assess_settlement(r, run_report_metered_usd="1.0")["status"] == "OBSERVED"


def test_FG_reconciliation_still_blocks_when_neither_credits_nor_free_storage_cover_growth():
    from orca.eval.control_runtime_qualification import build_financial_reconciliation, assess_settlement
    r = build_financial_reconciliation(_summary(metered="20.70", credits="-20.70"),
                                       {"metered_cost": "21.70", "billed_cost": "0", "adjustments": {"credits": "-20.90", "free_storage": "-0.10"}},
                                       credit_pool_usd="30.00", reserve_usd="5.00", max_run_cost_usd="1.25")
    st = assess_settlement(r, run_report_metered_usd="1.0")
    assert st["status"] != "OBSERVED" and any("coverage not confirmed" in x for x in st["reasons"])


# ══ Credit-sign fail-closed invariant ═════════════════════════════════════════════════════════════════


def test_CS_A_negative_credits_unchanged():
    d = _gate(_mixed(), worst_case_job_cost_usd="1.0828")
    assert d["allowed"] is True and d["credits_applied_usd"] == "20.70000000"


def test_CS_B_zero_credits_runway_is_only_the_unused_pool():
    d = _gate({"metered_cost": "0", "billed_cost": "0", "adjustments": {"credits": "0"}}, worst_case_job_cost_usd="1.0828")
    assert d["allowed"] is True and Decimal(d["remaining_promotional_credit_usd"]) == Decimal("30.00")


@pytest.mark.parametrize("val", ["0.50", "+0.50", "0.00000001", "100"])
def test_CS_C_positive_credits_block_fail_closed(val):
    d = _gate({"metered_cost": "0.50", "billed_cost": "0", "adjustments": {"credits": val}})
    assert d["allowed"] is False and any("unreadable" in r and "positive" in r for r in d["reasons"])
    from orca.eval.control_runtime_qualification import provider_billing_reconciliation
    with pytest.raises(ControlRuntimeError, match="positive"):
        provider_billing_reconciliation({"metered_cost": "0.50", "billed_cost": "0", "adjustments": {"credits": val}})


def test_CS_D_positive_credits_never_push_remaining_above_the_pool():
    d = _gate({"metered_cost": "0", "billed_cost": "0.50", "adjustments": {"credits": "0.50"}})
    assert d["allowed"] is False
    assert d["remaining_credit_usd"] is None or Decimal(d["remaining_credit_usd"]) <= Decimal("30.00")


def test_CS_E_real_mixed_fixture_and_positive_noncredit_semantics_unchanged():
    assert _gate(_mixed(), worst_case_job_cost_usd="1.0828")["allowed"] is True
    d = _gate(_mixed(surcharge="0.50000000"))
    assert d["allowed"] is False and not any("positive" in r for r in d["reasons"])
