"""
Phase 15.10 -- Production Proof engine tests, hardened by Phase 15.10.1's
integrity closure: category-identity binding, Court context binding,
anti-gaming evidence provenance, evidence-derived release policy,
evidence-backed non-VerificationRecord PASS categories, deployment/
rollback revision integrity, and the full failure-injection matrix.
"""
from __future__ import annotations

import pytest

from orca.mission.anti_gaming import AntiGamingFinding, FindingCategory, Severity
from orca.mission.cognitive_court import CourtDecision, CourtRole, CourtVerdict, RiskLevel
from orca.mission.production_proof import (
    CATEGORY_AUTHORITY,
    CATEGORY_BUILD,
    CATEGORY_E2E_TEST,
    CATEGORY_INTEGRATION_TEST,
    CATEGORY_SECURITY,
    CATEGORY_UNIT_TEST,
    NOT_ENGINEERING_READY,
    AntiGamingAnalysisEvidence,
    DeploymentResult,
    DeploymentState,
    ExternalPublicationConfirmation,
    ProductionProofError,
    RegressionResult,
    ReleaseQualificationPolicy,
    RollbackResult,
    canonical_json,
    compute_proof_hash,
    evaluate_scoped_category,
    generate_production_proof,
    not_applicable_category,
    redact_secrets,
    render_human_readable,
    to_dict,
    unverified_category,
)
from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import RequiredVerificationScope, ScopeError

_UNIT_TEST_SCOPE = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST"}))
_CRIT_SCOPE = RequiredVerificationScope(criterion_ids=frozenset({"c1", "c2"}))

# Fixtures in this file exercise only build/unit_tests/security by
# design -- integration/e2e/regression/authority are explicitly marked
# NOT_APPLICABLE by policy for tests that aren't specifically about
# them, rather than silently omitted (spec item 5's own instruction:
# absence of evidence must never make a category quietly optional).
_MINIMAL_POLICY = ReleaseQualificationPolicy(
    engineering_not_applicable={
        "integration_tests": "not exercised by this unit test fixture",
        "e2e_tests": "not exercised by this unit test fixture",
        "regression": "not exercised by this unit test fixture",
        "authority": "not exercised by this unit test fixture",
    },
)


def _rec(category=CATEGORY_UNIT_TEST, requirement_id="REQ-X-1", outcome=VerificationOutcome.PASS,
         mission_id="m1", revision="rev1", **overrides):
    defaults = dict(
        id=f"ver_{category}_{requirement_id}_{mission_id}_{revision}_{overrides.get('id_suffix', '0')}",
        mission_id=mission_id, requirement_id=requirement_id,
        criterion_id=None, category=category, verification_method=category, verifier_id="TestVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=outcome, revision=revision,
        evidence_refs=("x",) if outcome == VerificationOutcome.PASS else (),
    )
    overrides.pop("id_suffix", None)
    defaults.update(overrides)
    return VerificationRecord(**defaults)


def _accept_decision(**overrides):
    defaults = dict(
        decision_id="d1", mission_id="m1", revision="rev1", risk_level=RiskLevel.STANDARD,
        roles_invoked=(CourtRole.ARBITER,), findings_considered=(), verification_refs=("v1",),
        reasoning_summary="all good", verdict=CourtVerdict.ACCEPT,
    )
    defaults.update(overrides)
    return CourtDecision(**defaults)


def _finding(**overrides):
    defaults = dict(
        finding_id="f1", mission_id="m1", revision="rev1", baseline_revision="rev0",
        category=FindingCategory.ASSERTION_WEAKENED, severity=Severity.CRITICAL, file_path="x.py",
        description="weakened", detector_id="detect_assertion_weakening", confidence_basis="AST",
        security_relevance=True, blocking=True,
    )
    defaults.update(overrides)
    return AntiGamingFinding(**defaults)


def _ag_evidence(**overrides):
    defaults = dict(
        analysis_id="ag1", mission_id="m1", baseline_revision="rev0", candidate_revision="rev1",
        detector_ids=("detect_assertion_weakening",),
    )
    defaults.update(overrides)
    return AntiGamingAnalysisEvidence(**defaults)


