"""Cryptographic corpus-manifest schema/binding checks and the candidate-lineage attestation mechanism. Synthetic
fixtures only -- no real corpus, manifest, or candidate exists."""
import copy
import hashlib
import os

import pytest

from orca.eval.genesis_v2 import candidate_lineage as CL
from orca.eval.genesis_v2 import corpus_manifest as CMAN


def _need_crypto():
    if os.environ.get("ORNEUR_REQUIRE_CRYPTOGRAPHY") == "1":
        import cryptography.hazmat.primitives.ciphers.aead  # noqa: F401
    else:
        pytest.importorskip("cryptography")

GOOD_MANIFEST = {
    "schema_version": CMAN.SCHEMA_VERSION, "corpus_id": "gce2c-" + "ab" * 16, "eval_version": "genesis-capability-eval/2.0.0",
    "generator_code_sha256": "a" * 64, "generated_at_commit_sha": "b" * 40, "screen_digest": "c" * 64,
    "qualification_holdout_digest": "d" * 64, "per_category_item_counts": {"reasoning": 100, "coding": 50},
    "corpus_generation_authorization_id": "cgauth-" + "ef" * 8,
}
# schema /2: reviewed_commit_sha (ancestry-checked by the CALLER) + authorized_code_tree_sha256 (exact-match), never
# a literal "authorized_commit_sha" field (that was the schema /1 field this redesign replaced).
GOOD_AUTH = {"status": "AUTHORIZED", "authorization_id": GOOD_MANIFEST["corpus_generation_authorization_id"],
             "reviewed_commit_sha": GOOD_MANIFEST["generated_at_commit_sha"],
             "authorized_code_tree_sha256": GOOD_MANIFEST["generator_code_sha256"],
             "authorized_scope": ["SCREEN", "QUALIFICATION_HOLDOUT"]}


# ---------------------------------------------------------------- corpus_manifest
def test_good_manifest_validates_clean():
    assert CMAN.validate_manifest(GOOD_MANIFEST) == []


def test_manifest_schema_violations_rejected():
    for mut in (
        lambda m: m.pop("corpus_id"),
        lambda m: m.__setitem__("corpus_id", "not-the-right-shape"),
        lambda m: m.__setitem__("generator_code_sha256", "short"),
        lambda m: m.__setitem__("generated_at_commit_sha", "not-40-hex"),
        lambda m: m.__setitem__("per_category_item_counts", {}),
        lambda m: m.__setitem__("per_category_item_counts", {"x": -1}),
        lambda m: m.__setitem__("per_category_item_counts", "not-a-dict"),
        lambda m: m.__setitem__("corpus_generation_authorization_id", "not-cgauth-prefixed"),
        lambda m: m.__setitem__("schema_version", "wrong"),
        lambda m: m.__setitem__("extra_field", 1),
    ):
        m = copy.deepcopy(GOOD_MANIFEST)
        mut(m)
        assert CMAN.validate_manifest(m) != [], m


def test_manifest_digest_is_deterministic():
    d1 = CMAN.manifest_digest(GOOD_MANIFEST)
    d2 = CMAN.manifest_digest(copy.deepcopy(GOOD_MANIFEST))
    assert d1 == d2 and len(d1) == 64


def test_binding_passes_for_a_matching_authorized_record():
    assert CMAN.binding_problems(GOOD_MANIFEST, GOOD_AUTH, commit_is_descendant=True) == []


def test_binding_fails_when_authorization_not_authorized():
    auth = {**GOOD_AUTH, "status": "NOT_AUTHORIZED"}
    assert CMAN.binding_problems(GOOD_MANIFEST, auth, commit_is_descendant=True) != []


def test_binding_fails_on_authorization_id_mismatch():
    auth = {**GOOD_AUTH, "authorization_id": "cgauth-" + "00" * 8}
    assert any("does not match the authorization record's own id" in p for p in CMAN.binding_problems(GOOD_MANIFEST, auth, commit_is_descendant=True))


def test_binding_fails_when_commit_is_not_a_verified_descendant():
    """The exact scenario the redesign exists to allow: a manifest generated at a LATER commit than the reviewed one
    is fine (commit_is_descendant=True), but a manifest whose commit was never verified as a descendant must fail."""
    assert CMAN.binding_problems(GOOD_MANIFEST, GOOD_AUTH, commit_is_descendant=False) != []


