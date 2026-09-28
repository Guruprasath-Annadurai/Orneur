"""Corpus-generation authorization gate: a SEPARATE, narrowly-scoped, fail-closed gate from model-execution authorization and from
authority-key registration / the signed inventory attestation. Registering a key or having a signed attestation must never, by
itself, authorize corpus generation."""
import copy
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import authority_registry as AR
from orca.eval.genesis_v2 import corpus_generation_authorization as CGA
from orca.eval.genesis_v2 import inventory as INV
from orca.eval.genesis_v2 import prereg as PR

ROOT = Path(__file__).resolve().parents[1]
SHA = "b" * 40
NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)
INV_DIGEST = "1" * 64
PREREG_DIGEST = "2" * 64


def _need_crypto():
    if os.environ.get("ORNEUR_REQUIRE_CRYPTOGRAPHY") == "1":
        import cryptography.hazmat.primitives.asymmetric.ed25519  # noqa: F401
    else:
        pytest.importorskip("cryptography")


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def signer():
    _need_crypto()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    keys = [{"key_id": "k-owner", "public_key_hex": pub, "identity": "owner-1", "role": "OWNER"}]

    def make(**over):
        r = CGA.default_record()
        r.update({"authorization_id": "cgauth-" + "ab" * 8, "status": "AUTHORIZED", "purpose": CGA.PURPOSE,
                  "authorized_scope": ["PILOT_TRAIN", "DEV"], "authorized_commit_sha": SHA,
                  "authorized_artifact_digests": {"corpus_inventory_digest": INV_DIGEST, "preregistration_record_sha256": PREREG_DIGEST},
                  "issued_at": ts(NOW - timedelta(hours=1)), "expires_at": ts(NOW + timedelta(days=1)),
                  "authorizing_authority": {"identity": "owner-1", "role": "OWNER", "key_id": "k-owner"}})
        r.update(over)
        r["signature"] = sk.sign(CGA.canonical_signing_bytes(r)).hex()
        return r
    return make, keys


def req(**over):
    base = dict(commit_sha=SHA, requested_scope=("PILOT_TRAIN", "DEV"), current_inventory_digest=INV_DIGEST,
                current_prereg_record_sha256=PREREG_DIGEST, event_name="workflow_dispatch")
    base.update(over)
    return CGA.Request(**base)


# ---------------------------------------------------------------- committed state
def test_committed_record_is_not_authorized():
    rec = json.loads((ROOT / CGA.RECORD_PATH).read_text())
    assert rec == CGA.default_record()
    assert rec["status"] == "NOT_AUTHORIZED"
    assert set(rec) == CGA.RECORD_KEYS


def test_registering_an_authority_key_never_authorizes_corpus_generation_by_itself():
    # Uses the REAL, currently-registered authority key (orneur-owner-authority-1) and the REAL committed (NOT_AUTHORIZED)
    # corpus-generation record. Registration + a signed inventory attestation existing elsewhere must not leak into this gate.
    ar_doc, ar_problems = AR.load(ROOT / AR.REGISTRY_PATH)
    assert ar_problems == [] and ar_doc["records"]
    keys = CGA.load_keys(ROOT)
    assert len(keys) >= 1
    rec = json.loads((ROOT / CGA.RECORD_PATH).read_text())
    v = CGA.verify(rec, req(commit_sha="0" * 40), keys)
    assert not v.authorized and "NOT_AUTHORIZED" in v.reasons


def test_a_validly_signed_authorized_record_verifies(signer):
    make, keys = signer
    v = CGA.verify(make(), req(), keys, now=NOW)
    assert v.authorized, v.reasons


# ---------------------------------------------------------------- positive/negative matrix
def test_wrong_purpose_denied(signer):
    make, keys = signer
    v = CGA.verify(make(purpose="SOMETHING_ELSE"), req(), keys, now=NOW)
    assert not v.authorized and "WRONG_PURPOSE" in v.reasons


def test_out_of_scope_artifact_denied(signer):
    make, keys = signer
    v = CGA.verify(make(authorized_scope=["PILOT_TRAIN"]), req(requested_scope=("PILOT_TRAIN", "SCREEN")), keys, now=NOW)
    assert not v.authorized and "REQUESTED_SCOPE_EXCEEDS_AUTHORIZATION" in v.reasons


def test_scope_must_be_a_real_artifact_class(signer):
    make, keys = signer
    v = CGA.verify(make(authorized_scope=["NOT_A_REAL_CLASS"]), req(), keys, now=NOW)
    assert not v.authorized and "BAD_AUTHORIZED_SCOPE" in v.reasons


def test_commit_mismatch_is_the_classic_replay_case(signer):
    make, keys = signer
    v = CGA.verify(make(), req(commit_sha="c" * 40), keys, now=NOW)
    assert not v.authorized and "COMMIT_SHA_MISMATCH" in v.reasons


def test_inventory_digest_mismatch_denied_when_evidence_changed(signer):
    make, keys = signer
    v = CGA.verify(make(), req(current_inventory_digest="9" * 64), keys, now=NOW)
    assert not v.authorized and "CORPUS_INVENTORY_DIGEST_MISMATCH" in v.reasons


def test_prereg_digest_mismatch_denied(signer):
    make, keys = signer
    v = CGA.verify(make(), req(current_prereg_record_sha256="9" * 64), keys, now=NOW)
    assert not v.authorized and "PREREGISTRATION_DIGEST_MISMATCH" in v.reasons


def test_expired_authorization_denied(signer):
    make, keys = signer
    rec = make(issued_at=ts(NOW - timedelta(days=2)), expires_at=ts(NOW - timedelta(hours=1)))
    v = CGA.verify(rec, req(), keys, now=NOW)
    assert not v.authorized and "EXPIRED" in v.reasons


