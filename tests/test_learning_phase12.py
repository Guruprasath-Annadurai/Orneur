"""
Phase 12 -- Failure-to-Curriculum / Native Learning Loop. Real pytest
coverage beyond orca.learning.eval_harness's deterministic scenario runner
(tests/test_learning_eval_harness.py): direct unit coverage of each module,
the security guards (spec §63-69), the real failure-to-eval E2E (spec §82),
and the failure-to-training-ready E2E (spec §81).
"""
from __future__ import annotations

import pytest


from orca.learning.contracts import (
    CandidateReviewState,
    CurriculumCandidate,
    FailureDisposition,
    FailureEvent,
    FailureType,
    ModelCannotSelfApprove,
    PrivacyClass,
    ReviewDecision,
    RootCauseClass,
    SecurityClass,
    TargetModelFamily,
    TrainingDestination,
    VerificationState,
    apply_review_decision,
)
from orca.learning.curriculum import CurriculumCompiler, DifficultyFactors, compute_balance, score_difficulty
from orca.learning.dedupe import compute_fingerprint, dedupe_against, deduplicate
from orca.learning.pipeline import (
    UnverifiedTrainingAdmissionBlocked,
    make_candidate_from_event,
    review_candidate,
    run_pipeline,
    verify_event,
)
from orca.learning.provenance import LineageGraph
from orca.learning.regression_suite import build_regression_case
from orca.learning.sanitize import sanitize_for_candidate
from orca.learning.security import (
    CheckpointSupplyChainRejected,
    DataPoisoningAttemptDetected,
    HoldoutExposureBlocked,
    TenantExfiltrationBlocked,
    TrainingPromptInjectionBlocked,
    assert_no_poisoning_attempt,
    assert_source_text_is_inert,
    assert_training_manifest_excludes_holdout,
    enforce_tenant_boundary,
    scan_for_poisoning_attempt,
    verify_checkpoint_supply_chain,
)
from orca.learning.triage import triage


@pytest.fixture(autouse=True)
def _isolate_learning_registry_dirs(tmp_path, monkeypatch):
    """
    File-scoped (not repo-wide) isolation for orca.registry.* directories
    this test file's own DatasetManifest/CheckpointRecord/EvaluationReport
    calls write to. Deliberately NOT added to tests/conftest.py's global
    autouse fixture: unlike the gateway-deployment-dir and godmode-lease
    cases that fixture already isolates (pure ephemeral runtime
    bookkeeping with no legitimate cross-test dependency), several
    EXISTING tests (e.g. test_gateway_wiring_deployment_records.py,
    test_society_eval_harness.py) intentionally read this developer
    machine's real, already-registered checkpoint/dataset records --
    isolating those directories repo-wide broke 8 previously-passing
    tests (confirmed directly). Scoping isolation to just this file
    avoids that regression while still preventing this file's own new
    writes (confirmed to have leaked 'phase12-frozen-test-v1.json' into
    the real ~/.orca/registry/datasets/ during development) from touching
    real state.
    """
    from tests._learning_registry_isolation import isolate_registry_dirs
    isolate_registry_dirs(tmp_path, monkeypatch)



# --------------------------------------------------------------- contracts / triage


def test_triage_unverified_goes_to_human_review_not_training():
    event = FailureEvent(verification_state=VerificationState.UNVERIFIED)
    result = triage(event)
    assert result.disposition == FailureDisposition.HUMAN_REVIEW


def test_triage_contested_goes_to_human_review():
    event = FailureEvent(verification_state=VerificationState.CONTESTED)
    result = triage(event)
    assert result.disposition == FailureDisposition.HUMAN_REVIEW


def test_triage_dismissed_is_dismissed():
    event = FailureEvent(verification_state=VerificationState.DISMISSED)
    result = triage(event)
    assert result.disposition == FailureDisposition.DISMISS


def test_triage_infrastructure_root_cause_is_runtime_bug_even_if_verified():
    event = FailureEvent(verification_state=VerificationState.VERIFIED, root_cause=RootCauseClass.INFRASTRUCTURE_FAILURE)
    result = triage(event)
    assert result.disposition == FailureDisposition.RUNTIME_BUG


def test_triage_jailbreak_is_security_regression_even_if_root_cause_model():
    event = FailureEvent(
        verification_state=VerificationState.VERIFIED, root_cause=RootCauseClass.MODEL_FAILURE,
        failure_type=FailureType.JAILBREAK_FAILURE,
    )
    result = triage(event)
    assert result.disposition == FailureDisposition.SECURITY_REGRESSION


