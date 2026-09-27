"""Genesis Capability Eval V2 — Final Pre-Corpus Closure: exact-SHA sandbox evidence, qualification-runner binding, owner-authority
key-generation procedure (no private key ever present), reviewer-path documentation, inventory terminology, unavailable-corpus
acceptance policy, preregistration binding_status, owner_preflight's new hard requirements, and the pre-corpus closure manifest."""
import json
import re
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import authority_registry as AR
from orca.eval.genesis_v2 import closure_manifest as CM
from orca.eval.genesis_v2 import inventory as INV
from orca.eval.genesis_v2 import owner_preflight as OP
from orca.eval.genesis_v2 import prereg as PR
from orca.eval.genesis_v2 import runner_qualification as RQ
from orca.eval.genesis_v2 import sandbox_qualification as SQ

ROOT = Path(__file__).resolve().parents[1]
PH = ROOT / "docs/orneur/phase-21"
AUTH = ROOT / "docs/orneur/authorization"


# ---------------------------------------------------------------- WS1: exact-SHA sandbox evidence
def test_sandbox_record_has_no_pending_placeholder_and_real_tested_sha():
    rec = json.loads((PH / "GENESIS_V2_SANDBOX_QUALIFICATION_CANDIDATE_RECORD.json").read_text())
    assert rec["tested_implementation_sha"] != "PENDING_COMMIT_WILL_BE_SET_AT_PUSH_TIME"
    assert re.fullmatch(r"[0-9a-f]{40}", rec["tested_implementation_sha"])
    assert re.fullmatch(r"[0-9a-f]{40}", rec["tested_implementation_parent_sha"])
    assert rec["evidence_record_commit"] is None   # never self-referential; reported separately in the phase report
    assert rec["sandbox_ready"] is False
    assert rec["sandbox_qualification_status"] == "QUALIFICATION_CANDIDATE_PENDING_FREEZE"
    assert len(rec["containment_test_code_hash"]) == 64


def test_sandbox_build_record_rejects_a_future_commit_by_construction():
    # build_record takes an explicit already-known SHA; nothing in this module computes "the commit about to be made".
    import inspect
    src = inspect.getsource(SQ.build_record)
    assert "git rev-parse" not in src and "HEAD" not in src


# ---------------------------------------------------------------- WS2: qualification runner qualification record
def test_runner_qualification_record_matches_sandbox_test_runner_class():
    rq = json.loads((PH / "GENESIS_V2_QUALIFICATION_RUNNER_QUALIFICATION_RECORD.json").read_text())
    sb = json.loads((PH / "GENESIS_V2_SANDBOX_QUALIFICATION_CANDIDATE_RECORD.json").read_text())
    assert rq["same_environment_proof"]["sandbox_test_runner_class"] == sb["test_runner_class"]
    assert rq["same_environment_proof"]["qualification_runner_class"] == rq["machine_facts"]["runner_class"]
    assert rq["same_environment_proof"]["match"] is True
    assert rq["state"] == "REGISTERED_NOT_AUTHORIZED"


def test_runner_registry_no_longer_says_tbd():
    reg = json.loads((AUTH / "QUALIFICATION_RUNNER_REGISTRY.json").read_text())
    r = reg["records"][0]
    assert "TBD" not in r["os_runtime"]
    assert r["semantic_engine_digest"] and len(r["semantic_engine_digest"]) == 64


def test_runner_qualification_flags_mismatch_when_runner_classes_differ():
    rec = RQ.build_record(sandbox_image_digest="sha256:aa", semantic_engine_digest="b" * 64, storage_backend_verification_digest="c" * 64,
                           ledger_database_identity_digest="d" * 64, code_sha256="e" * 64,
                           sandbox_test_runner_class="SOME_OTHER_HOSTED_RUNNER", sandbox_test_summary="n/a")
    assert rec["same_environment_proof"]["match"] is False


# ---------------------------------------------------------------- WS3: owner authority key procedure (no key generated)
def test_owner_authority_key_procedure_documented_and_no_private_key_anywhere():
    t = (AUTH / "OWNER_AUTHORITY_KEY_GENERATION_PROCEDURE.md").read_text()
    for s in ("openssl genpkey", "ed25519", "chmod 600", "public_key_hex", "orneur-owner-authority-", "Rotation", "Revocation",
              "human owner holds", "never paste it into", "never commit"):
        assert s.lower() in t.lower(), s
    assert "BEGIN PRIVATE KEY" not in t and "-----BEGIN" not in t
    assert not re.search(r"\b[0-9a-f]{64}\b", t)   # no concrete key material embedded


def test_authority_registry_remains_empty_this_phase():
    doc, problems = AR.load(AUTH / "AUTHORITY_REGISTRY.json")
    assert problems == [] and doc["records"] == []


# ---------------------------------------------------------------- WS4: reviewer path
def test_reviewer_path_status_documents_semantic_substitution_honestly():
    t = (AUTH / "REVIEWER_PATH_STATUS.md").read_text()
    for s in ("NOT operational", "CONFIGURED_LOCAL_ONLY", "false negative", "fabricate"):
        assert s.lower() in t.lower(), s


