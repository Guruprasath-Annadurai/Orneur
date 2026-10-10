"""Fail-closed acceptance. The published register stays unaccepted.

History: Phase 0 remediation (Cursor-to-Claude handoff), a trust-boundary
hardening pass (closed a real, reproduced revocation-replay bug with
per-entry epochs), then this final pass, which replaces the epoch scheme
entirely after further review found it still let a caller omit a newer
record and succeed with a stale one. Trust is now two whole,
atomically-signed documents (`root_state`, `trust_snapshot`), each bound to
the exact commit SHA under evaluation, with `root_state` itself anchored to
a single permanent `bootstrap_root_key_hex`. All keys below (the bootstrap
anchor included) are freshly generated, in-memory-only synthetic Ed25519
keys for this test run; none is read from or written to any file, and none
touches the real (empty) `docs/orneur/acceptance/*` baselines.
"""

import copy
import hashlib
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "acceptance"))

import acceptance_engine as engine  # noqa: E402
from acceptance_engine import (  # noqa: E402
    AcceptanceRejected,
    POLICY_VERSION,
    PROTECTED_EVIDENCE_CLASSES,
    assert_published_baseline,
    checkpoint_payload_bytes,
    custody_challenge_bytes,
    evaluate,
    payload_bytes,
    root_state_payload_bytes,
    trust_snapshot_payload_bytes,
)
from validate_register_graph import build_nodes  # noqa: E402

SUBJECT = "a" * 40
ANCESTOR = "b" * 40

ALL_SCOPES = ["PRE_TRAINING", "APPLICATION", "POST_TRAINING_LAUNCH", "EXECUTION"]

ROOT_PRIVATE = Ed25519PrivateKey.generate()
BOOTSTRAP_PRIVATE = Ed25519PrivateKey.generate()


def _public_hex(private):
    return private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()


ROOT_PUBLIC_HEX = _public_hex(ROOT_PRIVATE)
BOOTSTRAP_PUBLIC_HEX = _public_hex(BOOTSTRAP_PRIVATE)
DEFAULT_ROOTS = [{"root_id": "root-1", "public_key_hex": ROOT_PUBLIC_HEX, "revoked": False}]


@pytest.fixture(autouse=True)
def _pin_synthetic_bootstrap(monkeypatch):
    """The real PINNED_BOOTSTRAP_ROOT_KEYS is empty (no real bootstrap
    identity is provisioned). Tests exercise the positive path with a
    synthetic bootstrap key by pinning it here, for this test run only --
    this never touches the module's committed source or the real baseline."""
    monkeypatch.setattr(engine, "PINNED_BOOTSTRAP_ROOT_KEYS", frozenset({BOOTSTRAP_PUBLIC_HEX}))


def _entry(role, key_id, *, scope=None, revoked=False):
    """A bare, unsigned-by-anything trust entry and its private key. Only
    becomes trusted once it appears inside a properly root-signed
    trust_snapshot (see `_chain`)."""
    private = Ed25519PrivateKey.generate()
    entry = {
        "key_id": key_id,
        "role": role,
        "public_key_hex": _public_hex(private),
        "scope": list(scope) if scope is not None else list(ALL_SCOPES),
        "revoked": revoked,
    }
    return private, entry


def _root_state(roots, *, generation=1, git_sha=SUBJECT, signer=BOOTSTRAP_PRIVATE):
    state = {"git_sha": git_sha, "generation": generation, "roots": roots}
    state["signature_hex"] = signer.sign(root_state_payload_bytes(state)).hex()
    return state


def _trust_snapshot(entries, *, generation=1, git_sha=SUBJECT, signer=ROOT_PRIVATE):
    snapshot = {"git_sha": git_sha, "generation": generation, "entries": entries}
    snapshot["signature_hex"] = signer.sign(trust_snapshot_payload_bytes(snapshot)).hex()
    return snapshot


def _checkpoint(trust_snapshot, root_state, *, generation=1, subject_sha=SUBJECT,
                previous_checkpoint_hash="", signer=ROOT_PRIVATE):
    checkpoint = {
        "subject_sha": subject_sha,
        "generation": generation,
        "trust_snapshot_hash": hashlib.sha256(trust_snapshot_payload_bytes(trust_snapshot)).hexdigest(),
        "root_state_hash": hashlib.sha256(root_state_payload_bytes(root_state)).hexdigest(),
        "previous_checkpoint_hash": previous_checkpoint_hash,
    }
    checkpoint["signature_hex"] = signer.sign(checkpoint_payload_bytes(checkpoint)).hex()
    return checkpoint


def _pin(checkpoint):
    return hashlib.sha256(checkpoint_payload_bytes(checkpoint)).hexdigest()


def _chain(entries, *, roots=None, generation=1, git_sha=SUBJECT, root_signer=ROOT_PRIVATE,
           bootstrap_signer=BOOTSTRAP_PRIVATE, checkpoint_signer=None):
    """The default, valid three-level trust chain: bootstrap signs root_state
    (naming `roots`, default just ROOT_PUBLIC_HEX), one of those roots
    signs trust_snapshot (naming `entries`), and that same root signs a
    trust_checkpoint committing to both, independently pinned by its own
    hash. Returns (trust_snapshot, root_state, trust_checkpoint, pinned_hash)."""
    roots = roots if roots is not None else DEFAULT_ROOTS
    snapshot = _trust_snapshot(entries, generation=generation, git_sha=git_sha, signer=root_signer)
    state = _root_state(roots, generation=generation, git_sha=git_sha, signer=bootstrap_signer)
    checkpoint = _checkpoint(
        snapshot, state, generation=generation, subject_sha=git_sha,
        signer=checkpoint_signer if checkpoint_signer is not None else root_signer,
    )
    return snapshot, state, checkpoint, _pin(checkpoint)


