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
GOOD_AUTH = {"status": "AUTHORIZED", "authorization_id": GOOD_MANIFEST["corpus_generation_authorization_id"],
             "authorized_commit_sha": GOOD_MANIFEST["generated_at_commit_sha"], "authorized_scope": ["SCREEN", "QUALIFICATION_HOLDOUT"]}


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
    assert CMAN.binding_problems(GOOD_MANIFEST, GOOD_AUTH) == []


def test_binding_fails_when_authorization_not_authorized():
    auth = {**GOOD_AUTH, "status": "NOT_AUTHORIZED"}
    assert CMAN.binding_problems(GOOD_MANIFEST, auth) != []


def test_binding_fails_on_authorization_id_mismatch():
    auth = {**GOOD_AUTH, "authorization_id": "cgauth-" + "00" * 8}
    assert any("does not match the authorization record's own id" in p for p in CMAN.binding_problems(GOOD_MANIFEST, auth))


def test_binding_fails_on_commit_sha_mismatch():
    auth = {**GOOD_AUTH, "authorized_commit_sha": "0" * 40}
    assert any("authorized_commit_sha" in p for p in CMAN.binding_problems(GOOD_MANIFEST, auth))


def test_binding_fails_when_authorization_scope_does_not_cover_both_private_splits():
    auth = {**GOOD_AUTH, "authorized_scope": ["PILOT_TRAIN"]}
    assert any("did not scope both" in p for p in CMAN.binding_problems(GOOD_MANIFEST, auth))


def test_binding_never_trusts_a_structurally_invalid_manifest():
    bad = copy.deepcopy(GOOD_MANIFEST)
    bad.pop("corpus_id")
    assert CMAN.binding_problems(bad, GOOD_AUTH) != []


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
    problems = CMAN.verify_against_artifacts(manifest, store=st, generator_code_root=code_dir, expected_corpus_digest=cdig)
    assert problems == [], problems


def test_verify_against_artifacts_rejects_a_wrong_generator_code_hash(real_generator_code, real_vault):
    code_dir, code_sha = real_generator_code
    st, corpus_id, cdig, screen_bytes, holdout_bytes = real_vault
    manifest = {**GOOD_MANIFEST, "corpus_id": corpus_id, "generator_code_sha256": "f" * 64,   # syntactically valid, ACTUALLY wrong
                "screen_digest": hashlib.sha256(screen_bytes).hexdigest(),
                "qualification_holdout_digest": hashlib.sha256(holdout_bytes).hexdigest()}
    problems = CMAN.verify_against_artifacts(manifest, store=st, generator_code_root=code_dir, expected_corpus_digest=cdig)
    assert any("does not match the ACTUAL current generator code" in p for p in problems)


def test_verify_against_artifacts_rejects_a_manifest_claiming_the_wrong_screen_content(real_generator_code, real_vault):
    """A syntactically valid SHA-256 that simply does not match the real decrypted content must never be accepted
    as proof the artifact was verified."""
    code_dir, code_sha = real_generator_code
    st, corpus_id, cdig, screen_bytes, holdout_bytes = real_vault
    manifest = {**GOOD_MANIFEST, "corpus_id": corpus_id, "generator_code_sha256": code_sha,
                "screen_digest": "0" * 64,   # syntactically valid hex, but not the real SCREEN plaintext's hash
                "qualification_holdout_digest": hashlib.sha256(holdout_bytes).hexdigest()}
    problems = CMAN.verify_against_artifacts(manifest, store=st, generator_code_root=code_dir, expected_corpus_digest=cdig)
    assert any("does not match the ACTUAL decrypted SCREEN plaintext" in p for p in problems)


def test_verify_against_artifacts_rejects_when_expected_corpus_digest_is_wrong(real_generator_code, real_vault):
    code_dir, code_sha = real_generator_code
    st, corpus_id, cdig, screen_bytes, holdout_bytes = real_vault
    manifest = {**GOOD_MANIFEST, "corpus_id": corpus_id, "generator_code_sha256": code_sha,
                "screen_digest": hashlib.sha256(screen_bytes).hexdigest(),
                "qualification_holdout_digest": hashlib.sha256(holdout_bytes).hexdigest()}
    problems = CMAN.verify_against_artifacts(manifest, store=st, generator_code_root=code_dir, expected_corpus_digest="9" * 64)
    assert problems   # the store itself refuses to even read with a wrong expected_corpus_digest -- fails closed


