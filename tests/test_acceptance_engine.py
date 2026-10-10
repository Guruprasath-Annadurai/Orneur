"""Fail-closed acceptance. The published register stays unaccepted.

Phase 0 remediation (temporary Cursor-to-Claude handoff), then a
trust-boundary hardening pass after an independent audit: every trust key
used below is enrolled against a single synthetic, in-memory founder root
keypair (`FOUNDER_ROOT_PRIVATE`/`ROOT_KEYS`), generated fresh for this test
run only. It is not read from or written to any file and never touches
the real (empty) `docs/orneur/acceptance/founder_root_keys.json` baseline.
"""

import copy
import itertools
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "acceptance"))

from acceptance_engine import (  # noqa: E402
    AcceptanceRejected,
    POLICY_VERSION,
    assert_published_baseline,
    enrollment_payload_bytes,
    evaluate,
    payload_bytes,
)
from validate_register_graph import build_nodes  # noqa: E402

SUBJECT = "a" * 40
ANCESTOR = "b" * 40

ALL_SCOPES = ["PRE_TRAINING", "APPLICATION", "POST_TRAINING_LAUNCH", "EXECUTION"]

FOUNDER_ROOT_PRIVATE = Ed25519PrivateKey.generate()


def _public_hex(private):
    return private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()


FOUNDER_ROOT_PUBLIC_HEX = _public_hex(FOUNDER_ROOT_PRIVATE)
ROOT_KEYS = [{"root_id": "root-1", "public_key_hex": FOUNDER_ROOT_PUBLIC_HEX, "revoked": False}]

_epoch_counter = itertools.count(1)


def _role_key(role, key_id, *, scope=None, revoked=False, epoch=None, root_private=FOUNDER_ROOT_PRIVATE):
    """Generate a reviewer/founder key enrolled by `root_private`.

    This is the one path every test uses to mint a usable trust entry --
    it always carries a real enrollment signature at a fresh, strictly
    increasing epoch, so a test that wants an UNTRUSTED key, or wants to
    construct a replay attempt by hand, builds its entry directly instead
    of through here.
    """
    private = Ed25519PrivateKey.generate()
    entry = {
        "key_id": key_id,
        "role": role,
        "public_key_hex": _public_hex(private),
        "scope": list(scope) if scope is not None else list(ALL_SCOPES),
        "revoked": revoked,
        "epoch": epoch if epoch is not None else next(_epoch_counter),
    }
    entry["enrollment_signature_hex"] = root_private.sign(enrollment_payload_bytes(entry)).hex()
    return private, entry


def _signed(node, private, trust, *, subject=SUBJECT, artifact=None, founder=None, **overrides):
    record = {
        "requirement_id": node["id"],
        "evidence_key": node["evidence_key"],
        "artifact_class": node["artifact_class"],
        "artifact_sha256": artifact or ("ab" * 32),
        "git_sha": subject,
        "scope": node["denominator"],
        "reviewer_role": node["independent_reviewer"],
        "policy_version": POLICY_VERSION,
        "bound_corpus_sha256": "",
    }
    record.update(overrides)
    record["signature_hex"] = private.sign(payload_bytes(record)).hex()
    record["reviewer_key_id"] = trust["key_id"]
    if founder is not None:
        founder_private, founder_trust = founder
        record["founder_key_id"] = founder_trust["key_id"]
        record["founder_signature_hex"] = founder_private.sign(payload_bytes(record)).hex()
    return record


def _node(nodes, requirement_id):
    return next(node for node in nodes if node["id"] == requirement_id)


def _reject(nodes, records, trust, code, *, founder_root_keys=ROOT_KEYS, **kwargs):
    with pytest.raises(AcceptanceRejected) as caught:
        evaluate(
            nodes,
            records,
            trust_keys=trust,
            subject_sha=SUBJECT,
            founder_root_keys=founder_root_keys,
            **kwargs,
        )
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
    errors = assert_published_baseline(
        nodes,
        "| G8 | M | M | PRE_TRAINING | yes | ACCEPTED |",
        [{"requirement_id": "G8"}],
        {"keys": [{"key_id": "x"}]},
        {"keys": [{"key_id": "root"}]},
    )
    assert "published status ACCEPTED" in errors
    assert any(error.startswith("markdown status ACCEPTED") for error in errors)
    assert "committed ledger is not empty" in errors
    assert "committed trust store is not empty" in errors
    assert "committed founder root key store is not empty" in errors


