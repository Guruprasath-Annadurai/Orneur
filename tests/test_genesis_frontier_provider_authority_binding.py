"""Phase 21B.4.19.1: provider-resolution AUTHORITY + PROVIDER BINDING +
DEPENDENCY + EVIDENCE-REFERENCE closure.

CONTROL-PLANE TESTS ONLY -- no provider was contacted, no account touched,
no API called. Closes four defects found by independent audit:
  1. provider/reference evidence was not machine-bound;
  2. an arbitrary non-empty dict could authorize an action;
  3. depends_on was descriptive, not enforced;
  4. execution/verified evidence references were not durably validated.

Every "synthetic" record below lives only in pytest's tmp_path, is labeled
SYNTHETIC TEST FIXTURE, and exists solely to exercise the validators. None
of it is evidence, none of it is written into the repository, and no real
queue action is ever authorized, executed or resolved by these tests.
"""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from orca.eval.candidate_registry import CandidateExecutionRegistry, EXPECTED_REFERENCE_NAMES
from orca.eval.frontier_provider_resolution import (
    GLOBAL_ACTION_IDS,
    OFFICIAL_PROVIDER_DOMAINS,
    PROVIDER_QUESTION_PREFIX,
    REFERENCE_PROVIDER,
    ProviderResolutionError,
    advance_action_state,
    assert_queue_fully_unauthorized,
    build_action_lookup,
    build_verified_account_setting_evidence_ref,
    build_verified_provider_evidence_ref,
    validate_account_setting_evidence,
    validate_action,
    validate_action_queue,
    validate_owner_authorization,
    validate_provider_response,
    validate_verified_evidence_ref,
)
from orca.eval.frontier_reference_admission_quorum import compute_admission_quorum

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CANDIDATE_EXECUTION_REGISTRY.json"
QUEUE_PATH = REPO_ROOT / "docs/orneur/phase-21/evidence/GENESIS_FRONTIER_PROVIDER_ACTION_QUEUE_2026-09-24.json"

AUTH_TS = "2000-01-01T00:00:00Z"
EXEC_TS = "2000-01-02T00:00:00Z"

EXPECTED_ACTION_IDS = {
    "QWN-01", "MIS-01", "DSK-01", "GLM-01", "MIS-02", "DSK-02", "DSK-03", "MNX-01", "KMI-01",
    "GLM-02", "MIS-03", "MNX-02", "KMI-02", "GLB-01", "GLB-02",
}
EXPECTED_DEPENDS_ON = {
    "MIS-02": ["MIS-01"], "MIS-03": ["MIS-01"], "DSK-03": ["DSK-01", "DSK-02"],
    "GLM-02": ["GLM-01"], "MNX-02": ["MNX-01"], "KMI-02": ["KMI-01"],
}
EXPECTED_REFERENCE_PROVIDER = {
    "DeepSeek V4.1-Flash": "DeepSeek AI",
    "GLM-5.3 (flagship)": "Zhipu AI / Z.ai",
    "Mistral Large 3": "Mistral AI",
    "MiniMax M3": "MiniMax",
    "Qwen3.8-Max": "Alibaba",
    "Kimi K3": "Moonshot AI",
}


@pytest.fixture(scope="module")
def registry():
    return CandidateExecutionRegistry.load(REGISTRY_PATH)


@pytest.fixture(scope="module")
def queue():
    return json.loads(QUEUE_PATH.read_text())


def _action(queue, action_id):
    return copy.deepcopy(next(a for a in queue["actions"] if a["action_id"] == action_id))


def _auth(action_id, /, **overrides):
    """SYNTHETIC TEST FIXTURE -- a structurally valid owner authorization."""
    record = {
        "action_id": action_id,
        "decision": "AUTHORIZED",
        "authorized_by_role": "OWNER",
        "authorized_at_utc": AUTH_TS,
        "authorization_source_kind": "OWNER_CHAT_MESSAGE",
        "authorization_source_ref": "synthetic-test-fixture/owner-message-1",
        "scope": "EXACT_ACTION_ONLY",
    }
    record.update(overrides)
    return record


def _exec_evidence(action, **overrides):
    """SYNTHETIC TEST FIXTURE -- structurally valid execution evidence."""
    record = {
        "action_id": action["action_id"],
        "action_type": action["action_type"],
        "provider": action["provider"],
        "reference_name": action["reference_name"],
        "executed_at_utc": EXEC_TS,
        "source_ref": "synthetic-test-fixture/sent-record-1",
    }
    record.update(overrides)
    return record


def _provider_record(tmp_path, provider, reference_name, *, sender_domain=None, tier="B", status="VERIFIED",
                     question_ids=None):
    """SYNTHETIC TEST FIXTURE -- NOT EVIDENCE. Exercises the validators only."""
    raw = tmp_path / "synthetic_response.txt"
    raw.write_bytes(b"SYNTHETIC TEST FIXTURE - NOT EVIDENCE")
    return {
        "provider": provider,
        "reference_name": reference_name,
        "incoming_channel": "EMAIL",
        "sender_identity": "SYNTHETIC",
        "sender_domain": sender_domain or OFFICIAL_PROVIDER_DOMAINS[provider][0],
        "message_id": "SYNTHETIC-1",
        "received_at_utc": "2000-01-03T00:00:00Z",
        "question_ids_answered": question_ids or [PROVIDER_QUESTION_PREFIX[provider] + "1"],
        "raw_response_location": "synthetic_response.txt",
        "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
        "quoted_authoritative_clauses": ["SYNTHETIC CLAUSE"],
        "interpretation": "SYNTHETIC",
        "remaining_ambiguity": [],
        "evidence_tier": tier,
        "review_status": status,
        "approved_state_changes": [],
        "reviewer": "SYNTHETIC-REVIEWER",
        "expiry_or_freshness": "SYNTHETIC",
    }