def _happy_path_kwargs(**overrides):
    unit_rec = _rec(category=CATEGORY_UNIT_TEST, requirement_id="REQ-X-1")
    build_rec = _rec(category=CATEGORY_BUILD, requirement_id=None, id_suffix="build")
    sec_rec = _rec(category=CATEGORY_SECURITY, requirement_id=None, id_suffix="sec")
    kwargs = dict(
        mission_id="m1", revision="rev1", required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
        records_by_requirement={"REQ-X-1": (unit_rec,)},
        court_decision=_accept_decision(), anti_gaming_evidence=_ag_evidence(),
        build_records=(build_rec,), unit_test_records=(unit_rec,),
        unit_test_stats={"collected": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0},
        security_records=(sec_rec,), release_policy=_MINIMAL_POLICY,
    )
    kwargs.update(overrides)
    return kwargs


# ══════════════════════════════════════════════════════════════════
# Item 1: VerificationRecord category + context binding
# ══════════════════════════════════════════════════════════════════

def test_a_unit_test_record_as_build_evidence_cannot_pass_build():
    unit_rec = _rec(category=CATEGORY_UNIT_TEST)
    proof = generate_production_proof(**_happy_path_kwargs(build_records=(unit_rec,)))
    assert proof.build.status is not VerificationOutcome.PASS


def test_b_unit_test_record_as_security_evidence_cannot_pass_security():
    unit_rec = _rec(category=CATEGORY_UNIT_TEST)
    proof = generate_production_proof(**_happy_path_kwargs(security_records=(unit_rec,)))
    assert proof.security.status is not VerificationOutcome.PASS


def test_c_stale_build_pass_record_is_unverified():
    stale_build = _rec(category=CATEGORY_BUILD, requirement_id=None, revision="rev0", id_suffix="stale")
    proof = generate_production_proof(**_happy_path_kwargs(build_records=(stale_build,)))
    assert proof.build.status is VerificationOutcome.UNVERIFIED


def test_d_cross_mission_security_pass_is_unverified():
    other_mission = _rec(category=CATEGORY_SECURITY, requirement_id=None, mission_id="m2", id_suffix="xm")
    proof = generate_production_proof(**_happy_path_kwargs(security_records=(other_mission,)))
    assert proof.security.status is VerificationOutcome.UNVERIFIED


def test_e_wrong_category_authority_evidence_is_unverified():
    wrong_cat = _rec(category=CATEGORY_UNIT_TEST, requirement_id=None, id_suffix="wrongcat")
    proof = generate_production_proof(**_happy_path_kwargs(authority_records=(wrong_cat,)))
    assert proof.authority.status is VerificationOutcome.UNVERIFIED


def test_f_genuine_correctly_scoped_build_record_can_pass():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.build.status is VerificationOutcome.PASS
    assert proof.build.evidence_refs


def test_g_genuine_correctly_scoped_security_record_can_pass():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.security.status is VerificationOutcome.PASS


def test_h_genuine_correctly_scoped_authority_record_can_pass():
    auth_rec = _rec(category=CATEGORY_AUTHORITY, requirement_id=None, id_suffix="auth")
    policy = ReleaseQualificationPolicy(engineering_not_applicable={
        "integration_tests": "n/a", "e2e_tests": "n/a", "regression": "n/a",
    })
    proof = generate_production_proof(**_happy_path_kwargs(authority_records=(auth_rec,), release_policy=policy))
    assert proof.authority.status is VerificationOutcome.PASS


def test_i_unit_integration_e2e_remain_independently_bound():
    unit_rec = _rec(category=CATEGORY_UNIT_TEST)
    integ_rec = _rec(category=CATEGORY_INTEGRATION_TEST, requirement_id=None, id_suffix="integ")
    proof = generate_production_proof(**_happy_path_kwargs(
        integration_test_records=(integ_rec,),
        integration_test_stats={"collected": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0},
    ))
    assert proof.unit_tests.status is VerificationOutcome.PASS
    assert proof.integration_tests.status is VerificationOutcome.PASS
    assert proof.e2e_tests.status is VerificationOutcome.UNVERIFIED
    # a UNIT_TEST record supplied as e2e evidence must not satisfy e2e:
    proof2 = generate_production_proof(**_happy_path_kwargs(e2e_test_records=(unit_rec,)))
    assert proof2.e2e_tests.status is not VerificationOutcome.PASS


