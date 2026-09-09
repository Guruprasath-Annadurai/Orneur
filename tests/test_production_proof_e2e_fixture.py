"""
Phase 15.10 -- end-to-end Production Proof fixture (spec section 33),
updated for Phase 15.10.1's category-identity binding, Court context
binding, and typed anti-gaming evidence.

Demonstrates the full in-process chain:

    MISSION -> required requirements -> explicit RequiredVerificationScope
    -> real, CORRECTLY-CATEGORIZED VerificationRecords -> requirement
    aggregation -> anti-gaming evidence (context-bound) -> Court ACCEPT
    (context-bound) -> Production Proof generation -> human-readable
    rendering -> (durable persistence + fresh-connection reload + stale
    detection are separately qualified in test_production_proof_live_neon.py
    against a real disposable Neon branch)

then mutates one required check (PASS -> FAIL), generates a NEW proof, and
confirms the earlier proof's outcome is untouched, followed by a fix
producing a THIRD proof that is ready again -- demonstrating
READY -> BLOCKED -> READY without rewriting any prior proof.

This fixture proves the Production Proof ENGINE's own internal
consistency. It does NOT claim the ORNEUR repository itself is
production-ready (spec section 35).
"""
from __future__ import annotations

from orca.mission.anti_gaming import AntiGamingFinding, FindingCategory, Severity
from orca.mission.cognitive_court import CourtDecision, CourtRole, CourtVerdict, RiskLevel
from orca.mission.production_proof import (
    CATEGORY_BUILD,
    CATEGORY_SECURITY,
    CATEGORY_UNIT_TEST,
    NOT_ENGINEERING_READY,
    AntiGamingAnalysisEvidence,
    ReleaseQualificationPolicy,
    compute_proof_hash,
    generate_production_proof,
    render_human_readable,
)
from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import RequiredVerificationScope

_MISSION_ID = "mis_e2e_fixture"
_REQUIREMENT_ID = "REQ-E2E-FIXTURE-001"
_SCOPE = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST"}))
_MINIMAL_POLICY = ReleaseQualificationPolicy(
    engineering_not_applicable={
        "integration_tests": "not exercised by this fixture", "e2e_tests": "not exercised by this fixture",
        "regression": "not exercised by this fixture", "authority": "not exercised by this fixture",
    },
)


def _unit_record(outcome: VerificationOutcome, revision: str, record_id: str) -> VerificationRecord:
    return VerificationRecord(
        id=record_id, mission_id=_MISSION_ID, requirement_id=_REQUIREMENT_ID, criterion_id=None,
        category=CATEGORY_UNIT_TEST, verification_method="UNIT_TEST", verifier_id="UnitTestVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=outcome, revision=revision,
        evidence_refs=("local:pytest",) if outcome is VerificationOutcome.PASS else (),
    )


def _build_record(revision: str, record_id: str) -> VerificationRecord:
    return VerificationRecord(
        id=record_id, mission_id=_MISSION_ID, requirement_id=None, criterion_id=None,
        category=CATEGORY_BUILD, verification_method="BUILD_VERIFICATION", verifier_id="BuildVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision=revision,
        evidence_refs=("local:build",),
    )


def _security_record(revision: str, record_id: str) -> VerificationRecord:
    return VerificationRecord(
        id=record_id, mission_id=_MISSION_ID, requirement_id=None, criterion_id=None,
        category=CATEGORY_SECURITY, verification_method="SECURITY_TEST", verifier_id="SecurityVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision=revision,
        evidence_refs=("local:security",),
    )


def _accept_decision(revision: str) -> CourtDecision:
    return CourtDecision(
        decision_id=f"d_e2e_{revision}", mission_id=_MISSION_ID, revision=revision,
        risk_level=RiskLevel.STANDARD, roles_invoked=(CourtRole.ARBITER,), findings_considered=(),
        verification_refs=(), reasoning_summary="e2e fixture decision", verdict=CourtVerdict.ACCEPT,
    )


def _ag_evidence(revision: str) -> AntiGamingAnalysisEvidence:
    return AntiGamingAnalysisEvidence(
        analysis_id=f"ag_e2e_{revision}", mission_id=_MISSION_ID, baseline_revision="rev0",
        candidate_revision=revision, detector_ids=("detect_assertion_weakening",),
    )


