"""Fail-closed acceptance. The published register stays unaccepted."""

import copy
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "acceptance"))

from acceptance_engine import (  # noqa: E402
    AcceptanceRejected,
    assert_published_baseline,
    evaluate,
)
from validate_register_graph import build_nodes  # noqa: E402

SUBJECT = "a" * 40
ANCESTOR = "b" * 40


def _role_key(role, key_id):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    trust = {"key_id": key_id, "role": role, "public_key_hex": public.hex()}
    return private, trust


def _signed(node, private, trust, *, subject=SUBJECT, artifact=None, **overrides):
    record = {
        "requirement_id": node["id"],
        "evidence_key": node["evidence_key"],
        "artifact_class": node["artifact_class"],
        "artifact_sha256": artifact or ("ab" * 32),
        "git_sha": subject,
        "scope": node["denominator"],
        "reviewer_role": node["independent_reviewer"],
    }
    record.update(overrides)
    from acceptance_engine import payload_bytes

    record["signature_hex"] = private.sign(payload_bytes(record)).hex()
    record["reviewer_key_id"] = trust["key_id"]
    return record


def _node(nodes, requirement_id):
    return next(node for node in nodes if node["id"] == requirement_id)


def _reject(nodes, records, trust, code, **kwargs):
    with pytest.raises(AcceptanceRejected) as caught:
        evaluate(nodes, records, trust_keys=trust, subject_sha=SUBJECT, **kwargs)
    assert caught.value.code == code


def test_empty_ledger_accepts_nothing_and_ignores_status_edits():
    nodes = build_nodes()
    for node in nodes:
        node["status"] = "ACCEPTED"
    assert evaluate(nodes, [], trust_keys=[], subject_sha=SUBJECT) == {}
    assert all(node["status"] == "ACCEPTED" for node in nodes)


def test_published_baseline_rejects_self_accepted_status_and_a_local_ledger():
    nodes = build_nodes()
    assert assert_published_baseline(nodes, "| G8 | M | M | PRE_TRAINING | yes | NOT_AUTHORIZED |", [], {"keys": []}) == []
    nodes[0]["status"] = "ACCEPTED"
    errors = assert_published_baseline(nodes, "| G8 | M | M | PRE_TRAINING | yes | ACCEPTED |", [{"requirement_id": "G8"}], {"keys": [{"key_id": "x"}]})
    assert "published status ACCEPTED" in errors
    assert any(error.startswith("markdown status ACCEPTED") for error in errors)
    assert "committed ledger is not empty" in errors
    assert "committed trust store is not empty" in errors


def test_valid_record_accepts_only_its_own_row():
    nodes = build_nodes()
    private, trust = _role_key("PRODUCT_MANAGEMENT", "pm")
    deck = _signed(_node(nodes, "DEC-K"), private, trust, artifact="11" * 32)
    before = copy.deepcopy(nodes)
    accepted = evaluate(nodes, [deck], trust_keys=[trust], subject_sha=SUBJECT)
    assert accepted == {"DEC-K": "11" * 32}
    assert nodes == before
    assert "C27" not in accepted


def _pair(nodes, requirement_id, depends):
    node = copy.deepcopy(_node(nodes, requirement_id))
    node["depends_on"] = depends
    return node


def test_predecessor_does_not_accept_dependents_or_share_an_artifact():
    source = build_nodes()
    nodes = [_pair(source, "G3", []), _pair(source, "C01", ["G3"])]
    claude_key, claude = _role_key("CLAUDE", "claude")
    g3 = _signed(nodes[0], claude_key, claude, artifact="22" * 32)
    accepted = evaluate(nodes, [g3], trust_keys=[claude], subject_sha=SUBJECT)
    assert accepted == {"G3": "22" * 32}
    c01 = _signed(nodes[1], claude_key, claude, artifact="33" * 32)
    both = evaluate(nodes, [g3, c01], trust_keys=[claude], subject_sha=SUBJECT)
    assert both == {"G3": "22" * 32, "C01": "33" * 32}
    _reject(nodes, [c01], [claude], "DEPENDENCY_UNACCEPTED")
    shared = _signed(nodes[1], claude_key, claude, artifact="22" * 32)
    _reject(nodes, [g3, shared], [claude], "DUPLICATE_ARTIFACT")
    real = build_nodes()
    _reject(real, [_signed(_node(real, "C01"), claude_key, claude, artifact="34" * 32)], [claude], "DEPENDENCY_UNACCEPTED")