def test_evaluate_scoped_category_directly_rejects_wrong_category():
    wrong = _rec(category=CATEGORY_UNIT_TEST, requirement_id=None)
    result = evaluate_scoped_category(
        (wrong,), expected_category=CATEGORY_BUILD, mission_id="m1", revision="rev1", not_run_summary="not run",
    )
    assert result.status is VerificationOutcome.UNVERIFIED
    assert "none matched" in result.summary


# ══════════════════════════════════════════════════════════════════
# Item 2: Court decision must be current-context bound
# ══════════════════════════════════════════════════════════════════

def test_stale_court_accept_blocked():
    stale = _accept_decision(revision="rev0")
    proof = generate_production_proof(**_happy_path_kwargs(court_decision=stale))
    assert proof.cognitive_court.context_bound is False
    assert proof.release_state == NOT_ENGINEERING_READY
    assert any("stale or cross-mission" in b for b in proof.blockers)


def test_cross_mission_court_accept_blocked():
    cross = _accept_decision(mission_id="m2")
    proof = generate_production_proof(**_happy_path_kwargs(court_decision=cross))
    assert proof.cognitive_court.context_bound is False
    assert proof.release_state == NOT_ENGINEERING_READY


def test_matching_current_court_accept_legitimate():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.cognitive_court.context_bound is True
    assert proof.release_state == "ENGINEERING_READY"


# ══════════════════════════════════════════════════════════════════
# Item 3: fabricated Court durability removed
# ══════════════════════════════════════════════════════════════════

def test_court_durability_cannot_be_asserted_by_caller():
    import inspect
    sig = inspect.signature(generate_production_proof)
    assert "court_decision_durable" not in sig.parameters


def test_court_snapshot_always_in_process_non_durable():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.cognitive_court.durable is False
    assert proof.cognitive_court.evidence_source == "IN_PROCESS_SNAPSHOT"
    assert any("not independently durable" in w for w in proof.warnings)


# ══════════════════════════════════════════════════════════════════
# Item 4: anti-gaming analysis needs evidence
# ══════════════════════════════════════════════════════════════════

def test_no_analysis_evidence_means_not_performed():
    kwargs = _happy_path_kwargs()
    kwargs["anti_gaming_evidence"] = None
    proof = generate_production_proof(**kwargs)
    assert proof.anti_test_gaming.analysis_performed is False
    assert proof.release_state == NOT_ENGINEERING_READY


def test_analysis_evidence_zero_findings_counts_as_analysis_performed():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.anti_test_gaming.analysis_performed is True
    assert proof.anti_test_gaming.total_findings == 0
    assert proof.release_state == "ENGINEERING_READY"


def test_stale_analysis_evidence_cannot_count():
    stale = _ag_evidence(candidate_revision="rev0")
    proof = generate_production_proof(**_happy_path_kwargs(anti_gaming_evidence=stale))
    assert proof.anti_test_gaming.analysis_performed is False


def test_cross_mission_analysis_evidence_cannot_count():
    cross = _ag_evidence(mission_id="m2")
    proof = generate_production_proof(**_happy_path_kwargs(anti_gaming_evidence=cross))
    assert proof.anti_test_gaming.analysis_performed is False


def test_analysis_evidence_with_blocking_finding_still_blocks():
    ev = _ag_evidence(findings=(_finding(),))
    proof = generate_production_proof(**_happy_path_kwargs(anti_gaming_evidence=ev))
    assert proof.anti_test_gaming.blocking_finding_ids == ("f1",)
    assert proof.release_state == NOT_ENGINEERING_READY


# ══════════════════════════════════════════════════════════════════
# Item 5: release state must be evidence-derived
# ══════════════════════════════════════════════════════════════════

def test_raw_submission_ready_boolean_no_longer_exists():
    import inspect
    sig = inspect.signature(generate_production_proof)
    assert "submission_ready_satisfied" not in sig.parameters


def test_raw_release_candidate_boolean_no_longer_exists():
    import inspect
    sig = inspect.signature(generate_production_proof)
    assert "release_candidate_satisfied" not in sig.parameters


def test_engineering_ready_reachable_with_minimal_policy():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.release_state == "ENGINEERING_READY"


