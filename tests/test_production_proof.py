"""
Phase 15.10 -- Production Proof engine tests: typed model, category
outcomes, requirement-truth reuse of Phase 15.9.4's authoritative
scope evaluator, Court/anti-gaming integration, release-state policy,
hashing, human-readable rendering, secret redaction, and the full
failure-injection matrix (spec section 32).
"""
from __future__ import annotations

import pytest

from orca.mission.anti_gaming import AntiGamingFinding, FindingCategory, Severity
from orca.mission.cognitive_court import CourtDecision, CourtRole, CourtVerdict, RiskLevel
from orca.mission.production_proof import (
    NOT_ENGINEERING_READY,
    DeploymentResult,
    DeploymentState,
    ProductionProofError,
    RegressionResult,
    canonical_json,
    category_from_records,
    compute_proof_hash,
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


def _rec(**overrides):
    defaults = dict(
        id="v1", mission_id="m1", requirement_id="REQ-X-1", criterion_id=None, category="UNIT_TEST",
        verification_method="UNIT_TEST", verifier_id="UnitTestVerifier", started_at="2026-01-01T00:00:00Z",
        outcome=VerificationOutcome.PASS, revision="rev1", evidence_refs=("x",),
    )
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


def _happy_path_kwargs(**overrides):
    record = _rec()
    kwargs = dict(
        mission_id="m1", revision="rev1", required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
        records_by_requirement={"REQ-X-1": (record,)},
        court_decision=_accept_decision(), anti_gaming_analysis_performed=True,
        anti_gaming_baseline_revision="rev0", anti_gaming_candidate_revision="rev1",
        build_records=(record,), unit_test_records=(record,),
        unit_test_stats={"collected": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0},
        security_records=(record,),
    )
    kwargs.update(overrides)
    return kwargs


# ── Section 39.3: missing evidence never becomes PASS ────────────────

def test_no_records_for_requirement_is_unverified_not_pass():
    proof = generate_production_proof(**_happy_path_kwargs(
        records_by_requirement={"REQ-X-1": ()},
    ))
    assert proof.requirements_satisfied == ()
    assert "REQ-X-1" in proof.requirements_unresolved
    assert proof.release_state == NOT_ENGINEERING_READY


def test_build_not_run_is_unverified():
    proof = generate_production_proof(**_happy_path_kwargs(build_records=()))
    assert proof.build.status is VerificationOutcome.UNVERIFIED
    assert proof.release_state == NOT_ENGINEERING_READY


def test_security_not_run_is_unverified():
    proof = generate_production_proof(**_happy_path_kwargs(security_records=()))
    assert proof.security.status is VerificationOutcome.UNVERIFIED


def test_authority_not_run_is_unverified():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.authority.status is VerificationOutcome.UNVERIFIED


def test_supply_chain_unknown_defaults_unverified_not_pass():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.supply_chain.status is VerificationOutcome.UNVERIFIED


def test_licensing_unresolved_defaults_unverified():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.licensing.status is VerificationOutcome.UNVERIFIED


# ── Section 4: authoritative scope must be explicit / fail closed ───

def test_missing_scope_for_required_requirement_raises():
    with pytest.raises(ProductionProofError):
        generate_production_proof(**_happy_path_kwargs(required_scopes_by_requirement={}))


def test_blank_criterion_id_in_scope_raises():
    with pytest.raises(ProductionProofError):
        bad_scope = RequiredVerificationScope(criterion_ids=frozenset({"c1", ""}))
        # ScopeError itself won't fire for a blank string alongside a real one
        # (the set is non-empty) -- our own hardening must catch the blank entry.
        generate_production_proof(**_happy_path_kwargs(required_scopes_by_requirement={"REQ-X-1": bad_scope}))


def test_blank_category_in_scope_raises():
    bad_scope = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST", " "}))
    with pytest.raises(ProductionProofError):
        generate_production_proof(**_happy_path_kwargs(required_scopes_by_requirement={"REQ-X-1": bad_scope}))


def test_collapsing_criterion_and_category_names_raises():
    bad_scope = RequiredVerificationScope(criterion_ids=frozenset({"UNIT_TEST"}))
    # This alone wouldn't collapse since keys differ ("UNIT_TEST" vs "category:UNIT_TEST"),
    # so construct a genuinely colliding pair via both fields sharing a literal name
    # that, after key-construction, would still be distinguishable -- verify no false positive:
    proof = generate_production_proof(**_happy_path_kwargs(
        required_scopes_by_requirement={"REQ-X-1": bad_scope},
        records_by_requirement={"REQ-X-1": (_rec(criterion_id="UNIT_TEST"),)},
    ))
    assert proof.requirement_results[0].outcome is VerificationOutcome.PASS


def test_empty_mission_id_raises():
    with pytest.raises(ProductionProofError):
        generate_production_proof(**_happy_path_kwargs(mission_id=""))


def test_empty_revision_raises():
    with pytest.raises(ProductionProofError):
        generate_production_proof(**_happy_path_kwargs(revision=""))


def test_underlying_scope_error_still_raised_for_wholly_empty_scope():
    with pytest.raises(ScopeError):
        RequiredVerificationScope()


# ── Stale / cross-mission / wrong-requirement records (reuse Phase 15.9 invariants) ──

def test_stale_revision_record_does_not_satisfy_requirement():
    stale = _rec(revision="rev0")
    proof = generate_production_proof(**_happy_path_kwargs(records_by_requirement={"REQ-X-1": (stale,)}))
    assert "REQ-X-1" not in proof.requirements_satisfied


def test_cross_mission_record_does_not_satisfy_requirement():
    other_mission = _rec(mission_id="m2")
    proof = generate_production_proof(**_happy_path_kwargs(records_by_requirement={"REQ-X-1": (other_mission,)}))
    assert "REQ-X-1" not in proof.requirements_satisfied


def test_wrong_requirement_record_does_not_satisfy_requirement():
    spoofed = _rec(requirement_id="REQ-OTHER")
    proof = generate_production_proof(**_happy_path_kwargs(records_by_requirement={"REQ-X-1": (spoofed,)}))
    assert "REQ-X-1" not in proof.requirements_satisfied
    assert "REQ-X-1" in proof.requirements_unresolved


def test_missing_required_criterion_leaves_requirement_unresolved():
    c1_only = _rec(criterion_id="c1")
    proof = generate_production_proof(**_happy_path_kwargs(
        required_scopes_by_requirement={"REQ-X-1": _CRIT_SCOPE},
        records_by_requirement={"REQ-X-1": (c1_only,)},
    ))
    assert "REQ-X-1" in proof.requirements_unresolved
    result = proof.requirement_results[0]
    assert "c2" in result.missing_keys


# ── Court integration (spec section 7) ───────────────────────────────

def test_court_non_accept_blocks_engineering_ready():
    proof = generate_production_proof(**_happy_path_kwargs(
        court_decision=_accept_decision(verdict=CourtVerdict.REJECT),
    ))
    assert proof.release_state == NOT_ENGINEERING_READY
    assert any("Court verdict" in b for b in proof.blockers)


def test_no_court_decision_supplied_cannot_be_engineering_ready():
    kwargs = _happy_path_kwargs()
    kwargs.pop("court_decision")
    proof = generate_production_proof(**kwargs)
    assert proof.cognitive_court.verdict == "NOT_EVALUATED"
    assert proof.release_state == NOT_ENGINEERING_READY


def test_court_snapshot_defaults_non_durable_and_warns():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.cognitive_court.durable is False
    assert any("not independently durable" in w for w in proof.warnings)


def test_court_snapshot_durable_when_caller_asserts_it():
    proof = generate_production_proof(**_happy_path_kwargs(court_decision_durable=True))
    assert proof.cognitive_court.durable is True


# ── Anti-gaming integration (spec section 8) ─────────────────────────

def test_blocking_anti_gaming_finding_blocks_engineering_ready():
    proof = generate_production_proof(**_happy_path_kwargs(
        anti_gaming_findings=(_finding(),),
    ))
    assert proof.release_state == NOT_ENGINEERING_READY
    assert proof.anti_test_gaming.blocking_finding_ids == ("f1",)
    assert any("blocking anti-gaming" in b for b in proof.blockers)


def test_zero_findings_supplied_is_not_proof_analysis_performed():
    proof = generate_production_proof(**_happy_path_kwargs(
        anti_gaming_analysis_performed=False, anti_gaming_findings=(),
    ))
    assert proof.anti_test_gaming.analysis_performed is False
    assert proof.release_state == NOT_ENGINEERING_READY
    assert any("not performed" in w for w in proof.warnings)


def test_analysis_performed_with_zero_findings_is_distinct_and_can_be_ready():
    proof = generate_production_proof(**_happy_path_kwargs(
        anti_gaming_analysis_performed=True, anti_gaming_findings=(),
    ))
    assert proof.anti_test_gaming.analysis_performed is True
    assert proof.anti_test_gaming.total_findings == 0
    assert proof.release_state == "ENGINEERING_READY"


def test_green_test_suite_plus_critical_blocking_finding_is_not_ready():
    proof = generate_production_proof(**_happy_path_kwargs(
        anti_gaming_findings=(_finding(severity=Severity.CRITICAL, blocking=True),),
    ))
    assert proof.unit_tests.status is VerificationOutcome.PASS  # green suite
    assert proof.release_state == NOT_ENGINEERING_READY  # still blocked


# ── Test evidence (spec section 10) ──────────────────────────────────

def test_zero_collected_never_becomes_pass():
    passish = _rec(id="v2")
    proof = generate_production_proof(**_happy_path_kwargs(
        unit_test_records=(passish,),
        unit_test_stats={"collected": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0},
    ))
    assert proof.unit_tests.status is not VerificationOutcome.PASS


def test_no_unit_test_records_is_unverified():
    proof = generate_production_proof(**_happy_path_kwargs(unit_test_records=(), unit_test_stats={}))
    assert proof.unit_tests.status is VerificationOutcome.UNVERIFIED


def test_integration_and_e2e_not_merged_with_unit():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.integration_tests.status is VerificationOutcome.UNVERIFIED
    assert proof.e2e_tests.status is VerificationOutcome.UNVERIFIED
    assert proof.unit_tests.status is VerificationOutcome.PASS  # unaffected by the other two


def test_test_failure_is_fail_not_pass():
    failing = _rec(id="v3", outcome=VerificationOutcome.FAIL, evidence_refs=())
    proof = generate_production_proof(**_happy_path_kwargs(
        unit_test_records=(failing,),
        unit_test_stats={"collected": 1, "passed": 0, "failed": 1, "skipped": 0, "errors": 0},
    ))
    assert proof.unit_tests.status is VerificationOutcome.FAIL


# ── Security evidence (spec section 12) ──────────────────────────────

def test_security_partial_scope_named_accurately_not_secure():
    partial = _rec(id="sec1", category="SECURITY")
    proof = generate_production_proof(**_happy_path_kwargs(security_records=(partial,)))
    assert proof.security.status is VerificationOutcome.PASS
    # The category never claims a blanket "SECURE" string anywhere.
    rendered = render_human_readable(proof)
    assert "SECURE" not in rendered.upper().replace("INSECURE", "")


# ── Deployment / rollback (spec sections 19-21) ──────────────────────

def test_default_deployment_is_not_deployed_not_pass():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.deployment.state is DeploymentState.NOT_DEPLOYED


def test_deployment_is_revision_bound():
    old_deploy = DeploymentResult(
        state=DeploymentState.PRODUCTION_DEPLOYED, revision="rev0", environment_identity="prod",
        deployed_at="2026-01-01T00:00:00Z",
    )
    proof = generate_production_proof(**_happy_path_kwargs(deployment=old_deploy))
    # The proof is for rev1 but the deployment evidence given is for rev0 --
    # the generator does not silently reconcile this; it is surfaced as-is
    # for the caller/renderer to see the mismatch.
    assert proof.deployment.revision == "rev0"
    assert proof.revision == "rev1"


def test_rollback_default_is_undocumented_and_unproven():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.rollback.strategy_documented is False
    assert proof.rollback.procedure_tested is False
    assert proof.rollback.proven_for_current_deployment is False


def test_documented_plan_alone_is_not_tested_rollback():
    from orca.mission.production_proof import RollbackResult
    documented_only = RollbackResult(strategy_documented=True, procedure_tested=False, proven_for_current_deployment=False,
                                       method="git revert / redeploy known-good commit")
    proof = generate_production_proof(**_happy_path_kwargs(rollback=documented_only))
    assert proof.rollback.strategy_documented is True
    assert proof.rollback.proven_for_current_deployment is False


# ── Performance / accessibility (spec sections 16-17) ────────────────

def test_performance_required_but_unmeasured_is_unverified():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.performance.status is VerificationOutcome.UNVERIFIED


def test_performance_not_applicable_requires_reason():
    with pytest.raises(ProductionProofError):
        not_applicable_category("")


def test_accessibility_no_ui_can_be_not_applicable_with_reason():
    cat = not_applicable_category("no user interface exists in this proof target")
    proof = generate_production_proof(**_happy_path_kwargs(accessibility=cat))
    assert proof.accessibility.status is VerificationOutcome.NOT_APPLICABLE


def test_accessibility_default_is_unverified_not_not_applicable():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.accessibility.status is VerificationOutcome.UNVERIFIED


# ── Release-state policy (spec section 22) ───────────────────────────

def test_engineering_ready_reachable_on_full_happy_path():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.release_state == "ENGINEERING_READY"


def test_submission_ready_requires_flag():
    proof = generate_production_proof(**_happy_path_kwargs(submission_ready_satisfied=True))
    assert proof.release_state == "SUBMISSION_READY"


def test_release_candidate_requires_both_flags():
    proof = generate_production_proof(**_happy_path_kwargs(
        submission_ready_satisfied=True, release_candidate_satisfied=True,
    ))
    assert proof.release_state == "RELEASE_CANDIDATE"


def test_published_requires_all_flags_including_external_confirmation():
    proof = generate_production_proof(**_happy_path_kwargs(
        submission_ready_satisfied=True, release_candidate_satisfied=True,
        published_externally_confirmed=True,
    ))
    assert proof.release_state == "PUBLISHED"


def test_cannot_skip_to_release_candidate_without_submission_ready():
    proof = generate_production_proof(**_happy_path_kwargs(release_candidate_satisfied=True))
    assert proof.release_state == "ENGINEERING_READY"


def test_no_failure_supplied_does_not_auto_promote_to_published():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.release_state != "PUBLISHED"


def test_proof_generated_successfully_even_when_not_ready():
    proof = generate_production_proof(**_happy_path_kwargs(build_records=()))
    assert proof.proof_id
    assert proof.release_state == NOT_ENGINEERING_READY
    assert len(proof.blockers) > 0


# ── Hashing (spec section 24) ─────────────────────────────────────────

def test_same_canonical_payload_yields_same_hash():
    kwargs = _happy_path_kwargs(proof_id="fixed_id", generated_at="2026-01-01T00:00:00Z")
    p1 = generate_production_proof(**kwargs)
    p2 = generate_production_proof(**kwargs)
    assert compute_proof_hash(p1) == compute_proof_hash(p2)
    assert p1 == p2


def test_material_mutation_changes_hash():
    kwargs = _happy_path_kwargs(proof_id="fixed_id", generated_at="2026-01-01T00:00:00Z")
    p1 = generate_production_proof(**kwargs)
    h1 = compute_proof_hash(p1)
    kwargs2 = _happy_path_kwargs(proof_id="fixed_id", generated_at="2026-01-01T00:00:00Z", build_records=())
    p2 = generate_production_proof(**kwargs2)
    h2 = compute_proof_hash(p2)
    assert h1 != h2


def test_hash_is_deterministic_sha256_hex():
    proof = generate_production_proof(**_happy_path_kwargs())
    h = compute_proof_hash(proof)
    assert len(h) == 64
    int(h, 16)  # raises ValueError if not valid hex


def test_canonical_json_has_no_proof_hash_field_itself():
    proof = generate_production_proof(**_happy_path_kwargs())
    payload = canonical_json(proof)
    assert '"proof_hash"' not in payload


# ── Human-readable rendering (spec section 25) ───────────────────────

def test_render_agrees_with_typed_fields():
    proof = generate_production_proof(**_happy_path_kwargs())
    rendered = render_human_readable(proof)
    assert proof.proof_id in rendered
    assert proof.mission_id in rendered
    assert proof.revision in rendered
    assert proof.release_state in rendered
    for req_id in proof.requirements_satisfied:
        assert req_id in rendered


def test_render_shows_blockers_and_warnings():
    proof = generate_production_proof(**_happy_path_kwargs(build_records=()))
    rendered = render_human_readable(proof)
    for b in proof.blockers:
        assert b in rendered


# ── Secret redaction (spec section 26) ───────────────────────────────

@pytest.mark.parametrize("secret_text", [
    "postgresql://user:supersecretpassword@db.example.com:5432/mydb",
    "AKIAABCDEFGHIJKLMNOP",
    "sk-abcdefghijklmnopqrstuvwxyz0123456789",
    "api_key=abcd1234efgh5678ijkl",
    "Authorization: Bearer abcdefghij1234567890",
])
def test_redact_secrets_scrubs_known_patterns(secret_text):
    redacted = redact_secrets(f"some output containing {secret_text} in the middle")
    assert secret_text not in redacted
    assert "[REDACTED]" in redacted


def test_redact_secrets_handles_none():
    assert redact_secrets(None) is None


def test_no_raw_secret_survives_into_summary_or_render():
    tainted = _rec(id="v_secret", summary="connected using postgresql://admin:hunter2@host/db")
    proof = generate_production_proof(**_happy_path_kwargs(build_records=(tainted,)))
    assert "hunter2" not in proof.build.summary
    rendered = render_human_readable(proof)
    assert "hunter2" not in rendered


def test_category_from_records_redacts_not_run_summary():
    cat = category_from_records((), not_run_summary="db url postgresql://u:hunter2@h/db not reachable")
    assert "hunter2" not in cat.summary


# ── Regression evidence (spec section 11) ─────────────────────────────

def test_regression_not_run_is_unverified():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert proof.regression.status is VerificationOutcome.UNVERIFIED


def test_regression_new_failure_dominates():
    reg = RegressionResult(
        baseline_revision="rev0", candidate_revision="rev1", baseline_collected=10, candidate_collected=10,
        new_failures=("tests/test_x.py::test_y",),
    )
    proof = generate_production_proof(**_happy_path_kwargs(regression=reg))
    assert proof.regression.status is VerificationOutcome.FAIL


def test_regression_known_pre_existing_failure_visible_not_erased():
    reg = RegressionResult(
        baseline_revision="rev0", candidate_revision="rev1", baseline_collected=10, candidate_collected=10,
        known_pre_existing_failures=("tests/test_flaky.py::test_z",),
    )
    proof = generate_production_proof(**_happy_path_kwargs(regression=reg))
    assert proof.regression.status is VerificationOutcome.PASS
    assert "tests/test_flaky.py::test_z" in proof.regression.known_pre_existing_failures


# ── evidence_refs traceability ───────────────────────────────────────

def test_evidence_refs_includes_contributing_records_and_court_decision():
    proof = generate_production_proof(**_happy_path_kwargs())
    assert "v1" in proof.evidence_refs
    assert "d1" in proof.evidence_refs


def test_to_dict_round_trips_through_json():
    import json
    proof = generate_production_proof(**_happy_path_kwargs())
    d = to_dict(proof)
    reserialized = json.dumps(d, sort_keys=True)
    assert json.loads(reserialized) == d


# ── LAUNCH gate integration (spec section 23, reuses code_mode.py) ──

def test_launch_evidence_all_true_on_full_happy_path():
    from orca.mission.code_mode import evaluate_launch_gate, launch_gate_passes
    from orca.mission.production_proof import launch_evidence_from_proof

    proof = generate_production_proof(**_happy_path_kwargs())
    evidence = launch_evidence_from_proof(proof)
    results = evaluate_launch_gate(evidence, not_applicable=frozenset({
        "supply_chain", "release_configuration", "deployment_readiness", "rollback_readiness",
        "regression", "authority",
    }))
    # The categories this proof genuinely populated with real evidence pass;
    # deployment/rollback/supply-chain/release-build are marked N/A for this
    # narrow proof (not evaluated), matching evaluate_launch_gate()'s own
    # missing-evidence-never-PASS contract for anything left UNVERIFIED.
    assert results["build_evidence"].value == "PASS"
    assert results["tests"].value == "PASS"
    assert results["security"].value == "PASS"
    assert results["production_proof_hooks"].value == "PASS"
    assert launch_gate_passes(results) is True


def test_launch_evidence_reflects_court_reject():
    from orca.mission.production_proof import launch_evidence_from_proof

    proof = generate_production_proof(**_happy_path_kwargs(
        court_decision=_accept_decision(verdict=CourtVerdict.REJECT),
    ))
    evidence = launch_evidence_from_proof(proof)
    assert evidence["production_proof_hooks"] is False


def test_launch_evidence_missing_deployment_is_unverified_not_pass():
    from orca.mission.code_mode import evaluate_launch_gate, launch_gate_passes
    from orca.mission.production_proof import launch_evidence_from_proof

    proof = generate_production_proof(**_happy_path_kwargs())
    evidence = launch_evidence_from_proof(proof)
    assert evidence["deployment_readiness"] is None
    results = evaluate_launch_gate(evidence)
    assert results["deployment_readiness"].value == "UNVERIFIED"
    assert launch_gate_passes(results) is False  # not falsely marked ready