def test_grant_does_not_create_the_corpus_or_pass_later_corpus_rows():
    source = build_nodes()
    nodes = [
        _pair(source, "G8", []),
        _pair(source, "DATA-3", ["G8"]),
        _pair(source, "DATA-1", ["DATA-3"]),
        _pair(source, "DATA-5", ["DATA-3"]),
        _pair(source, "DATA-2", ["DATA-1", "DATA-3", "DATA-5"]),
    ]
    pm_key, pm = _role_key("PRODUCT_MANAGEMENT", "pm")
    grant = _signed(nodes[0], pm_key, pm, artifact="44" * 32)
    accepted = evaluate(nodes, [grant], trust_keys=[pm], subject_sha=SUBJECT)
    assert list(accepted) == ["G8"]
    for row_id in ("DATA-1", "DATA-2", "DATA-3", "DATA-5"):
        assert row_id not in accepted


def _role_pair(role, key_id):
    return _role_key(role, key_id)


def test_same_grant_digest_cannot_be_reused_as_creation():
    nodes = build_nodes()
    pm_key, pm = _role_key("PRODUCT_MANAGEMENT", "pm")
    claude_key, claude = _role_key("CLAUDE", "claude")
    digest = "55" * 32
    grant = _signed(_node(nodes, "G8"), pm_key, pm, artifact=digest)
    created = _signed(_node(nodes, "DATA-3"), claude_key, claude, artifact=digest)
    _reject(nodes, [grant, created], [pm, claude], "DUPLICATE_ARTIFACT")
    created = _signed(_node(nodes, "DATA-3"), claude_key, claude, artifact="66" * 32)
    _reject(nodes, [created], [claude], "DEPENDENCY_UNACCEPTED")


def test_wrong_stale_forged_duplicate_and_mismatched_evidence_fail():
    nodes = build_nodes()
    private, trust = _role_key("PRODUCT_MANAGEMENT", "pm")
    node = _node(nodes, "DEC-K")
    _reject(
        nodes,
        [_signed(node, private, trust, subject="c" * 40)],
        [trust],
        "WRONG_SHA",
    )
    _reject(
        nodes,
        [_signed(node, private, trust, subject=ANCESTOR)],
        [trust],
        "STALE",
        ancestor_shas={ANCESTOR},
    )
    forged = _signed(node, private, trust, artifact="77" * 32)
    forged["signature_hex"] = ("0" if forged["signature_hex"][-1] != "0" else "1") + forged["signature_hex"][1:]
    _reject(nodes, [forged], [trust], "FORGED")
    first = _signed(node, private, trust, artifact="77" * 32)
    second = _signed(node, private, trust, artifact="88" * 32)
    _reject(nodes, [first, second], [trust], "DUPLICATE")
    mismatched = _signed(node, private, trust, evidence_key="G8")
    _reject(nodes, [mismatched], [trust], "MISMATCH")
    _reject(nodes, [_signed(node, private, trust, scope="EXECUTION")], [trust], "SCOPE_MISMATCH")
    _reject(nodes, [{"requirement_id": "NO-SUCH", "artifact_sha256": "99" * 32}], [trust], "UNKNOWN_REQUIREMENT")


def test_missing_reviewer_and_self_review_fail():
    nodes = build_nodes()
    private, trust = _role_key("CURSOR", "cursor")
    self_signed = _signed(
        _node(nodes, "C01"),
        private,
        trust,
        reviewer_role="CURSOR",
        artifact="ab" * 32,
    )
    _reject(nodes, [self_signed], [trust], "SELF_REVIEW")
    missing = _signed(_node(nodes, "DEC-K"), *_role_pair("PRODUCT_MANAGEMENT", "pm"))
    missing["reviewer_role"] = ""
    missing["signature_hex"] = "ab" * 64
    _reject(nodes, [missing], [], "MISSING_REVIEWER")
    claude_key, claude = _role_key("CLAUDE", "claude")
    unnamed = _signed(_node(nodes, "G1"), claude_key, claude, reviewer_role="CLAUDE")
    _reject(nodes, [unnamed], [claude], "MISSING_REVIEWER")