def test_submission_ready_requires_policy_categories_pass():
    from orca.mission.production_proof import evidence_backed_pass
    supply_chain_pass = generate_production_proof(**_happy_path_kwargs(
        supply_chain=evidence_backed_pass("dependency scan clean", evidence_refs=("scan:1",)),
        release_policy=ReleaseQualificationPolicy(
            engineering_not_applicable=_MINIMAL_POLICY.engineering_not_applicable,
            submission_required=frozenset({"supply_chain"}),
        ),
    ))
    assert supply_chain_pass.release_state == "SUBMISSION_READY"


def test_required_supply_chain_unverified_blocks_release_candidate():
    policy = ReleaseQualificationPolicy(
        engineering_not_applicable=_MINIMAL_POLICY.engineering_not_applicable,
        submission_required=frozenset(),
        release_candidate_required=frozenset({"supply_chain", "release_build", "rollback"}),
    )
    proof = generate_production_proof(**_happy_path_kwargs(release_policy=policy))
    # all base engineering categories PASS, but supply_chain/release_build/rollback
    # required by policy remain UNVERIFIED -- cannot reach RELEASE_CANDIDATE.
    assert proof.build.status is VerificationOutcome.PASS
    assert proof.unit_tests.status is VerificationOutcome.PASS
    assert proof.security.status is VerificationOutcome.PASS
    assert proof.release_state != "RELEASE_CANDIDATE"
    assert any("supply_chain" in b for b in proof.blockers) or any("release_build" in b for b in proof.blockers)


def test_release_candidate_reachable_when_policy_categories_genuinely_pass():
    from orca.mission.production_proof import evidence_backed_pass
    policy = ReleaseQualificationPolicy(
        engineering_not_applicable=_MINIMAL_POLICY.engineering_not_applicable,
        submission_required=frozenset({"supply_chain"}),
        release_candidate_required=frozenset({"release_build"}),
    )
    proof = generate_production_proof(**_happy_path_kwargs(
        supply_chain=evidence_backed_pass("scanned", evidence_refs=("scan:1",)),
        release_build=evidence_backed_pass("built", evidence_refs=("artifact:1",)),
        release_policy=policy,
    ))
    assert proof.release_state == "RELEASE_CANDIDATE"


def test_published_requires_typed_external_confirmation():
    policy = ReleaseQualificationPolicy(
        engineering_not_applicable=_MINIMAL_POLICY.engineering_not_applicable,
        submission_stage_addressed=True, release_candidate_stage_addressed=True,
    )
    proof = generate_production_proof(**_happy_path_kwargs(release_policy=policy))
    assert proof.release_state == "RELEASE_CANDIDATE"
    confirmation = ExternalPublicationConfirmation(
        source="app-store-connect", timestamp="2026-01-02T00:00:00Z", target="production",
        evidence_reference="submission:12345", revision="rev1",
    )
    proof2 = generate_production_proof(**_happy_path_kwargs(
        release_policy=policy, external_publication_confirmation=confirmation,
    ))
    assert proof2.release_state == "PUBLISHED"


def test_published_unreachable_without_confirmation():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.release_state != "PUBLISHED"


def test_external_confirmation_revision_mismatch_cannot_publish():
    confirmation = ExternalPublicationConfirmation(
        source="app-store-connect", timestamp="2026-01-02T00:00:00Z", target="production",
        evidence_reference="submission:12345", revision="rev-different",
    )
    proof = generate_production_proof(**_happy_path_kwargs(external_publication_confirmation=confirmation))
    assert proof.release_state != "PUBLISHED"


def test_engineering_not_applicable_requires_reason():
    with pytest.raises(ProductionProofError):
        ReleaseQualificationPolicy(engineering_not_applicable={"integration_tests": ""})


# ══════════════════════════════════════════════════════════════════
# Item 6: evidence-backed non-VerificationRecord PASS categories
# ══════════════════════════════════════════════════════════════════

def test_bare_pass_proof_category_rejected():
    from orca.mission.production_proof import ProofCategory
    with pytest.raises(ProductionProofError):
        ProofCategory(status=VerificationOutcome.PASS, summary="trust me")


def test_evidence_backed_pass_requires_real_refs():
    from orca.mission.production_proof import evidence_backed_pass
    with pytest.raises(ProductionProofError):
        evidence_backed_pass("trust me", evidence_refs=())


