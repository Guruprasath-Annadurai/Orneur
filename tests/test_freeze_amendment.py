"""The freeze amendment is prepared and inactive.

These tests must pass while the historical governance diff still fails.
A passing result here does not make that gate green and does not authorize
training.
"""
import json
from pathlib import Path

import pytest

from orca.freeze_amendment import (
    AWAITING,
    BASELINE,
    DECISION,
    PERMITTED,
    PROPOSAL_PATH,
    PROPOSAL_SHA256,
    REJECTED,
    SCHEMA_APPROVAL,
    SIGNING_DOMAIN,
    TRUST_ROOT_CODE_PATH,
    TRUST_ROOT_CODE_SHA256,
    UNCHANGED_PATHS,
    assess_approvals,
    canonical_approval_bytes,
    classify_diff,
    classify_presented_trust,
    ed25519_signature_matches,
    evaluate,
    file_digest,
    load_approval_documents,
    load_independent_trust,
    proposal_digest,
)

ROOT = Path(__file__).resolve().parents[1]
PERMITTED_PATHS = tuple(path for path, _digest in PERMITTED)
SIG = "ab" * 64


def _clean(**overrides):
    payload = {
        "baseline_present": True,
        "introducing_present": True,
        "entries": [("A", path) for path in PERMITTED_PATHS],
        "digests": {path: digest for path, digest in PERMITTED},
        "historical_digests": {path: digest for path, digest in PERMITTED},
        "unchanged": {path: ("same", "same") for path in UNCHANGED_PATHS},
        "trust_code_sha256": TRUST_ROOT_CODE_SHA256,
    }
    payload.update(overrides)
    return payload


def _approval(**overrides):
    document = {
        "schema_version": SCHEMA_APPROVAL,
        "proposal_sha256": PROPOSAL_SHA256,
        "baseline": BASELINE,
        "decision": DECISION,
        "paths": [{"path": path, "sha256": digest} for path, digest in PERMITTED],
        "founder": {"identity": "founder.example", "key_id": "founder-key-1"},
        "signature": SIG,
    }
    document.update(overrides)
    return document


def _sign(document: dict) -> tuple[bytes, dict]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    signed = dict(document)
    signed["signature"] = private.sign(canonical_approval_bytes(signed)).hex()
    return public, signed


def test_approval_instructions_do_not_activate_or_invent_a_key():
    text = (ROOT / "docs/orneur/cursor/FREEZE_AMENDMENT_APPROVAL.md").read_text(encoding="utf-8")
    assert PROPOSAL_SHA256 in text
    assert "AWAITING_FOUNDER_SIGNED_APPROVAL" in text
    assert "Do not generate a key" in text
    assert "Activated: false" in text
    for path, digest in PERMITTED:
        assert path in text and digest in text


def test_proposal_pin_matches_the_file_and_names_option_a():
    text = (ROOT / PROPOSAL_PATH).read_text(encoding="utf-8")
    assert proposal_digest(ROOT) == PROPOSAL_SHA256
    assert "AWAITING_FOUNDER_SIGNED_APPROVAL" in text
    assert "adopt_files" in text
    assert "Activated: false" in text
    for path, digest in PERMITTED:
        assert path in text and digest in text


def test_three_documents_match_the_pins_and_deny_training():
    for path, digest in PERMITTED:
        assert file_digest(ROOT / path) == digest
    registry, authorization, revocations = (json.loads((ROOT / path).read_text()) for path, _digest in PERMITTED)
    assert registry["records"] == []
    assert authorization["status"] == "NOT_AUTHORIZED"
    assert authorization["limits"]["gpu_allowed"] is False
    assert authorization["limits"]["max_spend_usd"] == 0
    assert authorization["signature"] is None
    assert revocations["revoked_authorization_ids"] == []


