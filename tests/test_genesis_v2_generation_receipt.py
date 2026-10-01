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


# ---------------------------------------------------------------- build_unsigned_payload() / payload_digest() /
# attest_receipt() (generation-event-emission-integration phase, items 2-3): the generator emits, the owner attests
@pytest.fixture
def owner_signer():
    _need_crypto()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    keys = [{"key_id": "k-owner", "public_key_hex": pub, "identity": "owner-1", "role": "OWNER"}]
    authority = {"identity": "owner-1", "role": "OWNER", "key_id": "k-owner"}
    return sk, keys, authority


def _payload(**over):
    p = GRC.build_unsigned_payload(corpus_generation_authorization_id=AUTH_ID, corpus_id=CORPUS_ID, eval_version=EVAL_VERSION,
                                    corpus_digest=CORPUS_DIGEST, generator_code_tree_sha256=CODE_HASH,
                                    generating_commit_sha=COMMIT_SHA, generator_identity="gen-1", generated_at=ts(NOW))
    p.update(over)
    return p


def test_build_unsigned_payload_has_exactly_the_generator_emitted_fields():
    p = _payload()
    assert set(p) == GRC.PAYLOAD_FIELDS
    assert GRC.PAYLOAD_FIELDS == GRC.REQUIRED_FIELDS - {"attesting_authority", "signature"}


def test_payload_digest_changes_when_any_field_changes():
    base = _payload()
    base_digest = GRC.payload_digest(base)
    for field, bad in [("generator_identity", "attacker-gen"), ("generating_commit_sha", "d" * 40),
                        ("generator_code_tree_sha256", "f" * 64), ("corpus_digest", "0" * 64),
                        ("corpus_id", "gce2c-" + "00" * 16), ("corpus_generation_authorization_id", "cgauth-" + "99" * 8),
                        ("generated_at", ts(NOW + timedelta(days=1))), ("eval_version", "some-other-version")]:
        tampered = {**base, field: bad}
        assert GRC.payload_digest(tampered) != base_digest, f"digest did not change for tampered field {field!r}"


def test_attest_receipt_produces_a_receipt_that_passes_the_unchanged_verify_receipt_path(owner_signer):
    sk, keys, authority = owner_signer
    payload = _payload()
    receipt = GRC.attest_receipt(payload, attesting_authority=authority, sign_bytes=sk.sign,
                                  expected_payload_digest=GRC.payload_digest(payload))
    assert set(receipt) == GRC.REQUIRED_FIELDS
    assert GRC.verify_receipt_signature(receipt, keys) is None
    problems = GRC.verify_receipt(receipt, authorization_record=_auth_record(), manifest=_manifest(),
                                   expected_corpus_digest=CORPUS_DIGEST, requested_eval_version=EVAL_VERSION, authority_keys=keys)
    assert problems == []


def test_attest_receipt_requires_expected_payload_digest_as_a_mandatory_parameter(owner_signer):
    """Item 1, final-emission-evidence-hardening phase: the weaker, digest-optional call shape is removed
    entirely. Calling the production attestation API without expected_payload_digest must be impossible --
    proven here as a TypeError (missing required keyword-only argument), never a permissive fallback."""
    sk, keys, authority = owner_signer
    with pytest.raises(TypeError):
        GRC.attest_receipt(_payload(), attesting_authority=authority, sign_bytes=sk.sign)
    import inspect
    params = inspect.signature(GRC.attest_receipt).parameters
    assert params["expected_payload_digest"].default is inspect.Parameter.empty   # no default -- truly required


@pytest.mark.parametrize("field,bad", [
    ("generator_identity", "attacker-substituted-generator"),
    ("generating_commit_sha", "d" * 40),
    ("generator_code_tree_sha256", "f" * 64),
    ("corpus_digest", "0" * 64),
    ("corpus_id", "gce2c-" + "00" * 16),
    ("corpus_generation_authorization_id", "cgauth-" + "99" * 8),
    ("generated_at", "2099-01-01T00:00:00Z"),
    ("eval_version", "genesis-capability-eval/9.9.9"),
])
def test_attest_receipt_refuses_to_sign_a_payload_tampered_after_emission(owner_signer, field, bad):
    """Item 1, final-emission-evidence-hardening phase, regression tests 2-9: every one of the nine payload fields
    -- generator identity, commit, code digest, corpus digest, corpus ID, CGA authorization ID, timestamp, and eval
    version -- is independently proven to invalidate the mandatory digest check when tampered with after emission.
    The owner's attestation tool is handed the digest captured at TRUE emission time; if the payload it is asked
    to sign has since been altered in ANY field, the digest no longer matches and signing is refused BEFORE any
    signature is produced."""
    sk, keys, authority = owner_signer
    original = _payload()
    expected_digest = GRC.payload_digest(original)
    tampered = {**original, field: bad}
    with pytest.raises(GRC.ReceiptAttestationError):
        GRC.attest_receipt(tampered, attesting_authority=authority, sign_bytes=sk.sign, expected_payload_digest=expected_digest)