def test_evidence_backed_pass_with_real_refs_accepted():
    from orca.mission.production_proof import evidence_backed_pass
    cat = evidence_backed_pass("real scan performed", evidence_refs=("scan:abc123",))
    assert cat.status is VerificationOutcome.PASS
    assert cat.evidence_refs == ("scan:abc123",)


def test_not_applicable_still_requires_real_reason():
    with pytest.raises(ProductionProofError):
        not_applicable_category("")


def test_unverified_may_have_no_evidence():
    cat = unverified_category("no scan performed")
    assert cat.status is VerificationOutcome.UNVERIFIED
    assert cat.evidence_refs == ()


# ══════════════════════════════════════════════════════════════════
# Item 7: deployment + rollback revision integrity
# ══════════════════════════════════════════════════════════════════

def test_reva_deployment_revb_proof_deployment_unverified():
    from orca.mission.production_proof import launch_evidence_from_proof
    old_deploy = DeploymentResult(
        state=DeploymentState.PRODUCTION_DEPLOYED, revision="revA", environment_identity="prod",
        deployed_at="2026-01-01T00:00:00Z",
    )
    proof = generate_production_proof(**_happy_path_kwargs(revision="revB", deployment=old_deploy))
    evidence = launch_evidence_from_proof(proof)
    assert evidence["deployment_readiness"] is None
    assert any("does not match" in w for w in proof.warnings)


def test_matching_revision_deployment_is_legitimate_readiness():
    from orca.mission.production_proof import launch_evidence_from_proof
    current_deploy = DeploymentResult(
        state=DeploymentState.PRODUCTION_DEPLOYED, revision="rev1", environment_identity="prod",
        deployed_at="2026-01-01T00:00:00Z",
    )
    proof = generate_production_proof(**_happy_path_kwargs(deployment=current_deploy))
    evidence = launch_evidence_from_proof(proof)
    assert evidence["deployment_readiness"] is True


def test_rollback_proven_with_no_current_deployment_cannot_count():
    from orca.mission.production_proof import launch_evidence_from_proof
    claimed_rollback = RollbackResult(strategy_documented=True, procedure_tested=True, proven_for_current_deployment=True)
    proof = generate_production_proof(**_happy_path_kwargs(rollback=claimed_rollback))
    evidence = launch_evidence_from_proof(proof)
    assert evidence["rollback_readiness"] is None


def test_rollback_proven_while_procedure_untested_cannot_count():
    from orca.mission.production_proof import launch_evidence_from_proof
    current_deploy = DeploymentResult(
        state=DeploymentState.PRODUCTION_DEPLOYED, revision="rev1", environment_identity="prod",
        deployed_at="2026-01-01T00:00:00Z",
    )
    claimed_rollback = RollbackResult(strategy_documented=True, procedure_tested=False, proven_for_current_deployment=True)
    proof = generate_production_proof(**_happy_path_kwargs(deployment=current_deploy, rollback=claimed_rollback))
    evidence = launch_evidence_from_proof(proof)
    assert evidence["rollback_readiness"] is None


def test_rollback_genuinely_proven_with_current_deployment_counts():
    from orca.mission.production_proof import launch_evidence_from_proof
    current_deploy = DeploymentResult(
        state=DeploymentState.PRODUCTION_DEPLOYED, revision="rev1", environment_identity="prod",
        deployed_at="2026-01-01T00:00:00Z",
    )
    real_rollback = RollbackResult(strategy_documented=True, procedure_tested=True, proven_for_current_deployment=True,
                                    method="git revert / redeploy known-good commit")
    proof = generate_production_proof(**_happy_path_kwargs(deployment=current_deploy, rollback=real_rollback))
    evidence = launch_evidence_from_proof(proof)
    assert evidence["rollback_readiness"] is True


# ══════════════════════════════════════════════════════════════════
# Item 9: stale-proof context fingerprint
# ══════════════════════════════════════════════════════════════════

def test_same_context_not_stale():
    from orca.mission.production_proof import is_proof_stale
    proof = generate_production_proof(**_happy_path_kwargs())
    stale = is_proof_stale(
        proof, current_revision="rev1", current_required_requirement_ids=("REQ-X-1",),
        current_required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert stale is False


def test_new_required_requirement_makes_stale():
    from orca.mission.production_proof import is_proof_stale
    proof = generate_production_proof(**_happy_path_kwargs())
    stale = is_proof_stale(
        proof, current_revision="rev1", current_required_requirement_ids=("REQ-X-1", "REQ-Y-1"),
        current_required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE, "REQ-Y-1": _UNIT_TEST_SCOPE},
    )
    assert stale is True