def test_valid_record_accepts_only_its_own_row():
    # DEC-K requires founder approval; a reviewer signature alone is not enough.
    nodes = build_nodes()
    private, trust = _role_key("PRODUCT_MANAGEMENT", "pm")
    founder_key, founder_trust = _role_key("FOUNDER", "founder-1")
    deck = _signed(
        _node(nodes, "DEC-K"), private, trust, artifact="11" * 32,
        founder=(founder_key, founder_trust),
    )
    before = copy.deepcopy(nodes)
    accepted = evaluate(
        nodes, [deck], trust_keys=[trust, founder_trust], subject_sha=SUBJECT,
        founder_root_keys=ROOT_KEYS,
    )
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
    accepted = evaluate(nodes, [g3], trust_keys=[claude], subject_sha=SUBJECT, founder_root_keys=ROOT_KEYS)
    assert accepted == {"G3": "22" * 32}
    c01 = _signed(nodes[1], claude_key, claude, artifact="33" * 32)
    both = evaluate(nodes, [g3, c01], trust_keys=[claude], subject_sha=SUBJECT, founder_root_keys=ROOT_KEYS)
    assert both == {"G3": "22" * 32, "C01": "33" * 32}
    _reject(nodes, [c01], [claude], "DEPENDENCY_UNACCEPTED")
    shared = _signed(nodes[1], claude_key, claude, artifact="22" * 32)
    _reject(nodes, [g3, shared], [claude], "DUPLICATE_ARTIFACT")
    real = build_nodes()
    _reject(real, [_signed(_node(real, "C01"), claude_key, claude, artifact="34" * 32)], [claude], "DEPENDENCY_UNACCEPTED")


def test_grant_does_not_create_the_corpus_or_pass_later_corpus_rows():
    # G8 (the founder grant) requires founder approval.
    source = build_nodes()
    nodes = [
        _pair(source, "G8", []),
        _pair(source, "DATA-3", ["G8"]),
        _pair(source, "DATA-1", ["DATA-3"]),
        _pair(source, "DATA-5", ["DATA-3"]),
        _pair(source, "DATA-2", ["DATA-1", "DATA-3", "DATA-5"]),
    ]
    pm_key, pm = _role_key("PRODUCT_MANAGEMENT", "pm")
    founder_key, founder = _role_key("FOUNDER", "founder-grant")
    grant = _signed(nodes[0], pm_key, pm, artifact="44" * 32, founder=(founder_key, founder))
    accepted = evaluate(
        nodes, [grant], trust_keys=[pm, founder], subject_sha=SUBJECT, founder_root_keys=ROOT_KEYS,
    )
    assert list(accepted) == ["G8"]
    for row_id in ("DATA-1", "DATA-2", "DATA-3", "DATA-5"):
        assert row_id not in accepted


def _role_pair(role, key_id):
    return _role_key(role, key_id)


def test_same_grant_digest_cannot_be_reused_as_creation():
    nodes = build_nodes()
    pm_key, pm = _role_key("PRODUCT_MANAGEMENT", "pm")
    claude_key, claude = _role_key("CLAUDE", "claude")
    founder_key, founder = _role_key("FOUNDER", "founder-grant")
    digest = "55" * 32
    grant = _signed(_node(nodes, "G8"), pm_key, pm, artifact=digest, founder=(founder_key, founder))
    created = _signed(_node(nodes, "DATA-3"), claude_key, claude, artifact=digest)
    _reject(nodes, [grant, created], [pm, claude, founder], "DUPLICATE_ARTIFACT")
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


def test_missing_or_corrupted_evidence_digest_is_rejected():
    nodes = build_nodes()
    private, trust = _role_key("CLAUDE", "claude")
    corrupted = _signed(_node(nodes, "G3"), private, trust, artifact="zz" * 32)
    _reject(nodes, [corrupted], [trust], "MISSING_FIELD")


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
            "founder_approval": "NOT_REQUIRED",
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
            "founder_approval": "NOT_REQUIRED",
        },
    ]
    key, trust = _role_key("CLAUDE", "claude")
    only_final = _signed(tiny[1], key, trust, artifact="14" * 32)
    _reject(tiny, [only_final], [trust], "FINAL_READINESS_BLOCKED")


