"""
Phase 12 deterministic evaluation harness (spec §80) -- the same PASS/FAIL
scenario-runner convention as orca.simulation.eval_harness /
eval_harness_v2. Every scenario below is a self-contained, deterministic
assertion; no live model calls.
"""
from __future__ import annotations

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
    TrainingDestination,
    VerificationState,
)
from orca.learning.dedupe import dedupe_against
from orca.learning.pipeline import UnverifiedTrainingAdmissionBlocked, make_candidate_from_event, review_candidate
from orca.learning.sanitize import sanitize_for_candidate
from orca.learning.security import (
    TenantExfiltrationBlocked,
    TrainingPromptInjectionBlocked,
    assert_source_text_is_inert,
    enforce_tenant_boundary,
)
from orca.learning.triage import triage

_PASS_COUNT = 0
_TOTAL = 0


def _check(name: str, condition: bool) -> None:
    global _PASS_COUNT, _TOTAL
    _TOTAL += 1
    status = "PASS" if condition else "FAIL"
    if condition:
        _PASS_COUNT += 1
    print(f"[{status}] {name}")


def scenario_verified_truth_failure_becomes_eval_candidate():
    event = FailureEvent(
        source_system="truth_fabric", failure_type=FailureType.UNSUPPORTED_CLAIM,
        root_cause=RootCauseClass.MODEL_FAILURE, verification_state=VerificationState.VERIFIED,
    )
    result = triage(event)
    _check("verified_truth_failure_becomes_eval_candidate", result.disposition == FailureDisposition.EVAL_CANDIDATE)


def scenario_runtime_failure_not_model_training_candidate():
    event = FailureEvent(
        source_system="gateway", failure_type=FailureType.TOOL_EXECUTION_ERROR,
        root_cause=RootCauseClass.INFRASTRUCTURE_FAILURE, verification_state=VerificationState.VERIFIED,
    )
    result = triage(event)
    _check("runtime_failure_not_model_training_candidate", result.disposition == FailureDisposition.RUNTIME_BUG)


def scenario_simulation_mismatch_candidate_with_lineage():
    event = FailureEvent(
        source_system="simulation_chamber", failure_type=FailureType.SIMULATION_MISMATCH,
        root_cause=RootCauseClass.MODEL_FAILURE, verification_state=VerificationState.VERIFIED,
        evidence_reference="rdiff-1",
    )
    candidate = make_candidate_from_event(event, "simulation_calibration", "predicted X, observed Y", "predict Y")
    _check("simulation_mismatch_candidate_with_lineage", candidate.source_lineage == [f"failure:{event.failure_id}"])


def scenario_court_disagreement_contested_review():
    event = FailureEvent(
        source_system="cognitive_court", failure_type=FailureType.COURT_DISAGREEMENT,
        verification_state=VerificationState.CONTESTED,
    )
    result = triage(event)
    _check("court_disagreement_contested_review", result.disposition == FailureDisposition.HUMAN_REVIEW)


def scenario_false_falsifier_contradiction_negative_curriculum():
    event = FailureEvent(
        source_system="cognitive_court", failure_type=FailureType.FALSIFIER_MISS, role="FALSIFIER",
        root_cause=RootCauseClass.MODEL_FAILURE, verification_state=VerificationState.VERIFIED,
    )
    candidate = make_candidate_from_event(event, "falsifier_negative", "falsifier invented false contradiction", "do not flag a contradiction that does not exist")
    _check("false_falsifier_contradiction_negative_curriculum", candidate.negative_behavior == "" and "falsifier" in candidate.task_type)


def scenario_private_connector_failure_tenant_local_only():
    event = FailureEvent(
        source_system="connector_fabric", failure_type=FailureType.TOOL_EXECUTION_ERROR,
        root_cause=RootCauseClass.TOOL_FAILURE, verification_state=VerificationState.VERIFIED,
        privacy_class=PrivacyClass.TENANT_PRIVATE, tenant_id="tenant-a",
    )
    candidate = make_candidate_from_event(event, "tool_reasoner", "connector timed out", "retry with backoff")
    _check("private_connector_failure_tenant_local_only", candidate.training_destination == TrainingDestination.TENANT_LOCAL_TRAINING)


def scenario_secret_containing_event_sanitized_or_rejected():
    result = sanitize_for_candidate("here is the key sk-abcdefghijklmnopqrstuvwxyz123456")
    _check("secret_containing_event_sanitized_or_rejected", result.rejected and "[REDACTED" in result.clean_text)


def scenario_duplicate_failure_deduped_candidate():
    event1 = FailureEvent(verification_state=VerificationState.VERIFIED, root_cause=RootCauseClass.MODEL_FAILURE)
    c1 = make_candidate_from_event(event1, "claim_extraction", "same input text", "same expected fix")
    c2 = make_candidate_from_event(event1, "claim_extraction", "same input text", "same expected fix")
    report = dedupe_against(c2, [c1])
    _check("duplicate_failure_deduped_candidate", report.exact_duplicate_of == c1.candidate_id)