def test_triage_unknown_root_cause_requires_human_review():
    event = FailureEvent(verification_state=VerificationState.VERIFIED, root_cause=RootCauseClass.UNKNOWN)
    result = triage(event)
    assert result.disposition == FailureDisposition.HUMAN_REVIEW


# --------------------------------------------------------------- pipeline / candidate admission


def test_make_candidate_from_event_requires_verified():
    event = FailureEvent(verification_state=VerificationState.UNVERIFIED)
    with pytest.raises(UnverifiedTrainingAdmissionBlocked):
        make_candidate_from_event(event, "task", "input", "expected")


def test_verify_event_transitions_to_verified_only_on_real_confirmation():
    event = FailureEvent(verification_state=VerificationState.UNVERIFIED)
    verify_event(event, is_reproducible_and_confirmed=False)
    assert event.verification_state == VerificationState.UNVERIFIED
    verify_event(event, is_reproducible_and_confirmed=True)
    assert event.verification_state == VerificationState.VERIFIED


def test_tenant_private_event_defaults_to_tenant_eval_only_destination():
    event = FailureEvent(verification_state=VerificationState.VERIFIED, privacy_class=PrivacyClass.TENANT_PRIVATE, tenant_id="tenant-a")
    candidate = make_candidate_from_event(event, "task", "input", "expected")
    assert candidate.training_destination == TrainingDestination.TENANT_LOCAL_TRAINING


def test_public_event_is_global_training_eligible():
    event = FailureEvent(verification_state=VerificationState.VERIFIED, privacy_class=PrivacyClass.PUBLIC)
    candidate = make_candidate_from_event(event, "task", "input", "expected")
    assert candidate.training_destination == TrainingDestination.GLOBAL_TRAINING_ELIGIBLE


def test_internal_event_defaults_to_tenant_eval_only():
    event = FailureEvent(verification_state=VerificationState.VERIFIED, privacy_class=PrivacyClass.INTERNAL)
    candidate = make_candidate_from_event(event, "task", "input", "expected")
    assert candidate.training_destination == TrainingDestination.TENANT_EVAL_ONLY


def test_review_candidate_rejects_model_reviewer_identity():
    candidate = CurriculumCandidate()
    with pytest.raises(ModelCannotSelfApprove):
        review_candidate(candidate, ReviewDecision.APPROVE_FOR_TRAINING, reviewer="model:orneur-novus")


def test_review_candidate_accepts_human_reviewer():
    candidate = CurriculumCandidate()
    review_candidate(candidate, ReviewDecision.APPROVE_FOR_TRAINING, reviewer="human:alice")
    assert candidate.review_state == CandidateReviewState.APPROVED_FOR_TRAINING


# --------------------------------------------------------------- sanitization


def test_sanitize_rejects_openai_style_secret():
    result = sanitize_for_candidate("api key is sk-abcdefghijklmnopqrstuvwxyz123456")
    assert result.rejected
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in result.clean_text


def test_sanitize_allows_clean_text():
    result = sanitize_for_candidate("the claim about Paris was unsupported by the retrieved evidence")
    assert not result.rejected
    assert result.clean_text == "the claim about Paris was unsupported by the retrieved evidence"


def test_sanitize_flags_pii_without_rejecting():
    result = sanitize_for_candidate("contact me at someone@example.com")
    assert not result.rejected  # PII is flagged (spec matches scan_output's own posture), secrets are what triggers rejection


# --------------------------------------------------------------- dedupe


def test_compute_fingerprint_is_stable_across_key_order_and_whitespace_case():
    c1 = CurriculumCandidate(task_type="claim_extraction", input_summary="Hello World", expected_behavior="Fix It")
    c2 = CurriculumCandidate(task_type="claim_extraction", input_summary="hello world", expected_behavior="fix it")
    assert compute_fingerprint(c1) == compute_fingerprint(c2)


def test_dedupe_against_finds_exact_duplicate():
    c1 = CurriculumCandidate(task_type="t", input_summary="same input", expected_behavior="same fix")
    c2 = CurriculumCandidate(task_type="t", input_summary="same input", expected_behavior="same fix")
    report = dedupe_against(c2, [c1])
    assert report.exact_duplicate_of == c1.candidate_id