def _account_record(tmp_path, provider, reference_name, **overrides):
    """SYNTHETIC TEST FIXTURE -- NOT EVIDENCE."""
    shot = tmp_path / "synthetic_screenshot.bin"
    shot.write_bytes(b"SYNTHETIC SCREENSHOT - NOT EVIDENCE")
    record = {
        "provider": provider,
        "reference_name": reference_name,
        "account_identifier_category": "ORG_ID_REDACTED",
        "setting_name": "SYNTHETIC",
        "old_state": "ENABLED",
        "new_state": "DISABLED",
        "effective_scope": "SYNTHETIC",
        "effective_timestamp_utc": "2000-01-03T00:00:00Z",
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


def _to_awaiting(action):
    """Move a queue action to AWAITING_OWNER_AUTHORIZATION without any gate."""
    if action["state"] == "PREPARED":
        return advance_action_state(action, "AWAITING_OWNER_AUTHORIZATION")
    return action


def _drive(action, target, tmp_path, *, lookup=None):
    """Drive a SYNTHETIC copy of an action forward through the real state
    machine using synthetic evidence in tmp_path, up to `target`."""
    order = ["AUTHORIZED_NOT_EXECUTED", "EXECUTED_AWAITING_PROVIDER", "PROVIDER_REPLIED_UNVERIFIED",
             "EVIDENCE_VERIFIED", "RESOLVED"]
    action = _to_awaiting(action)
    record = _provider_record(tmp_path, action["provider"], action["reference_name"])
    common = dict(evidence_root=tmp_path, dependency_actions=lookup)
    for state in order:
        kwargs = dict(common)
        if state == "AUTHORIZED_NOT_EXECUTED":
            kwargs["authorization_evidence"] = _auth(action["action_id"])
        elif state == "EXECUTED_AWAITING_PROVIDER":
            kwargs["execution_evidence"] = _exec_evidence(action)
        elif state == "PROVIDER_REPLIED_UNVERIFIED":
            kwargs["received_record"] = record
        elif state == "EVIDENCE_VERIFIED":
            kwargs["verified_evidence_record"] = record
        action = advance_action_state(action, state, **kwargs)
        if state == target:
            return action
    raise AssertionError(f"unknown target {target}")


# ══ §3: canonical provider <-> reference mapping ═════════════════════════


def test_canonical_reference_provider_mapping_is_exact(registry):
    assert REFERENCE_PROVIDER == EXPECTED_REFERENCE_PROVIDER
    assert set(REFERENCE_PROVIDER) == set(EXPECTED_REFERENCE_NAMES)
    for entry in registry.frontier_references:
        assert REFERENCE_PROVIDER[entry["reference_name"]] == entry["organization"]
    assert set(REFERENCE_PROVIDER.values()) == set(OFFICIAL_PROVIDER_DOMAINS) == set(PROVIDER_QUESTION_PREFIX)


# ══ §23: cross-provider binding ══════════════════════════════════════════


def test_A_deepseek_response_targeting_qwen_is_rejected(tmp_path):
    record = _provider_record(tmp_path, "DeepSeek AI", "Qwen3.8-Max", sender_domain="deepseek.com")
    with pytest.raises(ProviderResolutionError, match="does not own reference"):
        validate_provider_response(record, evidence_root=tmp_path)
    # binding applies even before/without full verification
    unreviewed = _provider_record(tmp_path, "DeepSeek AI", "Qwen3.8-Max", status="UNREVIEWED")
    with pytest.raises(ProviderResolutionError, match="does not own reference"):
        validate_provider_response(unreviewed, evidence_root=tmp_path)


def test_B_alibaba_response_targeting_deepseek_is_rejected(tmp_path):
    record = _provider_record(tmp_path, "Alibaba", "DeepSeek V4.1-Flash", sender_domain="alibabacloud.com")
    with pytest.raises(ProviderResolutionError, match="does not own reference"):
        validate_provider_response(record, evidence_root=tmp_path)


def test_C_deepseek_account_setting_targeting_mistral_is_rejected(tmp_path):
    record = _account_record(tmp_path, "DeepSeek AI", "Mistral Large 3")
    with pytest.raises(ProviderResolutionError, match="does not own reference"):
        validate_account_setting_evidence(record, evidence_root=tmp_path)
    with pytest.raises(ProviderResolutionError, match="does not own reference"):
        build_verified_account_setting_evidence_ref(record, evidence_root=tmp_path)


def test_D_mistral_action_targeting_qwen_is_rejected(queue):
    action = _action(queue, "MIS-01")
    action["reference_name"] = "Qwen3.8-Max"
    with pytest.raises(ProviderResolutionError, match="does not own reference"):
        validate_action(action)


def test_D_all_wildcards_only_allowed_for_documented_global_actions(queue):
    for provider, reference in (("ALL", "Qwen3.8-Max"), ("Alibaba", "ALL")):
        action = _action(queue, "QWN-01")
        action["provider"], action["reference_name"] = provider, reference
        with pytest.raises(ProviderResolutionError, match="ALL"):
            validate_action(action)
    # non-global action id with ALL/ALL
    action = _action(queue, "QWN-01")
    action["provider"] = action["reference_name"] = "ALL"
    with pytest.raises(ProviderResolutionError, match="documented global action"):
        validate_action(action)
    # a documented global action may not be pinned to a specific provider/reference
    for gid in GLOBAL_ACTION_IDS:
        action = _action(queue, gid)
        action["provider"], action["reference_name"] = "Mistral AI", "Mistral Large 3"
        with pytest.raises(ProviderResolutionError, match="must use provider=ALL"):
            validate_action(action)
    # a non-global action type may not hide behind a global id
    action = _action(queue, "GLB-01")
    action["action_type"] = "SEND_PROVIDER_EMAIL"
    with pytest.raises(ProviderResolutionError, match="documented global action"):
        validate_action(action)


def test_E_correct_provider_reference_pairs_pass(queue, tmp_path):
    for reference, provider in EXPECTED_REFERENCE_PROVIDER.items():
        validate_provider_response(_provider_record(tmp_path, provider, reference), evidence_root=tmp_path)
        validate_account_setting_evidence(_account_record(tmp_path, provider, reference), evidence_root=tmp_path)
    validate_action_queue(queue)  # every real action is correctly bound


def test_question_family_binding(tmp_path):
    # A Qwen response may not claim to have answered a DeepSeek question.
    bad = _provider_record(tmp_path, "Alibaba", "Qwen3.8-Max", question_ids=["DSK-Q1"])
    with pytest.raises(ProviderResolutionError, match="documented family"):
        validate_provider_response(bad, evidence_root=tmp_path)
    for malformed in ("QWN-Q", "QWN-1", "Q1", "", 7):
        with pytest.raises(ProviderResolutionError, match="documented family"):
            validate_provider_response(
                _provider_record(tmp_path, "Alibaba", "Qwen3.8-Max", question_ids=[malformed]), evidence_root=tmp_path)
    # documented prefix, including a future follow-up suffix, is accepted
    for ok in ("QWN-Q1", "QWN-Q8", "QWN-Q3a", "QWN-Q12.1"):
        validate_provider_response(
            _provider_record(tmp_path, "Alibaba", "Qwen3.8-Max", question_ids=[ok]), evidence_root=tmp_path)


# ══ §24: owner authorization ═════════════════════════════════════════════


def test_auth_A_arbitrary_nonempty_dict_does_not_authorize(queue):
    action = _to_awaiting(_action(queue, "MIS-01"))
    for junk in ({"note": "yes"}, {"note": "SYNTHETIC TEST AUTHORIZATION"}, {"authorized": True},
                 {"action_id": "MIS-01"}, "yes", ["MIS-01"], 1):
        with pytest.raises(ProviderResolutionError):
            advance_action_state(action, "AUTHORIZED_NOT_EXECUTED", authorization_evidence=junk)
    with pytest.raises(ProviderResolutionError):
        advance_action_state(action, "AUTHORIZED_NOT_EXECUTED")  # no evidence at all
    # a hand-built action claiming AUTHORIZED with junk evidence is invalid too
    claimed = copy.deepcopy(action)
    claimed.update(authorization_status="AUTHORIZED", state="AUTHORIZED_NOT_EXECUTED", authorization_evidence={"note": "yes"})
    with pytest.raises(ProviderResolutionError):
        validate_action(claimed)


@pytest.mark.parametrize("overrides,match", [
    ({"authorized_by_role": "CLAUDE"}, "role OWNER"),
    ({"authorized_by_role": "owner"}, "role OWNER"),
    ({"authorized_by_role": "CHATGPT"}, "role OWNER"),
    ({"decision": "DECLINED"}, "decision must be AUTHORIZED"),
    ({"decision": "authorized"}, "decision must be AUTHORIZED"),
    ({"scope": "ALL_PROVIDER_ACTIONS"}, "EXACT_ACTION_ONLY"),
    ({"scope": "PROVIDER_WIDE"}, "EXACT_ACTION_ONLY"),
    ({"scope": "PHASE_WIDE"}, "EXACT_ACTION_ONLY"),
    ({"scope": "*"}, "EXACT_ACTION_ONLY"),
    ({"authorization_source_ref": ""}, "non-empty"),
    ({"authorization_source_ref": "   "}, "non-empty"),
    ({"authorization_source_ref": "*"}, "wildcard"),
    ({"authorization_source_ref": "ALL"}, "wildcard"),
    ({"authorization_source_kind": "SELF_ASSERTED"}, "authorization_source_kind"),
    ({"authorized_at_utc": "yesterday"}, "UTC ISO-8601"),
    ({"authorized_at_utc": "2000-01-01"}, "UTC ISO-8601"),
    ({"authorized_at_utc": "2000-01-01T00:00:00+00:00"}, "UTC ISO-8601"),
    ({"authorized_at_utc": "2000-13-45T00:00:00Z"}, "not a valid timestamp"),
    ({"authorized_at_utc": ""}, "UTC ISO-8601"),
    ({"action_id": "ALL"}, "not 'MIS-01'"),
    ({"action_id": "*"}, "not 'MIS-01'"),
    ({"action_id": "MIS-02"}, "exactly one action"),
])
def test_auth_C_to_G_each_field_is_required_and_strict(overrides, match):
    with pytest.raises(ProviderResolutionError, match=match):
        validate_owner_authorization(_auth("MIS-01", **overrides), action_id="MIS-01")


def test_auth_missing_or_extra_fields_are_rejected():
    for field in ("action_id", "decision", "authorized_by_role", "authorized_at_utc",
                  "authorization_source_kind", "authorization_source_ref", "scope"):
        record = _auth("MIS-01")
        del record[field]
        with pytest.raises(ProviderResolutionError, match="missing required"):
            validate_owner_authorization(record, action_id="MIS-01")
    with pytest.raises(ProviderResolutionError, match="unexpected field"):
        validate_owner_authorization(_auth("MIS-01", also_authorizes=["MIS-02", "MIS-03"]), action_id="MIS-01")
    with pytest.raises(ProviderResolutionError, match="unexpected field"):
        validate_owner_authorization(_auth("MIS-01", providers=["ALL"]), action_id="MIS-01")


def test_auth_H_correct_structured_authorization_allows_synthetic_action(queue):
    action = _to_awaiting(_action(queue, "MIS-01"))
    authorized = advance_action_state(action, "AUTHORIZED_NOT_EXECUTED", authorization_evidence=_auth("MIS-01"))
    assert authorized["state"] == "AUTHORIZED_NOT_EXECUTED"
    assert authorized["authorization_status"] == "AUTHORIZED"
    assert authorized["authorization_evidence"] == _auth("MIS-01")
    assert authorized["executed_status"] == "NOT_EXECUTED"
    # the source action (and the real queue) is untouched
    assert action["authorization_status"] == "NOT_AUTHORIZED" and action["authorization_evidence"] is None


# ══ §8: one authorization = one action ═══════════════════════════════════


@pytest.mark.parametrize("granted,other", [
    ("MIS-01", "MIS-02"), ("MIS-01", "MIS-03"), ("DSK-01", "DSK-02"), ("DSK-01", "DSK-03"),
    ("GLM-01", "GLM-02"), ("MNX-01", "MNX-02"), ("KMI-01", "KMI-02"),
    ("MIS-01", "DSK-01"), ("QWN-01", "MIS-01"), ("GLM-01", "KMI-01"),
])
def test_one_authorization_never_authorizes_another_action(queue, tmp_path, granted, other):
    target = _to_awaiting(_action(queue, other))
    # supply a fully-resolved dependency context so ONLY the authorization
    # binding is under test
    lookup = {}
    for dep in target["depends_on"]:
        lookup[dep] = _drive(_action(queue, dep), "RESOLVED", tmp_path)
    with pytest.raises(ProviderResolutionError, match="exactly one action"):
        advance_action_state(target, "AUTHORIZED_NOT_EXECUTED", authorization_evidence=_auth(granted),
                             evidence_root=tmp_path, dependency_actions=lookup or None)


def test_authorization_does_not_imply_dependency_authorization(queue, tmp_path):
    """Authorizing MIS-02 does not authorize (or resolve) MIS-01."""
    mis01 = _to_awaiting(_action(queue, "MIS-01"))
    assert mis01["authorization_status"] == "NOT_AUTHORIZED"
    with pytest.raises(ProviderResolutionError, match="exactly one action"):
        advance_action_state(mis01, "AUTHORIZED_NOT_EXECUTED", authorization_evidence=_auth("MIS-02"))


# ══ §10/§11/§25: dependency enforcement ══════════════════════════════════


def test_depends_on_matches_the_specified_graph(queue):
    actual = {a["action_id"]: a["depends_on"] for a in queue["actions"] if a["depends_on"]}
    assert actual == EXPECTED_DEPENDS_ON


@pytest.mark.parametrize("dep_state", [
    "AWAITING_OWNER_AUTHORIZATION", "AUTHORIZED_NOT_EXECUTED", "EXECUTED_AWAITING_PROVIDER",
    "PROVIDER_REPLIED_UNVERIFIED", "EVIDENCE_VERIFIED",
])
def test_MIS02_cannot_authorize_until_MIS01_is_RESOLVED(queue, tmp_path, dep_state):
    mis01 = _action(queue, "MIS-01")
    dep = mis01 if dep_state == "AWAITING_OWNER_AUTHORIZATION" else _drive(mis01, dep_state, tmp_path)
    assert dep["state"] == dep_state
    mis02 = _to_awaiting(_action(queue, "MIS-02"))
    with pytest.raises(ProviderResolutionError, match="cannot proceed"):
        advance_action_state(mis02, "AUTHORIZED_NOT_EXECUTED", authorization_evidence=_auth("MIS-02"),
                             evidence_root=tmp_path, dependency_actions={"MIS-01": dep})


def test_MIS02_authorizes_once_MIS01_is_RESOLVED_and_owner_authorizes_independently(queue, tmp_path):
    resolved = _drive(_action(queue, "MIS-01"), "RESOLVED", tmp_path)
    assert resolved["state"] == "RESOLVED"
    mis02 = _to_awaiting(_action(queue, "MIS-02"))
    authorized = advance_action_state(mis02, "AUTHORIZED_NOT_EXECUTED", authorization_evidence=_auth("MIS-02"),
                                      evidence_root=tmp_path, dependency_actions={"MIS-01": resolved})
    assert authorized["state"] == "AUTHORIZED_NOT_EXECUTED"
    # ...and the resolved dependency's own authorization does NOT substitute
    with pytest.raises(ProviderResolutionError, match="exactly one action"):
        advance_action_state(mis02, "AUTHORIZED_NOT_EXECUTED", authorization_evidence=_auth("MIS-01"),
                             evidence_root=tmp_path, dependency_actions={"MIS-01": resolved})
    # execution is dependency-gated as well
    executed = advance_action_state(authorized, "EXECUTED_AWAITING_PROVIDER", execution_evidence=_exec_evidence(authorized),
                                    evidence_root=tmp_path, dependency_actions={"MIS-01": resolved})
    assert executed["executed_status"] == "EXECUTED"
    stale_dep = _drive(_action(queue, "MIS-01"), "EVIDENCE_VERIFIED", tmp_path)
    with pytest.raises(ProviderResolutionError, match="cannot proceed"):
        advance_action_state(authorized, "EXECUTED_AWAITING_PROVIDER", execution_evidence=_exec_evidence(authorized),
                             evidence_root=tmp_path, dependency_actions={"MIS-01": stale_dep})


def test_missing_dependency_context_fails_closed(queue, tmp_path):
    resolved = _drive(_action(queue, "MIS-01"), "RESOLVED", tmp_path)
    mis02 = _to_awaiting(_action(queue, "MIS-02"))
    kwargs = dict(authorization_evidence=_auth("MIS-02"))
    with pytest.raises(ProviderResolutionError, match="dependency_actions context is mandatory"):
        advance_action_state(mis02, "AUTHORIZED_NOT_EXECUTED", evidence_root=tmp_path, **kwargs)
    with pytest.raises(ProviderResolutionError, match="dependency_actions context is mandatory"):
        advance_action_state(mis02, "AUTHORIZED_NOT_EXECUTED", evidence_root=tmp_path, dependency_actions={}, **kwargs)
    with pytest.raises(ProviderResolutionError, match="evidence_root is mandatory"):
        advance_action_state(mis02, "AUTHORIZED_NOT_EXECUTED", dependency_actions={"MIS-01": resolved}, **kwargs)
    with pytest.raises(ProviderResolutionError, match="missing from the dependency context"):
        advance_action_state(mis02, "AUTHORIZED_NOT_EXECUTED", evidence_root=tmp_path,
                             dependency_actions={"DSK-01": resolved}, **kwargs)


def test_dependency_claiming_RESOLVED_must_re_prove_its_evidence(queue, tmp_path):
    """A hand-built dependency that merely claims RESOLVED (or whose
    persisted evidence changed) is not accepted."""
    resolved = _drive(_action(queue, "MIS-01"), "RESOLVED", tmp_path)
    mis02 = _to_awaiting(_action(queue, "MIS-02"))
    forged = copy.deepcopy(resolved)
    forged["verified_evidence_ref"]["sha256"] = "0" * 64
    with pytest.raises(ProviderResolutionError, match="no longer matches"):
        advance_action_state(mis02, "AUTHORIZED_NOT_EXECUTED", authorization_evidence=_auth("MIS-02"),
                             evidence_root=tmp_path, dependency_actions={"MIS-01": forged})
    fake_resolved = _to_awaiting(_action(queue, "MIS-01"))
    fake_resolved["state"] = "RESOLVED"
    with pytest.raises(ProviderResolutionError):
        advance_action_state(mis02, "AUTHORIZED_NOT_EXECUTED", authorization_evidence=_auth("MIS-02"),
                             evidence_root=tmp_path, dependency_actions={"MIS-01": fake_resolved})
    # tamper with the persisted source after resolution
    (tmp_path / "synthetic_response.txt").write_bytes(b"TAMPERED")
    with pytest.raises(ProviderResolutionError, match="no longer matches"):
        advance_action_state(mis02, "AUTHORIZED_NOT_EXECUTED", authorization_evidence=_auth("MIS-02"),
                             evidence_root=tmp_path, dependency_actions={"MIS-01": resolved})


@pytest.mark.parametrize("dependent", ["MIS-02", "MIS-03", "DSK-03", "GLM-02", "MNX-02", "KMI-02"])
def test_every_dependent_action_is_gated_by_the_real_queue(queue, tmp_path, dependent):
    lookup = build_action_lookup(queue)
    action = _to_awaiting(_action(queue, dependent))
    with pytest.raises(ProviderResolutionError, match="cannot proceed"):
        advance_action_state(action, "AUTHORIZED_NOT_EXECUTED", authorization_evidence=_auth(dependent),
                             evidence_root=tmp_path, dependency_actions=lookup)


def test_DSK03_requires_BOTH_dependencies(queue, tmp_path):
    dsk01 = _drive(_action(queue, "DSK-01"), "RESOLVED", tmp_path)
    dsk02 = _drive(_action(queue, "DSK-02"), "RESOLVED", tmp_path)
    dsk02_unresolved = _drive(_action(queue, "DSK-02"), "EVIDENCE_VERIFIED", tmp_path)
    dsk01_unresolved = _drive(_action(queue, "DSK-01"), "PROVIDER_REPLIED_UNVERIFIED", tmp_path)
    dsk03 = _to_awaiting(_action(queue, "DSK-03"))
    common = dict(authorization_evidence=_auth("DSK-03"), evidence_root=tmp_path)
    with pytest.raises(ProviderResolutionError, match="'DSK-02'"):
        advance_action_state(dsk03, "AUTHORIZED_NOT_EXECUTED", dependency_actions={"DSK-01": dsk01, "DSK-02": dsk02_unresolved}, **common)
    with pytest.raises(ProviderResolutionError, match="'DSK-01'"):
        advance_action_state(dsk03, "AUTHORIZED_NOT_EXECUTED", dependency_actions={"DSK-01": dsk01_unresolved, "DSK-02": dsk02}, **common)
    with pytest.raises(ProviderResolutionError, match="missing from the dependency context"):
        advance_action_state(dsk03, "AUTHORIZED_NOT_EXECUTED", dependency_actions={"DSK-01": dsk01}, **common)
    ok = advance_action_state(dsk03, "AUTHORIZED_NOT_EXECUTED", dependency_actions={"DSK-01": dsk01, "DSK-02": dsk02}, **common)
    assert ok["state"] == "AUTHORIZED_NOT_EXECUTED"


def test_queue_level_dependency_consistency_and_cycles(queue):
    # a dependent action claiming to be authorized while its dependency is not RESOLVED
    tampered = copy.deepcopy(queue)
    mis02 = next(a for a in tampered["actions"] if a["action_id"] == "MIS-02")
    mis02.update(authorization_status="AUTHORIZED", state="AUTHORIZED_NOT_EXECUTED", authorization_evidence=_auth("MIS-02"))
    validate_action(mis02)  # individually well-formed...
    with pytest.raises(ProviderResolutionError, match="dependency 'MIS-01'"):
        validate_action_queue(tampered)  # ...but not consistent with the queue
    cyclic = copy.deepcopy(queue)
    next(a for a in cyclic["actions"] if a["action_id"] == "MIS-01")["depends_on"] = ["MIS-02"]
    with pytest.raises(ProviderResolutionError, match="cycle"):
        validate_action_queue(cyclic)
    selfdep = _action(queue, "MIS-01")
    selfdep["depends_on"] = ["MIS-01"]
    with pytest.raises(ProviderResolutionError, match="depend on itself"):
        validate_action(selfdep)


# ══ §12: BLOCKED global frontier action ══════════════════════════════════


def test_GLB02_blocked_cannot_be_moved_by_authorization_or_dependencies(queue, tmp_path):
    blocked = _action(queue, "GLB-02")
    assert blocked["state"] == "BLOCKED" and blocked["action_type"] == "RUN_FRONTIER_API"
    for state in ("AUTHORIZED_NOT_EXECUTED", "EXECUTED_AWAITING_PROVIDER", "PREPARED", "RESOLVED"):
        with pytest.raises(ProviderResolutionError, match="not permitted"):
            advance_action_state(blocked, state, authorization_evidence=_auth("GLB-02"),
                                 evidence_root=tmp_path, dependency_actions=build_action_lookup(queue))
    # a global action can never hold provider-bound verified evidence
    forged = copy.deepcopy(blocked)
    forged.update(state="RESOLVED", executed_status="EXECUTED", authorization_status="AUTHORIZED",
                  authorization_evidence=_auth("GLB-02"), execution_evidence_ref=_exec_evidence(blocked),
                  verified_evidence_ref={"evidence_type": "PROVIDER_RESPONSE"})
    with pytest.raises(ProviderResolutionError):
        validate_action(forged)


# ══ §13/§14/§26: durable, validated execution evidence ═══════════════════


def _authorized(queue, action_id):
    return advance_action_state(_to_awaiting(_action(queue, action_id)), "AUTHORIZED_NOT_EXECUTED",
                                authorization_evidence=_auth(action_id))


def test_exec_A_random_dict_is_not_execution_evidence(queue):
    action = _authorized(queue, "MIS-01")
    for junk in ({"note": "synthetic"}, {}, None, "sent", {"action_id": "MIS-01"}):
        with pytest.raises(ProviderResolutionError):
            advance_action_state(action, "EXECUTED_AWAITING_PROVIDER", execution_evidence=junk)


@pytest.mark.parametrize("overrides,match", [
    ({"action_id": "MIS-02"}, "action_id"),
    ({"action_id": "*"}, "action_id"),
    ({"provider": "DeepSeek AI"}, "provider"),
    ({"provider": "ALL"}, "provider"),
    ({"reference_name": "Kimi K3"}, "reference_name"),
    ({"action_type": "SEND_COMMERCIAL_NOTICE"}, "action_type"),
    ({"source_ref": ""}, "non-empty"),
    ({"source_ref": "*"}, "wildcard"),
    ({"source_ref": "ALL"}, "wildcard"),
    ({"executed_at_utc": ""}, "UTC ISO-8601"),
    ({"executed_at_utc": "later"}, "UTC ISO-8601"),
    ({"executed_at_utc": "1999-12-31T23:59:59Z"}, "predates"),
])
def test_exec_B_wrong_or_incomplete_execution_evidence_is_rejected(queue, overrides, match):
    action = _authorized(queue, "MIS-01")
    with pytest.raises(ProviderResolutionError, match=match):
        advance_action_state(action, "EXECUTED_AWAITING_PROVIDER", execution_evidence=_exec_evidence(action, **overrides))


def test_exec_missing_field_or_extra_field_is_rejected(queue):
    action = _authorized(queue, "MIS-01")
    for field in ("executed_at_utc", "source_ref", "action_id"):
        record = _exec_evidence(action)
        del record[field]
        with pytest.raises(ProviderResolutionError, match="missing required"):
            advance_action_state(action, "EXECUTED_AWAITING_PROVIDER", execution_evidence=record)
    with pytest.raises(ProviderResolutionError, match="unexpected field"):
        advance_action_state(action, "EXECUTED_AWAITING_PROVIDER", execution_evidence=_exec_evidence(action, extra="x"))


def test_exec_C_valid_structured_evidence_is_persisted_on_the_action(queue):
    action = _authorized(queue, "MIS-01")
    evidence = _exec_evidence(action)
    executed = advance_action_state(action, "EXECUTED_AWAITING_PROVIDER", execution_evidence=evidence)
    assert executed["execution_evidence_ref"] == evidence
    assert executed["executed_status"] == "EXECUTED"


def test_exec_ref_is_required_when_executed_and_forbidden_otherwise(queue):
    executed = advance_action_state(_authorized(queue, "MIS-01"), "EXECUTED_AWAITING_PROVIDER",
                                    execution_evidence=_exec_evidence(_action(queue, "MIS-01")))
    stripped = copy.deepcopy(executed)
    stripped["execution_evidence_ref"] = None
    with pytest.raises(ProviderResolutionError, match="without a persisted execution_evidence_ref"):
        validate_action(stripped)
    stray = _action(queue, "MIS-01")
    stray["execution_evidence_ref"] = _exec_evidence(stray)
    with pytest.raises(ProviderResolutionError, match="NOT_EXECUTED but carries"):
        validate_action(stray)
    swapped = copy.deepcopy(executed)
    swapped["execution_evidence_ref"]["provider"] = "DeepSeek AI"
    with pytest.raises(ProviderResolutionError, match="provider"):
        validate_action(swapped)


def test_exec_evidence_requires_prior_authorization(queue):
    action = _to_awaiting(_action(queue, "MIS-01"))
    with pytest.raises(ProviderResolutionError, match="not permitted"):
        advance_action_state(action, "EXECUTED_AWAITING_PROVIDER", execution_evidence=_exec_evidence(action))


# ══ §15-§18/§27: verified evidence references ════════════════════════════


def _replied(queue, tmp_path, action_id="MIS-01"):
    return _drive(_action(queue, action_id), "PROVIDER_REPLIED_UNVERIFIED", tmp_path)


def test_ref_A_arbitrary_string_cannot_mark_EVIDENCE_VERIFIED_or_RESOLVED(queue, tmp_path):
    replied = _replied(queue, tmp_path)
    for junk in ("SYNTHETIC-REF", "yes", {"note": "x"}, {}, None, ["ref"]):
        with pytest.raises(ProviderResolutionError):
            advance_action_state(replied, "EVIDENCE_VERIFIED", verified_evidence_record=junk, evidence_root=tmp_path)
    with pytest.raises(TypeError):  # the old string-ref keyword no longer exists
        advance_action_state(replied, "EVIDENCE_VERIFIED", verified_evidence_ref="SYNTHETIC-REF", evidence_root=tmp_path)
    with pytest.raises(ProviderResolutionError, match="evidence_root"):
        advance_action_state(replied, "EVIDENCE_VERIFIED",
                             verified_evidence_record=_provider_record(tmp_path, "Mistral AI", "Mistral Large 3"))
    # RESOLVED cannot be reached without a validated ref either
    with pytest.raises(ProviderResolutionError, match="not permitted"):
        advance_action_state(replied, "RESOLVED", evidence_root=tmp_path)
    verified = _drive(_action(queue, "MIS-01"), "EVIDENCE_VERIFIED", tmp_path)
    with pytest.raises(ProviderResolutionError, match="evidence_root"):
        advance_action_state(verified, "RESOLVED")


def test_ref_hand_authored_refs_are_rejected(queue, tmp_path):
    verified = _drive(_action(queue, "MIS-01"), "EVIDENCE_VERIFIED", tmp_path)
    real_ref = verified["verified_evidence_ref"]
    validate_action(verified, evidence_root=tmp_path)

    def tampered(**changes):
        action = copy.deepcopy(verified)
        action["verified_evidence_ref"] = dict(real_ref, **changes)
        return action

    for changes, match in (
        ({"sha256": "0" * 64}, "no longer matches"),
        ({"sha256": "short"}, "64-hex"),
        ({"provider": "DeepSeek AI"}, "bound to"),
        ({"reference_name": "Kimi K3"}, "bound to"),
        ({"source_location": "missing.txt"}, "does not exist"),
        ({"source_location": ""}, "non-empty"),
        ({"source_location": "*"}, "wildcard"),
        ({"evidence_type": "ACCOUNT_SETTING"}, "missing required|unexpected"),
        ({"evidence_type": "MADE_UP"}, "unrecognized evidence_type"),
    ):
        with pytest.raises(ProviderResolutionError, match=match):
            validate_action(tampered(**changes), evidence_root=tmp_path)
    extra = tampered()
    extra["verified_evidence_ref"]["approved_by"] = "me"
    with pytest.raises(ProviderResolutionError, match="unexpected field"):
        validate_action(extra, evidence_root=tmp_path)
    as_string = copy.deepcopy(verified)
    as_string["verified_evidence_ref"] = "SYNTHETIC-REF"
    with pytest.raises(ProviderResolutionError, match="structured reference"):
        validate_action(as_string)


def test_ref_B_evidence_with_wrong_provider_reference_hash_or_tier_fails(queue, tmp_path):
    replied = _replied(queue, tmp_path, "MIS-01")
    # wrong provider/reference (a different provider's genuinely-official record)
    other = _provider_record(tmp_path, "DeepSeek AI", "DeepSeek V4.1-Flash")
    with pytest.raises(ProviderResolutionError, match="bound to"):
        advance_action_state(replied, "EVIDENCE_VERIFIED", verified_evidence_record=other, evidence_root=tmp_path)
    # cross-provider claim inside the record itself
    crossed = _provider_record(tmp_path, "DeepSeek AI", "Mistral Large 3")
    with pytest.raises(ProviderResolutionError, match="does not own reference"):
        advance_action_state(replied, "EVIDENCE_VERIFIED", verified_evidence_record=crossed, evidence_root=tmp_path)
    good = _provider_record(tmp_path, "Mistral AI", "Mistral Large 3")
    with pytest.raises(ProviderResolutionError, match="do not match"):
        advance_action_state(replied, "EVIDENCE_VERIFIED", verified_evidence_record=dict(good, sha256="0" * 64), evidence_root=tmp_path)
    with pytest.raises(ProviderResolutionError, match="Tier D"):
        advance_action_state(replied, "EVIDENCE_VERIFIED",
                             verified_evidence_record=_provider_record(tmp_path, "Mistral AI", "Mistral Large 3", tier="D"),
                             evidence_root=tmp_path)
    with pytest.raises(ProviderResolutionError, match="only a VERIFIED"):
        build_verified_provider_evidence_ref(
            _provider_record(tmp_path, "Mistral AI", "Mistral Large 3", status="UNREVIEWED"), evidence_root=tmp_path)
    with pytest.raises(ProviderResolutionError, match="official domain"):
        advance_action_state(replied, "EVIDENCE_VERIFIED",
                             verified_evidence_record=_provider_record(tmp_path, "Mistral AI", "Mistral Large 3", sender_domain="mistral.ai.evil.io"),
                             evidence_root=tmp_path)


def test_ref_C_valid_synthetic_evidence_derives_a_structured_ref_and_advances_the_action(queue, tmp_path):
    record = _provider_record(tmp_path, "Mistral AI", "Mistral Large 3")
    ref = build_verified_provider_evidence_ref(record, evidence_root=tmp_path)
    assert set(ref) == {"evidence_type", "provider", "reference_name", "source_location", "sha256",
                        "message_id", "evidence_tier", "received_at_utc"}
    assert ref["provider"] == "Mistral AI" and ref["reference_name"] == "Mistral Large 3"
    assert ref["sha256"] == record["sha256"] and ref["evidence_type"] == "PROVIDER_RESPONSE"

    verified = _drive(_action(queue, "MIS-01"), "EVIDENCE_VERIFIED", tmp_path)
    assert verified["verified_evidence_ref"] == ref
    resolved = advance_action_state(verified, "RESOLVED", evidence_root=tmp_path)
    assert resolved["state"] == "RESOLVED" and resolved["verified_evidence_ref"] == ref
    # RESOLVED re-verifies persisted bytes: tampering after verification blocks it
    (tmp_path / "synthetic_response.txt").write_bytes(b"TAMPERED AFTER VERIFICATION")
    with pytest.raises(ProviderResolutionError, match="no longer matches"):
        advance_action_state(verified, "RESOLVED", evidence_root=tmp_path)


def test_ref_evidence_type_must_suit_the_action_type(queue, tmp_path):
    # SEND_PROVIDER_EMAIL cannot be closed by account-setting evidence
    replied = _replied(queue, tmp_path, "MIS-01")
    account = _account_record(tmp_path, "Mistral AI", "Mistral Large 3")
    with pytest.raises(ProviderResolutionError, match="cannot close"):
        advance_action_state(replied, "EVIDENCE_VERIFIED", verified_evidence_record=account, evidence_root=tmp_path)
    # a setting-change action can be closed by account-setting evidence
    mis01 = _drive(_action(queue, "MIS-01"), "RESOLVED", tmp_path)
    mis02 = _to_awaiting(_action(queue, "MIS-02"))
    lookup = {"MIS-01": mis01}
    a = advance_action_state(mis02, "AUTHORIZED_NOT_EXECUTED", authorization_evidence=_auth("MIS-02"),
                             evidence_root=tmp_path, dependency_actions=lookup)
    a = advance_action_state(a, "EXECUTED_AWAITING_PROVIDER", execution_evidence=_exec_evidence(a),
                             evidence_root=tmp_path, dependency_actions=lookup)
    a = advance_action_state(a, "PROVIDER_REPLIED_UNVERIFIED", received_record=account)
    a = advance_action_state(a, "EVIDENCE_VERIFIED", verified_evidence_record=account, evidence_root=tmp_path)
    assert a["verified_evidence_ref"]["evidence_type"] == "ACCOUNT_SETTING"
    ref = build_verified_account_setting_evidence_ref(account, evidence_root=tmp_path)
    validate_verified_evidence_ref(ref, action=a, evidence_root=tmp_path)


def test_received_record_must_be_bound_to_the_action(queue, tmp_path):
    executed = _drive(_action(queue, "MIS-01"), "EXECUTED_AWAITING_PROVIDER", tmp_path)
    for bad in (
        None, {}, "reply",
        _provider_record(tmp_path, "DeepSeek AI", "DeepSeek V4.1-Flash"),
        dict(_provider_record(tmp_path, "Mistral AI", "Mistral Large 3"), raw_response_location=""),
        dict(_provider_record(tmp_path, "Mistral AI", "Mistral Large 3"), received_at_utc="soon"),
        dict(_provider_record(tmp_path, "Mistral AI", "Mistral Large 3"), question_ids_answered=["DSK-Q1"]),
    ):
        with pytest.raises(ProviderResolutionError):
            advance_action_state(executed, "PROVIDER_REPLIED_UNVERIFIED", received_record=bad)


def test_fresh_cycle_after_insufficient_evidence_requires_fresh_authorization(queue, tmp_path):
    replied = _replied(queue, tmp_path)
    insufficient = advance_action_state(replied, "EVIDENCE_INSUFFICIENT")
    prepared = advance_action_state(insufficient, "PREPARED")
    assert prepared["authorization_status"] == "NOT_AUTHORIZED" and prepared["authorization_evidence"] is None
    assert prepared["executed_status"] == "NOT_EXECUTED" and prepared["execution_evidence_ref"] is None
    assert prepared["verified_evidence_ref"] is None


# ══ §28/§29: the real queue and registry are untouched ═══════════════════


def test_real_queue_is_locked_at_15_unauthorized_unexecuted_actions(queue):
    assert {a["action_id"] for a in queue["actions"]} == EXPECTED_ACTION_IDS
    assert len(queue["actions"]) == 15
    assert_queue_fully_unauthorized(queue)
    for action in queue["actions"]:
        assert action["authorization_status"] == "NOT_AUTHORIZED"
        assert action["executed_status"] == "NOT_EXECUTED"
        assert action["authorization_evidence"] is None
        assert action["execution_evidence_ref"] is None
        assert action["verified_evidence_ref"] is None
        assert action["state"] not in ("RESOLVED", "EVIDENCE_VERIFIED", "EXECUTED_AWAITING_PROVIDER", "AUTHORIZED_NOT_EXECUTED")
    assert next(a for a in queue["actions"] if a["action_id"] == "GLB-02")["state"] == "BLOCKED"
    assert sum(1 for a in queue["actions"] if a["state"] == "RESOLVED") == 0
    for counter in ("messages_sent", "support_tickets_submitted", "account_settings_changed", "commercial_notices_sent"):
        assert queue[counter] == 0


def test_real_queue_has_no_hidden_action_and_every_action_is_bound(queue):
    for action in queue["actions"]:
        if action["action_id"] in GLOBAL_ACTION_IDS:
            assert action["provider"] == "ALL" and action["reference_name"] == "ALL"
        else:
            assert action["provider"] == REFERENCE_PROVIDER[action["reference_name"]]


def test_registry_state_and_quorum_preserved(registry):
    by_name = {r["reference_name"]: r for r in registry.frontier_references}
    assert by_name["Qwen3.8-Max"]["private_holdout_status"] == "PERMITTED"
    assert by_name["DeepSeek V4.1-Flash"]["private_holdout_status"] == "REVIEW_REQUIRED"
    assert by_name["Mistral Large 3"]["private_holdout_status"] == "REVIEW_REQUIRED"
    assert by_name["Kimi K3"]["private_holdout_status"] == "BLOCKED"
    assert by_name["GLM-5.3 (flagship)"]["reference_evaluation_admission_status"] == "REVIEW_REQUIRED"
    assert by_name["MiniMax M3"]["reference_evaluation_admission_status"] == "REVIEW_REQUIRED"
    for entry in registry.frontier_references:
        assert entry["access_preflight_status"] == "UNQUALIFIED"
        assert entry["full_protocol_access_validation"] == "FAILED"
    report = compute_admission_quorum(list(registry.frontier_references))
    assert report.validated_access_preflight_ready_count == 0
    assert report.quorum_counting_count == 0
    assert report.independent_lineage_count == 0
    assert report.quorum_status == "QUORUM_BLOCKED"