def _call(nodes, records, entries=(), *, artifact_bytes=None, subject_sha=SUBJECT, ancestor_shas=(),
          trust_snapshot=None, root_state=None, trust_checkpoint=None, pinned_checkpoint_hash=None,
          bootstrap_root_key_hex=BOOTSTRAP_PUBLIC_HEX, **chain_kwargs):
    if trust_snapshot is None or root_state is None or trust_checkpoint is None or pinned_checkpoint_hash is None:
        built_snapshot, built_state, built_checkpoint, built_pin = _chain(list(entries), **chain_kwargs)
        trust_snapshot = trust_snapshot if trust_snapshot is not None else built_snapshot
        root_state = root_state if root_state is not None else built_state
        if trust_checkpoint is None and pinned_checkpoint_hash is None:
            # Auto-build a checkpoint matching whatever trust_snapshot/root_state
            # end up being used, even if one of them was passed explicitly by
            # the caller -- any REAL rejection those adversarial documents
            # should trigger happens before checkpoint verification is ever
            # reached, so this default never masks the intended failure.
            trust_checkpoint = _checkpoint(trust_snapshot, root_state, subject_sha=subject_sha)
            pinned_checkpoint_hash = _pin(trust_checkpoint)
    return evaluate(
        nodes, records,
        trust_snapshot=trust_snapshot, root_state=root_state,
        bootstrap_root_key_hex=bootstrap_root_key_hex,
        trust_checkpoint=trust_checkpoint, pinned_checkpoint_hash=pinned_checkpoint_hash,
        subject_sha=subject_sha, ancestor_shas=ancestor_shas,
        artifact_bytes=artifact_bytes,
    )


def _reject(nodes, records, entries, code, **kwargs):
    with pytest.raises(AcceptanceRejected) as caught:
        _call(nodes, records, entries, **kwargs)
    assert caught.value.code == code


def _node(nodes, requirement_id):
    return next(node for node in nodes if node["id"] == requirement_id)


def _pair(nodes, requirement_id, depends):
    node = copy.deepcopy(_node(nodes, requirement_id))
    node["depends_on"] = depends
    return node


def _signed(node, private, trust, *, subject=SUBJECT, label=None, founder=None, custody_private=None, **overrides):
    """Returns (record, content_bytes). `content_bytes` is the synthetic
    evidence whose sha256 is the record's artifact_sha256 -- None if an
    override replaced artifact_sha256 directly (no known matching bytes),
    or if this row is a protected corpus-evidence class (no bytes ever
    exist for those; a custody_signature_hex is produced instead)."""
    label = label if label is not None else f"{node['id']}-synthetic-evidence"
    content = label.encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    record = {
        "requirement_id": node["id"],
        "evidence_key": node["evidence_key"],
        "artifact_class": node["artifact_class"],
        "artifact_sha256": digest,
        "git_sha": subject,
        "scope": node["denominator"],
        "reviewer_role": node["independent_reviewer"],
        "policy_version": POLICY_VERSION,
        "corpus_identity_sha256": "",
        "bound_corpus_identity_sha256": "",
    }
    record.update(overrides)
    if record["artifact_sha256"] != digest:
        content = None
    record["signature_hex"] = private.sign(payload_bytes(record)).hex()
    record["reviewer_key_id"] = trust["key_id"]
    if node["artifact_class"] in PROTECTED_EVIDENCE_CLASSES:
        signer = custody_private if custody_private is not None else private
        record["custody_signature_hex"] = signer.sign(custody_challenge_bytes(record)).hex()
        content = None
    if founder is not None:
        founder_private, founder_trust = founder
        record["founder_key_id"] = founder_trust["key_id"]
        record["founder_signature_hex"] = founder_private.sign(payload_bytes(record)).hex()
    return record, content


def _ledger(*signed):
    records = [r for r, _ in signed]
    artifact_bytes = {}
    for record, content in signed:
        if content is not None:
            artifact_bytes[record["artifact_sha256"]] = content
    return records, artifact_bytes


# ---------------------------------------------------------------------
# Baseline / empty-ledger behavior
# ---------------------------------------------------------------------

def test_empty_ledger_accepts_nothing_and_ignores_status_edits():
    nodes = build_nodes()
    for node in nodes:
        node["status"] = "ACCEPTED"
    empty_snapshot = {"git_sha": "", "generation": 0, "entries": [], "signature_hex": ""}
    empty_root_state = {"git_sha": "", "generation": 0, "roots": [], "signature_hex": ""}
    assert evaluate(
        nodes, [], trust_snapshot=empty_snapshot, root_state=empty_root_state,
        bootstrap_root_key_hex="", subject_sha=SUBJECT,
    ) == {}
    assert all(node["status"] == "ACCEPTED" for node in nodes)


def test_published_baseline_rejects_self_accepted_status_and_a_local_ledger():
    nodes = build_nodes()
    empty_snapshot = {"git_sha": "", "generation": 0, "entries": [], "signature_hex": ""}
    assert assert_published_baseline(nodes, "| G8 | M | M | PRE_TRAINING | yes | NOT_AUTHORIZED |", [], empty_snapshot) == []
    nodes[0]["status"] = "ACCEPTED"
    errors = assert_published_baseline(
        nodes,
        "| G8 | M | M | PRE_TRAINING | yes | ACCEPTED |",
        [{"requirement_id": "G8"}],
        {"git_sha": "x", "generation": 1, "entries": [{"key_id": "x"}], "signature_hex": "y"},
        {"git_sha": "x", "generation": 1, "roots": [{"root_id": "r"}], "signature_hex": "y"},
        {"public_key_hex": "z"},
    )
    assert "published status ACCEPTED" in errors
    assert any(error.startswith("markdown status ACCEPTED") for error in errors)
    assert "committed ledger is not empty" in errors
    assert "committed trust snapshot is not empty" in errors
    assert "committed root state is not empty" in errors
    assert "committed bootstrap root key is not empty" in errors


# ---------------------------------------------------------------------
# Core acceptance behavior (dependency ordering, duplicates, founder gate)
# ---------------------------------------------------------------------

def test_valid_record_accepts_only_its_own_row():
    nodes = build_nodes()
    private, trust = _entry("PRODUCT_MANAGEMENT", "pm")
    founder_private, founder_trust = _entry("FOUNDER", "founder-1")
    deck = _signed(_node(nodes, "DEC-K"), private, trust, label="deck", founder=(founder_private, founder_trust))
    before = copy.deepcopy(nodes)
    records, artifact_bytes = _ledger(deck)
    accepted = _call(nodes, records, [trust, founder_trust], artifact_bytes=artifact_bytes)
    assert accepted == {"DEC-K": deck[0]["artifact_sha256"]}
    assert nodes == before
    assert "C27" not in accepted


