"""Authority and reviewer registries: schema, expiry/revocation, separation of duties. Registration itself never authorizes anything — every
positive case here still needs a separate, request-exact authorization/review check (proven in test_genesis_v2_authorization.py / _review.py)."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import authority_registry as AR
from orca.eval.genesis_v2 import authorization as A
from orca.eval.genesis_v2 import identity_registry as ID
from orca.eval.genesis_v2 import reviewer_registry as RR

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)


def _need_crypto():
    import os
    if os.environ.get("ORNEUR_REQUIRE_CRYPTOGRAPHY") == "1":
        import cryptography.hazmat.primitives.asymmetric.ed25519  # noqa: F401
    else:
        pytest.importorskip("cryptography")


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def pubkey():
    _need_crypto()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def authority_rec(**over):
    r = {"id": "auth-owner-1", "role": "OWNER", "public_key_hex": pubkey(), "activation_timestamp": ts(NOW - timedelta(days=1)), "expiry": None,
         "revoked": False, "permitted_authorization_classes": ["QUALIFICATION"], "permitted_eval_stages": ["STAGE_1"], "gpu_permission": False,
         "spend_permission": False, "provider_inference_permission": False}
    r.update(over)
    return r


def reviewer_rec(**over):
    r = {"id": "rev-1", "role": "PRIVATE_BENCHMARK_REVIEWER", "public_key_hex": pubkey(), "activation_timestamp": ts(NOW - timedelta(days=1)),
         "expiry": None, "revoked": False, "allowed_review_domains": ["CONTAMINATION_REVIEW"], "allow_dual_role": False}
    r.update(over)
    return r


# ---------------------------------------------------------------- committed registries
def test_committed_registries_are_valid_and_empty():
    for mod in (AR, RR):
        doc = json.loads((ROOT / mod.REGISTRY_PATH).read_text())
        assert mod.validate(doc) == [] and doc["records"] == [] and doc["schema_version"] == mod.SCHEMA_VERSION


def test_committed_registries_yield_no_active_keys_so_authorization_and_review_stay_blocked():
    assert A.load_keys(ROOT) == []
    from orca.eval.genesis_v2 import review as R
    assert R.load_keys(ROOT) == []


# ---------------------------------------------------------------- schema validation
@pytest.mark.parametrize("mut", [
    lambda r: r.pop("role"), lambda r: r.__setitem__("role", "CLAUDE"), lambda r: r.__setitem__("public_key_hex", "short"),
    lambda r: r.__setitem__("public_key_hex", "zz" * 32), lambda r: r.__setitem__("activation_timestamp", "yesterday"),
    lambda r: r.__setitem__("expiry", "not-a-date"), lambda r: r.__setitem__("revoked", "no"), lambda r: r.__setitem__("extra_field", 1),
    lambda r: r.__setitem__("permitted_authorization_classes", []), lambda r: r.__setitem__("permitted_authorization_classes", ["BOGUS"]),
    lambda r: r.__setitem__("permitted_eval_stages", ["STAGE_9"]), lambda r: r.__setitem__("gpu_permission", "yes")])
def test_authority_record_mutations_are_rejected(mut):
    r = authority_rec()
    mut(r)
    assert AR.validate_record(r)
    doc = {"schema_version": AR.SCHEMA_VERSION, "records": [r]}
    assert AR.validate(doc)


@pytest.mark.parametrize("mut", [
    lambda r: r.pop("allowed_review_domains"), lambda r: r.__setitem__("allowed_review_domains", ["BOGUS"]),
    lambda r: r.__setitem__("role", "CLAUDE"), lambda r: r.__setitem__("allow_dual_role", "true"), lambda r: r.__setitem__("public_key_hex", "x")])
def test_reviewer_record_mutations_are_rejected(mut):
    r = reviewer_rec()
    mut(r)
    assert RR.validate_record(r)


def test_duplicate_ids_and_wrong_schema_version_rejected():
    r1, r2 = authority_rec(), authority_rec(id="auth-owner-1")
    doc = {"schema_version": AR.SCHEMA_VERSION, "records": [r1, r2]}
    assert any("duplicate" in p for p in AR.validate(doc))
    bad = {"schema_version": "wrong", "records": []}
    assert AR.validate(bad) == ["registry schema mismatch"]
    assert AR.validate("not a dict") == ["registry schema mismatch"]
    assert AR.validate({"schema_version": AR.SCHEMA_VERSION, "records": "not-a-list"}) == ["registry schema mismatch"]


# ---------------------------------------------------------------- expiry / revocation
def test_unregistered_malformed_wrong_role_revoked_and_expired_keys_are_all_denied():
    good = authority_rec()
    revoked = authority_rec(id="auth-2", revoked=True)
    expired = authority_rec(id="auth-3", activation_timestamp=ts(NOW - timedelta(days=10)), expiry=ts(NOW - timedelta(days=1)))
    not_yet = authority_rec(id="auth-4", activation_timestamp=ts(NOW + timedelta(days=1)))
    doc = {"schema_version": AR.SCHEMA_VERSION, "records": [good, revoked, expired, not_yet]}
    assert AR.validate(doc) == []
    active = {k["key_id"] for k in AR.active_authority_keys(doc)}
    assert active == {"auth-owner-1"}                                    # only the good, active record survives
    assert ID.is_active(good, NOW) and not ID.is_active(revoked, NOW) and not ID.is_active(expired, NOW) and not ID.is_active(not_yet, NOW)
    assert ID.is_active(good, NOW + timedelta(seconds=1))


def test_valid_registered_authority_signature_verifies_but_registration_alone_never_authorizes(tmp_path):
    _need_crypto()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    rec = authority_rec(id="auth-x", public_key_hex=pub)
    doc = {"schema_version": AR.SCHEMA_VERSION, "records": [rec]}
    assert AR.validate(doc) == []
    keys = AR.active_authority_keys(doc)
    r = A.default_record()
    r.update({"authorization_id": "auth-" + "1" * 16, "status": "AUTHORIZED", "commit_sha": "a" * 40, "eval_version": "genesis-capability-eval/2.0.0",
              "candidate": {"model_id": "m", "revision": "r"}, "permitted_stage": "STAGE_1", "permitted_runner_class": "SELF_HOSTED_CPU",
              "permitted_purpose": "SCREENING", "max_runs": 1, "max_spend_usd": 0, "issued_at": ts(NOW - timedelta(hours=1)),
              "expires_at": ts(NOW + timedelta(days=1)), "authorizing_authority": {"identity": "auth-x", "role": "OWNER", "key_id": "auth-x"},
              "gpu_allowed": False, "network_provider_inference_allowed": False})
    r["signature"] = sk.sign(A.canonical_signing_bytes(r)).hex()
    req = A.Request(commit_sha="a" * 40, eval_version="genesis-capability-eval/2.0.0", candidate_model_id="m", candidate_revision="r", stage="STAGE_1",
                    runner_class="SELF_HOSTED_CPU", purpose="SCREENING", event_name="workflow_dispatch")
    assert A.verify(r, req, keys, NOW).authorized                                    # a genuinely registered+signed authorization verifies
    empty_doc = AR.empty_registry()                                                   # but the committed (empty) registry still trusts nothing
    assert not A.verify(r, req, AR.active_authority_keys(empty_doc), NOW).authorized


def test_authority_for_request_scopes_by_class_stage_and_permission_flags():
    doc = {"schema_version": AR.SCHEMA_VERSION, "records": [
        authority_rec(id="a1", permitted_authorization_classes=["SCREENING"], permitted_eval_stages=["STAGE_1"]),
        authority_rec(id="a2", permitted_authorization_classes=["QUALIFICATION"], permitted_eval_stages=["STAGE_2"], gpu_permission=True)]}
    assert {r["id"] for r in AR.authority_for_request(doc, authorization_class="SCREENING", stage="STAGE_1", gpu=False, spend=False, provider_inference=False)} == {"a1"}
    assert {r["id"] for r in AR.authority_for_request(doc, authorization_class="QUALIFICATION", stage="STAGE_2", gpu=True, spend=False, provider_inference=False)} == {"a2"}
    assert AR.authority_for_request(doc, authorization_class="QUALIFICATION", stage="STAGE_1", gpu=False, spend=False, provider_inference=False) == []


# ---------------------------------------------------------------- separation of duties
def test_separation_of_duties_flags_dual_role_without_exception():
    auth_doc = {"schema_version": AR.SCHEMA_VERSION, "records": [authority_rec(id="person-1")]}
    rev_doc = {"schema_version": RR.SCHEMA_VERSION, "records": [reviewer_rec(id="person-1")]}
    assert RR.check_separation_of_duties(auth_doc, rev_doc) == ["person-1"]
    rev_doc2 = {"schema_version": RR.SCHEMA_VERSION, "records": [reviewer_rec(id="person-1", allow_dual_role=True)]}
    assert RR.check_separation_of_duties(auth_doc, rev_doc2) == []
    rev_doc3 = {"schema_version": RR.SCHEMA_VERSION, "records": [reviewer_rec(id="person-2")]}
    assert RR.check_separation_of_duties(auth_doc, rev_doc3) == []


def test_unreadable_or_missing_registry_file_yields_no_keys(tmp_path):
    doc, problems = AR.load(tmp_path / "nope.json")
    assert doc is None and problems
    p = tmp_path / "reg.json"
    p.write_text("not json")
    assert AR.load(p) == (None, problems if False else AR.load(p)[1])
    p.write_text(json.dumps({"schema_version": AR.SCHEMA_VERSION, "records": [{"bad": "record"}]}))
    doc, problems = AR.load(p)
    assert doc is None and problems