def test_training_authorization_and_execution_stay_separate():
    key, trust = _role_key("CLAUDE", "claude")
    pm_key, pm_trust = _role_key("PRODUCT_MANAGEMENT", "pm")
    founder_key, founder_trust = _role_key("FOUNDER", "founder-1")
    all_trust = [trust, pm_trust, founder_trust]
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
            "founder_approval": "NOT_REQUIRED",
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
            "founder_approval": "NOT_REQUIRED",
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
            "founder_approval": "REQUIRED",
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
            "founder_approval": "REQUIRED",
        },
    ]
    ready = [
        _signed(nodes[0], key, trust, artifact="21" * 32),
        _signed(nodes[1], key, trust, artifact="22" * 32),
    ]
    accepted = evaluate(nodes, ready, trust_keys=all_trust, subject_sha=SUBJECT, founder_root_keys=ROOT_KEYS)
    assert "FINAL-2" not in accepted and "EXEC-1" not in accepted

    # A reviewer attestation alone must never authorize FINAL-2.
    reviewer_only = _signed(nodes[2], pm_key, pm_trust, artifact="23" * 32)
    _reject(nodes, ready + [reviewer_only], all_trust, "MISSING_FOUNDER_APPROVAL")

    # The founder's own key cannot double as the reviewer's key on one record.
    dual_role = _signed(nodes[2], pm_key, pm_trust, artifact="23" * 32, founder=(pm_key, pm_trust))
    _reject(nodes, ready + [dual_role], all_trust, "SAME_KEY_DUAL_ROLE")

    grant = _signed(nodes[2], pm_key, pm_trust, artifact="23" * 32, founder=(founder_key, founder_trust))
    with_grant = evaluate(nodes, ready + [grant], trust_keys=all_trust, subject_sha=SUBJECT, founder_root_keys=ROOT_KEYS)
    assert "FINAL-2" in with_grant and "EXEC-1" not in with_grant

    early = _signed(nodes[3], key, trust, artifact="24" * 32, founder=(founder_key, founder_trust))
    _reject(nodes, ready + [early], all_trust, "DEPENDENCY_UNACCEPTED")

    wrong_scope = _signed(
        nodes[2], pm_key, pm_trust, artifact="25" * 32, scope="PRE_TRAINING",
        founder=(founder_key, founder_trust),
    )
    _reject(nodes, ready + [wrong_scope], all_trust, "SCOPE_MISMATCH")

    start = _signed(nodes[3], key, trust, artifact="26" * 32, founder=(founder_key, founder_trust))
    done = evaluate(
        nodes,
        ready + [grant, start],
        trust_keys=all_trust,
        subject_sha=SUBJECT,
        founder_root_keys=ROOT_KEYS,
    )
    assert list(done) == ["A", "FINAL-1", "FINAL-2", "EXEC-1"]


def test_injected_reviewer_key_without_founder_enrollment_is_untrusted():
    """An attacker who can shape the `trust_keys` argument itself still
    cannot get a key accepted without a real founder enrollment signature."""
    nodes = build_nodes()
    attacker_private = Ed25519PrivateKey.generate()
    injected = {
        "key_id": "attacker",
        "role": "PRODUCT_MANAGEMENT",
        "public_key_hex": _public_hex(attacker_private),
        "scope": ALL_SCOPES,
        # No enrollment_signature_hex -- never enrolled by the founder root.
    }
    founder_key, founder_trust = _role_key("FOUNDER", "founder-x")
    record = _signed(
        _node(nodes, "DEC-K"), attacker_private, injected, artifact="31" * 32,
        founder=(founder_key, founder_trust),
    )
    _reject(nodes, [record], [injected, founder_trust], "UNTRUSTED_KEY")


def test_tampering_with_a_caller_supplied_revoked_flag_also_fails_untrusted():
    """Flipping a legitimately-enrolled key's `revoked` flag after the fact
    invalidates its enrollment signature -- it does not un-revoke the key."""
    nodes = build_nodes()
    private, trust = _role_key("CLAUDE", "claude-tamper", revoked=True)
    tampered = dict(trust)
    tampered["revoked"] = False
    record = _signed(_node(nodes, "G3"), private, tampered, artifact="35" * 32)
    _reject(nodes, [record], [tampered], "UNTRUSTED_KEY")