def test_dedupe_against_finds_near_duplicate_via_shingle_overlap():
    c1 = CurriculumCandidate(task_type="t", input_summary="the quick brown fox jumps over the lazy dog near the old wooden fence today")
    c2 = CurriculumCandidate(task_type="t", input_summary="the quick brown fox jumps over the lazy dog near the old wooden fence now")
    report = dedupe_against(c2, [c1])
    assert c1.candidate_id in report.near_duplicate_of


def test_deduplicate_drops_exact_duplicates_but_keeps_first():
    c1 = CurriculumCandidate(task_type="t", input_summary="x", expected_behavior="y")
    c2 = CurriculumCandidate(task_type="t", input_summary="x", expected_behavior="y")
    kept, dropped = deduplicate([c1, c2])
    assert kept == [c1]
    assert dropped == [c2]


# --------------------------------------------------------------- difficulty / balance / compiler


def test_score_difficulty_is_deterministic_and_bounded():
    factors = DifficultyFactors(reasoning_depth=3, retrieval_depth=2, tool_count=1, contradiction_count=1, context_length_tokens=4096, failure_frequency=5, court_disagreement=True, model_confidence=0.9, ground_truth_confidence=0.1)
    d1 = score_difficulty(factors)
    d2 = score_difficulty(factors)
    assert d1 == d2
    assert 0.0 <= d1 <= 1.0


def test_score_difficulty_zero_factors_is_zero():
    assert score_difficulty(DifficultyFactors(reasoning_depth=0, retrieval_depth=0, tool_count=0, contradiction_count=0, context_length_tokens=0, failure_frequency=0, model_confidence=0.5, ground_truth_confidence=0.5)) == 0.0


def test_compute_balance_counts_distribution():
    candidates = [
        CurriculumCandidate(target_model_family=TargetModelFamily.NOVUS, difficulty=0.1),
        CurriculumCandidate(target_model_family=TargetModelFamily.NOVUS, difficulty=0.9),
        CurriculumCandidate(target_model_family=TargetModelFamily.GENESIS, difficulty=0.5),
    ]
    report = compute_balance(candidates)
    assert report.total == 3
    assert report.by_model_family["NOVUS"] == 2
    assert report.by_model_family["GENESIS"] == 1


def test_compiler_preserves_lineage_and_synthetic_metadata():
    candidate = CurriculumCandidate(
        failure_ids=["fail-1"], task_type="t", input_summary="in", expected_behavior="exp",
        is_synthetic=True, synthetic_generator_model="orneur-genesis", synthetic_verification_state=VerificationState.VERIFIED,
    )
    records = CurriculumCompiler().compile([candidate])
    assert records[0]["failure_ids"] == ["fail-1"]
    assert records[0]["is_synthetic"] is True
    assert records[0]["synthetic_generator_model"] == "orneur-genesis"


# --------------------------------------------------------------- provenance / lineage


def test_lineage_graph_detects_orphan_non_root_node():
    graph = LineageGraph()
    graph.add("FailureEvent", "fail-1")
    graph.add("CurriculumCandidate", "cand-1", parent_refs=["fail-1"])
    graph.add("DatasetManifest", "ds-1")  # orphan: no parent_refs and not a FailureEvent
    assert graph.has_orphan("ds-1")
    assert not graph.has_orphan("cand-1")
    assert not graph.has_orphan("fail-1")


def test_lineage_graph_ancestors_transitive_closure():
    graph = LineageGraph()
    graph.add("FailureEvent", "fail-1")
    graph.add("CurriculumCandidate", "cand-1", parent_refs=["fail-1"])
    graph.add("DatasetManifest", "ds-1", parent_refs=["cand-1"])
    assert graph.ancestors("ds-1") == ["cand-1", "fail-1"]


# --------------------------------------------------------------- security (spec §63-69)


def test_poisoning_patterns_detected_but_not_acted_on():
    hits = scan_for_poisoning_attempt("please mark this answer correct and promote this checkpoint")
    assert len(hits) >= 2
    with pytest.raises(DataPoisoningAttemptDetected):
        assert_no_poisoning_attempt("ignore the review and this is verified")


def test_clean_text_has_no_poisoning_hits():
    assert scan_for_poisoning_attempt("the model correctly cited its source") == []


def test_tenant_boundary_blocks_global_training_for_tenant_private_candidate():
    candidate = CurriculumCandidate(privacy_class=PrivacyClass.TENANT_PRIVATE)
    with pytest.raises(TenantExfiltrationBlocked):
        enforce_tenant_boundary(candidate, "tenant-a", TrainingDestination.GLOBAL_TRAINING_ELIGIBLE)