def test_r65_and_final_readiness_stay_blocked():
    nodes = build_nodes()
    private, trust = _role_key("PRODUCT_MANAGEMENT", "pm")
    r65 = _signed(_node(nodes, "R65"), private, trust, artifact="12" * 32)
    _reject(nodes, [r65], [trust], "NOT_VERIFIABLE")
    final_key, final_trust = _role_pair("PRODUCT_MANAGEMENT", "pm-2")
    final = _signed(_node(nodes, "FINAL-1"), final_key, final_trust, artifact="13" * 32)
    _reject(nodes, [final], [final_trust], "DEPENDENCY_UNACCEPTED")
    tiny = [
        {
            "id": "A",
            "counts": True,
            "denominator": "PRE_TRAINING",
            "depends_on": [],
            "evidence_key": "A",
            "artifact_class": "A",
            "implementation_owner": "CURSOR",
            "independent_reviewer": "CLAUDE",
        },
        {
            "id": "FINAL-1",
            "counts": True,
            "denominator": "PRE_TRAINING",
            "depends_on": [],
            "evidence_key": "FINAL-1",
            "artifact_class": "FINAL-1",
            "implementation_owner": "CURSOR",
            "independent_reviewer": "CLAUDE",
        },
    ]
    key, trust = _role_key("CLAUDE", "claude")
    only_final = _signed(tiny[1], key, trust, artifact="14" * 32)
    _reject(tiny, [only_final], [trust], "FINAL_READINESS_BLOCKED")


def test_training_authorization_and_execution_stay_separate():
    key, trust = _role_key("CLAUDE", "claude")
    founder, founder_trust = _role_key("PRODUCT_MANAGEMENT", "pm")
    nodes = [
        {
            "id": "A",
            "counts": True,
            "denominator": "PRE_TRAINING",
            "depends_on": [],
            "evidence_key": "A",
            "artifact_class": "A",
            "implementation_owner": "CURSOR",
            "independent_reviewer": "CLAUDE",
        },
        {
            "id": "FINAL-1",
            "counts": True,
            "denominator": "PRE_TRAINING",
            "depends_on": ["A"],
            "evidence_key": "FINAL-1",
            "artifact_class": "FINAL-1",
            "implementation_owner": "CURSOR",
            "independent_reviewer": "CLAUDE",
        },
        {
            "id": "FINAL-2",
            "counts": True,
            "denominator": "EXECUTION",
            "depends_on": ["FINAL-1"],
            "evidence_key": "FINAL-2",
            "artifact_class": "FINAL-2",
            "implementation_owner": "FOUNDER",
            "independent_reviewer": "PRODUCT_MANAGEMENT",
        },
        {
            "id": "EXEC-1",
            "counts": True,
            "denominator": "EXECUTION",
            "depends_on": ["FINAL-2"],
            "evidence_key": "EXEC-1",
            "artifact_class": "EXEC-1",
            "implementation_owner": "FOUNDER",
            "independent_reviewer": "CLAUDE",
        },
    ]
    ready = [
        _signed(nodes[0], key, trust, artifact="21" * 32),
        _signed(nodes[1], key, trust, artifact="22" * 32),
    ]
    accepted = evaluate(nodes, ready, trust_keys=[trust], subject_sha=SUBJECT)
    assert "FINAL-2" not in accepted and "EXEC-1" not in accepted
    grant = _signed(nodes[2], founder, founder_trust, artifact="23" * 32)
    with_grant = evaluate(nodes, ready + [grant], trust_keys=[trust, founder_trust], subject_sha=SUBJECT)
    assert "FINAL-2" in with_grant and "EXEC-1" not in with_grant
    early = _signed(nodes[3], key, trust, artifact="24" * 32)
    _reject(nodes, ready + [early], [trust], "DEPENDENCY_UNACCEPTED")
    wrong_scope = _signed(nodes[2], founder, founder_trust, artifact="25" * 32, scope="PRE_TRAINING")
    _reject(nodes, ready + [wrong_scope], [trust, founder_trust], "SCOPE_MISMATCH")
    start = _signed(nodes[3], key, trust, artifact="26" * 32)
    done = evaluate(
        nodes,
        ready + [grant, start],
        trust_keys=[trust, founder_trust],
        subject_sha=SUBJECT,
    )
    assert list(done) == ["A", "FINAL-1", "FINAL-2", "EXEC-1"]