def test_removed_required_requirement_makes_stale():
    from orca.mission.production_proof import is_proof_stale
    proof = generate_production_proof(**_happy_path_kwargs())
    stale = is_proof_stale(
        proof, current_revision="rev1", current_required_requirement_ids=(),
        current_required_scopes_by_requirement={},
    )
    assert stale is True


def test_scope_change_makes_stale():
    from orca.mission.production_proof import is_proof_stale
    proof = generate_production_proof(**_happy_path_kwargs())
    wider = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST", "SECURITY_TEST"}))
    stale = is_proof_stale(
        proof, current_revision="rev1", current_required_requirement_ids=("REQ-X-1",),
        current_required_scopes_by_requirement={"REQ-X-1": wider},
    )
    assert stale is True


def test_requirement_semantics_change_under_same_id_makes_stale():
    from orca.mission.production_proof import is_proof_stale
    proof = generate_production_proof(**_happy_path_kwargs(
        requirement_semantics_fingerprints={"REQ-X-1": "hash-of-original-statement"},
    ))
    stale = is_proof_stale(
        proof, current_revision="rev1", current_required_requirement_ids=("REQ-X-1",),
        current_required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
        current_requirement_semantics_fingerprints={"REQ-X-1": "hash-of-CHANGED-statement"},
    )
    assert stale is True


def test_revision_change_makes_stale():
    from orca.mission.production_proof import is_proof_stale
    proof = generate_production_proof(**_happy_path_kwargs())
    assert is_proof_stale(proof, current_revision="rev2") is True


def test_reordered_equivalent_inputs_not_stale():
    from orca.mission.production_proof import is_proof_stale
    scope_a = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST", "SECURITY_TEST"}))
    proof = generate_production_proof(**_happy_path_kwargs(
        required_requirement_ids=("REQ-A", "REQ-B"),
        required_scopes_by_requirement={"REQ-A": scope_a, "REQ-B": _UNIT_TEST_SCOPE},
        records_by_requirement={"REQ-A": (), "REQ-B": ()},
    ))
    stale = is_proof_stale(
        proof, current_revision="rev1",
        current_required_requirement_ids=("REQ-B", "REQ-A"),  # reordered
        current_required_scopes_by_requirement={"REQ-B": _UNIT_TEST_SCOPE, "REQ-A": scope_a},
    )
    assert stale is False


# ══════════════════════════════════════════════════════════════════
# Item 10: secret redaction across ALL persisted fields
# ══════════════════════════════════════════════════════════════════

def test_secret_in_known_limitations_does_not_persist():
    proof = generate_production_proof(**_happy_path_kwargs(
        known_limitations=("db url postgresql://admin:hunter2@host/db not reachable",),
    ))
    assert "hunter2" not in proof.known_limitations[0]
    assert "hunter2" not in canonical_json(proof)


def test_secret_in_deployment_metadata_does_not_persist():
    tainted = DeploymentResult(
        state=DeploymentState.PRODUCTION_DEPLOYED, revision="rev1",
        environment_identity="prod token=AKIAABCDEFGHIJKLMNOP", deployed_at="2026-01-01T00:00:00Z",
        notes="deployed with api_key=abcd1234efgh5678ijkl",
    )
    proof = generate_production_proof(**_happy_path_kwargs(deployment=tainted))
    assert "AKIAABCDEFGHIJKLMNOP" not in proof.deployment.environment_identity
    assert "abcd1234efgh5678ijkl" not in (proof.deployment.notes or "")
    assert "AKIAABCDEFGHIJKLMNOP" not in canonical_json(proof)


def test_secret_in_tool_metadata_does_not_persist():
    proof = generate_production_proof(**_happy_path_kwargs(
        tool_versions={"scanner": "v1 token=Bearer abcdefghij1234567890"},
    ))
    assert "abcdefghij1234567890" not in canonical_json(proof)