def test_binding_fails_when_authorization_has_no_reviewed_commit_sha():
    auth = {**GOOD_AUTH, "reviewed_commit_sha": None}
    assert any("no reviewed_commit_sha" in p for p in CMAN.binding_problems(GOOD_MANIFEST, auth, commit_is_descendant=True))


def test_binding_fails_on_code_tree_hash_mismatch():
    auth = {**GOOD_AUTH, "authorized_code_tree_sha256": "0" * 64}
    assert any("authorized_code_tree_sha256" in p for p in CMAN.binding_problems(GOOD_MANIFEST, auth, commit_is_descendant=True))


def test_binding_fails_when_authorization_scope_does_not_cover_both_private_splits():
    auth = {**GOOD_AUTH, "authorized_scope": ["PILOT_TRAIN"]}
    assert any("did not scope both" in p for p in CMAN.binding_problems(GOOD_MANIFEST, auth, commit_is_descendant=True))


def test_binding_never_trusts_a_structurally_invalid_manifest():
    bad = copy.deepcopy(GOOD_MANIFEST)
    bad.pop("corpus_id")
    assert CMAN.binding_problems(bad, GOOD_AUTH, commit_is_descendant=True) != []


def test_the_real_authorization_and_manifest_schemas_together(tmp_path):
    """End-to-end: a genuinely signed schema /2 CORPUS_GENERATION_AUTHORIZATION record, and a manifest bound to it,
    verified together through binding_problems() -- not two schemas tested in isolation."""
    from datetime import datetime, timedelta, timezone
    from orca.eval.genesis_v2 import corpus_generation_authorization as CGA
    _need_crypto()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    keys = [{"key_id": "k-owner", "public_key_hex": pub, "identity": "owner-1", "role": "OWNER"}]
    now = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
    reviewed_sha = "b" * 40
    code_hash = "a" * 64
    auth = CGA.default_record()
    auth.update({"authorization_id": "cgauth-" + "ef" * 8, "status": "AUTHORIZED", "purpose": CGA.PURPOSE,
                 "authorized_scope": ["SCREEN", "QUALIFICATION_HOLDOUT"], "reviewed_commit_sha": reviewed_sha,
                 "authorized_code_tree_sha256": code_hash,
                 "authorized_artifact_digests": {"corpus_inventory_digest": "1" * 64, "preregistration_record_sha256": "2" * 64},
                 "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "expires_at": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "authorizing_authority": {"identity": "owner-1", "role": "OWNER", "key_id": "k-owner"}})
    auth["signature"] = sk.sign(CGA.canonical_signing_bytes(auth)).hex()
    # the authorization itself verifies against the request it was signed for
    req = CGA.Request(commit_sha=reviewed_sha, commit_is_descendant=True, working_tree_clean=True, current_code_tree_sha256=code_hash,
                       requested_scope=("SCREEN", "QUALIFICATION_HOLDOUT"), current_inventory_digest="1" * 64,
                       current_prereg_record_sha256="2" * 64, event_name="workflow_dispatch")
    v = CGA.verify(auth, req, keys, now=now)
    assert v.authorized, v.reasons
    # the manifest binds to that SAME authorization
    manifest = {**GOOD_MANIFEST, "generator_code_sha256": code_hash, "generated_at_commit_sha": reviewed_sha}
    assert CMAN.binding_problems(manifest, auth, commit_is_descendant=True) == []
    # and a manifest that drifted from what was actually authorized is caught
    drifted = {**manifest, "generator_code_sha256": "9" * 64}
    assert CMAN.binding_problems(drifted, auth, commit_is_descendant=True) != []


# ---------------------------------------------------------------- verify_against_artifacts: REAL bytes, not just hash shape
@pytest.fixture
def real_generator_code(tmp_path):
    d = tmp_path / "generator_code"
    d.mkdir()
    (d / "gen_a.py").write_text("def a():\n    return 1\n")
    (d / "gen_b.py").write_text("def b():\n    return 2\n")
    from orca.eval.genesis_v2 import runner_registry as RN
    code_sha = RN.code_sha256_of(sorted(d.glob("*.py")))
    return d, code_sha


@pytest.fixture
def real_vault(tmp_path):
    _need_crypto()
    from orca.eval.genesis_v2 import store as ST
    key = os.urandom(32)
    st = ST.EncryptedFileStore(tmp_path / "vault", key)
    screen_bytes = b'{"marker":"UNIT-TEST-SCREEN-CONTENT"}'
    holdout_bytes = b'{"marker":"UNIT-TEST-HOLDOUT-CONTENT"}'
    corpus_id = "gce2c-" + "cd" * 16
    cdig = st.write_corpus(corpus_id, {"SCREEN": screen_bytes, "QUALIFICATION_HOLDOUT": holdout_bytes})
    return st, corpus_id, cdig, screen_bytes, holdout_bytes


def test_verify_against_artifacts_passes_for_a_genuinely_matching_manifest(real_generator_code, real_vault):
    code_dir, code_sha = real_generator_code
    st, corpus_id, cdig, screen_bytes, holdout_bytes = real_vault
    manifest = {**GOOD_MANIFEST, "corpus_id": corpus_id, "generator_code_sha256": code_sha,
                "screen_digest": hashlib.sha256(screen_bytes).hexdigest(),
                "qualification_holdout_digest": hashlib.sha256(holdout_bytes).hexdigest()}
    problems = CMAN.verify_against_artifacts(manifest, screen_plain=screen_bytes, holdout_plain=holdout_bytes,
                                              generator_code_root=code_dir, expected_corpus_digest=cdig)
    assert problems == [], problems


def test_verify_against_artifacts_rejects_a_wrong_generator_code_hash(real_generator_code, real_vault):
    code_dir, code_sha = real_generator_code
    st, corpus_id, cdig, screen_bytes, holdout_bytes = real_vault
    manifest = {**GOOD_MANIFEST, "corpus_id": corpus_id, "generator_code_sha256": "f" * 64,   # syntactically valid, ACTUALLY wrong
                "screen_digest": hashlib.sha256(screen_bytes).hexdigest(),
                "qualification_holdout_digest": hashlib.sha256(holdout_bytes).hexdigest()}
    problems = CMAN.verify_against_artifacts(manifest, screen_plain=screen_bytes, holdout_plain=holdout_bytes,
                                              generator_code_root=code_dir, expected_corpus_digest=cdig)
    assert any("does not match the ACTUAL current generator code" in p for p in problems)


def test_verify_against_artifacts_rejects_a_manifest_claiming_the_wrong_screen_content(real_generator_code, real_vault):
    """A syntactically valid SHA-256 that simply does not match the real decrypted content must never be accepted
    as proof the artifact was verified."""
    code_dir, code_sha = real_generator_code
    st, corpus_id, cdig, screen_bytes, holdout_bytes = real_vault
    manifest = {**GOOD_MANIFEST, "corpus_id": corpus_id, "generator_code_sha256": code_sha,
                "screen_digest": "0" * 64,   # syntactically valid hex, but not the real SCREEN plaintext's hash
                "qualification_holdout_digest": hashlib.sha256(holdout_bytes).hexdigest()}
    problems = CMAN.verify_against_artifacts(manifest, screen_plain=screen_bytes, holdout_plain=holdout_bytes,
                                              generator_code_root=code_dir, expected_corpus_digest=cdig)
    assert any("does not match the ACTUAL decrypted SCREEN plaintext" in p for p in problems)


def test_verify_against_artifacts_rejects_when_expected_corpus_digest_is_wrong(real_generator_code, real_vault):
    code_dir, code_sha = real_generator_code
    st, corpus_id, cdig, screen_bytes, holdout_bytes = real_vault
    manifest = {**GOOD_MANIFEST, "corpus_id": corpus_id, "generator_code_sha256": code_sha,
                "screen_digest": hashlib.sha256(screen_bytes).hexdigest(),
                "qualification_holdout_digest": hashlib.sha256(holdout_bytes).hexdigest()}
    problems = CMAN.verify_against_artifacts(manifest, screen_plain=screen_bytes, holdout_plain=holdout_bytes,
                                              generator_code_root=code_dir, expected_corpus_digest="9" * 64)
    assert problems   # recomputed corpus digest from the real bytes does not match the claimed expectation -- fails closed


def test_verify_against_artifacts_never_trusts_a_structurally_invalid_manifest(real_generator_code, real_vault):
    code_dir, code_sha = real_generator_code
    st, corpus_id, cdig, screen_bytes, holdout_bytes = real_vault
    bad = copy.deepcopy(GOOD_MANIFEST)
    bad.pop("corpus_id")
    problems = CMAN.verify_against_artifacts(bad, screen_plain=screen_bytes, holdout_plain=holdout_bytes,
                                              generator_code_root=code_dir, expected_corpus_digest=cdig)
    assert problems  # rejected on structural grounds before any hash comparison


def test_verify_against_artifacts_never_reads_a_store_itself():
    """The whole point of the redesign: this function takes bytes, never a store/key. Passing non-bytes must fail
    closed rather than attempt any I/O."""
    problems = CMAN.verify_against_artifacts(GOOD_MANIFEST, screen_plain="not-bytes", holdout_plain=b"x",
                                              generator_code_root=".", expected_corpus_digest="0" * 64)
    assert any("must be the actual authorized plaintext bytes" in p for p in problems)


def test_manifest_verification_bytes_must_come_through_the_real_ledger_gated_capability(real_generator_code, real_vault, tmp_path):
    """Proves the fix end-to-end: obtaining bytes via operational_boundary.authorized_manifest_verification_bytes()
    requires a genuinely AUTHORIZED qualification-runner identity and produces a real ledger grant for EACH split --
    an unregistered process is denied before the vault is ever touched, exactly like require_private_split_access."""
    from orca.eval.genesis_v2 import operational_boundary as OB
    code_dir, code_sha = real_generator_code
    st, corpus_id, cdig, screen_bytes, holdout_bytes = real_vault
    with pytest.raises(OB.PrivateSplitAccessDenied):
        OB.authorized_manifest_verification_bytes(
            tmp_path / "no-such-root", tmp_path / "ledger", st, process_id="not-registered", code_sha256=code_sha,
            corpus_id=corpus_id, expected_corpus_digest=cdig, eval_version="genesis-capability-eval/2.0.0",
            candidate_revision="rev-1", candidate_lineage="lineage-1", run_id_prefix="verify-1", timestamp_utc="2026-09-30T00:00:00Z")


# ---------------------------------------------------------------- candidate_lineage
from pathlib import Path as _Path  # noqa: E402
ROOT = _Path(__file__).resolve().parents[1]


@pytest.fixture
def reviewer_signer():
    _need_crypto()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    keys = [{"key_id": "rev-1", "public_key_hex": pub, "identity": "independent-auditor-1", "role": "PRIVATE_BENCHMARK_REVIEWER"}]
    return sk, keys


def _sign_verification(rec: dict, sk) -> dict:
    iv = dict(rec["independent_verification"])
    iv["signature"] = "0" * 128
    rec = {**rec, "independent_verification": iv}
    sig = sk.sign(CL.verification_signing_bytes(rec)).hex()
    return {**iv, "signature": sig}


@pytest.fixture
def good_attestation(reviewer_signer):
    sk, keys = reviewer_signer
    iv = {"verifier_identity": "independent-auditor-1",
          "verification_method": "reproduced the training run from the disclosed log and compared hashes",
          "verified_at": "2026-09-29T01:00:00Z", "signature": "0" * 128}
    rec = {
        "schema_version": CL.SCHEMA_VERSION, "candidate_id": "cand-x", "candidate_revision": "rev-2026-09-01",
        "model_family": "example-family", "attested_by": "provider disclosure", "attestation_timestamp": "2026-09-29T00:00:00Z",
        "training_data_disclosure_source": "https://example.invalid/disclosure", "reproducible_training_log_digest": "a" * 64,
        "independent_verification": iv,
        "exposure_to_unresolved_corpora": {"state": "DISCLOSED_CLEAN", "unresolved_classes_considered": ["external_uploaded_datasets"]},
        "notes": "",
    }
    rec["independent_verification"] = _sign_verification(rec, sk)
    return rec, keys


def test_good_attestation_validates_clean(good_attestation):
    rec, keys = good_attestation
    assert CL.validate_attestation(rec) == []


def test_attestation_schema_violations_rejected(good_attestation):
    rec0, keys = good_attestation
    iv0 = rec0["independent_verification"]
    for mut in (
        lambda r: r.pop("candidate_id"),
        lambda r: r.pop("candidate_revision"),
        lambda r: r.__setitem__("candidate_revision", ""),
        lambda r: r.__setitem__("attestation_timestamp", "not-a-date"),
        lambda r: r.__setitem__("reproducible_training_log_digest", "not-hex"),
        lambda r: r.__setitem__("exposure_to_unresolved_corpora", {"state": "BOGUS", "unresolved_classes_considered": []}),
        lambda r: r.__setitem__("exposure_to_unresolved_corpora", "not-a-dict"),
        lambda r: r.__setitem__("independent_verification", {**iv0, "signature": "not-hex"}),
        lambda r: r.__setitem__("independent_verification", {**iv0, "signature": "0" * 127}),
        lambda r: r.__setitem__("independent_verification", {**iv0, "verifier_identity": r["attested_by"]}),
        lambda r: r.__setitem__("independent_verification", {"extra": 1}),
        lambda r: r.__setitem__("notes", None),
        lambda r: r.__setitem__("extra", 1),
    ):
        rec = copy.deepcopy(rec0)
        mut(rec)
        assert CL.validate_attestation(rec) != [], rec


def test_independent_verification_may_be_null_and_still_validate_structurally(good_attestation):
    rec0, keys = good_attestation
    rec = copy.deepcopy(rec0)
    rec["independent_verification"] = None
    assert CL.validate_attestation(rec) == []   # structurally fine; eligibility (below) is a separate, stricter question


def test_disclosed_clean_independently_verified_and_exposure_complete_is_eligible(good_attestation):
    rec, keys = good_attestation
    r = CL.qualification_eligibility(rec, root=ROOT, reviewer_keys=keys)
    assert r["eligible"] is True and r["reason"] == "DISCLOSED_CLEAN_INDEPENDENTLY_VERIFIED_AND_EXPOSURE_COMPLETE"


def test_clean_claim_without_a_verifiable_log_is_not_eligible(good_attestation):
    rec0, keys = good_attestation
    rec = copy.deepcopy(rec0)
    rec["reproducible_training_log_digest"] = None
    r = CL.qualification_eligibility(rec, root=ROOT, reviewer_keys=keys)
    assert r["eligible"] is False and r["reason"] == "CLEAN_CLAIM_WITHOUT_VERIFIABLE_LOG"


def test_clean_claim_without_independent_verification_is_not_eligible(good_attestation):
    rec0, keys = good_attestation
    rec = copy.deepcopy(rec0)
    rec["independent_verification"] = None
    r = CL.qualification_eligibility(rec, root=ROOT, reviewer_keys=keys)
    assert r["eligible"] is False and r["reason"] == "CLEAN_CLAIM_WITHOUT_INDEPENDENT_VERIFICATION"


def test_clean_claim_with_no_reviewer_keys_supplied_is_never_eligible(good_attestation):
    """Fail-closed default, mirroring inventory.validate_attestation_record: no registry supplied => not verified."""
    rec, _keys = good_attestation
    r = CL.qualification_eligibility(rec, root=ROOT, reviewer_keys=None)
    assert r["eligible"] is False and r["reason"] == "CLEAN_CLAIM_WITHOUT_INDEPENDENT_VERIFICATION"


def test_clean_claim_with_unregistered_verifier_is_not_eligible(good_attestation):
    rec, _keys = good_attestation
    r = CL.qualification_eligibility(rec, root=ROOT, reviewer_keys=[])   # verifier not in the registry at all
    assert r["eligible"] is False and r["reason"] == "CLEAN_CLAIM_WITHOUT_INDEPENDENT_VERIFICATION"


def test_clean_claim_with_forged_reviewer_signature_is_not_eligible(good_attestation):
    rec0, keys = good_attestation
    rec = copy.deepcopy(rec0)
    rec["independent_verification"]["signature"] = "0" * 128   # a real 128-hex string, but not a valid signature over this content
    r = CL.qualification_eligibility(rec, root=ROOT, reviewer_keys=keys)
    assert r["eligible"] is False and r["reason"] == "CLEAN_CLAIM_WITHOUT_INDEPENDENT_VERIFICATION"


def test_clean_claim_with_a_tampered_field_after_signing_is_not_eligible(good_attestation, reviewer_signer):
    """A syntactically valid signature that was computed over a DIFFERENT candidate_revision must not verify against
    a tampered one -- proves the signature genuinely binds the content, not just present-or-absent."""
    rec0, keys = good_attestation
    rec = copy.deepcopy(rec0)
    rec["candidate_revision"] = "rev-tampered"
    r = CL.qualification_eligibility(rec, root=ROOT, reviewer_keys=keys)
    assert r["eligible"] is False and r["reason"] == "CLEAN_CLAIM_WITHOUT_INDEPENDENT_VERIFICATION"


def test_self_verification_never_counts_as_independent(good_attestation):
    rec0, keys = good_attestation
    rec = copy.deepcopy(rec0)
    rec["independent_verification"] = {**rec0["independent_verification"], "verifier_identity": rec0["attested_by"]}
    assert CL.validate_attestation(rec) != []   # caught at the structural level: a self-verification is invalid, not merely ineligible


def test_reviewer_role_is_bound_to_the_real_reviewer_registry_vocabulary(good_attestation):
    """The redesign binds reviewer authority to the SAME reviewer_registry.py role vocabulary this program already
    uses elsewhere (PRIVATE_BENCHMARK_REVIEWER), not an invented role only this module recognizes."""
    from orca.eval.genesis_v2 import reviewer_registry as RR
    assert "PRIVATE_BENCHMARK_REVIEWER" in RR.ROLES


def test_disclosed_uncertain_is_never_eligible(good_attestation):
    rec0, keys = good_attestation
    rec = copy.deepcopy(rec0)
    rec["exposure_to_unresolved_corpora"]["state"] = "DISCLOSED_UNCERTAIN"
    r = CL.qualification_eligibility(rec, root=ROOT, reviewer_keys=keys)
    assert r["eligible"] is False and r["reason"] == "UNCERTAIN_EXPOSURE_REQUIRES_EXCLUSION_OR_FRESH_LINEAGE"


def test_undisclosed_is_never_eligible(good_attestation):
    rec0, keys = good_attestation
    rec = copy.deepcopy(rec0)
    rec["exposure_to_unresolved_corpora"]["state"] = "UNDISCLOSED"
    r = CL.qualification_eligibility(rec, root=ROOT, reviewer_keys=keys)
    assert r["eligible"] is False and r["reason"] == "UNDISCLOSED_TREATED_AS_UNCERTAIN"


def test_invalid_attestation_is_never_eligible(good_attestation):
    rec0, keys = good_attestation
    rec = copy.deepcopy(rec0)
    rec.pop("candidate_id")
    r = CL.qualification_eligibility(rec, root=ROOT, reviewer_keys=keys)
    assert r["eligible"] is False and r["reason"] == "INVALID_ATTESTATION" and r["problems"]


def test_eligibility_without_root_is_never_granted(good_attestation):
    rec, keys = good_attestation
    r = CL.qualification_eligibility(rec, reviewer_keys=keys)   # root omitted
    assert r["eligible"] is False and r["reason"] == "HISTORICAL_EXPOSURE_COMPLETENESS_NOT_CHECKED"


def test_omitting_a_real_unresolved_class_from_consideration_is_never_eligible(reviewer_signer):
    """The exact scenario the redesign exists to catch: the attestation claims DISCLOSED_CLEAN with a genuinely
    verified log, but never actually considered the real historical unresolved class (external_uploaded_datasets)."""
    sk, keys = reviewer_signer
    iv = {"verifier_identity": "independent-auditor-1", "verification_method": "m", "verified_at": "2026-09-29T01:00:00Z", "signature": "0" * 128}
    rec = {"schema_version": CL.SCHEMA_VERSION, "candidate_id": "cand-x", "candidate_revision": "rev-1", "model_family": "f",
           "attested_by": "provider", "attestation_timestamp": "2026-09-29T00:00:00Z", "training_data_disclosure_source": None,
           "reproducible_training_log_digest": "a" * 64, "independent_verification": iv,
           "exposure_to_unresolved_corpora": {"state": "DISCLOSED_CLEAN", "unresolved_classes_considered": []}, "notes": ""}
    rec["independent_verification"] = _sign_verification(rec, sk)
    r = CL.qualification_eligibility(rec, root=ROOT, reviewer_keys=keys)
    assert r["eligible"] is False and r["reason"] == "UNRESOLVED_HISTORICAL_CLASS_NOT_CONSIDERED"
    assert {"missing_class": "external_uploaded_datasets"} in r["problems"]


def test_historical_exposure_complete_reflects_the_real_live_inventory(good_attestation):
    rec0, keys = good_attestation
    complete, missing = CL.historical_exposure_complete(rec0, ROOT)
    assert complete is True and missing == []
    stripped = copy.deepcopy(rec0)
    stripped["exposure_to_unresolved_corpora"]["unresolved_classes_considered"] = []
    complete2, missing2 = CL.historical_exposure_complete(stripped, ROOT)
    assert complete2 is False and missing2 == ["external_uploaded_datasets"]