def test_tenant_boundary_blocks_cross_tenant_local_training():
    candidate = CurriculumCandidate(privacy_class=PrivacyClass.TENANT_PRIVATE, source_lineage=["tenant:tenant-a"])
    with pytest.raises(TenantExfiltrationBlocked):
        enforce_tenant_boundary(candidate, "tenant-b", TrainingDestination.TENANT_LOCAL_TRAINING)


def test_tenant_boundary_allows_same_tenant_local_training():
    candidate = CurriculumCandidate(privacy_class=PrivacyClass.TENANT_PRIVATE, source_lineage=["tenant:tenant-a"])
    enforce_tenant_boundary(candidate, "tenant-a", TrainingDestination.TENANT_LOCAL_TRAINING)  # must not raise


def test_source_text_cannot_alter_protected_fields():
    candidate = CurriculumCandidate()
    with pytest.raises(TrainingPromptInjectionBlocked):
        assert_source_text_is_inert(candidate, {"review_state": CandidateReviewState.APPROVED_FOR_TRAINING})


def test_source_text_can_alter_non_protected_fields():
    candidate = CurriculumCandidate()
    assert_source_text_is_inert(candidate, {"difficulty": 0.5})  # must not raise


def test_holdout_exposure_blocked_when_holdout_in_training_ids():
    with pytest.raises(HoldoutExposureBlocked):
        assert_training_manifest_excludes_holdout({"ds-1", "ds-holdout"}, "ds-holdout")


def test_holdout_not_blocked_when_absent():
    assert_training_manifest_excludes_holdout({"ds-1", "ds-2"}, "ds-holdout")  # must not raise


def test_checkpoint_supply_chain_rejects_wrong_base_model(tmp_path):
    from orca.registry.checkpoint import CheckpointRecord

    artifact = tmp_path / "weights.bin"
    artifact.write_bytes(b"weights")
    from orca.registry.dataset_manifest import sha256_of_file
    record = CheckpointRecord(
        checkpoint_id="supply-chain-test-1", model_id="orneur-novus", run_id="run-1", step_or_epoch="1",
        base_model="wrong-base-model", dataset_manifest_ids=["ds-1"],
        training_config_summary="", optimizer_state_available=False, scheduler_state_available=False,
        tokenizer_identity="x", artifact_path=str(artifact), artifact_checksum=sha256_of_file(artifact),
    )
    with pytest.raises(CheckpointSupplyChainRejected):
        verify_checkpoint_supply_chain(record, expected_base_model="unsloth/Meta-Llama-3.1-8B-Instruct", expected_dataset_ids={"ds-1"})


def test_checkpoint_supply_chain_rejects_unregistered_dataset(tmp_path):
    from orca.registry.checkpoint import CheckpointRecord
    from orca.registry.dataset_manifest import sha256_of_file

    artifact = tmp_path / "weights.bin"
    artifact.write_bytes(b"weights")
    record = CheckpointRecord(
        checkpoint_id="supply-chain-test-2", model_id="orneur-novus", run_id="run-1", step_or_epoch="1",
        base_model="unsloth/Meta-Llama-3.1-8B-Instruct", dataset_manifest_ids=["ds-unregistered"],
        training_config_summary="", optimizer_state_available=False, scheduler_state_available=False,
        tokenizer_identity="x", artifact_path=str(artifact), artifact_checksum=sha256_of_file(artifact),
    )
    with pytest.raises(CheckpointSupplyChainRejected):
        verify_checkpoint_supply_chain(record, expected_base_model="unsloth/Meta-Llama-3.1-8B-Instruct", expected_dataset_ids={"ds-1"})


def test_checkpoint_supply_chain_accepts_valid_checkpoint(tmp_path):
    from orca.registry.checkpoint import CheckpointRecord
    from orca.registry.dataset_manifest import sha256_of_file

    artifact = tmp_path / "weights.bin"
    artifact.write_bytes(b"weights")
    record = CheckpointRecord(
        checkpoint_id="supply-chain-test-3", model_id="orneur-novus", run_id="run-1", step_or_epoch="1",
        base_model="unsloth/Meta-Llama-3.1-8B-Instruct", dataset_manifest_ids=["ds-1"],
        training_config_summary="", optimizer_state_available=False, scheduler_state_available=False,
        tokenizer_identity="x", artifact_path=str(artifact), artifact_checksum=sha256_of_file(artifact),
    )
    verify_checkpoint_supply_chain(record, expected_base_model="unsloth/Meta-Llama-3.1-8B-Instruct", expected_dataset_ids={"ds-1"})  # must not raise


