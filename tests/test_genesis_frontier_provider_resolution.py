"""Phase 21B.4.19: Genesis frontier provider resolution + human-authorization gate.

CONTROL-PLANE TESTS ONLY -- no provider was contacted, no account touched,
no API called. Proves (per the phase spec's required list, A-T):
  A. exact reference set remains six.        B. quorum constants remain 6/4/3.
  C. all provider actions default NOT_AUTHORIZED.
  D. no action is EXECUTED without authorization.
  E. a provider reply cannot be VERIFIED without evidence source/hash.
  F. a draft clarification cannot alter registry state.
  G. an account-setting checklist cannot alter registry state.
  H. a blocker cannot become RESOLVED without verified evidence.
  I/J/K. dimension transitions require valid, kind-matched provider evidence.
  L. a provider response cannot bypass validate_full_protocol_access_readiness().
  M-P. MiniMax notice unsent; DeepSeek opt-out, Mistral setting, Kimi agreement all unexecuted.
  Q. Qwen private-holdout finding preserved.   R. quorum remains honest.
  S. Phase 21C unauthorized.                   T. no execution code introduced.

Every "synthetic" record below lives only in pytest's tmp_path, is labeled
SYNTHETIC TEST FIXTURE, and exists solely to exercise the validators. None
of it is evidence and none of it is written into the repository.
"""

import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest

from orca.eval.candidate_registry import CandidateExecutionRegistry, EXPECTED_REFERENCE_NAMES
from orca.eval.frontier_provider_resolution import (
    ACTION_STATES,
    EXTERNAL_ACTION_TYPES,
    OFFICIAL_PROVIDER_DOMAINS,
    PROVIDER_QUESTION_PREFIX,
    RESPONSE_REQUIRED_FIELDS,
    ProviderResolutionError,
    advance_action_state,
    apply_verified_evidence,
    assert_queue_fully_unauthorized,
    compute_minimum_conditional_path,
    promote_access_status,
    resolve_blocker_token,
    validate_account_setting_evidence,
    validate_action,
    validate_action_queue,
    validate_provider_response,
)
from orca.eval.frontier_reference_admission_quorum import (
    MINIMUM_INDEPENDENT_ORGANIZATIONS,
    MINIMUM_USABLE_REFERENCES,
    TARGET_REFERENCES,
    AccessReadinessError,
    compute_admission_quorum,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CANDIDATE_EXECUTION_REGISTRY.json"
EVIDENCE_DIR = REPO_ROOT / "docs/orneur/phase-21/evidence"
QUEUE_PATH = EVIDENCE_DIR / "GENESIS_FRONTIER_PROVIDER_ACTION_QUEUE_2026-09-24.json"
SCHEMA_PATH = EVIDENCE_DIR / "GENESIS_FRONTIER_PROVIDER_RESPONSE_SCHEMA_2026-09-24.json"
PACKETS_PATH = EVIDENCE_DIR / "GENESIS_FRONTIER_PROVIDER_CLARIFICATION_PACKETS_2026-09-24.md"
ACCOUNT_SPEC_PATH = EVIDENCE_DIR / "GENESIS_FRONTIER_ACCOUNT_SETTING_EVIDENCE_SPEC_2026-09-24.md"
INDEX_PATH = EVIDENCE_DIR / "GENESIS_FRONTIER_PROVIDER_RESOLUTION_SHA256_INDEX_2026-09-24.json"
PLAN_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_FRONTIER_PROVIDER_RESOLUTION_PLAN_2026-09-24.md"
RESOLUTION_PY = REPO_ROOT / "orca/eval/frontier_provider_resolution.py"

# Canonical registry state at Phase 21B.4.18.1 close; Phase 21B.4.19 must not move any of it.
CANONICAL_STATE = {
    "DeepSeek V4.1-Flash": dict(license_or_terms_status="CLEAR", reference_evaluation_admission_status="ADMITTED", automated_evaluation_status="CLEAR", private_holdout_status="REVIEW_REQUIRED", access_preflight_status="UNQUALIFIED", model_identity_attributable=True, access_path_identified=True),
    "GLM-5.3 (flagship)": dict(license_or_terms_status="REVIEW_REQUIRED", reference_evaluation_admission_status="REVIEW_REQUIRED", automated_evaluation_status="REVIEW_REQUIRED", private_holdout_status="REVIEW_REQUIRED", access_preflight_status="UNQUALIFIED", model_identity_attributable=True, access_path_identified=True),
    "Mistral Large 3": dict(license_or_terms_status="CLEAR", reference_evaluation_admission_status="ADMITTED", automated_evaluation_status="REVIEW_REQUIRED", private_holdout_status="REVIEW_REQUIRED", access_preflight_status="UNQUALIFIED", model_identity_attributable=True, access_path_identified=True),
    "MiniMax M3": dict(license_or_terms_status="REVIEW_REQUIRED", reference_evaluation_admission_status="REVIEW_REQUIRED", automated_evaluation_status="REVIEW_REQUIRED", private_holdout_status="REVIEW_REQUIRED", access_preflight_status="UNQUALIFIED", model_identity_attributable=True, access_path_identified=False),
    "Qwen3.8-Max": dict(license_or_terms_status="REVIEW_REQUIRED", reference_evaluation_admission_status="REVIEW_REQUIRED", automated_evaluation_status="REVIEW_REQUIRED", private_holdout_status="PERMITTED", access_preflight_status="UNQUALIFIED", model_identity_attributable=False, access_path_identified=True),
    "Kimi K3": dict(license_or_terms_status="CLEAR", reference_evaluation_admission_status="ADMITTED", automated_evaluation_status="CLEAR", private_holdout_status="BLOCKED", access_preflight_status="UNQUALIFIED", model_identity_attributable=True, access_path_identified=True),
}


@pytest.fixture(scope="module")
def registry():
    return CandidateExecutionRegistry.load(REGISTRY_PATH)


@pytest.fixture(scope="module")
def queue():
    return json.loads(QUEUE_PATH.read_text())


def _entry(registry, name):
    return copy.deepcopy(next(r for r in registry.frontier_references if r["reference_name"] == name))


def _action(queue, action_id):
    return copy.deepcopy(next(a for a in queue["actions"] if a["action_id"] == action_id))


def _synthetic_verified_record(tmp_path, entry, changes, *, tier="B", sender_domain=None, ambiguity=None, status="VERIFIED"):
    """SYNTHETIC TEST FIXTURE -- NOT EVIDENCE. Exercises the validators only."""
    raw = tmp_path / "synthetic_response.txt"
    raw.write_bytes(b"SYNTHETIC TEST FIXTURE - NOT EVIDENCE")
    return {
        "provider": entry["organization"],
        "reference_name": entry["reference_name"],
        "incoming_channel": "EMAIL",
        "sender_identity": "SYNTHETIC",
        "sender_domain": sender_domain or OFFICIAL_PROVIDER_DOMAINS[entry["organization"]][0],
        "message_id": "SYNTHETIC-1",
        "received_at_utc": "2000-01-01T00:00:00Z",
        "question_ids_answered": [PROVIDER_QUESTION_PREFIX[entry["organization"]] + "1"],
        "raw_response_location": "synthetic_response.txt",
        "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
        "quoted_authoritative_clauses": ["SYNTHETIC CLAUSE"],
        "interpretation": "SYNTHETIC",
        "remaining_ambiguity": ambiguity or [],
        "evidence_tier": tier,
        "review_status": status,
        "approved_state_changes": changes,
        "reviewer": "SYNTHETIC-REVIEWER",
        "expiry_or_freshness": "SYNTHETIC",
    }


def _synthetic_account_setting(tmp_path, entry, **overrides):
    """SYNTHETIC TEST FIXTURE -- NOT EVIDENCE."""
    shot = tmp_path / "synthetic_screenshot.bin"
    shot.write_bytes(b"SYNTHETIC SCREENSHOT - NOT EVIDENCE")
    record = {
        "provider": entry["organization"],
        "reference_name": entry["reference_name"],
        "account_identifier_category": "ORG_ID_REDACTED",
        "setting_name": "SYNTHETIC",
        "old_state": "ENABLED",
        "new_state": "DISABLED",
        "effective_scope": "SYNTHETIC",
        "effective_timestamp_utc": "2000-01-01T00:00:00Z",
        "screenshot_evidence_reference": "synthetic_screenshot.bin",
        "sha256": hashlib.sha256(shot.read_bytes()).hexdigest(),
        "provider_documentation_reference": "SYNTHETIC",
        "prospective": True,
        "retroactive": False,
        "api_specific": True,
        "verification_result": "VERIFIED_ACTIVE",
        "reviewer": "SYNTHETIC-REVIEWER",
    }
    record.update(overrides)
    return record


def _holdout_change():
    return {"field": "private_holdout_status", "from": "REVIEW_REQUIRED", "to": "PERMITTED", "evidence_kind": "NO_TRAINING_CONFIDENTIALITY"}


# ── A/B: locked reference set and quorum constants ──────────────────────


def test_A_exact_reference_set_remains_six(registry, queue):
    assert len(registry.frontier_references) == 6
    assert {r["reference_name"] for r in registry.frontier_references} == set(EXPECTED_REFERENCE_NAMES)
    for action in queue["actions"]:
        assert action["reference_name"] == "ALL" or action["reference_name"] in EXPECTED_REFERENCE_NAMES


def test_B_quorum_constants_remain_6_4_3():
    assert (TARGET_REFERENCES, MINIMUM_USABLE_REFERENCES, MINIMUM_INDEPENDENT_ORGANIZATIONS) == (6, 4, 3)


# ── C/D: authorization defaults and execution gating ────────────────────


def test_C_all_provider_actions_default_not_authorized(queue):
    validate_action_queue(queue)
    assert_queue_fully_unauthorized(queue)
    assert queue["actions"]
    for action in queue["actions"]:
        assert action["requires_owner_authorization"] is True
        assert action["authorization_status"] == "NOT_AUTHORIZED"
        assert action["executed_status"] == "NOT_EXECUTED"
        assert action["authorization_evidence"] is None
        assert action["claude_can_execute"] is False
        assert action["action_type"] in EXTERNAL_ACTION_TYPES
    for counter in ("messages_sent", "support_tickets_submitted", "account_settings_changed", "commercial_notices_sent"):
        assert queue[counter] == 0


def test_D_executed_without_authorization_is_rejected(queue):
    action = _action(queue, "MIS-01")
    action["executed_status"] = "EXECUTED"
    with pytest.raises(ProviderResolutionError, match="EXECUTED without AUTHORIZED"):
        validate_action(action)

    action = _action(queue, "MIS-01")
    action["state"] = "EXECUTED_AWAITING_PROVIDER"
    with pytest.raises(ProviderResolutionError, match="asserts execution"):
        validate_action(action)

    action = _action(queue, "MIS-01")
    action["authorization_status"] = "AUTHORIZED"
    with pytest.raises(ProviderResolutionError, match="without authorization_evidence"):
        validate_action(action)


# The full evidence-gated state-machine chain (structured authorization,
# dependency enforcement, execution evidence, derived verified refs) is
# proven in tests/test_genesis_frontier_provider_authority_binding.py.


def test_state_machine_has_exactly_the_specified_states_and_no_sent_state():
    assert len(ACTION_STATES) == 11
    assert "SENT" not in ACTION_STATES
    assert {"NOT_REQUIRED", "PREPARED", "AWAITING_OWNER_AUTHORIZATION", "AUTHORIZED_NOT_EXECUTED",
            "EXECUTED_AWAITING_PROVIDER", "PROVIDER_REPLIED_UNVERIFIED", "EVIDENCE_VERIFIED",
            "EVIDENCE_INSUFFICIENT", "RESOLVED", "BLOCKED", "EXPIRED_OR_STALE"} == set(ACTION_STATES)


def test_blocked_action_is_terminal(queue):
    blocked = _action(queue, "GLB-02")
    assert blocked["state"] == "BLOCKED"
    for state in ACTION_STATES:
        with pytest.raises(ProviderResolutionError):
            advance_action_state(blocked, state)


def test_conditional_actions_depend_on_earlier_evidence(queue):
    for action_id in ("MIS-02", "MIS-03", "DSK-03", "GLM-02", "MNX-02", "KMI-02"):
        assert _action(queue, action_id)["depends_on"], action_id
        assert _action(queue, action_id)["state"] == "PREPARED", action_id


# ── E: provider replies cannot be VERIFIED without a persisted, hashed source ──


def test_E_valid_verified_record_passes(registry, tmp_path):
    entry = _entry(registry, "DeepSeek V4.1-Flash")
    validate_provider_response(_synthetic_verified_record(tmp_path, entry, [_holdout_change()]), evidence_root=tmp_path)


def test_E_verified_response_rejected_without_source_or_hash(registry, tmp_path):
    entry = _entry(registry, "DeepSeek V4.1-Flash")
    good = _synthetic_verified_record(tmp_path, entry, [_holdout_change()])

    no_location = dict(good, raw_response_location="")
    with pytest.raises(ProviderResolutionError, match="raw_response_location"):
        validate_provider_response(no_location, evidence_root=tmp_path)

    bad_hash = dict(good, sha256="0" * 64)
    with pytest.raises(ProviderResolutionError, match="do not match"):
        validate_provider_response(bad_hash, evidence_root=tmp_path)

    malformed = dict(good, sha256="abc")
    with pytest.raises(ProviderResolutionError, match="64-hex"):
        validate_provider_response(malformed, evidence_root=tmp_path)

    missing_file = dict(good, raw_response_location="does_not_exist.txt")
    with pytest.raises(ProviderResolutionError, match="does not exist"):
        validate_provider_response(missing_file, evidence_root=tmp_path)

    with pytest.raises(ProviderResolutionError, match="evidence_root"):
        validate_provider_response(good, evidence_root=None)

    escape = dict(good, raw_response_location="../outside.txt")
    with pytest.raises(ProviderResolutionError, match="escapes"):
        validate_provider_response(escape, evidence_root=tmp_path)


def test_E_tier_d_and_unofficial_sender_can_never_be_verified(registry, tmp_path):
    entry = _entry(registry, "DeepSeek V4.1-Flash")
    with pytest.raises(ProviderResolutionError, match="Tier D"):
        validate_provider_response(_synthetic_verified_record(tmp_path, entry, [], tier="D"), evidence_root=tmp_path)
    for lookalike in ("deepseek.com.evil.io", "notdeepseek.com", "gmail.com", "evil.io"):
        with pytest.raises(ProviderResolutionError, match="official domain"):
            validate_provider_response(_synthetic_verified_record(tmp_path, entry, [], sender_domain=lookalike), evidence_root=tmp_path)
    # a genuine official subdomain is accepted
    validate_provider_response(_synthetic_verified_record(tmp_path, entry, [], sender_domain="support.deepseek.com"), evidence_root=tmp_path)


def test_E_ambiguous_or_unverified_response_cannot_approve_state_changes(registry, tmp_path):
    entry = _entry(registry, "DeepSeek V4.1-Flash")
    with pytest.raises(ProviderResolutionError, match="ambiguity"):
        validate_provider_response(
            _synthetic_verified_record(tmp_path, entry, [_holdout_change()], ambiguity=["unclear scope"]), evidence_root=tmp_path)
    with pytest.raises(ProviderResolutionError, match="only a VERIFIED"):
        validate_provider_response(
            _synthetic_verified_record(tmp_path, entry, [_holdout_change()], status="UNREVIEWED"), evidence_root=tmp_path)
    with pytest.raises(ProviderResolutionError, match="only a VERIFIED"):
        validate_provider_response(
            _synthetic_verified_record(tmp_path, entry, [_holdout_change()], status="INSUFFICIENT"), evidence_root=tmp_path)


def test_E_response_schema_matches_module_required_fields():
    schema = json.loads(SCHEMA_PATH.read_text())
    assert set(schema["response_record"]["required_fields"]) == set(RESPONSE_REQUIRED_FIELDS)
    assert schema["resolving_tiers"] == ["A", "B", "C"]
    assert schema["tier_d_can_resolve_hard_blocker"] is False
    assert schema["example_format"]["_SYNTHETIC_NON_EVIDENCE"] is True
    assert schema["example_format"]["review_status"] == "UNREVIEWED"
    assert schema["example_format"]["approved_state_changes"] == []


# ── F/G: drafts, packets and checklists never alter registry state ──────


def test_F_registry_state_unchanged_by_drafts_and_queue(registry):
    for entry in registry.frontier_references:
        expected = CANONICAL_STATE[entry["reference_name"]]
        for field, value in expected.items():
            assert entry[field] == value, (entry["reference_name"], field)
        assert entry["full_protocol_access_validation"] == "FAILED"


def test_F_G_evidence_functions_never_mutate_their_input(registry, tmp_path):
    entry = _entry(registry, "DeepSeek V4.1-Flash")
    before = copy.deepcopy(entry)
    record = _synthetic_verified_record(tmp_path, entry, [_holdout_change()])
    apply_verified_evidence(entry, "private_holdout_status", "PERMITTED", provider_responses=[record],
                            evidence_root=tmp_path)
    assert entry == before


def test_G_account_setting_validator_is_strict(registry, tmp_path):
    entry = _entry(registry, "Mistral Large 3")
    validate_account_setting_evidence(_synthetic_account_setting(tmp_path, entry), evidence_root=tmp_path)
    for overrides, match in (
        ({"verification_result": "PLANNED"}, "VERIFIED_ACTIVE"),
        ({"prospective": False}, "prospective"),
        ({"api_specific": False}, "API-specific"),
        ({"new_state": "ENABLED"}, "old_state -> new_state"),
        ({"sha256": "0" * 64}, "do not match"),
        ({"account_identifier_category": "org-12345"}, "redacted category"),
        ({"account_identifier": "org-12345"}, "must not store"),
        ({"api_key": "sk-x"}, "must not store"),
        ({"screenshot_evidence_reference": ""}, "screenshot"),
    ):
        with pytest.raises(ProviderResolutionError, match=match):
            validate_account_setting_evidence(_synthetic_account_setting(tmp_path, entry, **overrides), evidence_root=tmp_path)
    with pytest.raises(ProviderResolutionError, match="evidence_root"):
        validate_account_setting_evidence(_synthetic_account_setting(tmp_path, entry), evidence_root=None)


def test_G_account_setting_spec_forbids_storing_secrets():
    text = ACCOUNT_SPEC_PATH.read_text()
    assert "Never store a real account number" in text
    assert "VERIFIED_ACTIVE" in text
    assert "can never set `access_preflight_status`" in text


# ── H: blockers need verified evidence ──────────────────────────────────


def test_H_blocker_cannot_be_resolved_without_verified_evidence(registry, tmp_path):
    entry = _entry(registry, "DeepSeek V4.1-Flash")
    with pytest.raises(ProviderResolutionError, match="needs 'PERMITTED'"):
        resolve_blocker_token(entry, "PRIVATE_HOLDOUT_CONFIDENTIALITY_UNRESOLVED", provider_responses=[], evidence_root=tmp_path)
    with pytest.raises(ProviderResolutionError, match="no VERIFIED provider evidence"):
        resolve_blocker_token(entry, "WRITTEN_PROVIDER_CLARIFICATION_REQUIRED", provider_responses=[], evidence_root=tmp_path)
    with pytest.raises(ProviderResolutionError, match="not present"):
        resolve_blocker_token(entry, "MODEL_IDENTITY_INSUFFICIENT", provider_responses=[], evidence_root=tmp_path)
    kimi = _entry(registry, "Kimi K3")
    with pytest.raises(ProviderResolutionError, match="never be resolved"):
        resolve_blocker_token(kimi, "SELF_HOST_COMPUTE_PROHIBITIVE", provider_responses=[], evidence_root=tmp_path)
    mistral = _entry(registry, "Mistral Large 3")
    with pytest.raises(ProviderResolutionError, match="account-setting"):
        resolve_blocker_token(mistral, "PROVIDER_ACCOUNT_SETTING_REQUIRED", provider_responses=[], evidence_root=tmp_path)


def test_H_unverified_or_wrong_reference_response_cannot_resolve_blocker(registry, tmp_path):
    entry = _entry(registry, "DeepSeek V4.1-Flash")
    change = [{"blocker_resolved": "WRITTEN_PROVIDER_CLARIFICATION_REQUIRED"}]
    unreviewed = _synthetic_verified_record(tmp_path, entry, [], status="UNREVIEWED")
    with pytest.raises(ProviderResolutionError, match="no VERIFIED"):
        resolve_blocker_token(entry, "WRITTEN_PROVIDER_CLARIFICATION_REQUIRED", provider_responses=[unreviewed], evidence_root=tmp_path)
    other = _entry(registry, "Mistral Large 3")
    foreign = _synthetic_verified_record(tmp_path, other, change)
    with pytest.raises(ProviderResolutionError, match="no VERIFIED"):
        resolve_blocker_token(entry, "WRITTEN_PROVIDER_CLARIFICATION_REQUIRED", provider_responses=[foreign], evidence_root=tmp_path)


# ── I/J/K: dimension transitions need valid, kind-matched evidence ──────


def test_I_holdout_review_required_to_permitted_requires_valid_evidence(registry, tmp_path):
    entry = _entry(registry, "DeepSeek V4.1-Flash")
    with pytest.raises(ProviderResolutionError, match="no VERIFIED provider evidence"):
        apply_verified_evidence(entry, "private_holdout_status", "PERMITTED", provider_responses=[], evidence_root=tmp_path)
    with pytest.raises(ProviderResolutionError, match="not a permitted transition"):
        apply_verified_evidence(entry, "private_holdout_status", "BLOCKED", provider_responses=[], evidence_root=tmp_path)
    good = _synthetic_verified_record(tmp_path, entry, [_holdout_change()])
    with pytest.raises(ProviderResolutionError, match="account-setting evidence"):
        apply_verified_evidence(entry, "private_holdout_status", "PERMITTED", provider_responses=[good],
                                evidence_root=tmp_path, requires_account_setting=True)
    updated = apply_verified_evidence(
        entry, "private_holdout_status", "PERMITTED", provider_responses=[good],
        account_setting_records=[_synthetic_account_setting(tmp_path, entry)], evidence_root=tmp_path,
        requires_account_setting=True)
    assert updated["private_holdout_status"] == "PERMITTED"
    # only that one dimension moved; readiness is untouched
    assert updated["access_preflight_status"] == "UNQUALIFIED"
    assert updated["full_protocol_access_validation"] == "FAILED"
    assert updated["non_financial_blocker_status"] == entry["non_financial_blocker_status"]


def test_I_wrong_evidence_kind_is_rejected(registry, tmp_path):
    entry = _entry(registry, "DeepSeek V4.1-Flash")
    wrong = dict(_holdout_change(), evidence_kind="TERMS_CLARIFICATION")
    with pytest.raises(ProviderResolutionError, match="evidence_kind"):
        apply_verified_evidence(entry, "private_holdout_status", "PERMITTED",
                                provider_responses=[_synthetic_verified_record(tmp_path, entry, [wrong])], evidence_root=tmp_path)


def test_J_automated_evaluation_requires_valid_provider_evidence(registry, tmp_path):
    entry = _entry(registry, "Mistral Large 3")
    with pytest.raises(ProviderResolutionError, match="no VERIFIED provider evidence"):
        apply_verified_evidence(entry, "automated_evaluation_status", "CLEAR", provider_responses=[], evidence_root=tmp_path)
    change = {"field": "automated_evaluation_status", "from": "REVIEW_REQUIRED", "to": "CLEAR", "evidence_kind": "AUTOMATED_EVALUATION_PERMISSION"}
    tier_d = _synthetic_verified_record(tmp_path, entry, [change], tier="D")
    with pytest.raises(ProviderResolutionError, match="Tier D"):
        apply_verified_evidence(entry, "automated_evaluation_status", "CLEAR", provider_responses=[tier_d], evidence_root=tmp_path)
    updated = apply_verified_evidence(entry, "automated_evaluation_status", "CLEAR",
                                      provider_responses=[_synthetic_verified_record(tmp_path, entry, [change], tier="A")],
                                      evidence_root=tmp_path)
    assert updated["automated_evaluation_status"] == "CLEAR"


def test_K_model_identity_false_to_true_requires_version_evidence(registry, tmp_path):
    entry = _entry(registry, "Qwen3.8-Max")
    assert entry["model_identity_attributable"] is False
    with pytest.raises(ProviderResolutionError, match="no VERIFIED provider evidence"):
        apply_verified_evidence(entry, "model_identity_attributable", True, provider_responses=[], evidence_root=tmp_path)
    wrong = {"field": "model_identity_attributable", "from": False, "to": True, "evidence_kind": "TERMS_CLARIFICATION"}
    with pytest.raises(ProviderResolutionError, match="PROVIDER_VERSION_IDENTITY"):
        apply_verified_evidence(entry, "model_identity_attributable", True,
                                provider_responses=[_synthetic_verified_record(tmp_path, entry, [wrong])], evidence_root=tmp_path)
    right = {"field": "model_identity_attributable", "from": False, "to": True, "evidence_kind": "PROVIDER_VERSION_IDENTITY"}
    updated = apply_verified_evidence(entry, "model_identity_attributable", True,
                                      provider_responses=[_synthetic_verified_record(tmp_path, entry, [right])], evidence_root=tmp_path)
    assert updated["model_identity_attributable"] is True
    assert updated["mutable_identity_status"] == "MUTABLE_REFERENCE_IDENTITY"  # identity type is not rewritten


# ── L: a provider response can never bypass the fail-closed validator ───


def test_L_response_may_never_approve_an_access_status_change(registry, tmp_path):
    entry = _entry(registry, "DeepSeek V4.1-Flash")
    forbidden = {"field": "access_preflight_status", "from": "UNQUALIFIED", "to": "QUALIFIED_FOR_FUTURE_EXECUTION", "evidence_kind": "X"}
    with pytest.raises(ProviderResolutionError, match="may never approve a change"):
        validate_provider_response(_synthetic_verified_record(tmp_path, entry, [forbidden]), evidence_root=tmp_path)
    forbidden2 = {"field": "full_protocol_access_validation", "from": "FAILED", "to": "PASSED", "evidence_kind": "X"}
    with pytest.raises(ProviderResolutionError, match="may never approve a change"):
        validate_provider_response(_synthetic_verified_record(tmp_path, entry, [forbidden2]), evidence_root=tmp_path)
    for token in ("SELF_HOST_COMPUTE_PROHIBITIVE", "ZERO_CASH_CHECK_REQUIRED"):
        with pytest.raises(ProviderResolutionError, match="never be resolved"):
            validate_provider_response(_synthetic_verified_record(tmp_path, entry, [{"blocker_resolved": token}]), evidence_root=tmp_path)


def test_L_promotion_still_requires_the_full_validator(registry):
    for name in CANONICAL_STATE:
        with pytest.raises(AccessReadinessError):
            promote_access_status(_entry(registry, name), "PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK")
    with pytest.raises(ProviderResolutionError, match="not a counting"):
        promote_access_status(_entry(registry, "DeepSeek V4.1-Flash"), "UNQUALIFIED")


def test_L_one_resolved_dimension_is_not_enough_but_all_resolved_is(registry, tmp_path):
    """Machinery proof on a SYNTHETIC fixture (tmp_path only): the gate is
    passable solely through verified evidence AND the validator."""
    entry = _entry(registry, "DeepSeek V4.1-Flash")
    changes = [_holdout_change(), {"blocker_resolved": "PRIVATE_HOLDOUT_CONFIDENTIALITY_UNRESOLVED"},
               {"blocker_resolved": "WRITTEN_PROVIDER_CLARIFICATION_REQUIRED"}]
    record = _synthetic_verified_record(tmp_path, entry, changes)
    setting = _synthetic_account_setting(tmp_path, entry)

    step1 = apply_verified_evidence(entry, "private_holdout_status", "PERMITTED", provider_responses=[record],
                                    account_setting_records=[setting], evidence_root=tmp_path, requires_account_setting=True)
    with pytest.raises(AccessReadinessError, match="non_financial_blocker_status"):
        promote_access_status(step1, "PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK")  # blockers remain

    step2 = resolve_blocker_token(step1, "PRIVATE_HOLDOUT_CONFIDENTIALITY_UNRESOLVED", provider_responses=[record], evidence_root=tmp_path)
    step3 = resolve_blocker_token(step2, "WRITTEN_PROVIDER_CLARIFICATION_REQUIRED", provider_responses=[record], evidence_root=tmp_path)
    assert step3["non_financial_blocker_status"] == "NONE"
    assert step3["access_preflight_status"] == "UNQUALIFIED"  # still not promoted until the validator runs

    promoted = promote_access_status(step3, "PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK")
    assert promoted["full_protocol_access_validation"] == "PASSED"
    assert compute_admission_quorum([promoted]).quorum_counting_count == 1
    # the untouched registry entry still does not count
    assert compute_admission_quorum([entry]).quorum_counting_count == 0


# ── M-P: nothing was sent, changed, or accepted ─────────────────────────


def test_M_minimax_notice_remains_unsent(registry, queue):
    notice = _action(queue, "MNX-02")
    assert notice["action_type"] == "SEND_COMMERCIAL_NOTICE"
    assert notice["executed_status"] == "NOT_EXECUTED" and notice["authorization_status"] == "NOT_AUTHORIZED"
    assert notice["depends_on"] == ["MNX-01"]
    assert queue["commercial_notices_sent"] == 0
    minimax = _entry(registry, "MiniMax M3")
    assert minimax["license_or_terms_status"] == "REVIEW_REQUIRED"
    assert "COMMERCIAL_USE_AMBIGUITY" in minimax["non_financial_blocker_status"]
    assert "NOT sent" in PACKETS_PATH.read_text() or "not sent" in PACKETS_PATH.read_text()


def test_N_deepseek_optout_remains_unexercised(registry, queue):
    for action_id in ("DSK-02", "DSK-03"):
        assert _action(queue, action_id)["executed_status"] == "NOT_EXECUTED"
    assert _action(queue, "DSK-02")["action_type"] == "INSPECT_PROVIDER_ACCOUNT_SETTING"
    assert _entry(registry, "DeepSeek V4.1-Flash")["private_holdout_status"] == "REVIEW_REQUIRED"


def test_O_mistral_setting_remains_unchanged(registry, queue):
    for action_id in ("MIS-02", "MIS-03"):
        assert _action(queue, action_id)["executed_status"] == "NOT_EXECUTED"
    assert queue["account_settings_changed"] == 0
    mistral = _entry(registry, "Mistral Large 3")
    assert mistral["private_holdout_status"] == "REVIEW_REQUIRED"
    assert "PROVIDER_ACCOUNT_SETTING_REQUIRED" in mistral["non_financial_blocker_status"]


def test_P_kimi_enterprise_agreement_nonexistent_and_unverified(registry, queue):
    agreement = _action(queue, "KMI-02")
    assert agreement["action_type"] == "ACCEPT_ENTERPRISE_TERM"
    assert agreement["executed_status"] == "NOT_EXECUTED" and agreement["verified_evidence_ref"] is None
    kimi = _entry(registry, "Kimi K3")
    assert kimi["private_holdout_status"] == "BLOCKED"
    assert "PROVIDER_TRAINING_ON_INPUTS" in kimi["non_financial_blocker_status"]
    assert "ordinary hosted terms" in PACKETS_PATH.read_text().lower()


# ── Q/R/S: preserved findings, honest quorum, program state ─────────────


def test_Q_qwen_private_holdout_finding_preserved(registry):
    qwen = _entry(registry, "Qwen3.8-Max")
    assert qwen["private_holdout_status"] == "PERMITTED"
    assert qwen["model_identity_attributable"] is False
    assert qwen["access_preflight_status"] == "UNQUALIFIED"
    assert "not reopened" in PACKETS_PATH.read_text()


def test_R_full_protocol_quorum_remains_honest(registry):
    report = compute_admission_quorum(list(registry.frontier_references))
    assert report.validated_access_preflight_ready_count == 0
    assert report.quorum_counting_count == 0
    assert report.independent_lineage_count == 0
    assert report.quorum_status == "QUORUM_BLOCKED"


def test_S_phase_21c_remains_unauthorized(queue):
    text = PLAN_PATH.read_text()
    assert "PHASE 21C: NOT AUTHORIZED" in text
    assert "FRONTIER EXECUTION AUTHORIZED: NO" in text
    run = _action(queue, "GLB-02")
    assert run["action_type"] == "RUN_FRONTIER_API" and run["state"] == "BLOCKED"


# ── quorum-recovery dependency graph ────────────────────────────────────


def test_conditional_path_is_computed_not_claimed(registry, queue):
    path = compute_minimum_conditional_path(list(registry.frontier_references), queue["actions"])
    assert path["achieved"] is False
    primary = path["primary"]
    assert len(primary["references"]) == MINIMUM_USABLE_REFERENCES
    assert len(primary["organizations"]) >= MINIMUM_INDEPENDENT_ORGANIZATIONS
    assert primary["references"] == ["DeepSeek V4.1-Flash", "GLM-5.3 (flagship)", "Mistral Large 3", "Qwen3.8-Max"]
    assert path["fallbacks"] and "MiniMax M3" in path["fallbacks"][0]["references"]
    assert "Kimi K3" not in primary["references"]  # highest contract burden


def test_dependency_graph_covers_all_six_references(queue):
    graph = queue["dependency_graph"]
    assert {g["reference"] for g in graph} == set(EXPECTED_REFERENCE_NAMES)
    for row in graph:
        for key in ("blockers", "owner_actions", "provider_actions", "evidence_needed",
                    "machine_fields_potentially_changed", "readiness_result"):
            assert row[key]


def test_prepared_artifact_targets_exist(queue):
    for action in queue["actions"]:
        target = action["prepared_artifact"].split("#")[0]
        assert (REPO_ROOT / target).is_file(), (action["action_id"], target)


def test_packets_contain_every_question_id_and_no_holdout_material():
    text = PACKETS_PATH.read_text()
    for prefix, count in (("MIS", 8), ("DSK", 8), ("KMI", 12), ("GLM", 10), ("MNX", 2), ("QWN", 8)):
        for i in range(1, count + 1):
            assert f"{prefix}-Q{i} " in text, (prefix, i)
    assert "MESSAGES SENT: 0" in text
    assert "No confidential material" in text


# ── artifacts and integrity ─────────────────────────────────────────────


def test_resolution_sha256_index_hashes_exactly():
    index = json.loads(INDEX_PATH.read_text())
    assert len(index["entries"]) == 5
    for entry in index["entries"]:
        path = REPO_ROOT / entry["path"]
        assert path.is_file(), entry["path"]
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["path"]
        assert len(data) == entry["size_bytes"]


# ── T: no execution code introduced ─────────────────────────────────────


def test_T_no_frontier_execution_or_outreach_code_introduced():
    text = RESOLUTION_PY.read_text()
    for forbidden in ("chat.completions.create(", "responses.create(", "requests.post(", "from_pretrained(",
                      "snapshot_download(", ".generate(", "gpu=", "modal.Gpu", "H100", "H200", "A100", "B200"):
        assert forbidden not in text, forbidden
    tree = ast.parse(text)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for banned in ("smtplib", "email", "subprocess", "webbrowser", "selenium", "playwright", "requests",
                   "urllib", "httpx", "http", "socket", "openai", "anthropic", "modal", "torch", "transformers"):
        assert banned not in imported, banned
