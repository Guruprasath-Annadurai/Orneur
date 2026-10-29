"""Phase 2–9 safe engineering gates for pretraining closure.

Protected actions remain refused. Synthetic tests never become physical PASS.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orca.pretrain_foundation.c27_feasibility import (
    investigate_c27,
    refuse_unauthorized_class_k_workaround,
)
from orca.pretrain_foundation.corpus_controls import (
    CorpusAdmissionRequest,
    CorpusControlError,
    admit_fixture,
    corpus_digest,
    invalidate_on_digest_change,
    refuse_user_conversation_ingestion,
)
from orca.pretrain_foundation.eval_boundary import (
    AccessAttempt,
    EvalBoundaryError,
    authorize_access,
    fail_closed_on_scoring_error,
    require_identity_separation,
)
from orca.pretrain_foundation.genesis_feasibility import assess_genesis, family_status_snapshot
from orca.pretrain_foundation.hardware_evidence_boundary import (
    EvidenceClaim,
    PhysicalEvidenceError,
    classify_claim,
    refuse_mock_as_acceptance,
)
from orca.pretrain_foundation.independent_codec import (
    CodecAgreementClaim,
    IndependentCodecError,
    c16_engineering_status,
    validate_independent_agreement,
)
from orca.pretrain_foundation.infra_record import (
    InfraRecordError,
    build_infra_record,
    refuse_hardware_pass_from_record,
)
from orca.pretrain_foundation.training_freeze import (
    TrainingFreezeError,
    assert_unauthorized_execution_refused,
    build_freeze_package,
    write_freeze_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def test_hardware_boundary_refuses_synthetic_as_acceptance():
    claim = EvidenceClaim(
        requirement_id="HW-01",
        kind="witness_serial_custody",
        synthetic=True,
        artifact_id="mock-serial",
    )
    assert classify_claim(claim) == "SYNTHETIC_SEMANTICS_ONLY"
    with pytest.raises(PhysicalEvidenceError, match="synthetic"):
        refuse_mock_as_acceptance(claim)


def test_hardware_boundary_requires_physical_when_absent():
    claim = EvidenceClaim(requirement_id="C24", kind="tpm_policy", synthetic=False)
    assert classify_claim(claim) == "PHYSICAL_EVIDENCE_REQUIRED"
    with pytest.raises(PhysicalEvidenceError, match="physical evidence required"):
        refuse_mock_as_acceptance(claim)


def test_c27_investigation_refuses_unauthorized_workaround():
    report = investigate_c27()
    assert report.requirement_id == "C27"
    assert report.unauthorized_workaround_refused is True
    assert report.engineering_disposition == "BLOCKED_BY_PROTECTED_DECISION"
    with pytest.raises(PermissionError, match="authorized class-K"):
        refuse_unauthorized_class_k_workaround(claimed_pass=True, authorized_path=False)


def test_independent_codec_refuses_cursor_self_cert():
    with pytest.raises(IndependentCodecError, match="self-certify"):
        validate_independent_agreement(
            CodecAgreementClaim(
                primary_implementation_id="orca.rse.imp4.ocr1",
                secondary_implementation_id="cursor",
                primary_verdict_digest="a" * 64,
                secondary_verdict_digest="a" * 64,
                vector_id="v1",
            )
        )
    assert "PRIMARY_ONLY" in c16_engineering_status(secondary_present=False)


def test_independent_codec_accepts_distinct_agreeing_second_impl():
    validate_independent_agreement(
        CodecAgreementClaim(
            primary_implementation_id="orca.rse.imp4.ocr1",
            secondary_implementation_id="antigravity-reference-codec",
            primary_verdict_digest="b" * 64,
            secondary_verdict_digest="b" * 64,
            vector_id="v1",
        )
    )


def test_eval_boundary_denies_training_identity_holdout_read():
    with pytest.raises(EvalBoundaryError, match="denied holdout"):
        authorize_access(
            AccessAttempt(
                actor_identity="training",
                resource_class="eval_holdout",
                action="read",
            )
        )


def test_eval_boundary_requires_identity_separation_and_fail_closed():
    with pytest.raises(EvalBoundaryError, match="must differ"):
        require_identity_separation("same", "same")
    with pytest.raises(EvalBoundaryError, match="failed closed"):
        fail_closed_on_scoring_error(scored_ok=False, error_detail="nan")


def test_corpus_controls_admit_synthetic_and_refuse_conversations():
    digest = admit_fixture(
        CorpusAdmissionRequest(
            fixture_class="synthetic_unit_fixture",
            source_license_id=None,
            content_sha256="c" * 64,
            holdout=False,
            training_authorized=False,
            corpus_generation_granted=False,
        )
    )
    assert digest.startswith("ADMITTED")
    with pytest.raises(CorpusControlError, match="user-conversation"):
        refuse_user_conversation_ingestion(source_type="user_conversation")
    d1 = corpus_digest([b"a", b"b"])
    d2 = corpus_digest([b"a", b"c"])
    with pytest.raises(CorpusControlError, match="invalidated"):
        invalidate_on_digest_change(frozen_digest=d1, candidate_digest=d2)


def test_corpus_controls_refuse_holdout_under_training_identity():
    with pytest.raises(CorpusControlError, match="holdout"):
        admit_fixture(
            CorpusAdmissionRequest(
                fixture_class="synthetic_unit_fixture",
                source_license_id=None,
                content_sha256="d" * 64,
                holdout=True,
                training_authorized=True,
                corpus_generation_granted=False,
            )
        )


def test_genesis_feasibility_is_analytical_and_unselected():
    report = assess_genesis()
    assert report.official_foundation_selected is False
    assert report.weights_downloaded is False
    assert report.frontier_pretraining_available is False
    assert report.parameter_count > 0
    assert report.family_statuses["GENESIS"] == "INTERFACE_ONLY"
    assert report.family_statuses["NOVUS"] == "NOT_AVAILABLE"
    assert report.family_statuses["AETERNUM"] == "NOT_AVAILABLE"
    assert family_status_snapshot()["GENESIS"] == "INTERFACE_ONLY"


def test_infra_record_pins_lockfiles_and_refuses_hardware_pass():
    rec = build_infra_record(ROOT, code_sha="abc123", dry_run_log_pointer="logs/dryrun.json")
    assert "uv.lock" in rec.lockfile_digests
    assert rec.gpu_provisioned is False
    assert rec.training_authorized is False
    with pytest.raises(InfraRecordError, match="GPU is not provisioned"):
        refuse_hardware_pass_from_record(
            build_infra_record(
                ROOT,
                code_sha="abc123",
                p2_environment_id="env-candidate",
                gpu_provisioned=False,
            )
        )


def test_training_freeze_package_is_nogo_and_refuses_execution(tmp_path):
    package = build_freeze_package(ROOT, code_sha="deadbeef", model_configuration={"arch": "genesis-arch-v1"})
    assert package.training_authorization == "NO-GO"
    assert package.status == "NOT_FROZEN"
    assert package.readiness_blockers
    with pytest.raises(TrainingFreezeError, match="unauthorized"):
        assert_unauthorized_execution_refused(package, execute_requested=True)
    out = tmp_path / "TRAINING_FREEZE_MANIFEST.json"
    write_freeze_manifest(out, package)
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["package"]["training_authorization"] == "NO-GO"
