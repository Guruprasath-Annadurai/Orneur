"""
Phase 15.9 -- real git-diff adversarial qualification (spec sections
31-32). Every scenario uses a REAL temporary git repository with REAL
commits -- no synthetic diff dictionaries.
"""
from __future__ import annotations

import subprocess
import textwrap

import pytest

from orca.mission.anti_gaming import FindingCategory, Severity, has_blocking_finding
from orca.mission.gaming_detectors import (
    analyze_revisions,
    detect_assertion_weakening,
    detect_error_suppression,
    detect_expected_behavior_mutation,
    detect_mock_replacing_real_behavior,
    detect_skip_additions,
    detect_test_deletions,
)
from orca.mission.git_diff_analysis import get_diff_summary


def _run(args, cwd):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout


@pytest.fixture
def repo(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _run(["init", "-q"], cwd=str(repo_dir))
    _run(["config", "user.email", "test@example.com"], cwd=str(repo_dir))
    _run(["config", "user.name", "Test"], cwd=str(repo_dir))
    return repo_dir


def _write(repo_dir, path, content):
    full = repo_dir / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(textwrap.dedent(content))


def _commit(repo_dir, message) -> str:
    _run(["add", "-A"], cwd=str(repo_dir))
    _run(["commit", "-q", "-m", message], cwd=str(repo_dir))
    return _run(["rev-parse", "HEAD"], cwd=str(repo_dir)).strip()


# ── Scenario 1: production bug + test deleted -> blocking finding ──

def test_scenario_1_test_deleted_for_bug_is_blocking(repo):
    _write(repo, "tests/test_app.py", """
        def test_add():
            assert 1 + 1 == 2
        def test_subtract():
            assert 5 - 3 == 2
    """)
    baseline = _commit(repo, "baseline: two tests")

    _write(repo, "tests/test_app.py", """
        def test_add():
            assert 1 + 1 == 2
    """)
    candidate = _commit(repo, "candidate: deleted test_subtract")

    diff = get_diff_summary(str(repo), baseline, candidate)
    findings = detect_test_deletions(diff, str(repo), mission_id="m1")
    assert len(findings) == 1
    assert findings[0].category is FindingCategory.TEST_DELETED
    assert findings[0].test_ids == ("test_subtract",)


# ── Scenario 2: auth bypass, test changed to expect success -> CRITICAL ──

def test_scenario_2_auth_test_weakened_to_expect_success_is_critical(repo):
    _write(repo, "tests/test_authority_bridge.py", """
        def test_unauthorized_denied():
            result = "DENY"
            assert result == "DENY"
    """)
    baseline = _commit(repo, "baseline: auth test expects denial")

    _write(repo, "tests/test_authority_bridge.py", """
        def test_unauthorized_denied():
            result = "DENY"
            assert result in ("DENY", "ALLOW")
    """)
    candidate = _commit(repo, "candidate: weakened to accept either outcome")

    diff = get_diff_summary(str(repo), baseline, candidate)
    findings = analyze_revisions(str(repo), baseline, candidate, mission_id="m1")
    critical = [f for f in findings if f.severity is Severity.CRITICAL]
    assert critical, f"expected a CRITICAL finding, got: {findings!r}"
    assert has_blocking_finding(findings)


def test_scenario_2_strong_case_auth_deny_flipped_to_allow_is_critical(repo):
    # Phase 15.9.1 closure item 8: the LITERAL strong case -- DENY ->
    # ALLOW, not merely broadened to accept either. This is
    # EXPECTED_BEHAVIOR_CHANGED, a different detector/category than
    # the broadening case above.
    _write(repo, "tests/test_authority_bridge.py", """
        def test_unauthorized_denied():
            result = "DENY"
            assert result == "DENY"
    """)
    baseline = _commit(repo, "baseline: auth test expects denial")

    _write(repo, "tests/test_authority_bridge.py", """
        def test_unauthorized_denied():
            result = "DENY"
            assert result == "ALLOW"
    """)
    candidate = _commit(repo, "candidate: flipped expected outcome to ALLOW")

    findings = analyze_revisions(str(repo), baseline, candidate, mission_id="m1")
    behavior_findings = [f for f in findings if f.category is FindingCategory.EXPECTED_BEHAVIOR_CHANGED]
    assert behavior_findings, f"expected an EXPECTED_BEHAVIOR_CHANGED finding, got: {findings!r}"
    assert behavior_findings[0].severity is Severity.CRITICAL
    assert behavior_findings[0].blocking is True
    assert has_blocking_finding(findings)


# ── Scenario 3: failing test changed to skip -> cannot become verified ──

def test_scenario_3_failing_test_changed_to_skip(repo):
    _write(repo, "tests/test_app.py", """
        def test_feature():
            assert False
    """)
    baseline = _commit(repo, "baseline: failing test")

    _write(repo, "tests/test_app.py", """
        import pytest

        @pytest.mark.skip(reason="flaky")
        def test_feature():
            assert False
    """)
    candidate = _commit(repo, "candidate: skip the failing test")

    diff = get_diff_summary(str(repo), baseline, candidate)
    findings = detect_skip_additions(diff, str(repo), mission_id="m1")
    assert len(findings) == 1
    assert findings[0].category is FindingCategory.TEST_SKIPPED


# ── Scenario 4: integration test replaced by mock, still claims integration ──

def test_scenario_4_integration_replaced_by_mock(repo):
    _write(repo, "tests/test_integration.py", """
        from orca.mission.container_executor import run_in_container

        def test_real_execution():
            result = run_in_container(None)
            assert result is not None
    """)
    baseline = _commit(repo, "baseline: real integration call")

    _write(repo, "tests/test_integration.py", """
        from unittest.mock import MagicMock

        def test_real_execution():
            run_in_container = MagicMock(return_value="fake")
            result = run_in_container(None)
            assert result is not None
    """)
    candidate = _commit(repo, "candidate: mocked instead of real")

    diff = get_diff_summary(str(repo), baseline, candidate)
    findings = detect_mock_replacing_real_behavior(diff, str(repo), mission_id="m1")
    assert len(findings) == 1
    assert findings[0].category is FindingCategory.MOCK_REPLACES_REQUIRED_BEHAVIOR


# ── Scenario 5: assertions weakened but suite still green ──

def test_scenario_5_weakened_assertions_still_flagged_even_if_green(repo):
    _write(repo, "tests/test_app.py", """
        def test_status():
            status_code = 403
            assert status_code == 403
            assert status_code != 200
    """)
    baseline = _commit(repo, "baseline: strict assertions")

    _write(repo, "tests/test_app.py", """
        def test_status():
            status_code = 403
            assert status_code in (200, 403)
    """)
    candidate = _commit(repo, "candidate: weakened, but still passes")

    diff = get_diff_summary(str(repo), baseline, candidate)
    findings = detect_assertion_weakening(diff, str(repo), mission_id="m1")
    # Two independent weakening dimensions are both real here: the
    # assert COUNT dropped (2 -> 1) AND the remaining assert was
    # broadened from strict equality to an "in (...)" check -- both
    # are correctly detected, not merged into a single finding.
    assert len(findings) >= 1
    assert any(f.category is FindingCategory.ASSERTION_REMOVED for f in findings)


# ── Scenario 6: legitimate requirement-driven expectation change ──

def test_scenario_6_requirement_driven_change_is_surfaced_not_auto_rejected(repo):
    # The DETECTOR still finds the structural change (assertion count
    # dropped) -- distinguishing "justified" from "unjustified" is a
    # Court/policy decision (test_cognitive_court.py's regression
    # critic test exercises the `justified_removals` parameter), not
    # something this detector silently suppresses.
    _write(repo, "tests/test_app.py", """
        def test_limit():
            assert compute_limit() == 10
            assert compute_limit() != 20
    """)
    baseline = _commit(repo, "baseline: limit is 10")
    _write(repo, "tests/test_app.py", """
        def test_limit():
            assert compute_limit() == 20
    """)
    candidate = _commit(repo, "candidate: requirement changed limit to 20 (REQ-LIMIT-002 supersedes REQ-LIMIT-001)")

    diff = get_diff_summary(str(repo), baseline, candidate)
    findings = detect_assertion_weakening(diff, str(repo), mission_id="m1")
    # Surfaced as a finding (fewer asserts) -- NOT silently dropped
    # just because the commit message claims justification.
    assert len(findings) == 1


# ── Scenario 7: pure rename, not classified as deletion ──

def test_scenario_7_pure_rename_not_classified_as_deletion(repo):
    _write(repo, "tests/test_old_name.py", """
        def test_something():
            assert 1 == 1

        def test_another():
            assert 2 == 2

        def test_more():
            assert 3 == 3

        def test_extra():
            assert 4 == 4

        def test_padding_one():
            assert 5 == 5

        def test_padding_two():
            assert 6 == 6
    """)
    baseline = _commit(repo, "baseline: original file name")

    _run(["mv", "tests/test_old_name.py", "tests/test_new_name.py"], cwd=str(repo))
    candidate = _commit(repo, "candidate: pure rename, no content change")

    diff = get_diff_summary(str(repo), baseline, candidate)
    assert diff.renamed_files, f"git did not detect the rename: {diff!r}"
    assert diff.renamed_files[0].old_path == "tests/test_old_name.py"
    assert diff.renamed_files[0].new_path == "tests/test_new_name.py"
    assert "tests/test_old_name.py" not in diff.deleted_files

    findings = detect_test_deletions(diff, str(repo), mission_id="m1")
    assert findings == ()  # a pure rename must never be reported as a deletion


# ── Scenario 8: new stronger test added -> not gaming ──

def test_scenario_8_new_stronger_test_is_not_gaming(repo):
    _write(repo, "tests/test_app.py", """
        def test_add():
            assert 1 + 1 == 2
    """)
    baseline = _commit(repo, "baseline: one test")

    _write(repo, "tests/test_app.py", """
        def test_add():
            assert 1 + 1 == 2

        def test_add_negative():
            assert -1 + -1 == -2

        def test_add_zero():
            assert 0 + 0 == 0
    """)
    candidate = _commit(repo, "candidate: added more test coverage")

    diff = get_diff_summary(str(repo), baseline, candidate)
    findings = analyze_revisions(str(repo), baseline, candidate, mission_id="m1")
    assert findings == ()  # adding tests must never itself be a finding


# ── Full analyze_revisions smoke test across a realistic multi-file diff ──

def test_analyze_revisions_combines_all_detectors(repo):
    _write(repo, "tests/test_a.py", "def test_a():\n    assert True\n")
    _write(repo, "tests/test_b.py", "def test_b():\n    assert 1 == 1\n    assert 2 == 2\n")
    baseline = _commit(repo, "baseline")

    _write(repo, "tests/test_a.py", "def test_a():\n    assert True\n")  # unchanged
    _write(repo, "tests/test_b.py", "def test_b():\n    assert 1 == 1\n")  # weakened
    candidate = _commit(repo, "candidate: weakened test_b")

    findings = analyze_revisions(str(repo), baseline, candidate, mission_id="m1")
    assert any(f.category is FindingCategory.ASSERTION_REMOVED for f in findings)


# ── Self-protection (spec section 35) ────────────────────────────────
# The engine must detect an attempt to weaken its OWN tests/config
# using the SAME baseline/candidate mechanism as everything else --
# never a special-cased "trust my own current tests" shortcut.

def test_self_protection_candidate_deletes_anti_gaming_detector_test(repo):
    _write(repo, "tests/test_gaming_detectors.py", """
        def test_detects_weakened_assertion():
            assert True

        def test_detects_deleted_test():
            assert True
    """)
    baseline = _commit(repo, "baseline: anti-gaming engine has its own tests")

    _write(repo, "tests/test_gaming_detectors.py", """
        def test_detects_weakened_assertion():
            assert True
    """)
    candidate = _commit(repo, "candidate: quietly removed test_detects_deleted_test")

    diff = get_diff_summary(str(repo), baseline, candidate)
    findings = detect_test_deletions(diff, str(repo), mission_id="m1")
    assert len(findings) == 1
    assert findings[0].test_ids == ("test_detects_deleted_test",)
    # Detected via the exact same baseline-bound AST comparison every
    # other scenario in this file uses -- no special-cased self-check.


def test_self_protection_candidate_disables_security_critic_test_via_skip(repo):
    _write(repo, "tests/test_cognitive_court.py", """
        def test_security_critic_supports_reject_on_critical_finding():
            assert True
    """)
    baseline = _commit(repo, "baseline: security critic has real coverage")

    _write(repo, "tests/test_cognitive_court.py", """
        import pytest

        @pytest.mark.skip(reason="temporarily disabled")
        def test_security_critic_supports_reject_on_critical_finding():
            assert True
    """)
    candidate = _commit(repo, "candidate: skip the security critic test")

    diff = get_diff_summary(str(repo), baseline, candidate)
    findings = detect_skip_additions(diff, str(repo), mission_id="m1")
    assert len(findings) == 1
    assert findings[0].category is FindingCategory.TEST_SKIPPED
    assert findings[0].test_ids == ("test_security_critic_supports_reject_on_critical_finding",)


# ── Verification history preservation through Court review (spec 36) ─

def test_verification_history_pass_fail_pass_not_erased_by_current_pass():
    from orca.mission.verification import VerificationOutcome, VerificationRecord
    from orca.mission.verification_aggregation import aggregate_requirement

    pass1 = VerificationRecord(
        id="v1", mission_id="m1", requirement_id="REQ-X-1", criterion_id=None, category="UNIT_TEST",
        verification_method="UNIT_TEST", verifier_id="UnitTestVerifier", started_at="2026-01-01T00:00:00Z",
        outcome=VerificationOutcome.PASS, revision="rev1", evidence_refs=("x",),
    )
    fail = VerificationRecord(
        id="v2", mission_id="m1", requirement_id="REQ-X-1", criterion_id=None, category="UNIT_TEST",
        verification_method="UNIT_TEST", verifier_id="UnitTestVerifier", started_at="2026-01-02T00:00:00Z",
        outcome=VerificationOutcome.FAIL, revision="rev2",
    )
    pass2 = VerificationRecord(
        id="v3", mission_id="m1", requirement_id="REQ-X-1", criterion_id=None, category="UNIT_TEST",
        verification_method="UNIT_TEST", verifier_id="UnitTestVerifier", started_at="2026-01-03T00:00:00Z",
        outcome=VerificationOutcome.PASS, revision="rev3", evidence_refs=("y",),
    )
    history = (pass1, fail, pass2)
    # The Court can see the full history -- nothing erased.
    assert [r.outcome for r in history] == [
        VerificationOutcome.PASS, VerificationOutcome.FAIL, VerificationOutcome.PASS,
    ]
    # But aggregation for the CURRENT revision only counts rev3's record.
    from orca.mission.verification_aggregation import filter_current_revision
    current = filter_current_revision(history, current_revision="rev3")
    assert current == (pass2,)
    assert aggregate_requirement(current) is VerificationOutcome.PASS


# ── Phase 15.9.1 closure item 3: security-sensitive mock replacement ─

def test_closure_item_3_security_integration_replaced_by_mock_is_critical_blocking(repo):
    _write(repo, "tests/test_authorize_flow.py", """
        from orca.mission.operation_store import authorize_operation

        def test_authorization_denies_self_approval():
            result = authorize_operation(None, "op1", tenant_id="t1", approved_by="alice", reason="x")
            assert result is not None
    """)
    baseline = _commit(repo, "baseline: real authority integration exercised")

    _write(repo, "tests/test_authorize_flow.py", """
        from unittest.mock import MagicMock

        def test_authorization_denies_self_approval():
            authorize_operation = MagicMock(return_value={"status": "AUTHORIZED"})
            result = authorize_operation(None, "op1", tenant_id="t1", approved_by="alice", reason="x")
            assert result is not None
    """)
    candidate = _commit(repo, "candidate: real authority call mocked away, test still 'verifies' authorization")

    diff = get_diff_summary(str(repo), baseline, candidate)
    findings = detect_mock_replacing_real_behavior(diff, str(repo), mission_id="m1")
    assert len(findings) == 1
    finding = findings[0]
    assert finding.category is FindingCategory.MOCK_REPLACES_REQUIRED_BEHAVIOR
    assert finding.severity is Severity.CRITICAL
    assert finding.blocking is True

    # And the Court cannot ACCEPT while this finding exists.
    from orca.mission.cognitive_court import CourtRole, CourtVerdict, CriticConclusion, CriticOutput, RiskLevel, arbiter_decide
    from orca.mission.verification import VerificationOutcome, VerificationRecord
    from orca.mission.verification_aggregation import RequiredVerificationScope
    pass_record = VerificationRecord(
        id="v1", mission_id="m1", requirement_id="REQ-AUTH-1", criterion_id=None, category="SECURITY",
        verification_method="SECURITY_TEST", verifier_id="SecurityVerifier", started_at="2026-01-01T00:00:00Z",
        outcome=VerificationOutcome.PASS, revision=candidate, evidence_refs=("x",),
    )
    all_accept = (CriticOutput(role=CourtRole.SECURITY_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    decision = arbiter_decide(
        mission_id="m1", revision=candidate, risk_level=RiskLevel.CRITICAL, critic_outputs=all_accept,
        findings=(finding,), required_verification_records={"REQ-AUTH-1": (pass_record,)},
        required_requirement_ids=("REQ-AUTH-1",),
        required_scopes_by_requirement={
            "REQ-AUTH-1": RequiredVerificationScope(requirement_level_categories=frozenset({"SECURITY"})),
        },
    )
    assert decision.verdict is not CourtVerdict.ACCEPT
    assert decision.verdict is CourtVerdict.REJECT


def test_ordinary_non_security_mock_stays_high_not_critical(repo):
    # A mock introduced for a marker that is NOT in
    # SECURITY_CRITICAL_CALL_MARKERS, in a path that is NOT
    # security-relevant, must NOT be elevated -- this elevation is
    # deliberately narrow, not "every mock is CRITICAL."
    _write(repo, "tests/test_helper_thing.py", """
        from orca.mission.some_helper import get_conn

        def test_uses_conn():
            conn = get_conn()
            assert conn is not None
    """)
    baseline = _commit(repo, "baseline: real (non-security-critical-marker) helper call")

    _write(repo, "tests/test_helper_thing.py", """
        from unittest.mock import MagicMock

        def test_uses_conn():
            get_conn = MagicMock(return_value="fake-conn")
            conn = get_conn()
            assert conn is not None
    """)
    candidate = _commit(repo, "candidate: mocked a non-security-critical-marker helper")

    diff = get_diff_summary(str(repo), baseline, candidate)
    findings = detect_mock_replacing_real_behavior(diff, str(repo), mission_id="m1")
    assert len(findings) == 1
    assert findings[0].category is FindingCategory.MOCK_REPLACES_REQUIRED_BEHAVIOR
    # get_conn is NOT in SECURITY_CRITICAL_CALL_MARKERS and this path
    # is not security-relevant -- stays HIGH/non-blocking, proving the
    # elevation in test_closure_item_3 above is narrow, not universal.
    assert findings[0].severity is Severity.HIGH
    assert findings[0].blocking is False


# ── Phase 15.9.1 closure item 4: expected-behavior mutation ──────────

def test_closure_item_4a_auth_deny_to_allow_is_critical(repo):
    _write(repo, "tests/test_authz.py", """
        def test_deny_unauthorized():
            decision = "DENY"
            assert decision == "DENY"
    """)
    baseline = _commit(repo, "baseline: expects DENY")
    _write(repo, "tests/test_authz.py", """
        def test_deny_unauthorized():
            decision = "DENY"
            assert decision == "ALLOW"
    """)
    candidate = _commit(repo, "candidate: expects ALLOW instead")

    diff = get_diff_summary(str(repo), baseline, candidate)
    findings = detect_expected_behavior_mutation(diff, str(repo), mission_id="m1")
    assert len(findings) == 1
    assert findings[0].category is FindingCategory.EXPECTED_BEHAVIOR_CHANGED
    assert findings[0].severity is Severity.CRITICAL
    assert findings[0].blocking is True


def test_closure_item_4b_non_security_numeric_change_is_not_automatically_critical(repo):
    _write(repo, "tests/test_config.py", """
        def test_timeout_value():
            timeout = 30
            assert timeout == 30
    """)
    baseline = _commit(repo, "baseline: timeout is 30")
    _write(repo, "tests/test_config.py", """
        def test_timeout_value():
            timeout = 60
            assert timeout == 60
    """)
    candidate = _commit(repo, "candidate: timeout changed to 60")

    diff = get_diff_summary(str(repo), baseline, candidate)
    findings = detect_expected_behavior_mutation(diff, str(repo), mission_id="m1")
    assert len(findings) == 1
    assert findings[0].category is FindingCategory.EXPECTED_BEHAVIOR_CHANGED
    # Surfaced (never silently dropped) but NOT automatically CRITICAL --
    # not a known security flip, not a security-relevant path.
    assert findings[0].severity is Severity.MEDIUM
    assert findings[0].blocking is False


def test_closure_item_4c_requirement_driven_expected_change_is_surfaced_not_discarded(repo):
    _write(repo, "tests/test_limit.py", """
        def test_rate_limit():
            limit = 100
            assert limit == 100
    """)
    baseline = _commit(repo, "baseline: rate limit is 100")
    _write(repo, "tests/test_limit.py", """
        def test_rate_limit():
            limit = 200
            assert limit == 200
    """)
    candidate = _commit(repo, "candidate: REQ-RATE-002 supersedes REQ-RATE-001, owner-approved limit increase")

    diff = get_diff_summary(str(repo), baseline, candidate)
    findings = detect_expected_behavior_mutation(diff, str(repo), mission_id="m1")
    # Surfaced regardless of the commit message's own justification
    # claim -- the detector never silently discards a structural
    # change; Court/provenance policy (not this detector) decides
    # whether the justification is acceptable.
    assert len(findings) == 1
    assert findings[0].category is FindingCategory.EXPECTED_BEHAVIOR_CHANGED