def test_revoked_reviewer_key_is_rejected():
    nodes = build_nodes()
    private, trust = _role_key("CLAUDE", "claude-revoked", revoked=True)
    record = _signed(_node(nodes, "G3"), private, trust, artifact="32" * 32)
    _reject(nodes, [record], [trust], "REVOKED_REVIEWER")


def test_reviewer_out_of_scope_is_rejected():
    nodes = build_nodes()
    private, trust = _role_key("CLAUDE", "claude-narrow", scope=["EXECUTION"])
    record = _signed(_node(nodes, "G3"), private, trust, artifact="36" * 32)
    _reject(nodes, [record], [trust], "OUT_OF_SCOPE")


def test_wrong_policy_version_is_rejected():
    nodes = build_nodes()
    private, trust = _role_key("CLAUDE", "claude")
    record = _signed(_node(nodes, "G3"), private, trust, artifact="33" * 32, policy_version="stale-policy/0")
    _reject(nodes, [record], [trust], "WRONG_POLICY_VERSION")


def test_corpus_evidence_must_share_one_digest():
    source = build_nodes()
    nodes = [
        _pair(source, "G8", []),
        _pair(source, "DATA-3", ["G8"]),
        _pair(source, "DATA-1", ["DATA-3"]),
        _pair(source, "DATA-5", ["DATA-3"]),
        _pair(source, "DATA-2", ["DATA-1", "DATA-3", "DATA-5"]),
    ]
    pm_key, pm_trust = _role_key("PRODUCT_MANAGEMENT", "pm")
    claude_key, claude_trust = _role_key("CLAUDE", "claude")
    founder_key, founder_trust = _role_key("FOUNDER", "founder-corpus")
    all_trust = [pm_trust, claude_trust, founder_trust]

    grant = _signed(nodes[0], pm_key, pm_trust, artifact="41" * 32, founder=(founder_key, founder_trust))
    creation = _signed(nodes[1], claude_key, claude_trust, artifact="42" * 32)
    inconsistent = _signed(nodes[2], pm_key, pm_trust, artifact="43" * 32, bound_corpus_sha256="ff" * 32)
    _reject(nodes, [grant, creation, inconsistent], all_trust, "CORPUS_IDENTITY_MISMATCH")

    consistent = _signed(nodes[2], pm_key, pm_trust, artifact="43" * 32, bound_corpus_sha256="42" * 32)
    accepted = evaluate(
        nodes, [grant, creation, consistent], trust_keys=all_trust,
        subject_sha=SUBJECT, founder_root_keys=ROOT_KEYS,
    )
    assert accepted["DATA-1"] == "43" * 32
    assert accepted["DATA-3"] == "42" * 32


def test_policy_version_is_bound_to_the_policy_document_hash():
    assert POLICY_VERSION.startswith("orneur-acceptance-policy/")
    digest = POLICY_VERSION.split("/", 1)[1]
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)


def test_revocation_cannot_be_replayed_by_presenting_the_stale_active_record():
    """A key that is genuinely re-enrolled (active -> revoked) at a higher
    epoch must stay revoked no matter what order the two legitimately
    founder-signed records are presented in -- the old active record is not
    expected to vanish from a real trust store; the engine must simply stop
    trusting it once something newer for the same key_id exists."""
    nodes = [_pair(build_nodes(), "G3", [])]
    key_private = Ed25519PrivateKey.generate()
    public_hex = _public_hex(key_private)
    active = {
        "key_id": "claude-replay", "role": "CLAUDE", "public_key_hex": public_hex,
        "scope": ALL_SCOPES, "revoked": False, "epoch": 1,
    }
    active["enrollment_signature_hex"] = FOUNDER_ROOT_PRIVATE.sign(enrollment_payload_bytes(active)).hex()
    revoked = dict(active, revoked=True, epoch=2)
    revoked["enrollment_signature_hex"] = FOUNDER_ROOT_PRIVATE.sign(enrollment_payload_bytes(revoked)).hex()

    record = _signed(_node(nodes, "G3"), key_private, active, artifact="51" * 32)

    # Stale-active-first: the exact order a naive first-match lookup would
    # get wrong.
    _reject(nodes, [record], [active, revoked], "REVOKED_REVIEWER")
    # Revoked-first: must be equally rejected (order must not matter either way).
    _reject(nodes, [record], [revoked, active], "REVOKED_REVIEWER")
    # Only the stale active record is presented (the caller simply never
    # learned about the revocation) -- still accepted, since nothing wrong
    # was presented; this is the caller's own staleness, not something this
    # pure function can detect without a second source of truth.
    accepted = evaluate(
        nodes, [record], trust_keys=[active], subject_sha=SUBJECT, founder_root_keys=ROOT_KEYS,
    )
    assert accepted == {"G3": "51" * 32}