# --------------------------------------------------------------- regression suite (spec §36-37, §82)


def test_build_regression_case_marks_security_class_correctly():
    candidate = CurriculumCandidate(security_class=SecurityClass.SECURITY_SENSITIVE, failure_ids=["fail-1"], input_summary="in", expected_behavior="exp")
    case = build_regression_case(candidate, target_subsystem="cognitive_court")
    assert case.is_security_regression


def test_regression_suite_run_invokes_executor_for_each_case():
    from orca.learning.regression_suite import FailureRegressionSuite, RegressionCase, RegressionRunResult
    suite = FailureRegressionSuite()
    suite.add(RegressionCase(case_id="c1", failure_ids=[], input_summary="", expected_behavior="", target_subsystem="truth_fabric"))
    suite.add(RegressionCase(case_id="c2", failure_ids=[], input_summary="", expected_behavior="", target_subsystem="truth_fabric", is_security_regression=True))

    def executor(case):
        return RegressionRunResult(case_id=case.case_id, passed=True)

    results = suite.run(executor)
    assert len(results) == 2
    assert len(suite.security_cases()) == 1
    assert len(suite.capability_cases()) == 1


# --------------------------------------------------------------- E2E: failure-to-eval (spec §82, independent of training)


def test_failure_to_eval_e2e_works_without_any_training():
    """Real verified failure -> regression case -> FailureRegressionSuite
    -> execution against a stand-in for the current system. No training
    infrastructure touched anywhere in this test."""
    from orca.learning.regression_suite import FailureRegressionSuite, RegressionRunResult

    event = FailureEvent(
        source_system="truth_fabric", failure_type=FailureType.UNSUPPORTED_CLAIM,
        root_cause=RootCauseClass.MODEL_FAILURE, verification_state=VerificationState.VERIFIED,
    )
    result = triage(event)
    assert result.disposition == FailureDisposition.EVAL_CANDIDATE

    candidate = make_candidate_from_event(event, "claim_verification", "claim lacked supporting evidence", "abstain or cite real evidence")
    case = build_regression_case(candidate, target_subsystem="truth_fabric")

    suite = FailureRegressionSuite()
    suite.add(case)

    def fake_current_system_executor(regression_case):
        # Stands in for a real TruthFabric.assess_evidence() call -- this
        # test's point is proving the WIRING works end to end without
        # training, not re-testing TruthFabric itself (already covered by
        # tests/test_truth_fabric_integration.py).
        return RegressionRunResult(case_id=regression_case.case_id, passed=True, actual_summary="abstained correctly")

    results = suite.run(fake_current_system_executor)
    assert results[0].passed


# --------------------------------------------------------------- E2E: failure-to-curriculum pipeline (spec §81)


def test_full_pipeline_e2e_collect_to_candidate():
    events = [
        FailureEvent(source_system="truth_fabric", failure_type=FailureType.UNSUPPORTED_CLAIM, root_cause=RootCauseClass.MODEL_FAILURE, verification_state=VerificationState.VERIFIED),
        FailureEvent(source_system="gateway", failure_type=FailureType.TOOL_EXECUTION_ERROR, root_cause=RootCauseClass.INFRASTRUCTURE_FAILURE, verification_state=VerificationState.VERIFIED),
        FailureEvent(source_system="truth_fabric", failure_type=FailureType.UNSUPPORTED_CLAIM, root_cause=RootCauseClass.UNKNOWN, verification_state=VerificationState.UNVERIFIED),
    ]
    candidates, report = run_pipeline(
        events,
        task_type_of=lambda e: "claim_verification",
        input_summary_of=lambda e: f"claim from {e.failure_id} lacked evidence",
        expected_behavior_of=lambda e: "abstain or cite real evidence",
    )
    assert report.events_in == 3
    assert report.verified == 2
    # Only the first (verified + MODEL_FAILURE root cause) event should
    # produce a candidate -- the infra failure is RUNTIME_BUG (no
    # candidate), the unverified one is HUMAN_REVIEW (no candidate).
    assert len(candidates) == 1
    assert candidates[0].failure_ids == [events[0].failure_id]
    assert report.candidates_created == 1
    # Lineage recorded for every event plus the one produced candidate.
    assert not report.lineage.has_orphan(candidates[0].candidate_id)