def test_verify_against_artifacts_never_trusts_a_structurally_invalid_manifest(real_generator_code, real_vault):
    code_dir, code_sha = real_generator_code
    st, corpus_id, cdig, screen_bytes, holdout_bytes = real_vault
    bad = copy.deepcopy(GOOD_MANIFEST)
    bad.pop("corpus_id")
    problems = CMAN.verify_against_artifacts(bad, store=st, generator_code_root=code_dir, expected_corpus_digest=cdig)
    assert problems  # never even attempts to read the vault for a structurally invalid manifest


# ---------------------------------------------------------------- candidate_lineage
from pathlib import Path as _Path  # noqa: E402
ROOT = _Path(__file__).resolve().parents[1]

GOOD_VERIFICATION = {"verifier_identity": "independent-auditor-1", "verifier_role": "INDEPENDENT_OF_CANDIDATE_PROVIDER",
                      "verification_method": "reproduced the training run from the disclosed log and compared hashes",
                      "verified_at": "2026-09-29T01:00:00Z", "confirms_log_digest": True}
GOOD_ATTESTATION = {
    "schema_version": CL.SCHEMA_VERSION, "candidate_id": "cand-x", "candidate_revision": "rev-2026-09-01",
    "model_family": "example-family", "attested_by": "provider disclosure", "attestation_timestamp": "2026-09-29T00:00:00Z",
    "training_data_disclosure_source": "https://example.invalid/disclosure", "reproducible_training_log_digest": "a" * 64,
    "independent_verification": GOOD_VERIFICATION,
    "exposure_to_unresolved_corpora": {"state": "DISCLOSED_CLEAN", "unresolved_classes_considered": ["external_uploaded_datasets"]},
    "notes": "",
}


def test_good_attestation_validates_clean():
    assert CL.validate_attestation(GOOD_ATTESTATION) == []


def test_attestation_schema_violations_rejected():
    for mut in (
        lambda r: r.pop("candidate_id"),
        lambda r: r.pop("candidate_revision"),
        lambda r: r.__setitem__("candidate_revision", ""),
        lambda r: r.__setitem__("attestation_timestamp", "not-a-date"),
        lambda r: r.__setitem__("reproducible_training_log_digest", "not-hex"),
        lambda r: r.__setitem__("exposure_to_unresolved_corpora", {"state": "BOGUS", "unresolved_classes_considered": []}),
        lambda r: r.__setitem__("exposure_to_unresolved_corpora", "not-a-dict"),
        lambda r: r.__setitem__("independent_verification", {**GOOD_VERIFICATION, "verifier_role": "SELF"}),
        lambda r: r.__setitem__("independent_verification", {**GOOD_VERIFICATION, "verifier_identity": r["attested_by"]}),
        lambda r: r.__setitem__("independent_verification", {**GOOD_VERIFICATION, "confirms_log_digest": "yes"}),
        lambda r: r.__setitem__("independent_verification", {"extra": 1}),
        lambda r: r.__setitem__("notes", None),
        lambda r: r.__setitem__("extra", 1),
    ):
        rec = copy.deepcopy(GOOD_ATTESTATION)
        mut(rec)
        assert CL.validate_attestation(rec) != [], rec


def test_independent_verification_may_be_null_and_still_validate_structurally():
    rec = copy.deepcopy(GOOD_ATTESTATION)
    rec["independent_verification"] = None
    assert CL.validate_attestation(rec) == []   # structurally fine; eligibility (below) is a separate, stricter question


def test_disclosed_clean_independently_verified_and_exposure_complete_is_eligible():
    r = CL.qualification_eligibility(GOOD_ATTESTATION, root=ROOT)
    assert r["eligible"] is True and r["reason"] == "DISCLOSED_CLEAN_INDEPENDENTLY_VERIFIED_AND_EXPOSURE_COMPLETE"