def test_predecessor_does_not_accept_dependents_or_share_an_artifact():
    source = build_nodes()
    nodes = [_pair(source, "G3", []), _pair(source, "C01", ["G3"])]
    claude_private, claude = _entry("CLAUDE", "claude")
    g3 = _signed(nodes[0], claude_private, claude, label="g3")
    c01 = _signed(nodes[1], claude_private, claude, label="c01")

    records, artifact_bytes = _ledger(g3)
    accepted = _call(nodes, records, [claude], artifact_bytes=artifact_bytes)
    assert accepted == {"G3": g3[0]["artifact_sha256"]}

    records, artifact_bytes = _ledger(g3, c01)
    both = _call(nodes, records, [claude], artifact_bytes=artifact_bytes)
    assert both == {"G3": g3[0]["artifact_sha256"], "C01": c01[0]["artifact_sha256"]}

    records, artifact_bytes = _ledger(c01)
    _reject(nodes, records, [claude], "DEPENDENCY_UNACCEPTED", artifact_bytes=artifact_bytes)

    shared = _signed(nodes[1], claude_private, claude, label="g3")  # same label -> same digest as g3
    records, artifact_bytes = _ledger(g3, shared)
    _reject(nodes, records, [claude], "DUPLICATE_ARTIFACT", artifact_bytes=artifact_bytes)

    real = build_nodes()
    only_c01 = _signed(_node(real, "C01"), claude_private, claude, label="c01-real")
    records, artifact_bytes = _ledger(only_c01)
    _reject(real, records, [claude], "DEPENDENCY_UNACCEPTED", artifact_bytes=artifact_bytes)


def test_grant_does_not_create_the_corpus_or_pass_later_corpus_rows():
    source = build_nodes()
    nodes = [
        _pair(source, "G8", []),
        _pair(source, "DATA-3", ["G8"]),
        _pair(source, "DATA-1", ["DATA-3"]),
        _pair(source, "DATA-5", ["DATA-3"]),
        _pair(source, "DATA-2", ["DATA-1", "DATA-3", "DATA-5"]),
    ]
    pm_private, pm = _entry("PRODUCT_MANAGEMENT", "pm")
    founder_private, founder = _entry("FOUNDER", "founder-grant")
    grant = _signed(nodes[0], pm_private, pm, label="grant", founder=(founder_private, founder))
    records, artifact_bytes = _ledger(grant)
    accepted = _call(nodes, records, [pm, founder], artifact_bytes=artifact_bytes)
    assert list(accepted) == ["G8"]
    for row_id in ("DATA-1", "DATA-2", "DATA-3", "DATA-5"):
        assert row_id not in accepted


def test_same_grant_digest_cannot_be_reused_as_creation():
    nodes = build_nodes()
    pm_private, pm = _entry("PRODUCT_MANAGEMENT", "pm")
    claude_private, claude = _entry("CLAUDE", "claude")
    founder_private, founder = _entry("FOUNDER", "founder-grant")
    grant = _signed(_node(nodes, "G8"), pm_private, pm, label="shared", founder=(founder_private, founder))
    created = _signed(_node(nodes, "DATA-3"), claude_private, claude, label="shared")
    records, artifact_bytes = _ledger(grant, created)
    _reject(nodes, records, [pm, claude, founder], "DUPLICATE_ARTIFACT", artifact_bytes=artifact_bytes)

    created = _signed(_node(nodes, "DATA-3"), claude_private, claude, label="distinct")
    records, artifact_bytes = _ledger(created)
    _reject(nodes, records, [claude], "DEPENDENCY_UNACCEPTED", artifact_bytes=artifact_bytes)


def test_wrong_stale_forged_duplicate_and_mismatched_evidence_fail():
    nodes = build_nodes()
    private, trust = _entry("PRODUCT_MANAGEMENT", "pm")
    founder_private, founder = _entry("FOUNDER", "founder-dec")
    node = _node(nodes, "DEC-K")

    wrong_sha, _ = _signed(node, private, trust, subject="c" * 40, founder=(founder_private, founder))
    _reject(nodes, [wrong_sha], [trust, founder], "WRONG_SHA")

    stale, _ = _signed(node, private, trust, subject=ANCESTOR, founder=(founder_private, founder))
    _reject(nodes, [stale], [trust, founder], "STALE", ancestor_shas={ANCESTOR})

    forged, _ = _signed(node, private, trust, label="forge-me", founder=(founder_private, founder))
    forged["signature_hex"] = ("0" if forged["signature_hex"][-1] != "0" else "1") + forged["signature_hex"][1:]
    _reject(nodes, [forged], [trust, founder], "FORGED")

    first, _ = _signed(node, private, trust, label="a", founder=(founder_private, founder))
    second, _ = _signed(node, private, trust, label="b", founder=(founder_private, founder))
    _reject(nodes, [first, second], [trust, founder], "DUPLICATE")

    mismatched, _ = _signed(node, private, trust, evidence_key="G8", founder=(founder_private, founder))
    _reject(nodes, [mismatched], [trust, founder], "MISMATCH")

    wrong_scope, _ = _signed(node, private, trust, scope="EXECUTION", founder=(founder_private, founder))
    _reject(nodes, [wrong_scope], [trust, founder], "SCOPE_MISMATCH")

    _reject(nodes, [{"requirement_id": "NO-SUCH", "artifact_sha256": "99" * 32}], [trust], "UNKNOWN_REQUIREMENT")


def test_missing_or_corrupted_evidence_digest_is_rejected():
    nodes = build_nodes()
    private, trust = _entry("CLAUDE", "claude")
    corrupted, _ = _signed(_node(nodes, "G3"), private, trust, artifact_sha256="zz" * 32)
    _reject(nodes, [corrupted], [trust], "MISSING_FIELD")


def test_missing_reviewer_and_self_review_fail():
    nodes = build_nodes()
    private, trust = _entry("CURSOR", "cursor")
    self_signed, self_bytes = _signed(_node(nodes, "C01"), private, trust, reviewer_role="CURSOR", label="self")
    _reject(nodes, [self_signed], [trust], "SELF_REVIEW", artifact_bytes={self_signed["artifact_sha256"]: self_bytes})

    pm_private, pm = _entry("PRODUCT_MANAGEMENT", "pm")
    missing, _ = _signed(_node(nodes, "DEC-K"), pm_private, pm)
    missing["reviewer_role"] = ""
    missing["signature_hex"] = "ab" * 64
    _reject(nodes, [missing], [], "MISSING_REVIEWER")

    claude_private, claude = _entry("CLAUDE", "claude")
    unnamed, _ = _signed(_node(nodes, "G1"), claude_private, claude, reviewer_role="CLAUDE")
    _reject(nodes, [unnamed], [claude], "MISSING_REVIEWER")


