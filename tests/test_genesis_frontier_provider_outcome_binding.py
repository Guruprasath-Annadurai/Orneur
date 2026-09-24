"""Phase 21B.4.19.2: provider-resolution OUTCOME-BOUND DEPENDENCY closure.

CONTROL-PLANE TESTS ONLY -- no provider was contacted, no account touched,
no API called. The defect: a dependency counted as satisfied when its
upstream action was merely RESOLVED, but RESOLVED only proves the provider
interaction concluded -- a definitive provider "NO" is valid, conclusive
evidence that must still not unlock a conditional downstream action.

Canonical rule proven here:  RESOLVED != PREREQUISITE_SATISFIED.

A dependency now satisfies a dependent only if it is RESOLVED, its verified
evidence re-proves, it carries a durable hash-verified resolution
assessment (EVIDENCE_REVIEWER) with outcome PREREQUISITE_SATISFIED, and
every fact THIS dependent requires is established.

Every record below is a SYNTHETIC TEST FIXTURE living only in pytest's
tmp_path. None is evidence, none is written into the repository, and no
real queue action is ever authorized, executed, resolved or assessed.
"""

import copy
import json
from pathlib import Path

import pytest

from orca.eval.candidate_registry import CandidateExecutionRegistry
from orca.eval.frontier_provider_resolution import (
    ACTION_FACT_CODES,
    CONTRADICTORY_FACT_GROUPS,
    DEPENDENCY_REQUIREMENTS,
    FACT_REQUIRED_QUESTIONS,
    RESOLUTION_OUTCOMES,
    UNLOCK_FACTS,
    ProviderResolutionError,
    advance_action_state,
    assert_queue_fully_unauthorized,
    assess_action_resolution,
    build_action_lookup,
    close_unavailable_branch,
    review_record_bytes,
    validate_action,
    validate_action_queue,
    validate_resolution_assessment,
)
from orca.eval.frontier_reference_admission_quorum import compute_admission_quorum
from tests.test_genesis_frontier_provider_authority_binding import (
    _account_record,
    _action,
    _assess,
    _auth,
    _drive,
    _exec_evidence,
    _family_questions,
    _provider_record,
    _to_awaiting,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CANDIDATE_EXECUTION_REGISTRY.json"
QUEUE_PATH = REPO_ROOT / "docs/orneur/phase-21/evidence/GENESIS_FRONTIER_PROVIDER_ACTION_QUEUE_2026-09-24.json"
SCHEMA_PATH = REPO_ROOT / "docs/orneur/phase-21/evidence/GENESIS_FRONTIER_PROVIDER_RESPONSE_SCHEMA_2026-09-24.json"

SAT = "PREREQUISITE_SATISFIED"
NOT_SAT = "PREREQUISITE_NOT_SATISFIED"
PARTIAL = "PARTIAL_INFORMATION"


@pytest.fixture(scope="module")
def registry():
    return CandidateExecutionRegistry.load(REGISTRY_PATH)


@pytest.fixture(scope="module")
def queue():
    return json.loads(QUEUE_PATH.read_text())


def _resolved(queue, tmp_path, action_id, facts, outcome):
    """SYNTHETIC: an upstream action driven to RESOLVED and assessed."""
    return _drive(_action(queue, action_id), "RESOLVED", tmp_path, facts=facts, outcome=outcome)


def _authorize(queue, tmp_path, dependent, deps):
    """Attempt to authorize `dependent` given a dependency context."""
    action = _to_awaiting(_action(queue, dependent))
    return advance_action_state(action, "AUTHORIZED_NOT_EXECUTED", authorization_evidence=_auth(dependent),
                                evidence_root=tmp_path, dependency_actions=deps)


DSK01_BOTH = ["DEEPSEEK_API_OPTOUT_APPLICABLE", "DEEPSEEK_API_OPTOUT_PROSPECTIVE"]
DSK02_PRESENT = ["DEEPSEEK_ACCOUNT_SETTING_PRESENT"]


# ══ §26: the central regression -- RESOLVED alone is NOT enough ══════════


@pytest.mark.parametrize("dependent", ["MIS-02", "MIS-03", "DSK-03", "GLM-02", "MNX-02", "KMI-02"])
def test_RESOLVED_without_assessment_never_satisfies_any_dependency(queue, tmp_path, dependent):
    deps = {dep: _drive(_action(queue, dep), "RESOLVED", tmp_path, assess=False)
            for dep in DEPENDENCY_REQUIREMENTS[dependent]}
    for dep in deps.values():
        assert dep["state"] == "RESOLVED" and dep["resolution_assessment"] is None
    with pytest.raises(ProviderResolutionError, match=r"RESOLVED != PREREQUISITE_SATISFIED"):
        _authorize(queue, tmp_path, dependent, deps)


def test_outcome_that_does_not_allow_followup_never_unlocks(queue, tmp_path):
    # every required fact present but outcome is only PARTIAL_INFORMATION
    partial = _resolved(queue, tmp_path, "MIS-01", ["MISTRAL_API_TRAINING_OPTOUT_APPLICABLE"], PARTIAL)
    assert partial["state"] == "RESOLVED" and partial["resolution_outcome"] == PARTIAL
    with pytest.raises(ProviderResolutionError, match="does not allow follow-up"):
        _authorize(queue, tmp_path, "MIS-02", {"MIS-01": partial})


def test_lifecycle_state_and_outcome_are_separate(queue, tmp_path):
    negative = _resolved(queue, tmp_path, "MIS-01", ["MISTRAL_API_TRAINING_OPTOUT_NOT_APPLICABLE"], NOT_SAT)
    assert negative["state"] == "RESOLVED"  # the provider question WAS answered
    assert negative["resolution_outcome"] == NOT_SAT  # ...but nothing downstream unlocks
    validate_action(negative, evidence_root=tmp_path)


# ══ §22: DeepSeek ════════════════════════════════════════════════════════


def test_DSK_A_negative_optout_answer_resolves_DSK01_but_does_not_unlock_DSK03(queue, tmp_path):
    negative = _resolved(queue, tmp_path, "DSK-01", ["DEEPSEEK_API_OPTOUT_NOT_APPLICABLE"], NOT_SAT)
    lacking = _resolved(queue, tmp_path, "DSK-01", [], NOT_SAT)  # simply lacks the positive facts
    dsk02 = _resolved(queue, tmp_path, "DSK-02", DSK02_PRESENT, SAT)
    for dsk01 in (negative, lacking):
        assert dsk01["state"] == "RESOLVED"
        with pytest.raises(ProviderResolutionError, match="does not allow follow-up"):
            _authorize(queue, tmp_path, "DSK-03", {"DSK-01": dsk01, "DSK-02": dsk02})


def test_DSK_B_positive_optout_but_no_account_setting_does_not_unlock_DSK03(queue, tmp_path):
    dsk01 = _resolved(queue, tmp_path, "DSK-01", DSK01_BOTH, SAT)
    dsk02_absent = _resolved(queue, tmp_path, "DSK-02", ["DEEPSEEK_ACCOUNT_SETTING_ABSENT"], NOT_SAT)
    with pytest.raises(ProviderResolutionError, match="'DSK-02'"):
        _authorize(queue, tmp_path, "DSK-03", {"DSK-01": dsk01, "DSK-02": dsk02_absent})


def test_DSK_only_one_of_the_two_required_DSK01_facts_is_not_enough(queue, tmp_path):
    only_applicable = _resolved(queue, tmp_path, "DSK-01", ["DEEPSEEK_API_OPTOUT_APPLICABLE"], SAT)
    dsk02 = _resolved(queue, tmp_path, "DSK-02", DSK02_PRESENT, SAT)
    with pytest.raises(ProviderResolutionError, match="did not establish required fact"):
        _authorize(queue, tmp_path, "DSK-03", {"DSK-01": only_applicable, "DSK-02": dsk02})


def test_DSK_C_both_positive_facts_allow_DSK03_with_independent_owner_authorization(queue, tmp_path):
    deps = {"DSK-01": _resolved(queue, tmp_path, "DSK-01", DSK01_BOTH, SAT),
            "DSK-02": _resolved(queue, tmp_path, "DSK-02", DSK02_PRESENT, SAT)}
    authorized = _authorize(queue, tmp_path, "DSK-03", deps)
    assert authorized["state"] == "AUTHORIZED_NOT_EXECUTED"
    # the dependencies' own authorizations never substitute for DSK-03's
    for wrong in ("DSK-01", "DSK-02"):
        with pytest.raises(ProviderResolutionError, match="exactly one action"):
            advance_action_state(_to_awaiting(_action(queue, "DSK-03")), "AUTHORIZED_NOT_EXECUTED",
                                 authorization_evidence=_auth(wrong), evidence_root=tmp_path, dependency_actions=deps)
    # the gate is re-checked at execution time as well
    executed = advance_action_state(authorized, "EXECUTED_AWAITING_PROVIDER", execution_evidence=_exec_evidence(authorized),
                                    evidence_root=tmp_path, dependency_actions=deps)
    assert executed["executed_status"] == "EXECUTED"
    regressed = dict(deps, **{"DSK-02": _resolved(queue, tmp_path, "DSK-02", ["DEEPSEEK_ACCOUNT_SETTING_ABSENT"], NOT_SAT)})
    with pytest.raises(ProviderResolutionError, match="'DSK-02'"):
        advance_action_state(authorized, "EXECUTED_AWAITING_PROVIDER", execution_evidence=_exec_evidence(authorized),
                             evidence_root=tmp_path, dependency_actions=regressed)


# ══ §23/§17: MiniMax ═════════════════════════════════════════════════════


def test_MNX_does_not_apply_never_unlocks_MNX02_and_closes_the_branch(queue, tmp_path):
    mnx01 = _resolved(queue, tmp_path, "MNX-01", ["MINIMAX_COMMERCIAL_USE_DOES_NOT_APPLY"], NOT_SAT)
    with pytest.raises(ProviderResolutionError, match="does not allow follow-up"):
        _authorize(queue, tmp_path, "MNX-02", {"MNX-01": mnx01})
    closed = close_unavailable_branch(_action(queue, "MNX-02"), dependency_actions={"MNX-01": mnx01}, evidence_root=tmp_path)
    assert closed["state"] == "NOT_REQUIRED"
    for state in ("AWAITING_OWNER_AUTHORIZATION", "AUTHORIZED_NOT_EXECUTED", "EXECUTED_AWAITING_PROVIDER", "PREPARED"):
        with pytest.raises(ProviderResolutionError, match="not permitted"):
            advance_action_state(closed, state, authorization_evidence=_auth("MNX-02"), evidence_root=tmp_path,
                                 dependency_actions={"MNX-01": mnx01})
    assert mnx01["state"] == "RESOLVED"  # the upstream question stays answered


def test_MNX_commercial_use_applies_unlocks_MNX02_on_a_synthetic_fixture(queue, tmp_path):
    mnx01 = _resolved(queue, tmp_path, "MNX-01", ["MINIMAX_COMMERCIAL_USE_APPLIES"], SAT)
    assert _authorize(queue, tmp_path, "MNX-02", {"MNX-01": mnx01})["state"] == "AUTHORIZED_NOT_EXECUTED"
    with pytest.raises(ProviderResolutionError, match="no dependency has definitively closed"):
        close_unavailable_branch(_action(queue, "MNX-02"), dependency_actions={"MNX-01": mnx01}, evidence_root=tmp_path)


@pytest.mark.parametrize("outcome", [NOT_SAT, PARTIAL])
def test_MNX_still_ambiguous_neither_unlocks_nor_closes(queue, tmp_path, outcome):
    mnx01 = _resolved(queue, tmp_path, "MNX-01", ["MINIMAX_COMMERCIAL_USE_STILL_AMBIGUOUS"], outcome)
    with pytest.raises(ProviderResolutionError):
        _authorize(queue, tmp_path, "MNX-02", {"MNX-01": mnx01})
    with pytest.raises(ProviderResolutionError, match="no dependency has definitively closed"):
        close_unavailable_branch(_action(queue, "MNX-02"), dependency_actions={"MNX-01": mnx01}, evidence_root=tmp_path)


def test_MNX_conclusions_are_mutually_exclusive_and_need_MNX_Q1(queue, tmp_path):
    action = _drive(_action(queue, "MNX-01"), "RESOLVED", tmp_path, assess=False)
    record = _provider_record(tmp_path, "MiniMax", "MiniMax M3", question_ids=_family_questions("MiniMax"))
    both = sorted(["MINIMAX_COMMERCIAL_USE_APPLIES", "MINIMAX_COMMERCIAL_USE_DOES_NOT_APPLY"])
    (tmp_path / "review_MNX-01.json").write_bytes(review_record_bytes(
        action_id="MNX-01", provider="MiniMax", reference_name="MiniMax M3", outcome=SAT, facts_established=both,
        questions_addressed=["MNX-Q1"], verified_evidence_ref=action["verified_evidence_ref"],
        assessed_by_role="EVIDENCE_REVIEWER", assessed_at_utc="2000-01-04T00:00:00Z"))
    with pytest.raises(ProviderResolutionError, match="contradictory/mutually-exclusive"):
        assess_action_resolution(action, outcome=SAT, facts_established=both, questions_addressed=["MNX-Q1"],
                                 assessed_at_utc="2000-01-04T00:00:00Z", assessment_source_ref="review_MNX-01.json",
                                 evidence_root=tmp_path, provider_evidence_record=record)
    # MNX-Q2 alone (hosted-API terms) can never establish a Commercial Use conclusion
    with pytest.raises(ProviderResolutionError, match=r"requires question\(s\) \['MNX-Q1'\]"):
        assess_action_resolution(action, outcome=SAT, facts_established=["MINIMAX_COMMERCIAL_USE_APPLIES"],
                                 questions_addressed=["MNX-Q2"], assessed_at_utc="2000-01-04T00:00:00Z",
                                 assessment_source_ref="review_MNX-01.json", evidence_root=tmp_path,
                                 provider_evidence_record=record)


# ══ §24/§18: Kimi ════════════════════════════════════════════════════════


def test_KMI_no_enterprise_path_never_unlocks_KMI02_and_closes_the_branch(queue, tmp_path):
    kmi01 = _resolved(queue, tmp_path, "KMI-01", ["KIMI_ENTERPRISE_NO_TRAINING_PATH_NOT_AVAILABLE"], NOT_SAT)
    with pytest.raises(ProviderResolutionError, match="does not allow follow-up"):
        _authorize(queue, tmp_path, "KMI-02", {"KMI-01": kmi01})
    assert close_unavailable_branch(_action(queue, "KMI-02"), dependency_actions={"KMI-01": kmi01},
                                    evidence_root=tmp_path)["state"] == "NOT_REQUIRED"


def test_KMI_positive_acceptable_path_fact_unlocks_synthetically(queue, tmp_path):
    kmi01 = _resolved(queue, tmp_path, "KMI-01", ["KIMI_ACCEPTABLE_ENTERPRISE_NO_TRAINING_PATH_AVAILABLE"], SAT)
    assert _authorize(queue, tmp_path, "KMI-02", {"KMI-01": kmi01})["state"] == "AUTHORIZED_NOT_EXECUTED"


def test_KMI_an_unrelated_or_partial_answer_cannot_establish_an_acceptable_path(queue, tmp_path):
    action = _drive(_action(queue, "KMI-01"), "RESOLVED", tmp_path, assess=False)
    record = _provider_record(tmp_path, "Moonshot AI", "Kimi K3", question_ids=_family_questions("Moonshot AI"))
    fact = ["KIMI_ACCEPTABLE_ENTERPRISE_NO_TRAINING_PATH_AVAILABLE"]
    for answered in (["KMI-Q8"], ["KMI-Q1", "KMI-Q2", "KMI-Q3"]):  # pricing-only; only part of the terms
        with pytest.raises(ProviderResolutionError, match="requires question"):
            assess_action_resolution(action, outcome=SAT, facts_established=fact, questions_addressed=answered,
                                     assessed_at_utc="2000-01-04T00:00:00Z", assessment_source_ref="review_KMI-01.json",
                                     evidence_root=tmp_path, provider_evidence_record=record)


# ══ §25/§20/§21: Mistral and GLM ═════════════════════════════════════════


def test_MIS_negative_control_availability_resolves_but_does_not_unlock_the_setting_actions(queue, tmp_path):
    negative = _resolved(queue, tmp_path, "MIS-01",
                         ["MISTRAL_API_TRAINING_OPTOUT_NOT_APPLICABLE", "MISTRAL_ZDR_NOT_APPLICABLE"], NOT_SAT)
    for dependent in ("MIS-02", "MIS-03"):
        with pytest.raises(ProviderResolutionError, match="does not allow follow-up"):
            _authorize(queue, tmp_path, dependent, {"MIS-01": negative})
        assert close_unavailable_branch(_action(queue, dependent), dependency_actions={"MIS-01": negative},
                                        evidence_root=tmp_path)["state"] == "NOT_REQUIRED"


def test_MIS_each_setting_action_needs_its_own_positive_fact(queue, tmp_path):
    optout_only = _resolved(queue, tmp_path, "MIS-01",
                            ["MISTRAL_API_TRAINING_OPTOUT_APPLICABLE", "MISTRAL_ZDR_NOT_APPLICABLE"], SAT)
    assert _authorize(queue, tmp_path, "MIS-02", {"MIS-01": optout_only})["state"] == "AUTHORIZED_NOT_EXECUTED"
    with pytest.raises(ProviderResolutionError, match=r"did not establish required fact\(s\) \['MISTRAL_ZDR_APPLICABLE'\]"):
        _authorize(queue, tmp_path, "MIS-03", {"MIS-01": optout_only})
    zdr_only = _resolved(queue, tmp_path, "MIS-01",
                         ["MISTRAL_API_TRAINING_OPTOUT_NOT_APPLICABLE", "MISTRAL_ZDR_APPLICABLE"], SAT)
    assert _authorize(queue, tmp_path, "MIS-03", {"MIS-01": zdr_only})["state"] == "AUTHORIZED_NOT_EXECUTED"
    with pytest.raises(ProviderResolutionError, match="did not establish required fact"):
        _authorize(queue, tmp_path, "MIS-02", {"MIS-01": zdr_only})


def test_MIS_automated_evaluation_permission_alone_unlocks_neither_setting(queue, tmp_path):
    only_eval = _resolved(queue, tmp_path, "MIS-01", ["MISTRAL_AUTOMATED_EVALUATION_PERMITTED"], NOT_SAT)
    for dependent in ("MIS-02", "MIS-03"):
        with pytest.raises(ProviderResolutionError):
            _authorize(queue, tmp_path, dependent, {"MIS-01": only_eval})


def test_GLM_negative_or_inapplicable_control_never_unlocks_GLM02(queue, tmp_path):
    for facts, outcome in (
        (["GLM_NO_TRAINING_CONTROL_NOT_AVAILABLE"], NOT_SAT),
        (["GLM_NO_TRAINING_CONTROL_AVAILABLE", "GLM_NO_TRAINING_CONTROL_DOES_NOT_APPLY_TO_GLM_5_3"], SAT),
        (["GLM_NO_TRAINING_CONTROL_AVAILABLE"], SAT),  # exists, but applicability to GLM-5.3 unproven
    ):
        glm01 = _resolved(queue, tmp_path, "GLM-01", facts, outcome)
        with pytest.raises(ProviderResolutionError):
            _authorize(queue, tmp_path, "GLM-02", {"GLM-01": glm01})


def test_GLM_positive_applicable_control_facts_allow_synthetic_authorization(queue, tmp_path):
    glm01 = _resolved(queue, tmp_path, "GLM-01",
                      ["GLM_NO_TRAINING_CONTROL_AVAILABLE", "GLM_NO_TRAINING_CONTROL_APPLIES_TO_GLM_5_3"], SAT)
    assert _authorize(queue, tmp_path, "GLM-02", {"GLM-01": glm01})["state"] == "AUTHORIZED_NOT_EXECUTED"


# ══ §10-§12: gate strictness ═════════════════════════════════════════════


def test_partial_provider_response_records_only_the_facts_actually_established(queue, tmp_path):
    partial = _resolved(queue, tmp_path, "DSK-01", ["DEEPSEEK_API_OPTOUT_APPLICABLE"], PARTIAL)
    assert partial["resolution_assessment"]["facts_established"] == ["DEEPSEEK_API_OPTOUT_APPLICABLE"]
    assert "DEEPSEEK_API_OPTOUT_PROSPECTIVE" not in partial["resolution_assessment"]["facts_established"]
    dsk02 = _resolved(queue, tmp_path, "DSK-02", DSK02_PRESENT, SAT)
    with pytest.raises(ProviderResolutionError, match="does not allow follow-up"):
        _authorize(queue, tmp_path, "DSK-03", {"DSK-01": partial, "DSK-02": dsk02})


def test_dependency_evidence_or_review_record_tampering_after_resolution_blocks_the_gate(queue, tmp_path):
    good = _resolved(queue, tmp_path, "MIS-01", ["MISTRAL_API_TRAINING_OPTOUT_APPLICABLE"], SAT)
    _authorize(queue, tmp_path, "MIS-02", {"MIS-01": good})  # passes while intact
    review = tmp_path / good["resolution_assessment"]["assessment_source_ref"]
    original = review.read_bytes()
    review.write_bytes(original.replace(b"MISTRAL_API_TRAINING_OPTOUT_APPLICABLE", b"MISTRAL_ZDR_APPLICABLE"))
    with pytest.raises(ProviderResolutionError, match="do not match assessment_sha256"):
        _authorize(queue, tmp_path, "MIS-02", {"MIS-01": good})
    review.write_bytes(original)
    _authorize(queue, tmp_path, "MIS-02", {"MIS-01": good})  # restored -> passes again


def test_assessment_and_outcome_are_cleared_when_an_action_goes_stale_or_restarts(queue, tmp_path):
    resolved = _resolved(queue, tmp_path, "MIS-01", ["MISTRAL_API_TRAINING_OPTOUT_APPLICABLE"], SAT)
    stale = advance_action_state(resolved, "EXPIRED_OR_STALE", evidence_root=tmp_path)
    assert stale["resolution_assessment"] is None and stale["resolution_outcome"] is None
    with pytest.raises(ProviderResolutionError, match="RESOLVED != PREREQUISITE_SATISFIED|dependency"):
        _authorize(queue, tmp_path, "MIS-02", {"MIS-01": stale})
    prepared = advance_action_state(stale, "PREPARED")
    assert prepared["resolution_assessment"] is None and prepared["verified_evidence_ref"] is None


# ══ §27: fact / assessment binding ═══════════════════════════════════════


def _unassessed(queue, tmp_path, action_id):
    action = _drive(_action(queue, action_id), "RESOLVED", tmp_path, assess=False)
    provider, reference = action["provider"], action["reference_name"]
    record = _provider_record(tmp_path, provider, reference, question_ids=_family_questions(provider))
    return action, record


def _assess_raw(action, record, tmp_path, *, outcome=SAT, facts, questions, at="2000-01-04T00:00:00Z",
                source_ref=None, write_review=True):
    ref_name = source_ref if source_ref is not None else f"review_{action['action_id']}.json"
    if write_review and ref_name:
        (tmp_path / ref_name).write_bytes(review_record_bytes(
            action_id=action["action_id"], provider=action["provider"], reference_name=action["reference_name"],
            outcome=outcome, facts_established=facts, questions_addressed=questions,
            verified_evidence_ref=action["verified_evidence_ref"], assessed_by_role="EVIDENCE_REVIEWER", assessed_at_utc=at))
    return assess_action_resolution(action, outcome=outcome, facts_established=facts, questions_addressed=questions,
                                    assessed_at_utc=at, assessment_source_ref=ref_name, evidence_root=tmp_path,
                                    provider_evidence_record=record)


def test_fact_from_the_wrong_action_or_an_unknown_code_is_rejected(queue, tmp_path):
    action, record = _unassessed(queue, tmp_path, "DSK-01")
    for bad in (["MISTRAL_ZDR_APPLICABLE"], ["MINIMAX_COMMERCIAL_USE_APPLIES"], ["MADE_UP_FACT"], ["DEEPSEEK_ACCOUNT_SETTING_PRESENT"]):
        with pytest.raises(ProviderResolutionError, match="not defined for action"):
            _assess_raw(action, record, tmp_path, facts=bad, questions=["DSK-Q1"])


def test_contradictory_facts_are_rejected(queue, tmp_path):
    action, record = _unassessed(queue, tmp_path, "DSK-01")
    with pytest.raises(ProviderResolutionError, match="contradictory"):
        _assess_raw(action, record, tmp_path,
                    facts=sorted(["DEEPSEEK_API_OPTOUT_APPLICABLE", "DEEPSEEK_API_OPTOUT_NOT_APPLICABLE"]), questions=["DSK-Q1"])


def test_unsorted_or_duplicate_facts_are_rejected(queue, tmp_path):
    action, record = _unassessed(queue, tmp_path, "DSK-01")
    good = _assess_raw(action, record, tmp_path, facts=sorted(DSK01_BOTH), questions=["DSK-Q1", "DSK-Q2"])
    for facts in (list(reversed(sorted(DSK01_BOTH))), DSK01_BOTH + DSK01_BOTH[:1]):
        broken = copy.deepcopy(good)
        broken["resolution_assessment"]["facts_established"] = facts
        with pytest.raises(ProviderResolutionError, match="sorted, duplicate-free"):
            validate_action(broken)


def test_assessment_must_be_bound_to_the_exact_action_provider_reference_and_evidence(queue, tmp_path):
    action, record = _unassessed(queue, tmp_path, "MIS-01")
    good = _assess_raw(action, record, tmp_path, facts=["MISTRAL_API_TRAINING_OPTOUT_APPLICABLE"],
                       questions=["MIS-Q2", "MIS-Q3", "MIS-Q4"])
    validate_action(good, evidence_root=tmp_path)
    for path, value, match in (
        (("action_id",), "MIS-02", "is for action_id"),
        (("provider",), "DeepSeek AI", "bound to"),
        (("reference_name",), "Kimi K3", "bound to"),
        (("verified_evidence_ref", "sha256"), "0" * 64, "own verified evidence"),
        (("verified_evidence_ref", "provider"), "DeepSeek AI", "own verified evidence"),
        (("assessed_by_role",), "OWNER", "EVIDENCE_REVIEWER"),
        (("assessed_by_role",), "CLAUDE", "EVIDENCE_REVIEWER"),
        (("outcome",), "NOT_ASSESSED", "invalid outcome"),
        (("outcome",), "SOMETHING_ELSE", "invalid outcome"),
        (("assessed_at_utc",), "yesterday", "UTC ISO-8601"),
        (("assessed_at_utc",), "2000-01-04", "UTC ISO-8601"),
        (("assessment_source_ref",), "", "non-empty"),
        (("assessment_source_ref",), "*", "wildcard"),
        (("assessment_sha256",), "abc", "64-hex"),
        (("questions_addressed",), ["DSK-Q1"], "documented family"),
    ):
        broken = copy.deepcopy(good)
        target = broken["resolution_assessment"]
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        with pytest.raises(ProviderResolutionError, match=match):
            validate_action(broken, evidence_root=tmp_path)
    extra = copy.deepcopy(good)
    extra["resolution_assessment"]["approved_by"] = "me"
    with pytest.raises(ProviderResolutionError, match="unexpected field"):
        validate_action(extra)
    missing = copy.deepcopy(good)
    del missing["resolution_assessment"]["facts_established"]
    with pytest.raises(ProviderResolutionError, match="missing required"):
        validate_action(missing)
    disagree = copy.deepcopy(good)
    disagree["resolution_outcome"] = NOT_SAT
    with pytest.raises(ProviderResolutionError, match="disagrees"):
        validate_action(disagree)
    orphan = copy.deepcopy(action)
    orphan["resolution_outcome"] = SAT
    with pytest.raises(ProviderResolutionError, match="without a resolution assessment"):
        validate_action(orphan)


def test_review_record_must_exist_hash_and_match_the_assessment(queue, tmp_path):
    action, record = _unassessed(queue, tmp_path, "MIS-01")
    kw = dict(facts=["MISTRAL_API_TRAINING_OPTOUT_APPLICABLE"], questions=["MIS-Q2", "MIS-Q3", "MIS-Q4"])
    with pytest.raises(ProviderResolutionError, match="does not exist"):
        _assess_raw(action, record, tmp_path, source_ref="missing_review.json", write_review=False, **kw)
    with pytest.raises(ProviderResolutionError, match="non-empty|does not exist|escapes"):
        _assess_raw(action, record, tmp_path, source_ref="", write_review=False, **kw)
    with pytest.raises(ProviderResolutionError, match="escapes"):
        _assess_raw(action, record, tmp_path, source_ref="../review.json", write_review=False, **kw)
    with pytest.raises(ProviderResolutionError, match="timestamp|UTC ISO-8601"):
        _assess_raw(action, record, tmp_path, at="soon", **kw)
    good = _assess_raw(action, record, tmp_path, **kw)
    # hash forged
    forged = copy.deepcopy(good)
    forged["resolution_assessment"]["assessment_sha256"] = "0" * 64
    with pytest.raises(ProviderResolutionError, match="do not match assessment_sha256"):
        validate_action(forged, evidence_root=tmp_path)
    # facts edited in the action but the persisted (hash-matching) review record is unchanged
    edited = copy.deepcopy(good)
    edited["resolution_assessment"]["facts_established"] = ["MISTRAL_API_TRAINING_OPTOUT_APPLICABLE", "MISTRAL_ZDR_APPLICABLE"]
    edited["resolution_assessment"]["questions_addressed"] = ["MIS-Q2", "MIS-Q3", "MIS-Q4", "MIS-Q5"]
    with pytest.raises(ProviderResolutionError, match="does not match the assessment's facts/outcome"):
        validate_action(edited, evidence_root=tmp_path)


def test_question_coverage_is_derived_from_the_validated_evidence(queue, tmp_path):
    action, _ = _unassessed(queue, tmp_path, "MIS-01")
    kw = dict(facts=["MISTRAL_API_TRAINING_OPTOUT_APPLICABLE"], questions=["MIS-Q2", "MIS-Q3", "MIS-Q4"])
    thin = _provider_record(tmp_path, "Mistral AI", "Mistral Large 3", question_ids=["MIS-Q1"])
    with pytest.raises(ProviderResolutionError, match="never answered claimed question"):
        _assess_raw(action, thin, tmp_path, **kw)
    with pytest.raises(ProviderResolutionError, match="original provider evidence record is required"):
        _assess_raw(action, None, tmp_path, **kw)
    other = _provider_record(tmp_path, "DeepSeek AI", "DeepSeek V4.1-Flash", question_ids=_family_questions("DeepSeek AI"))
    with pytest.raises(ProviderResolutionError, match="does not rebuild"):
        _assess_raw(action, other, tmp_path, **kw)
    # coverage is not enough: the facts must be defined and the outcome consistent
    full = _provider_record(tmp_path, "Mistral AI", "Mistral Large 3", question_ids=_family_questions("Mistral AI"))
    with pytest.raises(ProviderResolutionError, match="requires at least one dependency-unlocking"):
        _assess_raw(action, full, tmp_path, outcome=SAT, facts=["MISTRAL_AUTOMATED_EVALUATION_PERMITTED"], questions=["MIS-Q1"])
    with pytest.raises(ProviderResolutionError, match="may not carry dependency-unlocking"):
        _assess_raw(action, full, tmp_path, outcome=NOT_SAT, **kw)
    with pytest.raises(ProviderResolutionError, match="has downstream dependents"):
        _assess_raw(action, full, tmp_path, outcome="NO_FOLLOWUP_REQUIRED", facts=[], questions=[])


def test_account_setting_evidence_can_establish_the_DSK02_fact_but_answers_no_questions(queue, tmp_path):
    action = _to_awaiting(_action(queue, "DSK-02"))
    account = _account_record(tmp_path, "DeepSeek AI", "DeepSeek V4.1-Flash")
    action = advance_action_state(action, "AUTHORIZED_NOT_EXECUTED", authorization_evidence=_auth("DSK-02"))
    action = advance_action_state(action, "EXECUTED_AWAITING_PROVIDER", execution_evidence=_exec_evidence(action))
    action = advance_action_state(action, "PROVIDER_REPLIED_UNVERIFIED", received_record=account)
    action = advance_action_state(action, "EVIDENCE_VERIFIED", verified_evidence_record=account, evidence_root=tmp_path)
    action = advance_action_state(action, "RESOLVED", evidence_root=tmp_path)
    (tmp_path / "review_DSK-02.json").write_bytes(review_record_bytes(
        action_id="DSK-02", provider="DeepSeek AI", reference_name="DeepSeek V4.1-Flash", outcome=SAT,
        facts_established=DSK02_PRESENT, questions_addressed=[], verified_evidence_ref=action["verified_evidence_ref"],
        assessed_by_role="EVIDENCE_REVIEWER", assessed_at_utc="2000-01-04T00:00:00Z"))
    kw = dict(outcome=SAT, facts_established=DSK02_PRESENT, assessed_at_utc="2000-01-04T00:00:00Z",
              assessment_source_ref="review_DSK-02.json", evidence_root=tmp_path)
    with pytest.raises(ProviderResolutionError, match="answers no provider questions"):
        assess_action_resolution(action, questions_addressed=["DSK-Q1"], **kw)
    assessed = assess_action_resolution(action, questions_addressed=[], **kw)
    assert assessed["resolution_assessment"]["verified_evidence_ref"]["evidence_type"] == "ACCOUNT_SETTING"


def test_assessment_preconditions(queue, tmp_path):
    awaiting = _to_awaiting(_action(queue, "MIS-01"))
    kw = dict(outcome=NOT_SAT, facts_established=[], assessed_at_utc="2000-01-04T00:00:00Z",
              assessment_source_ref="x.json", evidence_root=tmp_path)
    with pytest.raises(ProviderResolutionError, match="must be RESOLVED"):
        assess_action_resolution(awaiting, **kw)
    verified = _drive(_action(queue, "MIS-01"), "EVIDENCE_VERIFIED", tmp_path)
    with pytest.raises(ProviderResolutionError, match="must be RESOLVED"):
        assess_action_resolution(verified, **kw)
    assessed = _resolved(queue, tmp_path, "MIS-01", ["MISTRAL_API_TRAINING_OPTOUT_APPLICABLE"], SAT)
    with pytest.raises(ProviderResolutionError, match="immutable"):
        assess_action_resolution(assessed, **kw)
    glb = _action(queue, "GLB-01")
    with pytest.raises(ProviderResolutionError):
        assess_action_resolution(glb, **kw)
    with pytest.raises(ProviderResolutionError, match="only a RESOLVED|carries a resolution assessment outside RESOLVED"):
        bad = _to_awaiting(_action(queue, "MIS-01"))
        bad["resolution_outcome"] = SAT
        bad["resolution_assessment"] = assessed["resolution_assessment"]
        validate_action(bad)


def test_close_unavailable_branch_preconditions(queue, tmp_path):
    negative = _resolved(queue, tmp_path, "KMI-01", ["KIMI_ENTERPRISE_NO_TRAINING_PATH_NOT_AVAILABLE"], NOT_SAT)
    with pytest.raises(ProviderResolutionError, match="not a conditional dependent"):
        close_unavailable_branch(_action(queue, "KMI-01"), dependency_actions={"KMI-01": negative}, evidence_root=tmp_path)
    with pytest.raises(ProviderResolutionError, match="only a PREPARED"):
        close_unavailable_branch(_to_awaiting(_action(queue, "KMI-02")), dependency_actions={"KMI-01": negative}, evidence_root=tmp_path)
    with pytest.raises(ProviderResolutionError, match="dependency_actions context"):
        close_unavailable_branch(_action(queue, "KMI-02"), dependency_actions={}, evidence_root=tmp_path)
    unassessed = _drive(_action(queue, "KMI-01"), "RESOLVED", tmp_path, assess=False)
    with pytest.raises(ProviderResolutionError, match="no dependency has definitively closed"):
        close_unavailable_branch(_action(queue, "KMI-02"), dependency_actions={"KMI-01": unassessed}, evidence_root=tmp_path)


# ══ policy tables ════════════════════════════════════════════════════════


EXPECTED_POLICY = {
    "MIS-02": {"MIS-01": {"MISTRAL_API_TRAINING_OPTOUT_APPLICABLE"}},
    "MIS-03": {"MIS-01": {"MISTRAL_ZDR_APPLICABLE"}},
    "DSK-03": {"DSK-01": {"DEEPSEEK_API_OPTOUT_APPLICABLE", "DEEPSEEK_API_OPTOUT_PROSPECTIVE"},
               "DSK-02": {"DEEPSEEK_ACCOUNT_SETTING_PRESENT"}},
    "GLM-02": {"GLM-01": {"GLM_NO_TRAINING_CONTROL_AVAILABLE", "GLM_NO_TRAINING_CONTROL_APPLIES_TO_GLM_5_3"}},
    "MNX-02": {"MNX-01": {"MINIMAX_COMMERCIAL_USE_APPLIES"}},
    "KMI-02": {"KMI-01": {"KIMI_ACCEPTABLE_ENTERPRISE_NO_TRAINING_PATH_AVAILABLE"}},
}


def test_dependency_requirement_policy_is_exactly_the_specified_mapping(queue):
    actual = {dep_on: {d: set(r["required_facts"]) for d, r in deps.items()} for dep_on, deps in DEPENDENCY_REQUIREMENTS.items()}
    assert actual == EXPECTED_POLICY
    # MNX-02 unlocks only on COMMERCIAL_USE_APPLIES -- DOES_NOT_APPLY never satisfies it
    mnx = DEPENDENCY_REQUIREMENTS["MNX-02"]["MNX-01"]
    assert mnx["required_facts"] == {"MINIMAX_COMMERCIAL_USE_APPLIES"}
    assert "MINIMAX_COMMERCIAL_USE_DOES_NOT_APPLY" in mnx["closing_facts"]
    assert "MINIMAX_COMMERCIAL_USE_DOES_NOT_APPLY" not in mnx["required_facts"]
    # the queue's declared graph is covered by exactly this policy
    depends = {a["action_id"]: set(a["depends_on"]) for a in queue["actions"] if a["depends_on"]}
    assert depends == {k: set(v) for k, v in DEPENDENCY_REQUIREMENTS.items()}
    validate_action_queue(queue)


def test_fact_tables_are_internally_consistent():
    assert set(FACT_REQUIRED_QUESTIONS) == set().union(*ACTION_FACT_CODES.values())
    assert RESOLUTION_OUTCOMES == ("NOT_ASSESSED", "PREREQUISITE_SATISFIED", "PREREQUISITE_NOT_SATISFIED",
                                   "PARTIAL_INFORMATION", "NO_FOLLOWUP_REQUIRED")
    for group in CONTRADICTORY_FACT_GROUPS:
        assert len({f.split("_")[0] for f in group}) == 1  # a group never crosses providers
    mnx = next(g for g in CONTRADICTORY_FACT_GROUPS if "MINIMAX_COMMERCIAL_USE_APPLIES" in g)
    assert len(mnx) == 3
    for req_by_dep in DEPENDENCY_REQUIREMENTS.values():
        for dep_id, req in req_by_dep.items():
            assert not (req["required_facts"] & req["closing_facts"])
            assert req["required_facts"] <= UNLOCK_FACTS[dep_id]
    # every fact belongs to exactly one action
    seen = {}
    for aid, facts in ACTION_FACT_CODES.items():
        for f in facts:
            assert f not in seen, f
            seen[f] = aid


def test_policy_is_documented_in_the_response_schema():
    schema = json.loads(SCHEMA_PATH.read_text())
    doc = schema["resolution_assessment"]
    assert doc["resolved_is_not_prerequisite_satisfied"] is True
    assert doc["assessor_role"] == "EVIDENCE_REVIEWER"
    assert doc["outcomes"] == list(RESOLUTION_OUTCOMES)
    assert {k: {d: sorted(f) for d, f in v.items()} for k, v in doc["dependency_required_facts"].items()} == {
        k: {d: sorted(f) for d, f in v.items()} for k, v in EXPECTED_POLICY.items()}
    assert doc["registry_dimensions_mutated"] is False


# ══ §13/§28/§29: registry and real queue untouched ═══════════════════════


def test_outcomes_and_facts_never_change_registry_or_quorum(registry, queue, tmp_path):
    before = copy.deepcopy(list(registry.frontier_references))
    deps = {"MIS-01": _resolved(queue, tmp_path, "MIS-01",
                                ["MISTRAL_API_TRAINING_OPTOUT_APPLICABLE", "MISTRAL_ZDR_APPLICABLE"], SAT)}
    assert _authorize(queue, tmp_path, "MIS-02", deps)["state"] == "AUTHORIZED_NOT_EXECUTED"
    assert list(registry.frontier_references) == before
    by_name = {r["reference_name"]: r for r in registry.frontier_references}
    assert by_name["Mistral Large 3"]["private_holdout_status"] == "REVIEW_REQUIRED"
    report = compute_admission_quorum(list(registry.frontier_references))
    assert (report.validated_access_preflight_ready_count, report.quorum_counting_count,
            report.independent_lineage_count, report.quorum_status) == (0, 0, 0, "QUORUM_BLOCKED")


def test_real_queue_has_no_outcome_assessment_or_facts(queue):
    assert len(queue["actions"]) == 15
    assert_queue_fully_unauthorized(queue)
    lookup = build_action_lookup(queue)
    assert len(lookup) == 15
    for action in queue["actions"]:
        assert action["authorization_status"] == "NOT_AUTHORIZED" and action["executed_status"] == "NOT_EXECUTED"
        assert action["resolution_outcome"] is None and action["resolution_assessment"] is None
        assert action["verified_evidence_ref"] is None and action["execution_evidence_ref"] is None
        assert action["state"] != "RESOLVED"
    assert next(a for a in queue["actions"] if a["action_id"] == "GLB-02")["state"] == "BLOCKED"
    for counter in ("messages_sent", "support_tickets_submitted", "account_settings_changed", "commercial_notices_sent"):
        assert queue[counter] == 0


def test_queue_level_validation_rejects_an_unsatisfied_dependency_behind_an_authorized_dependent(queue, tmp_path):
    """A hand-edited queue with MIS-02 authorized while MIS-01 is only
    RESOLVED-negative is inconsistent, even though every action is
    individually well-formed."""
    negative = _resolved(queue, tmp_path, "MIS-01", ["MISTRAL_API_TRAINING_OPTOUT_NOT_APPLICABLE"], NOT_SAT)
    tampered = copy.deepcopy(queue)
    for i, a in enumerate(tampered["actions"]):
        if a["action_id"] == "MIS-01":
            tampered["actions"][i] = negative
        if a["action_id"] == "MIS-02":
            a.update(authorization_status="AUTHORIZED", state="AUTHORIZED_NOT_EXECUTED", authorization_evidence=_auth("MIS-02"))
    with pytest.raises(ProviderResolutionError, match="does not allow follow-up"):
        validate_action_queue(tampered, evidence_root=tmp_path)
    # a dependent policy that no longer matches the declared graph is rejected
    broken = copy.deepcopy(queue)
    next(a for a in broken["actions"] if a["action_id"] == "DSK-03")["depends_on"] = ["DSK-01"]
    with pytest.raises(ProviderResolutionError, match="no matching dependency requirement policy"):
        validate_action_queue(broken)