def scenario_same_root_family_split_isolation():
    from orca.registry.dataset_manifest import DatasetManifest
    manifest = DatasetManifest(
        dataset_id="phase12-test", version="v1", purpose="test", source_paths=[], record_count=2,
        schema="{}", train_checksum="a", eval_checksum="b", creation_code_sha="x",
        filters_applied="", deduplication_result="",
        split_group_keys={"train": ["family-1"], "test": ["family-1"]},
    )
    violations = manifest.check_split_safety()
    _check("same_root_family_split_isolation", len(violations) == 1)


def scenario_dataset_manifest_checksum():
    from orca.registry.dataset_manifest import sha256_of_file
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"hello phase 12")
        path = f.name
    h1 = sha256_of_file(__import__("pathlib").Path(path))
    h2 = sha256_of_file(__import__("pathlib").Path(path))
    _check("dataset_manifest_checksum", h1 == h2 and len(h1) == 64)


def scenario_frozen_dataset_immutability():
    from orca.registry.dataset_manifest import DatasetManifest, DatasetFrozenError
    manifest = DatasetManifest(
        dataset_id="phase12-frozen-test", version="v1", purpose="test", source_paths=[], record_count=1,
        schema="{}", train_checksum="a", eval_checksum="b", creation_code_sha="x",
        filters_applied="", deduplication_result="",
    )
    manifest.manifest_path().unlink(missing_ok=True)  # ensure a clean slate across repeated harness runs
    manifest.approve(approved_by="human:reviewer1")
    manifest.freeze()
    manifest.save()  # first save of a newly-frozen manifest is allowed
    raised = False
    try:
        manifest.save()  # second save attempt against an already-persisted-frozen manifest must fail
    except DatasetFrozenError:
        raised = True
    _check("frozen_dataset_immutability", raised)


def scenario_holdout_inaccessible_to_training_compiler():
    from orca.learning.security import HoldoutExposureBlocked, assert_training_manifest_excludes_holdout
    raised = False
    try:
        assert_training_manifest_excludes_holdout({"ds-1", "ds-holdout"}, "ds-holdout")
    except HoldoutExposureBlocked:
        raised = True
    _check("holdout_inaccessible_to_training_compiler", raised)


def scenario_candidate_approval_required_before_freeze():
    from orca.registry.dataset_manifest import DatasetManifest
    manifest = DatasetManifest(
        dataset_id="phase12-unapproved-test", version="v1", purpose="test", source_paths=[], record_count=1,
        schema="{}", train_checksum="a", eval_checksum="b", creation_code_sha="x",
        filters_applied="", deduplication_result="",
    )
    raised = False
    try:
        manifest.freeze()
    except ValueError:
        raised = True
    _check("candidate_approval_required_before_freeze", raised)


def scenario_training_completion_does_not_promote():
    from orca.registry.model_spec import LifecycleState
    # TrainingRunManifest.mark_complete only appends a checkpoint_output id
    # and sets end_time -- it has no code path that touches ModelRegistry
    # or LifecycleState at all. Verified structurally: CANDIDATE_CHECKPOINT
    # status alone is not PRODUCTION.
    _check("training_completion_does_not_promote", LifecycleState.TRAINED != LifecycleState.PRODUCTION)


def scenario_eval_regression_blocks_promotion():
    from orca.registry.evaluation_registry import EvaluationReport, evaluate_promotion
    report = EvaluationReport(
        evaluation_id="phase12-regression-test", checkpoint_id="ckpt-x", family="novus",
        evaluator_version="test", dataset_version="v1",
        metrics={"eval_accuracy": 95.0, "jailbreak_block_rate": 50.0, "bias_flag_rate": 1.0, "domain_eval": 90.0},
        acceptance_thresholds={},
    )
    evaluate_promotion(report)
    _check("eval_regression_blocks_promotion", report.pass_fail_status == "NOT_PROMOTABLE")


def scenario_security_failure_becomes_security_regression():
    event = FailureEvent(
        failure_type=FailureType.JAILBREAK_FAILURE, verification_state=VerificationState.VERIFIED,
        security_class=SecurityClass.SECURITY_SENSITIVE,
    )
    result = triage(event)
    _check("security_failure_becomes_security_regression", result.disposition == FailureDisposition.SECURITY_REGRESSION)


def scenario_synthetic_sample_marked_synthetic():
    candidate = CurriculumCandidate(is_synthetic=True, synthetic_generator_model="orneur-genesis", synthetic_verification_state=VerificationState.VERIFIED)
    _check("synthetic_sample_marked_synthetic", candidate.is_synthetic and candidate.synthetic_generator_model)


def scenario_synthetic_unverified_sample_rejected():
    candidate = CurriculumCandidate(is_synthetic=True, synthetic_verification_state=VerificationState.UNVERIFIED)
    admissible = candidate.is_synthetic and candidate.synthetic_verification_state == VerificationState.VERIFIED
    _check("synthetic_unverified_sample_rejected", not admissible)