def test_r65_and_final_readiness_stay_blocked():
    nodes = build_nodes()
    private, trust = _entry("PRODUCT_MANAGEMENT", "pm")
    r65, _ = _signed(_node(nodes, "R65"), private, trust, label="r65")
    _reject(nodes, [r65], [trust], "NOT_VERIFIABLE")

    final, final_bytes = _signed(_node(nodes, "FINAL-1"), private, trust, label="final")
    _reject(nodes, [final], [trust], "DEPENDENCY_UNACCEPTED", artifact_bytes={final["artifact_sha256"]: final_bytes})

    tiny = [
        {
            "id": "A", "counts": True, "denominator": "PRE_TRAINING", "depends_on": [],
            "evidence_key": "A", "artifact_class": "A",
            "implementation_owner": "CURSOR", "independent_reviewer": "CLAUDE",
            "founder_approval": "NOT_REQUIRED",
        },
        {
            "id": "FINAL-1", "counts": True, "denominator": "PRE_TRAINING", "depends_on": [],
            "evidence_key": "FINAL-1", "artifact_class": "FINAL-1",
            "implementation_owner": "CURSOR", "independent_reviewer": "CLAUDE",
            "founder_approval": "NOT_REQUIRED",
        },
    ]
    claude_private, claude = _entry("CLAUDE", "claude")
    only_final, only_final_bytes = _signed(tiny[1], claude_private, claude, label="only-final")
    _reject(tiny, [only_final], [claude], "FINAL_READINESS_BLOCKED", artifact_bytes={only_final["artifact_sha256"]: only_final_bytes})


def test_training_authorization_and_execution_stay_separate():
    claude_private, claude = _entry("CLAUDE", "claude")
    pm_private, pm = _entry("PRODUCT_MANAGEMENT", "pm")
    founder_private, founder = _entry("FOUNDER", "founder-1")
    all_entries = [claude, pm, founder]
    nodes = [
        {
            "id": "A", "counts": True, "denominator": "PRE_TRAINING", "depends_on": [],
            "evidence_key": "A", "artifact_class": "A",
            "implementation_owner": "CURSOR", "independent_reviewer": "CLAUDE",
            "founder_approval": "NOT_REQUIRED",
        },
        {
            "id": "FINAL-1", "counts": True, "denominator": "PRE_TRAINING", "depends_on": ["A"],
            "evidence_key": "FINAL-1", "artifact_class": "FINAL-1",
            "implementation_owner": "CURSOR", "independent_reviewer": "CLAUDE",
            "founder_approval": "NOT_REQUIRED",
        },
        {
            "id": "FINAL-2", "counts": True, "denominator": "EXECUTION", "depends_on": ["FINAL-1"],
            "evidence_key": "FINAL-2", "artifact_class": "FINAL-2",
            "implementation_owner": "FOUNDER", "independent_reviewer": "PRODUCT_MANAGEMENT",
            "founder_approval": "REQUIRED",
        },
        {
            "id": "EXEC-1", "counts": True, "denominator": "EXECUTION", "depends_on": ["FINAL-2"],
            "evidence_key": "EXEC-1", "artifact_class": "EXEC-1",
            "implementation_owner": "FOUNDER", "independent_reviewer": "CLAUDE",
            "founder_approval": "REQUIRED",
        },
    ]
    a_rec = _signed(nodes[0], claude_private, claude, label="a")
    final1_rec = _signed(nodes[1], claude_private, claude, label="final1")
    ready_records, ready_bytes = _ledger(a_rec, final1_rec)
    accepted = _call(nodes, ready_records, all_entries, artifact_bytes=ready_bytes)
    assert "FINAL-2" not in accepted and "EXEC-1" not in accepted

    reviewer_only, _ = _signed(nodes[2], pm_private, pm, label="final2-a")
    _reject(nodes, ready_records + [reviewer_only], all_entries, "MISSING_FOUNDER_APPROVAL",
            artifact_bytes={**ready_bytes, reviewer_only["artifact_sha256"]: b"final2-a"})

    dual_role, _ = _signed(nodes[2], pm_private, pm, label="final2-a", founder=(pm_private, pm))
    _reject(nodes, ready_records + [dual_role], all_entries, "SAME_KEY_DUAL_ROLE",
            artifact_bytes={**ready_bytes, dual_role["artifact_sha256"]: b"final2-a"})

    grant, grant_bytes = _signed(nodes[2], pm_private, pm, label="final2-grant", founder=(founder_private, founder))
    with_grant = _call(nodes, ready_records + [grant], all_entries, artifact_bytes={**ready_bytes, grant["artifact_sha256"]: grant_bytes})
    assert "FINAL-2" in with_grant and "EXEC-1" not in with_grant

    early, early_bytes = _signed(nodes[3], claude_private, claude, label="exec-early", founder=(founder_private, founder))
    _reject(nodes, ready_records + [early], all_entries, "DEPENDENCY_UNACCEPTED",
            artifact_bytes={**ready_bytes, early["artifact_sha256"]: early_bytes})

    wrong_scope, _ = _signed(
        nodes[2], pm_private, pm, label="final2-grant", scope="PRE_TRAINING", founder=(founder_private, founder),
    )
    _reject(nodes, ready_records + [wrong_scope], all_entries, "SCOPE_MISMATCH",
            artifact_bytes={**ready_bytes, wrong_scope["artifact_sha256"]: grant_bytes})

    start, start_bytes = _signed(nodes[3], claude_private, claude, label="exec-start", founder=(founder_private, founder))
    done = _call(
        nodes, ready_records + [grant, start], all_entries,
        artifact_bytes={**ready_bytes, grant["artifact_sha256"]: grant_bytes, start["artifact_sha256"]: start_bytes},
    )
    assert list(done) == ["A", "FINAL-1", "FINAL-2", "EXEC-1"]


# ---------------------------------------------------------------------
# Trust-snapshot / root-state chain: injection, revocation, scope
# ---------------------------------------------------------------------

def test_injected_reviewer_key_without_enrollment_is_untrusted():
    """A key that never appears in a properly root-signed trust_snapshot
    at all -- not even as an unsigned entry -- is simply unknown."""
    nodes = build_nodes()
    attacker_private = Ed25519PrivateKey.generate()
    attacker_entry = {
        "key_id": "attacker", "role": "PRODUCT_MANAGEMENT",
        "public_key_hex": _public_hex(attacker_private), "scope": ALL_SCOPES, "revoked": False,
    }
    founder_private, founder = _entry("FOUNDER", "founder-x")
    record, content = _signed(_node(nodes, "DEC-K"), attacker_private, attacker_entry, label="attacker", founder=(founder_private, founder))
    # attacker_entry is never passed to _chain -- only `founder` is enrolled.
    _reject(nodes, [record], [founder], "FORGED", artifact_bytes={record["artifact_sha256"]: content})