def test_clean_claim_without_a_verifiable_log_is_not_eligible():
    rec = copy.deepcopy(GOOD_ATTESTATION)
    rec["reproducible_training_log_digest"] = None
    r = CL.qualification_eligibility(rec, root=ROOT)
    assert r["eligible"] is False and r["reason"] == "CLEAN_CLAIM_WITHOUT_VERIFIABLE_LOG"


def test_clean_claim_without_independent_verification_is_not_eligible():
    rec = copy.deepcopy(GOOD_ATTESTATION)
    rec["independent_verification"] = None
    r = CL.qualification_eligibility(rec, root=ROOT)
    assert r["eligible"] is False and r["reason"] == "CLEAN_CLAIM_WITHOUT_INDEPENDENT_VERIFICATION"


def test_clean_claim_with_verification_that_does_not_confirm_the_digest_is_not_eligible():
    rec = copy.deepcopy(GOOD_ATTESTATION)
    rec["independent_verification"] = {**GOOD_VERIFICATION, "confirms_log_digest": False}
    r = CL.qualification_eligibility(rec, root=ROOT)
    assert r["eligible"] is False and r["reason"] == "CLEAN_CLAIM_WITHOUT_INDEPENDENT_VERIFICATION"


def test_self_verification_never_counts_as_independent():
    rec = copy.deepcopy(GOOD_ATTESTATION)
    rec["independent_verification"] = {**GOOD_VERIFICATION, "verifier_identity": rec["attested_by"]}
    assert CL.validate_attestation(rec) != []   # caught at the structural level: a self-verification is invalid, not merely ineligible


def test_disclosed_uncertain_is_never_eligible():
    rec = copy.deepcopy(GOOD_ATTESTATION)
    rec["exposure_to_unresolved_corpora"]["state"] = "DISCLOSED_UNCERTAIN"
    r = CL.qualification_eligibility(rec, root=ROOT)
    assert r["eligible"] is False and r["reason"] == "UNCERTAIN_EXPOSURE_REQUIRES_EXCLUSION_OR_FRESH_LINEAGE"


def test_undisclosed_is_never_eligible():
    rec = copy.deepcopy(GOOD_ATTESTATION)
    rec["exposure_to_unresolved_corpora"]["state"] = "UNDISCLOSED"
    r = CL.qualification_eligibility(rec, root=ROOT)
    assert r["eligible"] is False and r["reason"] == "UNDISCLOSED_TREATED_AS_UNCERTAIN"


def test_invalid_attestation_is_never_eligible():
    rec = copy.deepcopy(GOOD_ATTESTATION)
    rec.pop("candidate_id")
    r = CL.qualification_eligibility(rec, root=ROOT)
    assert r["eligible"] is False and r["reason"] == "INVALID_ATTESTATION" and r["problems"]


def test_eligibility_without_root_is_never_granted():
    r = CL.qualification_eligibility(GOOD_ATTESTATION)   # root omitted
    assert r["eligible"] is False and r["reason"] == "HISTORICAL_EXPOSURE_COMPLETENESS_NOT_CHECKED"


def test_omitting_a_real_unresolved_class_from_consideration_is_never_eligible():
    """The exact scenario the redesign exists to catch: the attestation claims DISCLOSED_CLEAN with a verified log,
    but never actually considered the real historical unresolved class (external_uploaded_datasets)."""
    rec = copy.deepcopy(GOOD_ATTESTATION)
    rec["exposure_to_unresolved_corpora"]["unresolved_classes_considered"] = []
    r = CL.qualification_eligibility(rec, root=ROOT)
    assert r["eligible"] is False and r["reason"] == "UNRESOLVED_HISTORICAL_CLASS_NOT_CONSIDERED"
    assert {"missing_class": "external_uploaded_datasets"} in r["problems"]


def test_historical_exposure_complete_reflects_the_real_live_inventory():
    complete, missing = CL.historical_exposure_complete(GOOD_ATTESTATION, ROOT)
    assert complete is True and missing == []
    stripped = copy.deepcopy(GOOD_ATTESTATION)
    stripped["exposure_to_unresolved_corpora"]["unresolved_classes_considered"] = []
    complete2, missing2 = CL.historical_exposure_complete(stripped, ROOT)
    assert complete2 is False and missing2 == ["external_uploaded_datasets"]