def test_attest_receipt_never_invokes_the_signing_callback_when_the_digest_comparison_fails(owner_signer):
    """Item 1, regression test 10: the signing callback must never even be CALLED when the digest mismatches --
    not merely that its result is discarded. Proven with a callback that records every invocation and would raise
    AssertionError if somehow invoked on tampered input."""
    sk, keys, authority = owner_signer
    calls = []

    def recording_sign(b):
        calls.append(b)
        return sk.sign(b)

    original = _payload()
    expected_digest = GRC.payload_digest(original)
    tampered = {**original, "corpus_digest": "0" * 64}
    with pytest.raises(GRC.ReceiptAttestationError):
        GRC.attest_receipt(tampered, attesting_authority=authority, sign_bytes=recording_sign, expected_payload_digest=expected_digest)
    assert calls == []   # never invoked

    # sanity: the SAME callback genuinely IS invoked on a correct, matching payload
    GRC.attest_receipt(original, attesting_authority=authority, sign_bytes=recording_sign, expected_payload_digest=expected_digest)
    assert len(calls) == 1


def test_attest_receipt_refuses_a_payload_for_a_different_successful_write():
    """Item 4: a receipt 'created for a different successful write' -- the owner tool is expected to sign payload
    A (digest captured from write A) but is handed payload B (a genuinely real, well-formed payload from a
    DIFFERENT write) instead. Caught by the same digest mismatch, before any signature is produced."""
    sk, keys, authority = None, None, None
    import os
    if os.environ.get("ORNEUR_REQUIRE_CRYPTOGRAPHY") == "1":
        import cryptography.hazmat.primitives.asymmetric.ed25519  # noqa: F401
    else:
        pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    authority = {"identity": "owner-1", "role": "OWNER", "key_id": "k-owner"}

    payload_a = _payload(corpus_id=CORPUS_ID)
    digest_a = GRC.payload_digest(payload_a)
    payload_b = _payload(corpus_id="gce2c-" + "00" * 16, corpus_digest="0" * 64)   # a genuinely different real write
    with pytest.raises(GRC.ReceiptAttestationError):
        GRC.attest_receipt(payload_b, attesting_authority=authority, sign_bytes=sk.sign, expected_payload_digest=digest_a)


def test_attest_receipt_rejects_a_malformed_payload_schema(owner_signer):
    sk, keys, authority = owner_signer
    digest = GRC.payload_digest(_payload())
    with pytest.raises(GRC.ReceiptAttestationError):
        GRC.attest_receipt({"only": "one field"}, attesting_authority=authority, sign_bytes=sk.sign, expected_payload_digest=digest)
    with pytest.raises(GRC.ReceiptAttestationError):
        GRC.attest_receipt("not a dict", attesting_authority=authority, sign_bytes=sk.sign, expected_payload_digest=digest)


def test_attest_receipt_rejects_a_malformed_attesting_authority(owner_signer):
    sk, keys, authority = owner_signer
    payload = _payload()
    with pytest.raises(GRC.ReceiptAttestationError):
        GRC.attest_receipt(payload, attesting_authority={"identity": "owner-1"}, sign_bytes=sk.sign,
                            expected_payload_digest=GRC.payload_digest(payload))


def test_attest_receipt_rejects_an_empty_or_non_string_expected_payload_digest(owner_signer):
    sk, keys, authority = owner_signer
    payload = _payload()
    for bad in ("", None, 12345):
        with pytest.raises(GRC.ReceiptAttestationError):
            GRC.attest_receipt(payload, attesting_authority=authority, sign_bytes=sk.sign, expected_payload_digest=bad)


def test_attest_receipt_never_holds_or_imports_a_private_key_itself():
    """The generator must never be handed the OWNER's private signing key (item 2's explicit constraint) --
    confirmed here by scanning attest_receipt()'s own source for any private-key-loading capability; it only ever
    calls the caller-supplied `sign_bytes` callable."""
    import inspect
    src = inspect.getsource(GRC.attest_receipt)
    for forbidden in ("PrivateKey", "private_key", "load_pem", "load_der"):
        assert forbidden not in src


# ---------------------------------------------------------------- item 5.B: attestation substitution across TWO
# genuinely different, real payloads (not just one payload tampered in place)
def test_attest_receipt_refuses_payload_a_paired_with_digest_b(owner_signer):
    sk, keys, authority = owner_signer
    payload_a = _payload(corpus_id=CORPUS_ID)
    payload_b = _payload(corpus_id="gce2c-" + "00" * 16, corpus_digest="0" * 64)
    digest_b = GRC.payload_digest(payload_b)
    with pytest.raises(GRC.ReceiptAttestationError):
        GRC.attest_receipt(payload_a, attesting_authority=authority, sign_bytes=sk.sign, expected_payload_digest=digest_b)


def test_attest_receipt_refuses_payload_b_paired_with_digest_a(owner_signer):
    sk, keys, authority = owner_signer
    payload_a = _payload(corpus_id=CORPUS_ID)
    digest_a = GRC.payload_digest(payload_a)
    payload_b = _payload(corpus_id="gce2c-" + "00" * 16, corpus_digest="0" * 64)
    with pytest.raises(GRC.ReceiptAttestationError):
        GRC.attest_receipt(payload_b, attesting_authority=authority, sign_bytes=sk.sign, expected_payload_digest=digest_a)


def test_attest_receipt_over_the_authentic_matching_pairing_succeeds(owner_signer):
    """The positive control for the two tests above: payload A paired with digest A (its OWN digest) succeeds."""
    sk, keys, authority = owner_signer
    payload_a = _payload(corpus_id=CORPUS_ID)
    digest_a = GRC.payload_digest(payload_a)
    receipt = GRC.attest_receipt(payload_a, attesting_authority=authority, sign_bytes=sk.sign, expected_payload_digest=digest_a)
    assert GRC.verify_receipt_signature(receipt, keys) is None