def test_a_snapshot_signed_by_a_key_not_in_root_state_is_untrusted():
    """Even a well-formed, internally self-consistent trust_snapshot is
    worthless unless its own signature verifies against a root named in
    root_state -- an attacker cannot just also forge the snapshot wrapper."""
    nodes = [_pair(build_nodes(), "G3", [])]
    claude_private, claude = _entry("CLAUDE", "claude")
    record, content = _signed(_node(nodes, "G3"), claude_private, claude, label="g3")
    attacker_root_signer = Ed25519PrivateKey.generate()
    snapshot = _trust_snapshot([claude], signer=attacker_root_signer)  # not root-1
    root_state = _root_state(DEFAULT_ROOTS)
    _reject(
        nodes, [record], [], "UNTRUSTED_TRUST_SNAPSHOT",
        trust_snapshot=snapshot, root_state=root_state, artifact_bytes={record["artifact_sha256"]: content},
    )


def test_revoked_reviewer_key_is_rejected():
    nodes = build_nodes()
    private, trust = _entry("CLAUDE", "claude-revoked", revoked=True)
    record, content = _signed(_node(nodes, "G3"), private, trust, label="revoked")
    _reject(nodes, [record], [trust], "REVOKED_REVIEWER", artifact_bytes={record["artifact_sha256"]: content})


def test_reviewer_out_of_scope_is_rejected():
    nodes = build_nodes()
    private, trust = _entry("CLAUDE", "claude-narrow", scope=["EXECUTION"])
    record, content = _signed(_node(nodes, "G3"), private, trust, label="scope")
    _reject(nodes, [record], [trust], "OUT_OF_SCOPE", artifact_bytes={record["artifact_sha256"]: content})


def test_wrong_policy_version_is_rejected():
    nodes = build_nodes()
    private, trust = _entry("CLAUDE", "claude")
    record, content = _signed(_node(nodes, "G3"), private, trust, label="policy", policy_version="stale-policy/0")
    _reject(nodes, [record], [trust], "WRONG_POLICY_VERSION", artifact_bytes={record["artifact_sha256"]: content})


def test_policy_version_is_bound_to_policy_engine_and_graph_content():
    assert POLICY_VERSION.startswith("orneur-acceptance-policy/")
    digest = POLICY_VERSION.split("/", 1)[1]
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
    import acceptance_engine as engine_module
    policy_only = hashlib.sha256(engine_module._POLICY_DOC.read_bytes()).hexdigest()
    assert digest != policy_only, "POLICY_VERSION must bind more than just the prose document"


# ---------------------------------------------------------------------
# Mandatory scenario: equal/conflicting enrollments and malformed generation
# ---------------------------------------------------------------------

def test_duplicate_key_id_within_one_snapshot_is_rejected_either_order():
    nodes = [_pair(build_nodes(), "G3", [])]
    private, active = _entry("CLAUDE", "claude-dup", revoked=False)
    revoked = dict(active, revoked=True)
    record, content = _signed(_node(nodes, "G3"), private, active, label="dup")

    _reject(nodes, [record], [active, revoked], "DUPLICATE_ENROLLMENT", artifact_bytes={record["artifact_sha256"]: content})
    _reject(nodes, [record], [revoked, active], "DUPLICATE_ENROLLMENT", artifact_bytes={record["artifact_sha256"]: content})


def test_malformed_generation_fails_closed_for_both_documents():
    nodes = [_pair(build_nodes(), "G3", [])]
    private, trust = _entry("CLAUDE", "claude")
    record, content = _signed(_node(nodes, "G3"), private, trust, label="malformed")
    artifact_bytes = {record["artifact_sha256"]: content}

    for bad_generation in (None, "1", -1, True, 1.5):
        snapshot, root_state, _cp, _pn = _chain([trust])
        snapshot["generation"] = bad_generation
        _reject(
            nodes, [record], [], "MALFORMED_GENERATION",
            trust_snapshot=snapshot, root_state=root_state, artifact_bytes=artifact_bytes,
        )

    for bad_generation in (None, "1", -1, True):
        snapshot, root_state, _cp, _pn = _chain([trust])
        root_state["generation"] = bad_generation
        _reject(
            nodes, [record], [], "MALFORMED_GENERATION",
            trust_snapshot=snapshot, root_state=root_state, artifact_bytes=artifact_bytes,
        )


# ---------------------------------------------------------------------
# Mandatory scenario: omission/rollback -- a stale document cannot stand in
# ---------------------------------------------------------------------

def test_old_active_enrollment_alone_after_authenticated_revocation_is_rejected():
    """The founder genuinely revokes a key at the current commit. A caller
    that presents only the OLD snapshot (where the key was still active,
    signed for an earlier commit) cannot succeed -- the old snapshot's own
    git_sha pins it to that earlier commit, not to the one under
    evaluation, exactly like a stale evidence record."""
    nodes = [_pair(build_nodes(), "G3", [])]
    private, active = _entry("CLAUDE", "claude-omit")
    record, content = _signed(_node(nodes, "G3"), private, active, label="omit", subject=SUBJECT)
    artifact_bytes = {record["artifact_sha256"]: content}

    stale_snapshot, stale_root_state, _cp, _pn = _chain([active], generation=1, git_sha=ANCESTOR)
    _reject(
        nodes, [record], [], "STALE_TRUST_SNAPSHOT",
        trust_snapshot=stale_snapshot, root_state=_root_state(DEFAULT_ROOTS, generation=1, git_sha=SUBJECT),
        ancestor_shas={ANCESTOR}, artifact_bytes=artifact_bytes,
    )

    # The real, current trust state (key revoked) is what the engine must
    # actually be evaluated against -- confirming the revocation is live.
    revoked = dict(active, revoked=True)
    current_snapshot, current_root_state, _cp, _pn = _chain([revoked], generation=2, git_sha=SUBJECT)
    _reject(
        nodes, [record], [], "REVOKED_REVIEWER",
        trust_snapshot=current_snapshot, root_state=current_root_state, artifact_bytes=artifact_bytes,
    )


def test_rollback_to_earlier_trust_snapshot_is_rejected():
    nodes = [_pair(build_nodes(), "G3", [])]
    private, v2_entry = _entry("CLAUDE", "claude-rollback")
    record, content = _signed(_node(nodes, "G3"), private, v2_entry, label="rollback")
    artifact_bytes = {record["artifact_sha256"]: content}

    v1_snapshot, _rs, _cp, _pn = _chain([], generation=1, git_sha=ANCESTOR)
    root_state = _root_state(DEFAULT_ROOTS, generation=2, git_sha=SUBJECT)
    _reject(
        nodes, [record], [], "STALE_TRUST_SNAPSHOT",
        trust_snapshot=v1_snapshot, root_state=root_state,
        ancestor_shas={ANCESTOR}, artifact_bytes=artifact_bytes,
    )