def test_live_verdict_is_awaiting_and_inactive():
    verdict = evaluate(ROOT)
    assert verdict.status == AWAITING
    assert verdict.activated is False
    assert verdict.reason == "approval_absent"
    assert verdict.baseline == BASELINE
    assert verdict.baseline_present is True
    assert verdict.historical_commit_present is True
    assert verdict.digest_ok is True
    assert verdict.observed_paths == PERMITTED_PATHS
    assert verdict.signature_checked is False
    assert verdict.founder_authenticated is False
    assert verdict.training_permission is False
    assert verdict.gpu_permission is False
    assert verdict.spending_permission is False
    assert verdict.corpus_permission is False
    assert verdict.model_selection_permission is False
    assert load_independent_trust()["established"] is False
    assert load_independent_trust()["public_key"] is None


def test_governance_test_still_requires_an_empty_historical_diff():
    source = (ROOT / "tests" / "test_evalinfra_governance.py").read_text(encoding="utf-8")
    start = source.index("def test_no_frozen_or_private_path_differs_from_the_branch_point")
    body = source[start:source.index("\ndef ", start + 1) if "\ndef " in source[start + 1:] else len(source)]
    assert "pytest.skip" not in body
    assert "pytest.fail" in body
    assert 'out.stdout.strip() == ""' in body
    assert BASELINE in body
    assert "freeze_amendment" not in source
    assert classify_diff(**_clean()) == ()


def test_historical_diff_is_exactly_the_three_additions():
    import subprocess

    probe = subprocess.run(["git", "diff", "--name-only", BASELINE, "--", *PERMITTED_PATHS[:1]], cwd=ROOT, capture_output=True, text=True)
    assert probe.returncode == 0
    out = subprocess.run(
        ["git", "diff", "--name-only", BASELINE, "--",
         "docs/orneur/acceptance", "docs/orneur/authorization", "docs/orneur/phase-21/rse",
         "orca/rse", "orca/train/authorization.py", "docs/orneur/acceptance/register_graph.json",
         "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_STATUS.json", "eval_private"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert out.returncode == 0
    assert out.stdout.splitlines() == list(PERMITTED_PATHS)


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda payload: payload.update(baseline_present=False), "missing_historical_commit"),
        (lambda payload: payload.update(introducing_present=False), "missing_historical_commit"),
        (lambda payload: payload.update(entries=None), "historical_evidence_unreadable"),
        (lambda payload: payload["entries"].append(("A", "docs/orneur/authorization/EXTRA.json")), "unauthorized_path"),
        (lambda payload: payload.update(digests={**payload["digests"], PERMITTED_PATHS[0]: "0" * 64}), "permitted_bytes_modified"),
        (lambda payload: payload["entries"].remove(("A", PERMITTED_PATHS[2])), "permitted_path_missing"),
        (lambda payload: payload["entries"].append(("D", "docs/orneur/phase-21/rse/gone.json")), "frozen_deletion"),
        (lambda payload: payload["entries"].append(("M", "docs/orneur/acceptance/acceptance_ledger.json")), "acceptance_ledger_changed"),
        (lambda payload: payload["entries"].append(("M", "docs/orneur/acceptance/register_graph.json")), "acceptance_graph_changed"),
        (lambda payload: payload["entries"].append(("M", "orca/train/authorization.py")), "training_authorization_changed"),
        (lambda payload: payload["unchanged"].update({"docs/orneur/authorization/TRAINING_AUTHORITY_REGISTRY.json": ("old", "new")}), "trust_root_changed"),
        (lambda payload: payload.update(trust_code_sha256="f" * 64), "trust_root_changed"),
        (lambda payload: payload.update(historical_digests={**payload["historical_digests"], PERMITTED_PATHS[1]: "1" * 64}), "historical_bytes_mismatch"),
    ],
)
def test_diff_classifier_rejects_unauthorized_shapes(mutate, reason):
    payload = _clean()
    mutate(payload)
    assert classify_diff(**payload)[0] == reason


def test_presented_trust_is_never_authority():
    assert classify_presented_trust(None) == "missing_trust_material"
    assert classify_presented_trust(b"\x00" * 32) == "caller_supplied_trust_refused"
    assert classify_presented_trust({"schema_version": "registry", "records": []}) == "empty_registry_not_authority"
    assert classify_presented_trust({"public_key_hex": "ab" * 32, "expiry": "2000-01-01T00:00:00Z"}) == "stale_trust_material"
    assert classify_presented_trust({"public_key_hex": "ab" * 32, "expiry": "2999-01-01T00:00:00Z"}) == "caller_supplied_trust_refused"
    substituted = evaluate(ROOT)
    assert substituted.activated is False


