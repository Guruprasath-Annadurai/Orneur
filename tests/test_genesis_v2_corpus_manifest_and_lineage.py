"""Cryptographic corpus-manifest schema/binding checks and the candidate-lineage attestation mechanism. Synthetic
fixtures only -- no real corpus, manifest, or candidate exists."""
import copy

from orca.eval.genesis_v2 import candidate_lineage as CL
from orca.eval.genesis_v2 import corpus_manifest as CMAN

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


# ---------------------------------------------------------------- candidate_lineage
GOOD_ATTESTATION = {
    "schema_version": CL.SCHEMA_VERSION, "candidate_id": "cand-x", "model_family": "example-family",
    "attested_by": "provider disclosure", "attestation_timestamp": "2026-09-29T00:00:00Z",
    "training_data_disclosure_source": "https://example.invalid/disclosure", "reproducible_training_log_digest": "a" * 64,
    "exposure_to_unresolved_corpora": {"state": "DISCLOSED_CLEAN", "unresolved_classes_considered": ["external_uploaded_datasets"]},
    "notes": "",
}


def test_good_attestation_validates_clean():
    assert CL.validate_attestation(GOOD_ATTESTATION) == []


def test_attestation_schema_violations_rejected():
    for mut in (
        lambda r: r.pop("candidate_id"),
        lambda r: r.__setitem__("attestation_timestamp", "not-a-date"),
        lambda r: r.__setitem__("reproducible_training_log_digest", "not-hex"),
        lambda r: r.__setitem__("exposure_to_unresolved_corpora", {"state": "BOGUS", "unresolved_classes_considered": []}),
        lambda r: r.__setitem__("exposure_to_unresolved_corpora", "not-a-dict"),
        lambda r: r.__setitem__("notes", None),
        lambda r: r.__setitem__("extra", 1),
    ):
        rec = copy.deepcopy(GOOD_ATTESTATION)
        mut(rec)
        assert CL.validate_attestation(rec) != [], rec


def test_disclosed_clean_with_verifiable_log_is_eligible():
    r = CL.qualification_eligibility(GOOD_ATTESTATION)
    assert r["eligible"] is True and r["reason"] == "DISCLOSED_CLEAN_WITH_VERIFIABLE_LOG"


def test_clean_claim_without_a_verifiable_log_is_not_eligible():
    rec = copy.deepcopy(GOOD_ATTESTATION)
    rec["reproducible_training_log_digest"] = None
    r = CL.qualification_eligibility(rec)
    assert r["eligible"] is False and r["reason"] == "CLEAN_CLAIM_WITHOUT_VERIFIABLE_LOG"


def test_disclosed_uncertain_is_never_eligible():
    rec = copy.deepcopy(GOOD_ATTESTATION)
    rec["exposure_to_unresolved_corpora"]["state"] = "DISCLOSED_UNCERTAIN"
    r = CL.qualification_eligibility(rec)
    assert r["eligible"] is False and r["reason"] == "UNCERTAIN_EXPOSURE_REQUIRES_EXCLUSION_OR_FRESH_LINEAGE"


def test_undisclosed_is_never_eligible():
    rec = copy.deepcopy(GOOD_ATTESTATION)
    rec["exposure_to_unresolved_corpora"]["state"] = "UNDISCLOSED"
    r = CL.qualification_eligibility(rec)
    assert r["eligible"] is False and r["reason"] == "UNDISCLOSED_TREATED_AS_UNCERTAIN"


def test_invalid_attestation_is_never_eligible():
    rec = copy.deepcopy(GOOD_ATTESTATION)
    rec.pop("candidate_id")
    r = CL.qualification_eligibility(rec)
    assert r["eligible"] is False and r["reason"] == "INVALID_ATTESTATION" and r["problems"]