def test_a_revoked_founder_root_cannot_anchor_new_enrollments_but_others_still_can():
    """Founder roots are independently identified and independently
    revocable: compromising or retiring one must not silently invalidate
    enrollments anchored to a different, still-good root."""
    nodes = [_pair(build_nodes(), "G3", [])]
    other_root_private = Ed25519PrivateKey.generate()
    roots = [
        {"root_id": "root-1", "public_key_hex": FOUNDER_ROOT_PUBLIC_HEX, "revoked": True},
        {"root_id": "root-2", "public_key_hex": _public_hex(other_root_private), "revoked": False},
    ]
    # Enrolled against the now-revoked root -- must not verify any more.
    stale_private, stale_trust = _role_key("CLAUDE", "claude-stale-root")
    stale_record = _signed(_node(nodes, "G3"), stale_private, stale_trust, artifact="52" * 32)
    _reject(nodes, [stale_record], [stale_trust], "UNTRUSTED_KEY", founder_root_keys=roots)

    # Enrolled against the still-good second root -- must verify fine.
    fresh_private, fresh_trust = _role_key("CLAUDE", "claude-fresh-root", root_private=other_root_private)
    fresh_record = _signed(_node(nodes, "G3"), fresh_private, fresh_trust, artifact="53" * 32)
    accepted = evaluate(
        nodes, [fresh_record], trust_keys=[fresh_trust], subject_sha=SUBJECT, founder_root_keys=roots,
    )
    assert accepted == {"G3": "53" * 32}


def test_corpus_custody_must_be_an_independent_key_not_just_an_independent_role():
    """DATA-5's own evidence text requires "a custodian who is not the
    creator". Checked at the role level alone, two records sharing a role
    name (here both PRODUCT_MANAGEMENT, to isolate the mechanism from the
    real register's CLAUDE/PRODUCT_MANAGEMENT role split) would look
    independent even if the exact same physical key signed both -- this
    proves the engine instead checks key identity."""
    source = build_nodes()
    nodes = [
        _pair(source, "G8", []),
        dict(_pair(source, "DATA-3", ["G8"]), independent_reviewer="PRODUCT_MANAGEMENT"),
        dict(_pair(source, "DATA-5", ["DATA-3"]), independent_reviewer="PRODUCT_MANAGEMENT"),
    ]
    founder_key, founder_trust = _role_key("FOUNDER", "founder-custody")
    grant_signer, grant_trust = _role_key("PRODUCT_MANAGEMENT", "pm-grant")
    grant = _signed(nodes[0], grant_signer, grant_trust, artifact="54" * 32, founder=(founder_key, founder_trust))

    creator_key, creator_trust = _role_key("PRODUCT_MANAGEMENT", "pm-creator")
    creation = _signed(nodes[1], creator_key, creator_trust, artifact="55" * 32)

    # Same physical key (same key_id) signs DATA-5 as signed DATA-3 -- same
    # role on both, so REVIEWER_MISMATCH would not catch this; only the
    # custody-independence check does.
    same_key_custody = _signed(
        nodes[2], creator_key, creator_trust, artifact="56" * 32, bound_corpus_sha256="55" * 32,
    )
    _reject(
        nodes, [grant, creation, same_key_custody],
        [grant_trust, founder_trust, creator_trust], "CUSTODY_NOT_INDEPENDENT",
    )

    custodian_key, custodian_trust = _role_key("PRODUCT_MANAGEMENT", "pm-custodian")
    independent_custody = _signed(
        nodes[2], custodian_key, custodian_trust, artifact="56" * 32, bound_corpus_sha256="55" * 32,
    )
    accepted = evaluate(
        nodes, [grant, creation, independent_custody],
        trust_keys=[grant_trust, founder_trust, creator_trust, custodian_trust],
        subject_sha=SUBJECT, founder_root_keys=ROOT_KEYS,
    )
    assert accepted["DATA-5"] == "56" * 32