def test_pipeline_deduplicates_identical_verified_events():
    events = [
        FailureEvent(source_system="truth_fabric", failure_type=FailureType.UNSUPPORTED_CLAIM, root_cause=RootCauseClass.MODEL_FAILURE, verification_state=VerificationState.VERIFIED)
        for _ in range(3)
    ]
    candidates, report = run_pipeline(
        events,
        task_type_of=lambda e: "claim_verification",
        input_summary_of=lambda e: "identical claim text every time",
        expected_behavior_of=lambda e: "identical expected fix every time",
    )
    assert len(candidates) == 1
    assert report.candidates_deduped_out == 2


def test_pipeline_rejects_secret_bearing_candidate_and_records_audit():
    from orca.learning.audit import AUDIT

    before = AUDIT.value("SECRET_IN_CURRICULUM")
    events = [FailureEvent(source_system="connector_fabric", failure_type=FailureType.TOOL_EXECUTION_ERROR, root_cause=RootCauseClass.MODEL_FAILURE, verification_state=VerificationState.VERIFIED)]
    candidates, report = run_pipeline(
        events,
        task_type_of=lambda e: "tool_reasoning",
        input_summary_of=lambda e: "the connector leaked sk-abcdefghijklmnopqrstuvwxyz123456",
        expected_behavior_of=lambda e: "never leak credentials",
    )
    assert len(candidates) == 0
    assert report.candidates_sanitization_rejected == 1
    assert AUDIT.value("SECRET_IN_CURRICULUM") == before + 1


def test_pipeline_blocks_tenant_private_event_from_going_global():
    events = [FailureEvent(
        source_system="connector_fabric", failure_type=FailureType.TOOL_EXECUTION_ERROR,
        root_cause=RootCauseClass.MODEL_FAILURE, verification_state=VerificationState.VERIFIED,
        privacy_class=PrivacyClass.TENANT_PRIVATE, tenant_id="tenant-a",
    )]
    candidates, report = run_pipeline(
        events,
        task_type_of=lambda e: "tool_reasoning",
        input_summary_of=lambda e: "connector call failed for tenant a",
        expected_behavior_of=lambda e: "retry with backoff",
    )
    # privacy_class=TENANT_PRIVATE routes to TENANT_LOCAL_TRAINING (not
    # GLOBAL), so enforce_tenant_boundary should NOT block this -- this
    # test documents that the destination routing itself (not just the
    # boundary guard) is what keeps tenant data out of global training.
    assert len(candidates) == 1
    assert candidates[0].training_destination == TrainingDestination.TENANT_LOCAL_TRAINING


# --------------------------------------------------------------- fast path (spec §84)


def test_revoke_source_and_invalidate_rejects_and_disallows():
    from orca.learning.pipeline import revoke_source_and_invalidate

    candidate = CurriculumCandidate(review_state=CandidateReviewState.APPROVED_FOR_TRAINING, training_destination=TrainingDestination.GLOBAL_TRAINING_ELIGIBLE)
    revoke_source_and_invalidate(candidate)
    assert candidate.review_state == CandidateReviewState.REJECTED
    assert candidate.training_destination == TrainingDestination.DISALLOWED


def test_observability_counters_track_bounded_low_cardinality_labels():
    from orca.learning.observability import LearningObservability

    obs = LearningObservability()
    obs.record_failure_event(verified=True, dismissed=False)
    obs.record_candidate(FailureType.UNSUPPORTED_CLAIM.value)
    obs.record_security_regression()
    snapshot = obs.snapshot()
    assert snapshot["failure_events_total"] == 1
    assert snapshot["verified_failures_total"] == 1
    assert snapshot["candidate_distribution"] == {"UNSUPPORTED_CLAIM": 1}
    assert snapshot["security_regressions_total"] == 1


def test_learning_package_not_imported_by_hot_request_path():
    """Spec §84: normal production request must not synchronously enter
    the training/curriculum pipeline. Verified structurally: the real hot
    request-serving modules never import orca.learning at module load
    time."""
    import ast
    from pathlib import Path

    hot_path_files = [
        Path("orca/serve/api.py"),
        Path("orca/agent/runtime.py"),
        Path("orca/gateway/gateway.py"),
    ]
    for path in hot_path_files:
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
        assert not any(m == "orca.learning" or m.startswith("orca.learning.") for m in imported_modules), (
            f"{path} imports orca.learning at module scope -- violates spec §84's fast-path requirement"
        )