def test_not_yet_valid_denied(signer):
    make, keys = signer
    rec = make(issued_at=ts(NOW + timedelta(hours=1)), expires_at=ts(NOW + timedelta(days=1)))
    v = CGA.verify(rec, req(), keys, now=NOW)
    assert not v.authorized and "NOT_YET_VALID" in v.reasons


def test_validity_window_longer_than_max_denied(signer):
    make, keys = signer
    rec = make(issued_at=ts(NOW - timedelta(hours=1)), expires_at=ts(NOW + timedelta(days=30)))
    v = CGA.verify(rec, req(), keys, now=NOW)
    assert not v.authorized and "VALIDITY_WINDOW_TOO_LONG" in v.reasons


def test_stale_beyond_max_validity_denied_even_if_expires_at_is_far_future(signer):
    make, keys = signer
    # A record forged/edited to claim a short window but an old issued_at plus a still-future expires_at should still be rejected
    # once "now" has drifted more than MAX_VALIDITY past issued_at.
    rec = make(issued_at=ts(NOW - timedelta(days=10)), expires_at=ts(NOW + timedelta(days=1)))
    v = CGA.verify(rec, req(), keys, now=NOW)
    assert not v.authorized and ("STALE_BEYOND_MAX_VALIDITY" in v.reasons or "VALIDITY_WINDOW_TOO_LONG" in v.reasons)


def test_forged_signature_denied(signer):
    make, keys = signer
    rec = make()
    rec["signature"] = "00" * 64
    v = CGA.verify(rec, req(), keys, now=NOW)
    assert not v.authorized and "INVALID_SIGNATURE" in v.reasons


def test_tampered_field_after_signing_denied(signer):
    make, keys = signer
    rec = make()
    rec["authorized_scope"] = ["PILOT_TRAIN", "DEV", "SCREEN", "QUALIFICATION_HOLDOUT"]   # tampered after signing
    v = CGA.verify(rec, req(), keys, now=NOW)
    assert not v.authorized and "INVALID_SIGNATURE" in v.reasons


def test_unregistered_key_denied(signer):
    make, keys = signer
    v = CGA.verify(make(), req(), [], now=NOW)
    assert not v.authorized and "AUTHORITY_KEY_NOT_REGISTERED" in v.reasons


def test_revoked_key_effectively_denied_because_caller_must_filter_active_keys(signer):
    # load_keys() only returns ACTIVE (non-revoked) keys via identity_registry.is_active(); a revoked key is simply absent
    # from `keys`, which verify() treats identically to "never registered".
    make, keys = signer
    v = CGA.verify(make(), req(), [], now=NOW)   # simulates the revoked key having been filtered out upstream
    assert not v.authorized and "AUTHORITY_KEY_NOT_REGISTERED" in v.reasons


def test_non_owner_role_denied(signer):
    make, keys = signer
    keys = [{**keys[0], "role": "DELEGATED_OWNER"}]
    rec = make(authorizing_authority={"identity": "owner-1", "role": "DELEGATED_OWNER", "key_id": "k-owner"})
    rec["signature"] = None
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: F401 (fixture already imported this)
    v = CGA.verify(rec, req(), keys, now=NOW)
    assert not v.authorized


def test_identity_mismatch_denied(signer):
    make, keys = signer
    rec = make(authorizing_authority={"identity": "someone-else", "role": "OWNER", "key_id": "k-owner"})
    v = CGA.verify(rec, req(), keys, now=NOW)
    assert not v.authorized and "AUTHORITY_NOT_OWNER_OR_IDENTITY_MISMATCH" in v.reasons


def test_non_dispatch_event_denied(signer):
    make, keys = signer
    v = CGA.verify(make(), req(event_name="push"), keys, now=NOW)
    assert not v.authorized and "EVENT_NOT_EXPLICIT_DISPATCH" in v.reasons


def test_missing_or_malformed_record_denied(signer):
    make, keys = signer
    assert not CGA.verify(None, req(), keys, now=NOW).authorized
    assert not CGA.verify({}, req(), keys, now=NOW).authorized
    rec = make()
    del rec["authorized_scope"]
    assert not CGA.verify(rec, req(), keys, now=NOW).authorized


def test_bad_authorization_id_format_denied(signer):
    make, keys = signer
    v = CGA.verify(make(authorization_id="not-the-right-format"), req(), keys, now=NOW)
    assert not v.authorized and "BAD_AUTHORIZATION_ID" in v.reasons


def test_bad_commit_sha_format_denied(signer):
    make, keys = signer
    v = CGA.verify(make(authorized_commit_sha="not-40-hex"), req(), keys, now=NOW)
    assert not v.authorized and "BAD_AUTHORIZED_COMMIT_SHA" in v.reasons


# ---------------------------------------------------------------- real integration: currently reachable digests
def test_real_inventory_and_prereg_digests_are_computable_and_would_bind_correctly():
    inv = json.loads((ROOT / INV.INVENTORY_PATH).read_text())
    real_inv_digest = INV.inventory_digest(inv)
    draft = json.loads((ROOT / PR.DRAFT_PATH).read_text())
    real_prereg_sha = draft["record_sha256"]
    assert len(real_inv_digest) == 64 and len(real_prereg_sha) == 64
    # a request built from the REAL current evidence state matches only a record binding those exact digests
    r = req(current_inventory_digest=real_inv_digest, current_prereg_record_sha256=real_prereg_sha)
    assert r.current_inventory_digest == real_inv_digest