def test_root_state_rollback_after_root_revocation_is_rejected():
    """A root that gets compromised and revoked cannot be resurrected by
    replaying the earlier root_state in which it was still active."""
    nodes = [_pair(build_nodes(), "G3", [])]
    private, trust = _entry("CLAUDE", "claude-root-rollback")
    record, content = _signed(_node(nodes, "G3"), private, trust, label="root-rollback")
    artifact_bytes = {record["artifact_sha256"]: content}

    old_root_state = _root_state(DEFAULT_ROOTS, generation=1, git_sha=ANCESTOR)
    snapshot = _trust_snapshot([trust], generation=1, git_sha=SUBJECT)
    _reject(
        nodes, [record], [], "STALE_ROOT_STATE",
        trust_snapshot=snapshot, root_state=old_root_state,
        ancestor_shas={ANCESTOR}, artifact_bytes=artifact_bytes,
    )


def test_malicious_root_substitution_is_rejected():
    """An attacker signs their own root_state, naming their own root, with
    their own key instead of the bootstrap anchor."""
    nodes = [_pair(build_nodes(), "G3", [])]
    attacker_root_signer = Ed25519PrivateKey.generate()
    attacker_root_public = _public_hex(Ed25519PrivateKey.generate())
    forged_root_state = _root_state(
        [{"root_id": "attacker-root", "public_key_hex": attacker_root_public, "revoked": False}],
        signer=attacker_root_signer,
    )
    private, trust = _entry("CLAUDE", "claude")
    record, content = _signed(_node(nodes, "G3"), private, trust, label="substitution")
    snapshot = _trust_snapshot([trust], signer=attacker_root_signer)
    _reject(
        nodes, [record], [], "UNTRUSTED_ROOT_STATE",
        trust_snapshot=snapshot, root_state=forged_root_state,
        artifact_bytes={record["artifact_sha256"]: content},
    )


def test_forged_root_state_update_after_signing_is_rejected():
    """Tampering with root_state's `roots` list after the bootstrap signed
    it (e.g. quietly un-revoking a root) invalidates the signature."""
    nodes = [_pair(build_nodes(), "G3", [])]
    root_state = _root_state(DEFAULT_ROOTS)
    tampered = dict(root_state, roots=[dict(DEFAULT_ROOTS[0], revoked=False)])  # no-op edit still breaks the signature path below
    tampered["roots"] = [{"root_id": "root-1", "public_key_hex": ROOT_PUBLIC_HEX, "revoked": False}, {"root_id": "root-2", "public_key_hex": _public_hex(Ed25519PrivateKey.generate()), "revoked": False}]
    private, trust = _entry("CLAUDE", "claude")
    record, content = _signed(_node(nodes, "G3"), private, trust, label="forged-root")
    snapshot = _trust_snapshot([trust])
    _reject(
        nodes, [record], [], "UNTRUSTED_ROOT_STATE",
        trust_snapshot=snapshot, root_state=tampered,
        artifact_bytes={record["artifact_sha256"]: content},
    )


def test_valid_root_rotation_revokes_old_root_and_adds_a_new_one():
    nodes = [_pair(build_nodes(), "G3", [])]
    new_root_private = Ed25519PrivateKey.generate()
    new_root_public = _public_hex(new_root_private)
    rotated_roots = [
        {"root_id": "root-1", "public_key_hex": ROOT_PUBLIC_HEX, "revoked": True},
        {"root_id": "root-2", "public_key_hex": new_root_public, "revoked": False},
    ]
    rotated_root_state = _root_state(rotated_roots, generation=2, git_sha=SUBJECT)

    private, trust = _entry("CLAUDE", "claude-rotated")
    record, content = _signed(_node(nodes, "G3"), private, trust, label="rotated")

    # Signed by the OLD (now revoked) root -- must fail.
    old_signed_snapshot = _trust_snapshot([trust], generation=2, git_sha=SUBJECT, signer=ROOT_PRIVATE)
    _reject(
        nodes, [record], [], "UNTRUSTED_TRUST_SNAPSHOT",
        trust_snapshot=old_signed_snapshot, root_state=rotated_root_state,
        artifact_bytes={record["artifact_sha256"]: content},
    )

    # Signed by the NEW root named in the rotated root_state -- must succeed.
    new_signed_snapshot = _trust_snapshot([trust], generation=2, git_sha=SUBJECT, signer=new_root_private)
    checkpoint = _checkpoint(new_signed_snapshot, rotated_root_state, generation=2, signer=new_root_private)
    accepted = evaluate(
        nodes, [record],
        trust_snapshot=new_signed_snapshot, root_state=rotated_root_state,
        bootstrap_root_key_hex=BOOTSTRAP_PUBLIC_HEX, subject_sha=SUBJECT,
        trust_checkpoint=checkpoint, pinned_checkpoint_hash=_pin(checkpoint),
        artifact_bytes={record["artifact_sha256"]: content},
    )
    assert accepted == {"G3": record["artifact_sha256"]}


# ---------------------------------------------------------------------
# Evidence integrity: real bytes for ordinary rows, custody receipts for
# the four protected corpus-evidence classes
# ---------------------------------------------------------------------

def test_nonexistent_artifact_with_a_valid_signature_still_fails():
    nodes = build_nodes()
    private, trust = _entry("CLAUDE", "claude")
    record, _real_content = _signed(_node(nodes, "G3"), private, trust, label="exists-nowhere")
    # artifact_bytes deliberately omitted/empty: no bytes resolve this digest.
    _reject(nodes, [record], [trust], "EVIDENCE_NOT_RESOLVED", artifact_bytes={})


def test_mismatched_artifact_bytes_also_fail():
    nodes = build_nodes()
    private, trust = _entry("CLAUDE", "claude")
    record, _real_content = _signed(_node(nodes, "G3"), private, trust, label="real")
    wrong_bytes = {record["artifact_sha256"]: b"this does not hash to the declared digest"}
    _reject(nodes, [record], [trust], "EVIDENCE_NOT_RESOLVED", artifact_bytes=wrong_bytes)


def test_resolved_artifact_bytes_are_accepted():
    nodes = [_pair(build_nodes(), "G3", [])]
    private, trust = _entry("CLAUDE", "claude")
    record, content = _signed(_node(nodes, "G3"), private, trust, label="present")
    accepted = _call(nodes, [record], [trust], artifact_bytes={record["artifact_sha256"]: content})
    assert accepted == {"G3": record["artifact_sha256"]}


