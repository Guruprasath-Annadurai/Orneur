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
from decimal import Decimal
from pathlib import Path

import pytest

from orca.eval.candidate_registry import CandidateExecutionRegistry, EXPECTED_CONTROL_NAMES
from orca.eval.control_runtime_qualification import (
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
        raw = f'{{"content": "SYNTHETIC-{sid}"}}'
        outputs.append({"smoke_id": sid, "http_status": 200, "raw_response": raw,
                        "raw_response_sha256": hashlib.sha256(raw.encode()).hexdigest(), "executed": False})
        prompts.append({"smoke_id": sid, "messages": [{"role": "user", "content": "synthetic"}]})
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
        "smoke_prompts": prompts, "generation_config": {"temperature": 0}, "smoke_outputs": outputs,
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
    ({"technical_serving_status": "FAILED"}, "derives|QUALIFIED"),
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
    assert derive_runtime_status(**dict(ok, technical="BLOCKED_PENDING_ZERO_CASH_RUNWAY")) == "BLOCKED_PENDING_ZERO_CASH_RUNWAY"
    assert set(RUNTIME_QUALIFICATION_STATUSES) == {"RUNTIME_QUALIFIED", "NOT_ACCEPTED", "FAILED", "NOT_TESTED", "BLOCKED_PENDING_ZERO_CASH_RUNWAY"}


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
    ({"metered_delta_usd": "0E-8"}, "not yet visible"),
    ({"credits_applied_postrun_usd": "20.03"}, "credit coverage not confirmed"),
    ({"billing_delta_usd": "0.01"}, "owner-payable"),
    ({"derived_credit_remaining_after_usd": "4.99"}, "below the reserve"),
    ({"metered_delta_usd": "1.30", "credits_applied_postrun_usd": "21.33"}, "exceeds the maximum"),
])
def test_settlement_is_not_claimed_without_evidence(over, frag):
    r = assess_settlement(_recon(**over), run_report_metered_usd=None)
    assert r["status"] == SETTLEMENT_NOT_OBSERVABLE and r["stop_before_next_control"] is True
    assert any(frag in x for x in r["reasons"])


def test_settlement_visible_via_the_run_report_alone_is_accepted_when_credits_flat_and_no_growth():
    r = assess_settlement(_recon(metered_delta_usd="0E-8", credits_applied_postrun_usd="20.03"), run_report_metered_usd="0.87")
    assert r["status"] == SETTLEMENT_OBSERVED


def test_qualified_requires_reconciliation_settlement_and_discrepancy_reference(tmp_path):
    for key, frag in (("financial_reconciliation", "financial_reconciliation"), ("billing_settlement", "billing_settlement"),
                      ("billing_discrepancy_observation", "discrepancy")):
        rec = _qualified_record(tmp_path)
        del rec[key]
        with pytest.raises(ControlRuntimeError, match=frag):
            validate_control_runtime_record(rec, evidence_root=tmp_path)
    rec = _qualified_record(tmp_path)
    rec["billing_settlement"] = {"status": SETTLEMENT_NOT_OBSERVABLE, "reasons": ["x"]}
    with pytest.raises(ControlRuntimeError, match="observed"):
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