def test_secret_in_rollback_method_does_not_persist():
    tainted = RollbackResult(
        strategy_documented=True, procedure_tested=True, proven_for_current_deployment=True,
        method="git revert (using postgresql://u:hunter3@h/db for state check)",
    )
    proof = generate_production_proof(**_happy_path_kwargs(rollback=tainted))
    assert "hunter3" not in canonical_json(proof)


def test_secret_in_regression_notes_does_not_persist():
    tainted = RegressionResult(
        baseline_revision="rev0", candidate_revision="rev1", baseline_collected=1, candidate_collected=1,
        notes="ran with secret=verysecretvalue1234",
    )
    proof = generate_production_proof(**_happy_path_kwargs(regression=tainted, release_policy=ReleaseQualificationPolicy(
        engineering_not_applicable={"integration_tests": "n/a", "e2e_tests": "n/a", "authority": "n/a"},
    )))
    assert "verysecretvalue1234" not in canonical_json(proof)


def test_secret_never_survives_into_render():
    proof = generate_production_proof(**_happy_path_kwargs(
        known_limitations=("postgresql://admin:hunter4@host/db",),
    ))
    rendered = render_human_readable(proof)
    assert "hunter4" not in rendered


def test_redact_secrets_scrubs_credentialed_postgres_url():
    redacted = redact_secrets("output containing postgresql://user:supersecretpassword@db.example.com:5432/mydb")
    assert "supersecretpassword" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_secrets_handles_none():
    assert redact_secrets(None) is None


# ══════════════════════════════════════════════════════════════════
# Item 11: regression evidence binding
# ══════════════════════════════════════════════════════════════════

def test_regression_candidate_revision_mismatch_is_unverified():
    mismatched = RegressionResult(
        baseline_revision="rev0", candidate_revision="rev-other", baseline_collected=10, candidate_collected=10,
    )
    proof = generate_production_proof(**_happy_path_kwargs(regression=mismatched))
    assert proof.regression.status is VerificationOutcome.UNVERIFIED
    assert proof.regression.candidate_revision is None


def test_regression_pre_existing_claim_without_baseline_rejected():
    with pytest.raises(ProductionProofError):
        RegressionResult(
            baseline_revision=None, candidate_revision="rev1", baseline_collected=None, candidate_collected=10,
            known_pre_existing_failures=("tests/test_x.py::test_y",),
        )


def test_regression_not_run_is_unverified():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.regression.status is VerificationOutcome.UNVERIFIED


def test_regression_new_failure_dominates_when_bound_to_revision():
    reg = RegressionResult(
        baseline_revision="rev0", candidate_revision="rev1", baseline_collected=10, candidate_collected=10,
        new_failures=("tests/test_x.py::test_y",),
    )
    proof = generate_production_proof(**_happy_path_kwargs(regression=reg))
    assert proof.regression.status is VerificationOutcome.FAIL


# ══════════════════════════════════════════════════════════════════
# Item 12: blockers must match release policy
# ══════════════════════════════════════════════════════════════════

def test_blockers_never_contradict_engineering_ready_state():
    proof = generate_production_proof(**_happy_path_kwargs())
    if proof.release_state == "ENGINEERING_READY":
        for category in ("build", "unit_tests", "security"):
            status = getattr(proof, category).status
            assert status is VerificationOutcome.PASS, f"{category} is {status} but release_state is ENGINEERING_READY"


def test_blockers_populated_when_not_ready():
    proof = generate_production_proof(**_happy_path_kwargs(build_records=()))
    assert proof.release_state == NOT_ENGINEERING_READY
    assert len(proof.blockers) > 0
    assert any("build" in b for b in proof.blockers)


# ══════════════════════════════════════════════════════════════════
# Remaining failure-injection matrix items (13, 20-25 numbering follows spec item 13)
# ══════════════════════════════════════════════════════════════════

def test_missing_scope_for_required_requirement_raises():
    with pytest.raises(ProductionProofError):
        generate_production_proof(**_happy_path_kwargs(required_scopes_by_requirement={}))


def test_stale_revision_record_does_not_satisfy_requirement():
    stale = _rec(category=CATEGORY_UNIT_TEST, revision="rev0")
    proof = generate_production_proof(**_happy_path_kwargs(records_by_requirement={"REQ-X-1": (stale,)}))
    assert "REQ-X-1" not in proof.requirements_satisfied