def test_substituted_trust_loader_cannot_activate(monkeypatch):
    public, signed = _sign(_approval())
    monkeypatch.setattr(
        "orca.freeze_amendment.load_independent_trust",
        lambda: {
            "established": True,
            "stale": False,
            "source": "test",
            "reason": None,
            "public_key": public,
            "key_id": "founder-key-1",
            "identity": "founder.example",
        },
    )
    assert ed25519_signature_matches(public, bytes.fromhex(signed["signature"]), signed) is True
    verdict = evaluate(ROOT, approvals=[signed])
    assert verdict.status == REJECTED
    assert verdict.activated is False
    assert verdict.reason == "caller_supplied_trust_refused"
    assert verdict.founder_authenticated is False
    assert verdict.signature_checked is False


def test_signed_approval_cannot_clear_an_unauthorized_diff(monkeypatch):
    import orca.freeze_amendment as amendment

    _public, signed = _sign(_approval())
    observed = amendment._observe(ROOT)
    observed["entries"] = list(observed["entries"]) + [("A", "docs/orneur/authorization/EXTRA.json")]
    observed["observed_paths"] = tuple(path for _status, path in observed["entries"])
    monkeypatch.setattr(amendment, "_observe", lambda _root: observed)
    verdict = evaluate(ROOT, approvals=[signed])
    assert verdict.status == REJECTED
    assert verdict.reason == "unauthorized_path"
    assert verdict.activated is False
    assert verdict.training_permission is False


def test_valid_ephemeral_signature_does_not_activate_or_cross_domains():
    public, signed = _sign(_approval())
    assert ed25519_signature_matches(public, bytes.fromhex(signed["signature"]), signed) is True
    verdict = evaluate(ROOT, approvals=[signed])
    assert verdict.status == AWAITING
    assert verdict.reason == "missing_trust_material"
    assert verdict.activated is False
    assert verdict.signature_checked is False
    assert verdict.founder_authenticated is False
    altered = dict(signed)
    altered["signature"] = ("00" + signed["signature"][2:])
    assert ed25519_signature_matches(public, bytes.fromhex(altered["signature"]), altered) is False
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    private = Ed25519PrivateKey.generate()
    other_public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    foreign = private.sign(b"orneur-training-authorization/1\n" + canonical_approval_bytes(signed)[len(SIGNING_DOMAIN):])
    assert ed25519_signature_matches(other_public, foreign, signed) is False
    genesis = private.sign(b"orneur-genesis-native-pretraining-authorization/1\n" + canonical_approval_bytes(signed)[len(SIGNING_DOMAIN):])
    assert ed25519_signature_matches(other_public, genesis, signed) is False


@pytest.mark.parametrize(
    ("documents", "reason"),
    [
        ([_approval(decision="remove_files")], "decision_rejected"),
        ([_approval(proposal_sha256="22" * 32)], "proposal_not_bound"),
        ([_approval(baseline="0" * 40)], "baseline_not_bound"),
        ([_approval(paths=_approval()["paths"] + [{"path": "docs/orneur/authorization/EXTRA.json", "sha256": "33" * 32}])], "path_set_mismatch"),
        ([_approval(paths=[{**_approval()["paths"][0], "sha256": "44" * 32}, *_approval()["paths"][1:]])], "digest_not_bound"),
        ([_approval(gpu_allowed=False)], "malformed_approval"),
        ([_approval(signature="abcd")], "malformed_approval"),
        ([_approval(founder={"identity": "", "key_id": "founder-key-1"})], "malformed_approval"),
        ([_approval(), _approval()], "duplicate_approvals"),
        ([_approval(), _approval(founder={"identity": "other.example", "key_id": "founder-key-2"})], "conflicting_approvals"),
        (["not-a-document"], "malformed_approval"),
    ],
)
def test_approval_shapes_are_rejected(documents, reason):
    assert assess_approvals(documents)[0] == reason
    verdict = evaluate(ROOT, approvals=documents)
    assert verdict.status == REJECTED
    assert verdict.activated is False
    assert verdict.reason == reason


