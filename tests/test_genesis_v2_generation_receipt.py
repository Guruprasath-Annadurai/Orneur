"""Generation receipt: durable, authenticated evidence of WHEN a specific corpus was actually generated, bound to
the CGA that permitted it and the manifest describing its content (generation-provenance-closure phase, items 1-2)."""
import os
from datetime import datetime, timedelta, timezone

import pytest

from orca.eval.genesis_v2 import generation_receipt as GRC

NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
AUTH_ID = "cgauth-" + "ab" * 8
CORPUS_ID = "gce2c-" + "cd" * 16
EVAL_VERSION = "genesis-capability-eval/2.0.0"
CORPUS_DIGEST = "1" * 64
CODE_HASH = "2" * 64
COMMIT_SHA = "b" * 40


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
        r = {"schema_version": GRC.SCHEMA_VERSION, "corpus_generation_authorization_id": AUTH_ID, "corpus_id": CORPUS_ID,
             "eval_version": EVAL_VERSION, "corpus_digest": CORPUS_DIGEST, "generator_code_tree_sha256": CODE_HASH,
             "generating_commit_sha": COMMIT_SHA, "generator_identity": "gen-1", "generated_at": ts(NOW),
             "attesting_authority": {"identity": "owner-1", "role": "OWNER", "key_id": "k-owner"}, "signature": "0" * 128}
        r.update(over)
        r["signature"] = sk.sign(GRC.receipt_signing_bytes(r)).hex()
        return r
    return make, keys


def _auth_record(**over):
    r = {"authorization_id": AUTH_ID, "reviewed_commit_sha": COMMIT_SHA, "authorized_code_tree_sha256": CODE_HASH,
         "issued_at": ts(NOW - timedelta(hours=1)), "expires_at": ts(NOW + timedelta(days=1))}
    r.update(over)
    return r


def _manifest(**over):
    r = {"corpus_id": CORPUS_ID, "generator_code_sha256": CODE_HASH, "generated_at_commit_sha": COMMIT_SHA}
    r.update(over)
    return r


# ---------------------------------------------------------------- structural validation
def test_default_receipt_has_the_required_schema_shape():
    assert set(GRC.default_receipt()) == GRC.REQUIRED_FIELDS


def test_validate_receipt_rejects_non_dict():
    assert GRC.validate_receipt(None) == ["RECEIPT_NOT_AN_OBJECT"]
    assert GRC.validate_receipt("not a dict") == ["RECEIPT_NOT_AN_OBJECT"]


def test_validate_receipt_rejects_schema_mismatch():
    assert GRC.validate_receipt({"only": "one field"})[0].startswith("RECEIPT_SCHEMA_MISMATCH")


def test_validate_receipt_accepts_a_well_formed_receipt(signer):
    make, _ = signer
    assert GRC.validate_receipt(make()) == []


@pytest.mark.parametrize("field,bad", [
    ("corpus_generation_authorization_id", "not-a-real-id"),
    ("corpus_id", "not-a-real-corpus-id"),
    ("eval_version", ""),
    ("corpus_digest", "not-hex"),
    ("generator_code_tree_sha256", "z" * 64),
    ("generating_commit_sha", "short"),
    ("generator_identity", ""),
    ("generated_at", "not-a-timestamp"),
    ("signature", ""),
])
def test_validate_receipt_catches_malformed_fields(signer, field, bad):
    make, _ = signer
    rec = make()
    rec[field] = bad
    assert GRC.validate_receipt(rec) != []


def test_validate_receipt_catches_malformed_attesting_authority(signer):
    make, _ = signer
    rec = make()
    rec["attesting_authority"] = {"identity": "x"}   # missing role/key_id
    assert any("attesting_authority" in p for p in GRC.validate_receipt(rec))


# ---------------------------------------------------------------- signature authentication
def test_verify_receipt_signature_accepts_a_genuine_signature(signer):
    make, keys = signer
    assert GRC.verify_receipt_signature(make(), keys) is None


def test_verify_receipt_signature_rejects_an_unsigned_receipt(signer):
    make, keys = signer
    rec = make()
    rec["signature"] = "0" * 128
    assert GRC.verify_receipt_signature(rec, keys) == "INVALID_SIGNATURE"


def test_verify_receipt_signature_rejects_an_attacker_signed_receipt(signer):
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    make, keys = signer
    rec = make()
    attacker_sk = Ed25519PrivateKey.generate()
    rec["signature"] = attacker_sk.sign(GRC.receipt_signing_bytes(rec)).hex()
    assert GRC.verify_receipt_signature(rec, keys) == "INVALID_SIGNATURE"