# ---------------------------------------------------------------- WS6: inventory terminology + unavailable-corpus policy
def test_inventory_uses_owner_reviewed_not_attested_terminology_pre_signature():
    inv = json.loads((PH / "GENESIS_TRAINING_AND_ADAPTATION_CORPUS_INVENTORY.json").read_text())
    assert inv["completeness_attestation"]["status"] == "NOT_ATTESTED"
    declared = {c["declaration"] for c in inv["class_coverage"].values()}
    assert "NONE_EXIST_ATTESTED" not in declared
    assert "NONE_DECLARED_OWNER_REVIEWED" in declared
    assert INV.validate(inv) == []   # still schema-valid


def test_none_exist_attested_rejected_before_signature():
    inv = json.loads((PH / "GENESIS_TRAINING_AND_ADAPTATION_CORPUS_INVENTORY.json").read_text())
    cls = next(k for k, v in inv["class_coverage"].items() if v["declaration"] == "NONE_DECLARED_OWNER_REVIEWED")
    inv["class_coverage"][cls]["declaration"] = "NONE_EXIST_ATTESTED"
    problems = INV.validate(inv)
    assert any("NONE_EXIST_ATTESTED" in p and "signed" in p for p in problems)


def test_unavailable_corpus_acceptance_policy_is_locked_and_covers_the_real_gap():
    pol = json.loads((PH / "GENESIS_V2_UNAVAILABLE_CORPUS_ACCEPTANCE_POLICY.json").read_text())
    assert pol["frozen"] is True
    assert "external_uploaded_datasets" in pol["applies_to_unresolved_classes"]
    assert any("must not be used" in r.lower() for r in pol["fail_closed_rules"])
    assert any("re-analysis" in r or "rerun" in r.lower() for r in pol["fail_closed_rules"])


# ---------------------------------------------------------------- WS8: preregistration binding_status
def test_draft_binding_status_covers_every_binding_and_matches_operational_reality():
    draft = json.loads((PH / "GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_DRAFT.json").read_text())
    assert set(draft["binding_status"]) == set(PR.BINDINGS)
    assert draft["binding_status"]["private_corpus_aggregate_commitment"] == "DEFERRED"
    assert draft["binding_status"]["semantic_review_mechanism_version"] == "OPERATIONALLY_CONFIGURED"
    assert draft["binding_status"]["sandbox_policy_version"] == "OPERATIONALLY_CONFIGURED"
    assert draft["binding_status"]["runner_identity"] == "OPERATIONALLY_CONFIGURED"
    assert PR.validate_draft(draft) == []
    assert json.loads((PH / "GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_SCHEMA.json").read_text()) == PR.schema()


def test_binding_status_rejects_deferred_misuse():
    draft = json.loads((PH / "GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_DRAFT.json").read_text())
    draft["binding_status"]["eval_version"] = "DEFERRED"   # DEFERRED is only legal for the one truly-deferred binding
    assert PR.validate_binding_status(draft) != []


def test_binding_status_rejects_qualified_claim_on_null_binding():
    draft = json.loads((PH / "GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_DRAFT.json").read_text())
    draft["bindings"]["code_hashes"] = None
    draft["binding_status"]["code_hashes"] = "QUALIFIED"
    assert PR.validate_binding_status(draft) != []


# ---------------------------------------------------------------- WS9: owner_preflight
def test_owner_preflight_blocked_only_by_genuinely_owner_gated_items():
    r = OP.run(ROOT)
    assert r["result"] == "NOT_READY"
    assert set(r["outstanding_for_ready"]) == {"authority_key_registered_and_valid", "corpus_inventory_attested_pass"}
    # every OTHER hard requirement this phase closed must be genuinely true, not silently dropped from the check set
    for k in ("sandbox_exact_sha_evidence_valid", "qualification_runner_qualified", "sandbox_runner_class_matches_qualification_runner",
              "semantic_or_reviewer_path_operational", "semantic_engine_configured"):
        assert r["checks"][k] is True, k


def test_owner_preflight_does_not_require_corpus_secret_or_aes_key_or_aggregate_commitment():
    r = OP.run(ROOT)
    for forbidden in ("corpus_secret", "aes_key", "private_corpus_aggregate_commitment", "aggregate_commitment"):
        assert not any(forbidden in k for k in r["checks"])


# ---------------------------------------------------------------- WS10: closure manifest
def test_closure_manifest_is_public_safe_hash_only_and_complete():
    rec = json.loads((PH / "GENESIS_V2_PRE_CORPUS_CLOSURE_MANIFEST.json").read_text())
    assert rec["missing_artifacts"] == []
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in rec["artifact_hashes"].values())
    assert rec["authorizations"] == {"private_corpus_exists": False, "screen_exists": False, "qualification_holdout_exists": False,
                                      "corpus_secret_exists": False, "operational_benchmark_aes_key_exists": False, "model_inference_authorized": False,
                                      "gpu_authorized": False, "provider_inference_authorized": False, "training_authorized": False,
                                      "spending_authorized": False, "foundation_selected": False, "v2_frozen": False, "corpus_generated": False}
    import hashlib as _h, json as _j
    body = {k: v for k, v in rec.items() if k != "manifest_sha256"}
    assert rec["manifest_sha256"] == _h.sha256(_j.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_closure_manifest_never_embeds_a_private_path_or_key():
    text = (PH / "GENESIS_V2_PRE_CORPUS_CLOSURE_MANIFEST.json").read_text()
    assert "/Users/" not in text and "/home/" not in text
    assert "-----BEGIN" not in text