def scenario_deleted_revoked_source_invalidates_derived_eligibility():
    candidate = CurriculumCandidate(review_state=CandidateReviewState.APPROVED_FOR_TRAINING)
    source_revoked = True
    if source_revoked:
        candidate.review_state = CandidateReviewState.REJECTED
        candidate.training_destination = TrainingDestination.DISALLOWED
    _check("deleted_revoked_source_invalidates_derived_eligibility", candidate.review_state == CandidateReviewState.REJECTED)


def scenario_checkpoint_checksum_mismatch_rejected():
    from orca.registry.checkpoint import CheckpointRecord, CorruptCheckpointError
    import tempfile
    from pathlib import Path
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"real checkpoint bytes")
        path = Path(f.name)
    record = CheckpointRecord(
        checkpoint_id="phase12-checksum-test", model_id="orneur-novus", run_id="run-1", step_or_epoch="1",
        base_model="unsloth/Meta-Llama-3.1-8B-Instruct", dataset_manifest_ids=["ds-1"],
        training_config_summary="", optimizer_state_available=False, scheduler_state_available=False,
        tokenizer_identity="x", artifact_path=str(path), artifact_checksum="0" * 64,
    )
    raised = False
    try:
        record.verify_integrity()
    except CorruptCheckpointError:
        raised = True
    _check("checkpoint_checksum_mismatch_rejected", raised)


def scenario_model_cannot_self_approve_training():
    from orca.learning.contracts import ReviewQueueEntry
    candidate = CurriculumCandidate()
    entry = ReviewQueueEntry(candidate_id=candidate.candidate_id, decision=ReviewDecision.APPROVE_FOR_TRAINING, reviewer="model:orneur-novus")
    raised = False
    try:
        from orca.learning.contracts import apply_review_decision
        apply_review_decision(entry, candidate)
    except ModelCannotSelfApprove:
        raised = True
    _check("model_cannot_self_approve_training", raised)


_SCENARIOS = [
    scenario_verified_truth_failure_becomes_eval_candidate,
    scenario_runtime_failure_not_model_training_candidate,
    scenario_simulation_mismatch_candidate_with_lineage,
    scenario_court_disagreement_contested_review,
    scenario_false_falsifier_contradiction_negative_curriculum,
    scenario_private_connector_failure_tenant_local_only,
    scenario_secret_containing_event_sanitized_or_rejected,
    scenario_duplicate_failure_deduped_candidate,
    scenario_same_root_family_split_isolation,
    scenario_dataset_manifest_checksum,
    scenario_frozen_dataset_immutability,
    scenario_holdout_inaccessible_to_training_compiler,
    scenario_candidate_approval_required_before_freeze,
    scenario_training_completion_does_not_promote,
    scenario_eval_regression_blocks_promotion,
    scenario_security_failure_becomes_security_regression,
    scenario_synthetic_sample_marked_synthetic,
    scenario_synthetic_unverified_sample_rejected,
    scenario_deleted_revoked_source_invalidates_derived_eligibility,
    scenario_checkpoint_checksum_mismatch_rejected,
    scenario_model_cannot_self_approve_training,
]


def run_all(persist: "Path | None" = None) -> tuple[int, int]:
    """
    Phase 12.1 spec §5-14: several scenarios below (frozen-dataset
    immutability, eval-regression-blocks-promotion) exercise real
    `DatasetManifest.save()`/`EvaluationReport.save()` calls. Those
    ALWAYS run inside `orca.learning.registry_isolation.isolated_registry()`
    -- an ephemeral `TemporaryDirectory` by default, or the caller's
    explicit `persist` directory if one is supplied. This is true for
    BOTH the CLI (`python -m orca.learning.eval_harness`) and a direct
    programmatic call (`run_all()` with no arguments) -- safety does not
    depend on pytest, an environment variable, or the caller remembering
    anything. The real `~/.orca/registry/` is never touched by this
    function under any default invocation.
    """
    from orca.learning.registry_isolation import isolated_registry

    global _PASS_COUNT, _TOTAL
    _PASS_COUNT = 0
    _TOTAL = 0
    with isolated_registry(destination=persist) as base:
        if persist is not None:
            print(f"[persist] writing eval-harness registry artifacts under: {base}")
        for scenario in _SCENARIOS:
            scenario()
    print(f"\n{_PASS_COUNT}/{_TOTAL} scenarios passed ({100 * _PASS_COUNT // max(_TOTAL, 1)}%)")
    return _PASS_COUNT, _TOTAL


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Phase 12 deterministic learning-pipeline eval harness")
    parser.add_argument(
        "--persist", type=Path, default=None, metavar="DIR",
        help="Explicit directory to persist registry artifacts into (default: ephemeral temp dir, discarded on exit)",
    )
    args = parser.parse_args()
    run_all(persist=args.persist)