def test_replay_across_two_signed_bodies_conflicts_and_stays_inactive():
    _first_public, first = _sign(_approval())
    _second_public, second = _sign(_approval(founder={"identity": "other.example", "key_id": "founder-key-2"}))
    assert assess_approvals([first, second]) == ("conflicting_approvals",)
    verdict = evaluate(ROOT, approvals=[first, second])
    assert verdict.activated is False
    assert verdict.status == REJECTED


def test_approval_store_refuses_symlinks_and_non_json(tmp_path):
    store = tmp_path / "docs" / "orneur" / "cursor" / "freeze_amendment_approvals"
    store.mkdir(parents=True)
    target = tmp_path / "elsewhere.json"
    target.write_text("{}", encoding="utf-8")
    (store / "approval.json").symlink_to(target)
    refused = load_approval_documents(tmp_path)
    assert refused.reason == "approval_store_refused"
    (store / "approval.json").unlink()
    (store / "note.txt").write_text("{}", encoding="utf-8")
    assert load_approval_documents(tmp_path).reason == "malformed_approval"
    (store / "note.txt").unlink()
    (store / "broken.json").write_text("{", encoding="utf-8")
    assert load_approval_documents(tmp_path).reason == "malformed_approval"


def test_missing_store_is_not_an_approval():
    assert load_approval_documents(ROOT).documents == ()
    assert load_approval_documents(ROOT).reason is None


def test_activation_cannot_be_true_in_this_source():
    source = (ROOT / "orca" / "freeze_amendment.py").read_text(encoding="utf-8")
    assert "activated=True" not in source
    assert "activated = True" not in source
    assert '"established": True' not in source
    assert "return True" not in source.split("def load_independent_trust")[1].split("def ")[0]


def test_native_pretraining_and_locks_remain_denied():
    from orca.genesis.governance.authorization import (
        NativePretrainingNotAuthorized,
        authorize_native_pretraining,
    )
    from orca.genesis.model.family_registry import default_registry
    from orca.rse.imp1.locks import (
        corpus_generation_authorized,
        gpu_authorized,
        model_selection_authorized,
        spending_authorized,
        training_authorized,
    )
    from orca.train.pretraining_evidence import worksheet

    registry = default_registry()
    assert registry["GENESIS"].status == "INTERFACE_ONLY"
    assert registry["NOVUS"].status == "NOT_AVAILABLE"
    assert registry["AETERNUM"].status == "NOT_AVAILABLE"
    assert training_authorized() is False
    assert gpu_authorized() is False
    assert spending_authorized() is False
    assert corpus_generation_authorized() is False
    assert model_selection_authorized() is False
    sheet = worksheet(ROOT)
    assert sheet["counted"] == 95
    assert sheet["ledger_accepted_count"] == 0
    assert sheet["ledger_sha256"] == "37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"
    assert sheet["founder_authorized"] is False
    assert sheet["training_start_permitted"] is False
    assert file_digest(ROOT / TRUST_ROOT_CODE_PATH) == TRUST_ROOT_CODE_SHA256
    with pytest.raises(NativePretrainingNotAuthorized) as denied:
        authorize_native_pretraining(
            repo_root=ROOT,
            record=_approval(),
            registry={"schema_version": "orneur-genesis-native-pretraining-authority-registry/1", "records": []},
            revoked_ids=[],
            req=None,
            revocation_check=lambda _authorization_id: False,
        )
    assert any(item.startswith("FOUNDER_ACCEPTANCE_INCOMPLETE") for item in denied.value.reasons)


def test_signature_verifier_rejects_a_short_key():
    _public, signed = _sign(_approval())
    assert ed25519_signature_matches(b"\x01" * 31, bytes.fromhex(signed["signature"]), signed) is False
    assert ed25519_signature_matches(b"\x01" * 32, b"\x02" * 63, signed) is False
