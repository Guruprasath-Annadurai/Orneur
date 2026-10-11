"""Offline schema/integrity tests for the foundation-model evidence reassessment (Workstream D).

No network, no model loading.  The REAL evidence file must verify cleanly, and synthetic corruptions must each be rejected, proving that
every rule in scripts/foundation/verify_evidence.py actually fires.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "orneur" / "status" / "foundation" / "foundation_evidence.json"
_spec = importlib.util.spec_from_file_location("verify_evidence", ROOT / "scripts" / "foundation" / "verify_evidence.py")
V = importlib.util.module_from_spec(_spec)
sys.modules["verify_evidence"] = V
_spec.loader.exec_module(V)


@pytest.fixture(scope="module")
def doc():
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def _fails(d, needle):
    errs = V.verify(d, ROOT)
    assert any(needle in e for e in errs), (needle, errs[:5])


def test_real_evidence_verifies(doc):
    assert V.verify(doc, ROOT) == []


def test_cli_exit_code_zero():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "foundation" / "verify_evidence.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout


def test_every_candidate_claim_has_class_source_timestamp_revision(doc):
    n = 0
    for c in doc["candidates"] + doc["identity_only_candidates"]:
        for cl in c["claims"]:
            n += 1
            assert cl["claim_class"] in V.CLASSES
            assert cl["source_url"] and cl["retrieved_at"] and cl["revision"]
    assert n > 100


def test_four_deep_candidates_present_and_pinned(doc):
    ids = {c["id"]: c["revision"] for c in doc["candidates"]}
    assert ids == {"qwen3-8b": "b968826d9c46dd6066d109eabc6255188de91218",
                   "mistral-nemo-instruct-2407": "04d8a90549d23fc6bd7f642064003592df51e9b3",
                   "phi-4": "2db69c1c3e91a05d2c64a3185acfbaf36f744e25",
                   "unsloth-qwen2.5-3b-instruct": "7548fff1f997f57b2e9e8ab1ec7be96949b00ed0"}


@pytest.mark.parametrize("key", ["source_url", "retrieved_at", "revision", "claim_class"])
def test_missing_provenance_field_rejected(doc, key):
    d = copy.deepcopy(doc)
    del d["candidates"][0]["claims"][0][key]
    errs = V.verify(d, ROOT)
    assert errs, "removing a provenance field must be rejected"


def test_bad_claim_class_rejected(doc):
    d = copy.deepcopy(doc)
    d["candidates"][0]["claims"][0]["claim_class"] = "VENDOR_SAYS_SO"
    _fails(d, "claim_class")


def test_bad_timestamp_rejected(doc):
    d = copy.deepcopy(doc)
    d["candidates"][1]["claims"][2]["retrieved_at"] = "yesterday"
    _fails(d, "ISO-8601")


def test_bad_revision_rejected(doc):
    d = copy.deepcopy(doc)
    d["candidates"][1]["claims"][2]["revision"] = "main"
    _fails(d, "revision")


def test_independently_reproduced_requires_repo_evidence(doc):
    d = copy.deepcopy(doc)
    c = next(cl for cl in d["candidates"][0]["claims"] if cl["claim_class"] == "INDEPENDENTLY_REPRODUCED")
    c["source_url"] = "https://example.com/not-the-repo"
    _fails(d, "INDEPENDENTLY_REPRODUCED")


def test_repo_source_must_exist(doc):
    d = copy.deepcopy(doc)
    c = next(cl for cl in d["candidates"][0]["claims"] if cl["claim_class"] == "INDEPENDENTLY_REPRODUCED")
    c["source_url"] = "repo:docs/orneur/phase-21/DOES_NOT_EXIST.json"
    _fails(d, "does not exist")


def test_estimates_must_be_hypotheses(doc):
    d = copy.deepcopy(doc)
    c = next(cl for cl in d["candidates"][0]["claims"] if cl["topic"] == "memory_estimate")
    c["claim_class"] = "DOCUMENTED_FACT"
    _fails(d, "UNTESTED_HYPOTHESIS")


def test_granted_without_text_hash_rejected(doc):
    d = copy.deepcopy(doc)
    nemo = next(c for c in d["candidates"] if c["id"] == "mistral-nemo-instruct-2407")
    nemo["license"]["license_status"] = "GRANTED"
    _fails(d, "GRANTED without a retrieved licence text")


def test_identity_only_candidate_cannot_be_granted(doc):
    d = copy.deepcopy(doc)
    d["identity_only_candidates"][0]["license"]["license_status"] = "GRANTED"
    _fails(d, "GRANTED")


def test_nemo_is_not_granted_in_real_evidence(doc):
    nemo = next(c for c in doc["candidates"] if c["id"] == "mistral-nemo-instruct-2407")
    assert nemo["license"]["license_status"] == "REQUIRES_COUNSEL" and nemo["license"]["text"] is None
    q25 = next(c for c in doc["candidates"] if c["id"] == "unsloth-qwen2.5-3b-instruct")
    assert q25["license"]["license_status"] == "RESTRICTED_NONCOMMERCIAL"


def test_granted_licences_have_verifiable_hashes(doc):
    granted = [c for c in doc["candidates"] if c["license"]["license_status"] == "GRANTED"]
    assert {c["id"] for c in granted} == {"qwen3-8b", "phi-4"}
    for c in granted:
        t = c["license"]["text"]
        b = (ROOT / t["file"]).read_bytes()
        import hashlib
        assert hashlib.sha256(b).hexdigest() == t["sha256"]
        assert V.blob_sha1(b) == t["git_blob_sha1"]


def test_licence_hash_tamper_rejected(doc):
    d = copy.deepcopy(doc)
    q3 = next(c for c in d["candidates"] if c["id"] == "qwen3-8b")
    q3["license"]["text"]["sha256"] = "0" * 64
    _fails(d, "sha256 mismatch")


def test_licence_blob_id_tamper_rejected(doc):
    d = copy.deepcopy(doc)
    p4 = next(c for c in d["candidates"] if c["id"] == "phi-4")
    p4["license"]["text"]["git_blob_sha1"] = "f" * 40
    _fails(d, "git blob sha1 mismatch")


def test_recorded_text_hash_tamper_rejected(doc):
    d = copy.deepcopy(doc)
    d["texts"][0]["sha256"] = "1" * 64
    _fails(d, "sha256 mismatch")


def test_template_hash_in_claim_must_match_registry(doc):
    d = copy.deepcopy(doc)
    q3 = next(c for c in d["candidates"] if c["id"] == "qwen3-8b")
    cl = next(x for x in q3["claims"] if x["topic"] == "chat_template")
    cl["value"]["template_sha256"] = "2" * 64
    _fails(d, "template_sha256")


def test_all_recorded_texts_rehash(doc):
    import hashlib
    assert len(doc["texts"]) >= 15
    for t in doc["texts"]:
        b = (ROOT / t["path"]).read_bytes()
        assert hashlib.sha256(b).hexdigest() == t["sha256"], t["key"]
        if t.get("git_blob_sha1"):
            assert V.blob_sha1(b) == t["git_blob_sha1"], t["key"]


def test_nemo_template_hash_equals_repo_recorded(doc):
    rec = json.loads((ROOT / "docs/orneur/phase-21/evidence/GENESIS_MISTRAL_NEMO_CHAT_TEMPLATE_ROOT_CAUSE_ANALYSIS_V2_2026-09-26.json").read_text())
    want = rec["A_pinned_tokenizer_config"]["chat_template_sha256"]
    t = next(x for x in doc["texts"] if x["key"] == "mistral-nemo-instruct-2407/chat_template.jinja.txt")
    assert t["sha256"] == want


def test_weights_cross_check_against_repo_manifests(doc):
    d = copy.deepcopy(doc)
    # corrupt one stored LFS hash in a COPY of the tree manifest is not possible via the doc, so assert the real check ran clean
    assert V.verify(d, ROOT) == []
    assert set(doc["weights_integrity_cross_check"]["manifests"]) == {"qwen3-8b", "mistral-nemo-instruct-2407", "phi-4"}


def test_ranking_is_provisional_and_not_a_selection(doc):
    rk = doc["provisional_ranking"]
    assert rk["status"] == "PROVISIONAL_NON_BINDING" and rk["is_selection"] is False and rk["binding"] is False and rk["selected_foundation"] is None
    assert "NOT A SELECTION" in rk["statement"]


@pytest.mark.parametrize("mutation,needle", [
    (lambda r: r.__setitem__("is_selection", True), "is_selection=false"),
    (lambda r: r.__setitem__("binding", True), "is_selection=false"),
    (lambda r: r.__setitem__("selected_foundation", "qwen3-8b"), "is_selection=false"),
    (lambda r: r["candidate_scores"][0]["scores"].__setitem__("F", 9), "non-scoreable"),
    (lambda r: r["candidate_scores"][0]["scores"].__setitem__("H", 3), "non-scoreable"),
    (lambda r: r["criteria"][3].__setitem__("evaluation_state", "SCORED_FROM_DOCUMENTED_EVIDENCE"), "must be NOT_EVALUATED"),
    (lambda r: r["criteria"][4].__setitem__("weight", 99), "sum to 100"),
    (lambda r: r["candidate_scores"][0].__setitem__("documented_subset_points", 99.0), "arithmetic"),
])
def test_ranking_guards(doc, mutation, needle):
    d = copy.deepcopy(doc)
    mutation(d["provisional_ranking"])
    _fails(d, needle)


def test_capability_criteria_not_evaluated_in_real_evidence(doc):
    states = {c["id"]: c["evaluation_state"] for c in doc["provisional_ranking"]["criteria"]}
    for k in "FGHI":
        assert states[k] == "NOT_EVALUATED"
    assert sum(c["weight"] for c in doc["provisional_ranking"]["criteria"] if c["kind"] == "weighted") == 100
    scored = {cid for r in doc["provisional_ranking"]["candidate_scores"] for cid in r["scores"]}
    assert scored <= {"D", "E", "L", "O", "P"}


def test_gate_k_pass_requires_granted_status(doc):
    d = copy.deepcopy(doc)
    d["provisional_ranking"]["gates"]["mistral-nemo-instruct-2407"]["K"]["result"] = "PASS"
    _fails(d, "gate K PASS")


def test_constraints_flags_must_be_false(doc):
    d = copy.deepcopy(doc)
    d["constraints_observed"]["gpu"] = True
    _fails(d, "constraints_observed.gpu")


def test_not_verified_entries_are_class_not_verified(doc):
    assert doc["not_verified"], "NOT_VERIFIED list must not be empty"
    assert all(r["claim_class"] == "NOT_VERIFIED" for r in doc["not_verified"])
    d = copy.deepcopy(doc)
    d["not_verified"][0]["claim_class"] = "DOCUMENTED_FACT"
    _fails(d, "must be NOT_VERIFIED")


def test_no_network_modules_in_verifier():
    src = (ROOT / "scripts" / "foundation" / "verify_evidence.py").read_text()
    for banned in ("import requests", "import urllib", "import socket", "import http", "urlopen", "subprocess"):
        assert banned not in src, banned