def test_verify_receipt_signature_rejects_an_unregistered_key_id(signer):
    make, keys = signer
    rec = make()
    rec["attesting_authority"] = {**rec["attesting_authority"], "key_id": "k-unregistered"}
    assert GRC.verify_receipt_signature(rec, keys) == "AUTHORITY_KEY_NOT_REGISTERED"


def test_verify_receipt_signature_rejects_a_non_owner_authority(signer):
    make, keys = signer
    keys = [{**keys[0], "role": "DELEGATED_OWNER"}]
    assert GRC.verify_receipt_signature(make(), keys) == "AUTHORITY_NOT_OWNER_OR_IDENTITY_MISMATCH"


def test_verify_receipt_signature_never_raises_on_malformed_input():
    assert GRC.verify_receipt_signature({"attesting_authority": None}, []) == "AUTHORITY_KEY_NOT_REGISTERED"
    assert GRC.verify_receipt_signature({}, [None, 42, "not-a-dict"]) == "AUTHORITY_KEY_NOT_REGISTERED"


# ---------------------------------------------------------------- item 1: window problems (issued_at <= generated_at <= expires_at)
def test_window_problems_accepts_a_receipt_inside_the_window():
    assert GRC.window_problems({"generated_at": ts(NOW)}, _auth_record()) == []


def test_window_problems_rejects_generated_at_before_issued():
    p = GRC.window_problems({"generated_at": ts(NOW - timedelta(hours=2))}, _auth_record())
    assert p == ["GENERATED_AT_BEFORE_AUTHORIZATION_ISSUED"]


def test_window_problems_rejects_generated_at_after_expires():
    p = GRC.window_problems({"generated_at": ts(NOW + timedelta(days=2))}, _auth_record())
    assert p == ["GENERATED_AT_AFTER_AUTHORIZATION_EXPIRED"]


def test_window_problems_never_uses_the_current_verification_time_clock():
    """The core item-1 property: a HISTORICAL authorization window (long elapsed relative to 'now' in the real
    world) is checked against the RECEIPT's own generated_at, never against datetime.now(). A receipt correctly
    timestamped inside a decade-old window still passes; this function accepts no 'now' parameter at all."""
    import inspect
    assert "now" not in inspect.signature(GRC.window_problems).parameters
    historical_auth = _auth_record(issued_at="2020-01-01T00:00:00Z", expires_at="2020-01-03T00:00:00Z")
    assert GRC.window_problems({"generated_at": "2020-01-02T00:00:00Z"}, historical_auth) == []


def test_window_problems_rejects_an_impossible_generated_at_timestamp():
    assert GRC.window_problems({"generated_at": "not-a-timestamp"}, _auth_record()) == ["IMPOSSIBLE_GENERATED_AT_TIMESTAMP"]


def test_window_problems_rejects_an_unparseable_authorization_window():
    assert GRC.window_problems({"generated_at": ts(NOW)}, _auth_record(issued_at="garbage")) == ["AUTHORIZATION_WINDOW_UNPARSEABLE"]


# ---------------------------------------------------------------- item 2: binding to the OTHER authenticated objects
def test_binding_problems_accepts_a_correctly_bound_receipt(signer):
    make, _ = signer
    assert GRC.binding_problems(make(), authorization_record=_auth_record(), manifest=_manifest(),
                                 expected_corpus_digest=CORPUS_DIGEST, requested_eval_version=EVAL_VERSION) == []


def test_binding_problems_catches_authorization_id_mismatch(signer):
    make, _ = signer
    rec = make(corpus_generation_authorization_id="cgauth-" + "99" * 8)
    p = GRC.binding_problems(rec, authorization_record=_auth_record(), manifest=_manifest(),
                              expected_corpus_digest=CORPUS_DIGEST, requested_eval_version=EVAL_VERSION)
    assert any("corpus_generation_authorization_id" in x for x in p)


def test_binding_problems_catches_corpus_id_mismatch(signer):
    make, _ = signer
    rec = make(corpus_id="gce2c-" + "00" * 16)
    p = GRC.binding_problems(rec, authorization_record=_auth_record(), manifest=_manifest(),
                              expected_corpus_digest=CORPUS_DIGEST, requested_eval_version=EVAL_VERSION)
    assert any("receipt.corpus_id" in x for x in p)