def test_end_to_end_ready_then_blocked_then_ready_without_rewriting_history():
    # ── Step 1: rev1 -- everything genuinely passes -> ENGINEERING_READY.
    record_rev1 = _unit_record(VerificationOutcome.PASS, "rev1", "ver_e2e_rev1")
    proof_rev1 = generate_production_proof(
        mission_id=_MISSION_ID, revision="rev1", required_requirement_ids=(_REQUIREMENT_ID,),
        required_scopes_by_requirement={_REQUIREMENT_ID: _SCOPE},
        records_by_requirement={_REQUIREMENT_ID: (record_rev1,)},
        court_decision=_accept_decision("rev1"), anti_gaming_evidence=_ag_evidence("rev1"),
        build_records=(_build_record("rev1", "ver_e2e_build1"),), unit_test_records=(record_rev1,),
        unit_test_stats={"collected": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0},
        security_records=(_security_record("rev1", "ver_e2e_sec1"),), release_policy=_MINIMAL_POLICY,
    )
    assert proof_rev1.release_state == "ENGINEERING_READY"
    rendered_rev1 = render_human_readable(proof_rev1, proof_hash=compute_proof_hash(proof_rev1))
    assert "ENGINEERING_READY" in rendered_rev1
    assert _REQUIREMENT_ID in rendered_rev1

    # ── Step 2: rev2 -- the same required check now FAILS -> BLOCKED.
    failing_record = _unit_record(VerificationOutcome.FAIL, "rev2", "ver_e2e_rev2_fail")
    proof_rev2_blocked = generate_production_proof(
        mission_id=_MISSION_ID, revision="rev2", required_requirement_ids=(_REQUIREMENT_ID,),
        required_scopes_by_requirement={_REQUIREMENT_ID: _SCOPE},
        records_by_requirement={_REQUIREMENT_ID: (failing_record,)},
        anti_gaming_evidence=_ag_evidence("rev2"),
        build_records=(_build_record("rev2", "ver_e2e_build2"),), release_policy=_MINIMAL_POLICY,
    )
    assert proof_rev2_blocked.release_state == NOT_ENGINEERING_READY
    assert _REQUIREMENT_ID in proof_rev2_blocked.requirements_failed
    assert len(proof_rev2_blocked.blockers) > 0

    # proof_rev1's own outcome is unchanged by rev2's failure:
    assert proof_rev1.release_state == "ENGINEERING_READY"
    assert proof_rev1.requirements_failed == ()

    # ── Step 3: rev3 -- the check is fixed -> ready again.
    fixed_record = _unit_record(VerificationOutcome.PASS, "rev3", "ver_e2e_rev3_fixed")
    proof_rev3_fixed = generate_production_proof(
        mission_id=_MISSION_ID, revision="rev3", required_requirement_ids=(_REQUIREMENT_ID,),
        required_scopes_by_requirement={_REQUIREMENT_ID: _SCOPE},
        records_by_requirement={_REQUIREMENT_ID: (fixed_record,)},
        court_decision=_accept_decision("rev3"), anti_gaming_evidence=_ag_evidence("rev3"),
        build_records=(_build_record("rev3", "ver_e2e_build3"),), unit_test_records=(fixed_record,),
        unit_test_stats={"collected": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0},
        security_records=(_security_record("rev3", "ver_e2e_sec3"),), release_policy=_MINIMAL_POLICY,
    )
    assert proof_rev3_fixed.release_state == "ENGINEERING_READY"

    # ── History demonstration: READY -> BLOCKED -> READY, no rewriting.
    history = [proof_rev1, proof_rev2_blocked, proof_rev3_fixed]
    assert [p.revision for p in history] == ["rev1", "rev2", "rev3"]
    assert [p.release_state for p in history] == ["ENGINEERING_READY", NOT_ENGINEERING_READY, "ENGINEERING_READY"]
    hashes = {compute_proof_hash(p) for p in history}
    assert len(hashes) == 3
    ids = {p.proof_id for p in history}
    assert len(ids) == 3


def test_fixture_does_not_claim_whole_repository_is_production_ready():
    import inspect
    import tests.test_production_proof_e2e_fixture as this_module
    for name, func in inspect.getmembers(this_module, inspect.isfunction):
        if not name.startswith("test_") or name == "test_fixture_does_not_claim_whole_repository_is_production_ready":
            continue
        body = inspect.getsource(func)
        assert "production ready" not in body.lower()
        assert "production_ready" not in body.lower()


def test_blocking_anti_gaming_finding_also_blocks_the_e2e_happy_path():
    record = _unit_record(VerificationOutcome.PASS, "rev1", "ver_e2e_gaming")
    finding = AntiGamingFinding(
        finding_id="f_e2e_1", mission_id=_MISSION_ID, revision="rev1", baseline_revision="rev0",
        category=FindingCategory.MOCK_REPLACES_REQUIRED_BEHAVIOR, severity=Severity.CRITICAL,
        file_path="orca/godmode/x.py", description="security mock", detector_id="detect_mock_replacing_real_behavior",
        confidence_basis="AST", security_relevance=True, blocking=True,
    )
    ag_evidence = AntiGamingAnalysisEvidence(
        analysis_id="ag_e2e_gaming", mission_id=_MISSION_ID, baseline_revision="rev0", candidate_revision="rev1",
        detector_ids=("detect_mock_replacing_real_behavior",), findings=(finding,),
    )
    proof = generate_production_proof(
        mission_id=_MISSION_ID, revision="rev1", required_requirement_ids=(_REQUIREMENT_ID,),
        required_scopes_by_requirement={_REQUIREMENT_ID: _SCOPE},
        records_by_requirement={_REQUIREMENT_ID: (record,)},
        court_decision=_accept_decision("rev1"), anti_gaming_evidence=ag_evidence,
        build_records=(_build_record("rev1", "ver_e2e_gbuild"),), unit_test_records=(record,),
        unit_test_stats={"collected": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0},
        security_records=(_security_record("rev1", "ver_e2e_gsec"),), release_policy=_MINIMAL_POLICY,
    )
    assert proof.release_state == NOT_ENGINEERING_READY
    assert "f_e2e_1" in proof.anti_test_gaming.blocking_finding_ids