def test_cross_mission_record_does_not_satisfy_requirement():
    other_mission = _rec(category=CATEGORY_UNIT_TEST, mission_id="m2")
    proof = generate_production_proof(**_happy_path_kwargs(records_by_requirement={"REQ-X-1": (other_mission,)}))
    assert "REQ-X-1" not in proof.requirements_satisfied


def test_wrong_requirement_record_does_not_satisfy_requirement():
    spoofed = _rec(category=CATEGORY_UNIT_TEST, requirement_id="REQ-OTHER")
    proof = generate_production_proof(**_happy_path_kwargs(records_by_requirement={"REQ-X-1": (spoofed,)}))
    assert "REQ-X-1" not in proof.requirements_satisfied


def test_missing_required_criterion_leaves_requirement_unresolved():
    c1_only = _rec(criterion_id="c1")
    proof = generate_production_proof(**_happy_path_kwargs(
        required_scopes_by_requirement={"REQ-X-1": _CRIT_SCOPE},
        records_by_requirement={"REQ-X-1": (c1_only,)},
    ))
    assert "REQ-X-1" in proof.requirements_unresolved


def test_green_test_suite_plus_critical_blocking_finding_is_not_ready():
    ev = _ag_evidence(findings=(_finding(severity=Severity.CRITICAL, blocking=True),))
    proof = generate_production_proof(**_happy_path_kwargs(anti_gaming_evidence=ev))
    assert proof.unit_tests.status is VerificationOutcome.PASS
    assert proof.release_state == NOT_ENGINEERING_READY


def test_zero_collected_never_becomes_pass():
    passish = _rec(category=CATEGORY_UNIT_TEST, id_suffix="zc")
    proof = generate_production_proof(**_happy_path_kwargs(
        unit_test_records=(passish,),
        unit_test_stats={"collected": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0},
    ))
    assert proof.unit_tests.status is not VerificationOutcome.PASS


def test_evidence_refs_includes_contributing_records_and_court_decision():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert "d1" in proof.evidence_refs


def test_hash_deterministic_and_mutation_sensitive():
    kwargs = _happy_path_kwargs(proof_id="fixed_id", generated_at="2026-01-01T00:00:00Z")
    p1 = generate_production_proof(**kwargs)
    p2 = generate_production_proof(**kwargs)
    assert compute_proof_hash(p1) == compute_proof_hash(p2)
    kwargs2 = _happy_path_kwargs(proof_id="fixed_id", generated_at="2026-01-01T00:00:00Z", build_records=())
    p3 = generate_production_proof(**kwargs2)
    assert compute_proof_hash(p1) != compute_proof_hash(p3)


def test_canonical_json_has_no_proof_hash_field():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert '"proof_hash"' not in canonical_json(proof)


def test_render_agrees_with_typed_fields():
    proof = generate_production_proof(**_happy_path_kwargs())
    rendered = render_human_readable(proof)
    assert proof.proof_id in rendered
    assert proof.release_state in rendered


def test_to_dict_round_trips_through_json():
    import json
    proof = generate_production_proof(**_happy_path_kwargs())
    d = to_dict(proof)
    assert json.loads(json.dumps(d, sort_keys=True)) == d


def test_empty_mission_id_raises():
    with pytest.raises(ProductionProofError):
        generate_production_proof(**_happy_path_kwargs(mission_id=""))


def test_empty_revision_raises():
    with pytest.raises(ProductionProofError):
        generate_production_proof(**_happy_path_kwargs(revision=""))


def test_underlying_scope_error_still_raised_for_wholly_empty_scope():
    with pytest.raises(ScopeError):
        RequiredVerificationScope()


def test_launch_gate_integration_all_true_on_full_happy_path():
    from orca.mission.code_mode import evaluate_launch_gate, launch_gate_passes
    from orca.mission.production_proof import launch_evidence_from_proof
    proof = generate_production_proof(**_happy_path_kwargs())
    evidence = launch_evidence_from_proof(proof)
    results = evaluate_launch_gate(evidence, not_applicable=frozenset({
        "supply_chain", "release_configuration", "deployment_readiness", "rollback_readiness", "regression", "authority",
    }))
    assert results["build_evidence"].value == "PASS"
    assert results["tests"].value == "PASS"
    assert results["security"].value == "PASS"
    assert launch_gate_passes(results) is True