def test_protected_corpus_row_without_custody_signature_fails():
    """A correctly shaped, correctly reviewer-signed digest is not enough
    for a protected corpus-evidence row: no real bytes are ever available
    or appropriate, but a non-disclosing custody-possession signature is
    required and was not produced here."""
    source = build_nodes()
    nodes = [_pair(source, "DATA-3", [])]
    private, trust = _entry("CLAUDE", "claude")
    record, _content = _signed(_node(nodes, "DATA-3"), private, trust, label="no-custody", corpus_identity_sha256="aa" * 32)
    del record["custody_signature_hex"]
    record["signature_hex"] = private.sign(payload_bytes(record)).hex()
    _reject(nodes, [record], [trust], "CUSTODY_NOT_AUTHENTICATED")


def test_protected_corpus_row_with_custody_signature_passes():
    source = build_nodes()
    nodes = [_pair(source, "DATA-3", [])]
    private, trust = _entry("CLAUDE", "claude")
    record, _content = _signed(_node(nodes, "DATA-3"), private, trust, label="with-custody", corpus_identity_sha256="bb" * 32)
    accepted = _call(nodes, [record], [trust])
    assert accepted == {"DATA-3": record["artifact_sha256"]}


# ---------------------------------------------------------------------
# Distinct corpus identity vs. DATA-3's own record digest; custody by key
# ---------------------------------------------------------------------

def test_corpus_identity_is_distinct_from_datas3_record_digest():
    source = build_nodes()
    nodes = [
        _pair(source, "G8", []),
        _pair(source, "DATA-3", ["G8"]),
        _pair(source, "DATA-1", ["DATA-3"]),
    ]
    pm_private, pm = _entry("PRODUCT_MANAGEMENT", "pm")
    claude_private, claude = _entry("CLAUDE", "claude")
    founder_private, founder = _entry("FOUNDER", "founder-corpus")
    all_entries = [pm, claude, founder]

    grant, grant_bytes = _signed(nodes[0], pm_private, pm, label="grant", founder=(founder_private, founder))
    creation, _creation_content = _signed(
        nodes[1], claude_private, claude, label="creation-record", corpus_identity_sha256="cc" * 32,
    )
    # Binding to DATA-3's own RECORD digest (the old, now-wrong behavior)
    # must fail: the record digest and the corpus identity are different things.
    wrong_binding, _wb_content = _signed(
        nodes[2], pm_private, pm, label="provenance",
        bound_corpus_identity_sha256=creation["artifact_sha256"],
    )
    records, artifact_bytes = _ledger((grant, grant_bytes), (creation, None), (wrong_binding, None))
    _reject(nodes, records, all_entries, "CORPUS_IDENTITY_MISMATCH", artifact_bytes=artifact_bytes)

    # Binding to the distinct declared corpus_identity_sha256 succeeds.
    right_binding, _rb_content = _signed(
        nodes[2], pm_private, pm, label="provenance", bound_corpus_identity_sha256="cc" * 32,
    )
    records, artifact_bytes = _ledger((grant, grant_bytes), (creation, None), (right_binding, None))
    accepted = _call(nodes, records, all_entries, artifact_bytes=artifact_bytes)
    assert accepted["DATA-1"] == right_binding["artifact_sha256"]
    assert accepted["DATA-3"] != "cc" * 32  # DATA-3's own record digest is unrelated to the identity it declares


def test_missing_corpus_identity_on_data3_itself_is_rejected():
    source = build_nodes()
    nodes = [_pair(source, "DATA-3", [])]
    claude_private, claude = _entry("CLAUDE", "claude")
    record, _content = _signed(_node(nodes, "DATA-3"), claude_private, claude, label="no-identity")
    # corpus_identity_sha256 left as the default "" from _signed().
    _reject(nodes, [record], [claude], "MISSING_CORPUS_IDENTITY")


def test_corpus_custody_must_be_an_independent_key_not_just_an_independent_role():
    """DATA-5's own evidence text requires "a custodian who is not the
    creator". Role equality alone would not catch two records sharing a
    role but signed by the exact same physical key; this proves the
    engine checks resolved key identity."""
    source = build_nodes()
    nodes = [
        _pair(source, "G8", []),
        dict(_pair(source, "DATA-3", ["G8"]), independent_reviewer="PRODUCT_MANAGEMENT"),
        dict(_pair(source, "DATA-5", ["DATA-3"]), independent_reviewer="PRODUCT_MANAGEMENT"),
    ]
    founder_private, founder = _entry("FOUNDER", "founder-custody")
    grant_private, grant_trust = _entry("PRODUCT_MANAGEMENT", "pm-grant")
    grant, grant_bytes = _signed(nodes[0], grant_private, grant_trust, label="grant", founder=(founder_private, founder))

    creator_private, creator_trust = _entry("PRODUCT_MANAGEMENT", "pm-creator")
    creation, _creation_content = _signed(nodes[1], creator_private, creator_trust, label="creation", corpus_identity_sha256="dd" * 32)

    same_key_custody, _ = _signed(
        nodes[2], creator_private, creator_trust, label="custody-same-key", bound_corpus_identity_sha256="dd" * 32,
    )
    all_entries = [grant_trust, founder, creator_trust]
    records, artifact_bytes = _ledger((grant, grant_bytes), (creation, None), (same_key_custody, None))
    _reject(nodes, records, all_entries, "CUSTODY_NOT_INDEPENDENT", artifact_bytes=artifact_bytes)

    custodian_private, custodian_trust = _entry("PRODUCT_MANAGEMENT", "pm-custodian")
    independent_custody, _ = _signed(
        nodes[2], custodian_private, custodian_trust, label="custody-independent", bound_corpus_identity_sha256="dd" * 32,
    )
    records, artifact_bytes = _ledger((grant, grant_bytes), (creation, None), (independent_custody, None))
    accepted = _call(nodes, records, [grant_trust, founder, creator_trust, custodian_trust], artifact_bytes=artifact_bytes)
    assert accepted["DATA-5"] == independent_custody["artifact_sha256"]


# ---------------------------------------------------------------------
# Audit #003: same-SHA rollback, bootstrap substitution, self-reference
# ---------------------------------------------------------------------