def test_binding_problems_catches_eval_version_mismatch(signer):
    make, _ = signer
    rec = make()
    p = GRC.binding_problems(rec, authorization_record=_auth_record(), manifest=_manifest(),
                              expected_corpus_digest=CORPUS_DIGEST, requested_eval_version="some-other-version")
    assert any("receipt.eval_version" in x for x in p)


def test_binding_problems_catches_corpus_digest_mismatch(signer):
    make, _ = signer
    rec = make(corpus_digest="0" * 64)
    p = GRC.binding_problems(rec, authorization_record=_auth_record(), manifest=_manifest(),
                              expected_corpus_digest=CORPUS_DIGEST, requested_eval_version=EVAL_VERSION)
    assert any("receipt.corpus_digest" in x for x in p)


def test_binding_problems_catches_generating_commit_mismatch(signer):
    make, _ = signer
    rec = make(generating_commit_sha="d" * 40)
    p = GRC.binding_problems(rec, authorization_record=_auth_record(), manifest=_manifest(),
                              expected_corpus_digest=CORPUS_DIGEST, requested_eval_version=EVAL_VERSION)
    assert any("receipt.generating_commit_sha" in x for x in p)


def test_binding_problems_catches_code_tree_mismatch_against_both_manifest_and_authorization(signer):
    make, _ = signer
    rec = make(generator_code_tree_sha256="f" * 64)
    p = GRC.binding_problems(rec, authorization_record=_auth_record(), manifest=_manifest(),
                              expected_corpus_digest=CORPUS_DIGEST, requested_eval_version=EVAL_VERSION)
    assert len(p) == 2
    assert any("signed manifest's generator_code_sha256" in x for x in p)
    assert any("authenticated CGA's authorized_code_tree_sha256" in x for x in p)


# ---------------------------------------------------------------- composition: verify_receipt()
def test_verify_receipt_accepts_a_fully_valid_receipt(signer):
    make, keys = signer
    problems = GRC.verify_receipt(make(), authorization_record=_auth_record(), manifest=_manifest(),
                                   expected_corpus_digest=CORPUS_DIGEST, requested_eval_version=EVAL_VERSION, authority_keys=keys)
    assert problems == []


def test_verify_receipt_checks_structure_before_signature(signer):
    make, keys = signer
    problems = GRC.verify_receipt({"not": "a receipt"}, authorization_record=_auth_record(), manifest=_manifest(),
                                   expected_corpus_digest=CORPUS_DIGEST, requested_eval_version=EVAL_VERSION, authority_keys=keys)
    assert problems and problems[0].startswith("RECEIPT_SCHEMA_MISMATCH")


def test_verify_receipt_checks_signature_before_binding(signer):
    make, keys = signer
    rec = make(corpus_id="gce2c-" + "00" * 16)   # also a binding violation
    rec["signature"] = "0" * 128   # but unsigned -- this must be caught FIRST
    problems = GRC.verify_receipt(rec, authorization_record=_auth_record(), manifest=_manifest(),
                                   expected_corpus_digest=CORPUS_DIGEST, requested_eval_version=EVAL_VERSION, authority_keys=keys)
    assert problems == ["SIGNATURE_INVALID:INVALID_SIGNATURE"]


def test_verify_receipt_checks_binding_before_window(signer):
    make, keys = signer
    rec = make(corpus_id="gce2c-" + "00" * 16, generated_at=ts(NOW + timedelta(days=30)))   # also outside the window
    problems = GRC.verify_receipt(rec, authorization_record=_auth_record(), manifest=_manifest(),
                                   expected_corpus_digest=CORPUS_DIGEST, requested_eval_version=EVAL_VERSION, authority_keys=keys)
    assert problems and all("corpus_id" in p for p in problems)   # the window problem never appears


def test_verify_receipt_reaches_window_check_only_once_everything_else_is_valid(signer):
    make, keys = signer
    rec = make(generated_at=ts(NOW + timedelta(days=30)))
    problems = GRC.verify_receipt(rec, authorization_record=_auth_record(), manifest=_manifest(),
                                   expected_corpus_digest=CORPUS_DIGEST, requested_eval_version=EVAL_VERSION, authority_keys=keys)
    assert problems == ["GENERATED_AT_AFTER_AUTHORIZATION_EXPIRED"]


def test_verify_receipt_never_raises_on_malformed_input():
    assert GRC.verify_receipt(None, authorization_record={}, manifest={}, expected_corpus_digest="x",
                               requested_eval_version="x", authority_keys=[None, 42]) == ["RECEIPT_NOT_AN_OBJECT"]