def test_same_sha_rollback_is_rejected_by_checkpoint_pinning():
    """Antigravity reproduced this exact scenario: two trust_snapshot
    generations both validly carry the SAME subject_sha (nothing about
    commit identity orders them). Presenting the earlier one together
    with a checkpoint that is itself perfectly self-consistent for THAT
    snapshot still fails, because its hash is not the externally pinned
    one -- freshness here comes from exact pinning, not generation
    comparison or git_sha matching."""
    nodes = [_pair(build_nodes(), "G3", [])]
    private, active = _entry("CLAUDE", "claude-same-sha")
    record, content = _signed(_node(nodes, "G3"), private, active, label="same-sha")
    artifact_bytes = {record["artifact_sha256"]: content}

    gen1_snapshot = _trust_snapshot([active], generation=1, git_sha=SUBJECT)
    root_state = _root_state(DEFAULT_ROOTS, generation=1, git_sha=SUBJECT)
    revoked = dict(active, revoked=True)
    gen2_snapshot = _trust_snapshot([revoked], generation=2, git_sha=SUBJECT)
    assert gen1_snapshot["git_sha"] == gen2_snapshot["git_sha"] == SUBJECT
    assert gen1_snapshot["generation"] != gen2_snapshot["generation"]

    # The externally-pinned "current" checkpoint actually commits to gen2
    # (the founder's real, later revocation decision).
    current_checkpoint = _checkpoint(gen2_snapshot, root_state, generation=2, subject_sha=SUBJECT)
    real_pin = _pin(current_checkpoint)

    # A caller presents gen1 (the key still looks active) together with a
    # checkpoint that is internally self-consistent for gen1 -- but its
    # hash does not match the externally pinned one.
    rollback_checkpoint = _checkpoint(gen1_snapshot, root_state, generation=1, subject_sha=SUBJECT)
    with pytest.raises(AcceptanceRejected) as caught:
        evaluate(
            nodes, [record],
            trust_snapshot=gen1_snapshot, root_state=root_state,
            bootstrap_root_key_hex=BOOTSTRAP_PUBLIC_HEX,
            trust_checkpoint=rollback_checkpoint, pinned_checkpoint_hash=real_pin,
            subject_sha=SUBJECT, artifact_bytes=artifact_bytes,
        )
    assert caught.value.code == "UNPINNED_CHECKPOINT"

    # The real, pinned current state (gen2, key revoked) correctly rejects
    # the same record too, but for the right reason -- proving the pin
    # defense is not just blocking everything regardless of content.
    with pytest.raises(AcceptanceRejected) as caught:
        evaluate(
            nodes, [record],
            trust_snapshot=gen2_snapshot, root_state=root_state,
            bootstrap_root_key_hex=BOOTSTRAP_PUBLIC_HEX,
            trust_checkpoint=current_checkpoint, pinned_checkpoint_hash=real_pin,
            subject_sha=SUBJECT, artifact_bytes=artifact_bytes,
        )
    assert caught.value.code == "REVOKED_REVIEWER"


def test_caller_supplied_bootstrap_key_never_becomes_authoritative():
    """A self-consistent root_state -- validly signed by SOME key, with
    that same key supplied as bootstrap_root_key_hex -- still fails unless
    that exact key also appears in this module's own hardcoded
    PINNED_BOOTSTRAP_ROOT_KEYS. Passing a key in is never, by itself,
    enough to make it authoritative."""
    nodes = [_pair(build_nodes(), "G3", [])]
    attacker_bootstrap = Ed25519PrivateKey.generate()
    attacker_bootstrap_hex = _public_hex(attacker_bootstrap)
    attacker_roots = [{"root_id": "attacker-root", "public_key_hex": ROOT_PUBLIC_HEX, "revoked": False}]
    attacker_root_state = _root_state(attacker_roots, signer=attacker_bootstrap)
    private, trust = _entry("CLAUDE", "claude")
    record, content = _signed(_node(nodes, "G3"), private, trust, label="bootstrap-attack")
    snapshot = _trust_snapshot([trust])
    with pytest.raises(AcceptanceRejected) as caught:
        evaluate(
            nodes, [record],
            trust_snapshot=snapshot, root_state=attacker_root_state,
            bootstrap_root_key_hex=attacker_bootstrap_hex,
            subject_sha=SUBJECT, artifact_bytes={record["artifact_sha256"]: content},
        )
    assert caught.value.code == "UNPINNED_BOOTSTRAP"


def test_committed_baseline_pins_no_real_bootstrap_key():
    """The real, committed PINNED_BOOTSTRAP_ROOT_KEYS is empty -- no real
    bootstrap identity is provisioned yet. Checked from this module's own
    source text rather than by reloading the module mid-suite (which would
    mutate shared global state -- POLICY_VERSION, the class identity of
    AcceptanceRejected, etc. -- for every other test in this process)."""
    source = Path(engine.__file__).read_text(encoding="utf-8")
    assert "PINNED_BOOTSTRAP_ROOT_KEYS = frozenset()" in source


def test_checkpoint_pin_is_independent_of_the_subject_sha_itself():
    """Guards against the self-referential anti-pattern the audit
    explicitly warned against: the pin is a hash of the checkpoint's own
    content (which includes subject_sha as one input among several, not
    the whole of it), never the raw commit SHA. Publishing a checkpoint
    as part of commit X's own tree therefore never requires computing X's
    hash in advance to construct the file that must later match it."""
    nodes = [_pair(build_nodes(), "G3", [])]
    private, trust = _entry("CLAUDE", "claude")
    record, content = _signed(_node(nodes, "G3"), private, trust, label="self-ref")
    snapshot, root_state, checkpoint, pin = _chain([trust])
    assert pin != SUBJECT
    assert checkpoint["subject_sha"] == SUBJECT

    # Two checkpoints sharing the same subject_sha but different
    # snapshot/root content must produce different pins -- the pin
    # distinguishes documents at the same commit, not just commits from
    # each other.
    _other_private, other_trust = _entry("CLAUDE", "claude-2")
    other_snapshot = _trust_snapshot([other_trust], generation=1, git_sha=SUBJECT)
    other_checkpoint = _checkpoint(other_snapshot, root_state, generation=1, subject_sha=SUBJECT)
    assert other_checkpoint["subject_sha"] == checkpoint["subject_sha"]
    assert _pin(other_checkpoint) != pin

    accepted = evaluate(
        nodes, [record], trust_snapshot=snapshot, root_state=root_state,
        bootstrap_root_key_hex=BOOTSTRAP_PUBLIC_HEX,
        trust_checkpoint=checkpoint, pinned_checkpoint_hash=pin,
        subject_sha=SUBJECT, artifact_bytes={record["artifact_sha256"]: content},
    )
    assert accepted == {"G3": record["artifact_sha256"]}
