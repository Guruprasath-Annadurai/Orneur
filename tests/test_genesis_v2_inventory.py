"""Genesis training/adaptation corpus inventory: fail-closed completeness contract, including the signed owner-attestation schema."""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import contamination as C
from orca.eval.genesis_v2 import inventory as INV

ROOT = Path(__file__).resolve().parents[1]


def sha(b):
    return hashlib.sha256(b).hexdigest()


def _need_crypto():
    if os.environ.get("ORNEUR_REQUIRE_CRYPTOGRAPHY") == "1":
        import cryptography.hazmat.primitives.asymmetric.ed25519  # noqa: F401
    else:
        pytest.importorskip("cryptography")


def corpus(cid, path_rel, data: bytes, cls="public_sft_datasets", **over):
    c = {"corpus_id": cid, "version": "v1", "corpus_class": cls, "purpose": "sft", "provenance": "test", "classification": "PUBLIC",
         "storage": {"kind": "REPO_PATH", "location": path_rel}, "manifest_id_or_sha256": sha(data), "record_count": data.count(b"\n"),
         "used_in_training": False, "used_in_adaptation": False, "visible_during_screen": False, "visible_during_qualification_holdout": False,
         "permitted_lifecycle": "x", "contamination_check_status": "PASS", "owner": "owner", "status": "PRESENT"}
    c.update(over)
    return c


def _sign_attestation(inv: dict, sk, *, completeness_status="COMPLETE", unresolved=None):
    record = {"schema_version": INV.ATTESTATION_SCHEMA_VERSION, "inventory_version": inv["inventory_version"],
              "corpus_inventory_digest": INV.inventory_digest(inv), "owner_identity": "owner-1", "review_timestamp": "2026-09-27T09:00:00Z",
              "scope_reviewed": ["test scope"], "unresolved_classes": unresolved or [], "completeness_status": completeness_status, "signature": None}
    record["signature"] = sk.sign(INV.attestation_signing_bytes(record)).hex()
    return record


@pytest.fixture
def signer():
    _need_crypto()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    keys = [{"key_id": "owner-1", "public_key_hex": pub, "identity": "owner-1", "role": "OWNER"}]
    return sk, keys


@pytest.fixture
def good(tmp_path, signer):
    sk, keys = signer
    data = b'{"text": "an unrelated training record about orchids"}\n'
    (tmp_path / "d.jsonl").write_bytes(data)
    inv = INV.empty_inventory()
    inv["corpora"] = [corpus("c1", "d.jsonl", data)]
    for cls in INV.CORPUS_CLASSES:
        inv["class_coverage"][cls] = {"declaration": "NONE_DECLARED_OWNER_REVIEWED", "corpus_ids": []}
    inv["class_coverage"]["public_sft_datasets"] = {"declaration": "LISTED", "corpus_ids": ["c1"]}
    inv["completeness_attestation"] = {"status": "ATTESTED", "record": _sign_attestation(inv, sk)}
    return inv, tmp_path, keys, sk


def test_a_complete_signed_attested_resolvable_inventory_passes(good):
    inv, root, keys, sk = good
    assert INV.validate(inv, authority_keys=keys) == []
    r = INV.evaluate(inv, root, authority_keys=keys)
    assert r.status == C.PASS, (r.status, r.findings)


# ---------------------------------------------------------------- pre-corpus attestation vs. full contamination qualification
def test_pre_corpus_attestation_can_pass_while_full_qualification_stays_incomplete(tmp_path, signer):
    """The exact stage-boundary scenario the independent audit flagged: a real, validly-signed (test key) owner attestation that
    honestly declares one class unresolved (covered by a frozen acceptance policy) must be able to PASS the pre-corpus attestation
    gate, while FULL contamination qualification — which needs the private V2 corpus to compare against and every source resolvable
    — correctly remains far from PASS (here: DATASET_UNAVAILABLE, because of the declared-unavailable corpus)."""
    sk, keys = signer
    data = b'{"text": "an unrelated training record about orchids"}\n'
    (tmp_path / "d.jsonl").write_bytes(data)
    inv = INV.empty_inventory()
    present = corpus("c1", "d.jsonl", data)
    unavailable = corpus("c2", "does-not-exist.jsonl", data, cls="external_uploaded_datasets", status="UNAVAILABLE", manifest_id_or_sha256=None)
    inv["corpora"] = [present, unavailable]
    for cls in INV.CORPUS_CLASSES:
        inv["class_coverage"][cls] = {"declaration": "NONE_DECLARED_OWNER_REVIEWED", "corpus_ids": []}
    inv["class_coverage"]["public_sft_datasets"] = {"declaration": "LISTED", "corpus_ids": ["c1"]}
    inv["class_coverage"]["external_uploaded_datasets"] = {"declaration": "LISTED", "corpus_ids": ["c2"]}
    inv["completeness_attestation"] = {"status": "ATTESTED", "record": _sign_attestation(
        inv, sk, completeness_status="COMPLETE_WITH_DECLARED_UNAVAILABLE", unresolved=["external_uploaded_datasets"])}
    policy = {"frozen": True, "applies_to_unresolved_classes": ["external_uploaded_datasets"]}

    pre = INV.evaluate_pre_corpus_attestation(inv, authority_keys=keys, acceptance_policy=policy)
    assert pre.status == C.PASS, (pre.status, pre.findings, pre.note)

    full = INV.evaluate(inv, tmp_path, authority_keys=keys)
    assert full.status != C.PASS
    assert full.status == C.DATASET_UNAVAILABLE


def test_pre_corpus_attestation_fails_when_unresolved_class_is_not_covered_by_policy(tmp_path, signer):
    sk, keys = signer
    inv = INV.empty_inventory()
    for cls in INV.CORPUS_CLASSES:
        inv["class_coverage"][cls] = {"declaration": "NONE_DECLARED_OWNER_REVIEWED", "corpus_ids": []}
    inv["completeness_attestation"] = {"status": "ATTESTED", "record": _sign_attestation(
        inv, sk, completeness_status="COMPLETE_WITH_DECLARED_UNAVAILABLE", unresolved=["external_uploaded_datasets"])}
    r = INV.evaluate_pre_corpus_attestation(inv, authority_keys=keys, acceptance_policy={"frozen": True, "applies_to_unresolved_classes": []})
    assert r.status == C.FAIL
    r2 = INV.evaluate_pre_corpus_attestation(inv, authority_keys=keys, acceptance_policy=None)
    assert r2.status == C.INCOMPLETE
    r3 = INV.evaluate_pre_corpus_attestation(inv, authority_keys=keys, acceptance_policy={"frozen": False, "applies_to_unresolved_classes": ["external_uploaded_datasets"]})
    assert r3.status == C.INCOMPLETE


def test_pre_corpus_attestation_never_passes_unsigned_or_unattested(tmp_path, signer):
    sk, keys = signer
    inv = INV.empty_inventory()
    for cls in INV.CORPUS_CLASSES:
        inv["class_coverage"][cls] = {"declaration": "NONE_DECLARED_OWNER_REVIEWED", "corpus_ids": []}
    assert INV.evaluate_pre_corpus_attestation(inv, authority_keys=keys).status == C.INCOMPLETE     # status NOT_ATTESTED
    signed = _sign_attestation(inv, sk, completeness_status="COMPLETE")
    inv["completeness_attestation"] = {"status": "ATTESTED", "record": signed}
    assert INV.evaluate_pre_corpus_attestation(inv, authority_keys=None).status == C.FAIL           # no registry supplied => SIGNATURE_NOT_VERIFIED
    inv2 = copy.deepcopy(inv)
    inv2["completeness_attestation"]["record"]["signature"] = "00" * 64
    assert INV.evaluate_pre_corpus_attestation(inv2, authority_keys=keys).status == C.FAIL           # forged signature


def test_empty_inventory_never_means_pass(tmp_path):
    r = INV.evaluate(INV.empty_inventory(), tmp_path)
    assert r.status == C.INCOMPLETE and "empty" in r.note
    assert C.overall([r])["pass"] is False


def test_unsigned_or_unverifiable_attestation_never_passes(good):
    inv, root, keys, sk = good
    assert INV.evaluate(inv, root).status in (C.FAIL, C.INCOMPLETE)                        # no authority_keys supplied at all: never PASS
    inv2 = copy.deepcopy(inv)
    inv2["completeness_attestation"] = {"status": "NOT_ATTESTED", "record": None}
    assert INV.evaluate(inv2, root, authority_keys=keys).status == C.INCOMPLETE
    inv3 = copy.deepcopy(inv)
    inv3["completeness_attestation"]["record"]["signature"] = "00" * 64                     # forged signature
    assert INV.evaluate(inv3, root, authority_keys=keys).status == C.FAIL
    inv4 = copy.deepcopy(inv)
    inv4["completeness_attestation"]["record"]["owner_identity"] = "not-registered"
    assert INV.evaluate(inv4, root, authority_keys=keys).status == C.FAIL
    inv5 = copy.deepcopy(inv)
    inv5["completeness_attestation"]["record"] = _sign_attestation(inv5, sk, completeness_status="INCOMPLETE")
    assert INV.evaluate(inv5, root, authority_keys=keys).status == C.INCOMPLETE            # validly signed, but the owner said it's incomplete


def test_completeness_with_declared_unavailable_can_still_pass_other_checks(good):
    inv, root, keys, sk = good
    inv["completeness_attestation"]["record"] = _sign_attestation(inv, sk, completeness_status="COMPLETE_WITH_DECLARED_UNAVAILABLE",
                                                                  unresolved=["external_uploaded_datasets"])
    assert INV.validate(inv, authority_keys=keys) == []
    assert INV.evaluate(inv, root, authority_keys=keys).status == C.PASS


def test_unattested_class_coverage_blocks(good):
    inv, root, keys, _sk = good
    inv["class_coverage"]["coding_datasets"] = {"declaration": "NONE_KNOWN_UNATTESTED", "corpus_ids": []}
    inv["completeness_attestation"]["record"] = _sign_attestation(inv, _sk)
    r = INV.evaluate(inv, root, authority_keys=keys)
    assert r.status == C.INCOMPLETE and {"class": "coding_datasets", "declaration": "NONE_KNOWN_UNATTESTED"} in r.findings


@pytest.mark.parametrize("status", ["UNAVAILABLE", "DECLARED_NOT_PRESENT"])
def test_unresolved_unavailable_sources_block(good, status):
    inv, root, keys, _sk = good
    inv["corpora"].append(corpus("c2", "nope.jsonl", b"x\n", cls="distillation_data", status=status))
    inv["class_coverage"]["distillation_data"] = {"declaration": "LISTED", "corpus_ids": ["c2"]}
    inv["completeness_attestation"]["record"] = _sign_attestation(inv, _sk)
    r = INV.evaluate(inv, root, authority_keys=keys)
    assert r.status == C.DATASET_UNAVAILABLE and r.findings[0]["why"] == status


def test_retired_corpora_do_not_block(good):
    inv, root, keys, _sk = good
    inv["corpora"].append(corpus("c2", "nope.jsonl", b"x\n", cls="distillation_data", status="RETIRED"))
    inv["class_coverage"]["distillation_data"] = {"declaration": "LISTED", "corpus_ids": ["c2"]}
    inv["completeness_attestation"]["record"] = _sign_attestation(inv, _sk)
    assert INV.evaluate(inv, root, authority_keys=keys).status == C.PASS


def test_present_but_not_resolvable_in_this_environment_is_unavailable(good):
    inv, root, keys, _sk = good
    inv["corpora"].append(corpus("c2", "training/raw/x.jsonl", b"x\n", cls="distillation_data", storage={"kind": "ORCA_HOME_PATH", "location": "training/raw/x.jsonl"}))
    inv["class_coverage"]["distillation_data"] = {"declaration": "LISTED", "corpus_ids": ["c2"]}
    inv["completeness_attestation"]["record"] = _sign_attestation(inv, _sk)
    assert INV.evaluate(inv, root, authority_keys=keys).status == C.DATASET_UNAVAILABLE                         # no orca_home => not resolvable
    (root / "home/training/raw").mkdir(parents=True)
    (root / "home/training/raw/x.jsonl").write_bytes(b"x\n")
    assert INV.evaluate(inv, root, root / "home", authority_keys=keys).status == C.PASS
    ext = corpus("c3", "n/a", b"y\n", cls="external_uploaded_datasets", storage={"kind": "EXTERNAL_DESCRIPTOR", "location": "kaggle:x"})
    inv["corpora"].append(ext)
    inv["class_coverage"]["external_uploaded_datasets"] = {"declaration": "LISTED", "corpus_ids": ["c3"]}
    inv["completeness_attestation"]["record"] = _sign_attestation(inv, _sk)
    assert INV.evaluate(inv, root, root / "home", authority_keys=keys).status == C.DATASET_UNAVAILABLE


def test_hash_mismatch_fails(good):
    inv, root, keys, _sk = good
    (root / "d.jsonl").write_bytes(b'{"text": "tampered"}\n')
    r = INV.evaluate(inv, root, authority_keys=keys)
    assert r.status == C.FAIL and r.findings[0]["why"] == "HASH_MISMATCH"


@pytest.mark.parametrize("field", INV.TRISTATE_FIELDS)
def test_unknown_usage_or_visibility_flags_block(good, field):
    inv, root, keys, _sk = good
    inv["corpora"][0][field] = "UNKNOWN"
    inv["completeness_attestation"]["record"] = _sign_attestation(inv, _sk)
    r = INV.evaluate(inv, root, authority_keys=keys)
    assert r.status == C.INCOMPLETE and {"corpus": "c1", "field": field} in r.findings


def test_contamination_check_not_pass_blocks(good):
    inv, root, keys, _sk = good
    inv["corpora"][0]["contamination_check_status"] = "PENDING_V2_CORPUS"
    inv["completeness_attestation"]["record"] = _sign_attestation(inv, _sk)
    assert INV.evaluate(inv, root, authority_keys=keys).status == C.INCOMPLETE


@pytest.mark.parametrize("mut", [
    lambda inv: inv["corpora"][0].pop("owner"), lambda inv: inv["corpora"][0].__setitem__("status", "MAYBE"),
    lambda inv: inv["corpora"][0].__setitem__("corpus_class", "nonsense"), lambda inv: inv["corpora"][0].__setitem__("classification", "SECRET"),
    lambda inv: inv["corpora"][0].__setitem__("storage", {"kind": "S3", "location": "x"}), lambda inv: inv["corpora"][0].__setitem__("record_count", -1),
    lambda inv: inv["corpora"][0].__setitem__("used_in_training", "maybe"), lambda inv: inv["corpora"][0].__setitem__("manifest_id_or_sha256", "short"),
    lambda inv: inv["corpora"].append(copy.deepcopy(inv["corpora"][0])), lambda inv: inv["class_coverage"].pop("coding_datasets"),
    lambda inv: inv["class_coverage"]["public_sft_datasets"].__setitem__("corpus_ids", []),
    lambda inv: inv["class_coverage"]["reasoning_datasets"].__setitem__("declaration", "BOGUS"),
    lambda inv: inv.__setitem__("schema_version", "x"), lambda inv: inv.__setitem__("completeness_attestation", {"status": "YES"})])
def test_schema_violations_fail_closed(good, mut):
    inv, root, keys, _sk = good
    mut(inv)
    r = INV.evaluate(inv, root, authority_keys=keys)
    assert r.status == C.FAIL and r.findings, r


def test_coverage_must_list_every_present_class(good):
    inv, root, keys, _sk = good
    inv["corpora"].append(corpus("c2", "d.jsonl", b"x\n", cls="distillation_data"))
    assert any("not LISTED" in p for p in INV.validate(inv, authority_keys=keys))


def test_inventory_gates_the_overlap_comparison(good):
    inv, root, keys, _sk = good
    item = {"item_id": "gce2-" + "1" * 24, "category": "research", "prompt": "an unrelated training record about orchids", "input": {}, "system": None}
    r = INV.check_v2_against_inventory([item], inv, root)[0]      # no authority_keys passed through check_v2_against_inventory => INCOMPLETE
    assert r.name == "training_corpora" and r.status != C.PASS
    clean = {**item, "prompt": "Consider a glacier survey team choosing between drones and ground radar for the coming season and report failure modes"}
    inv2 = copy.deepcopy(inv)
    inv2["completeness_attestation"]["status"] = "NOT_ATTESTED"
    r2 = INV.check_v2_against_inventory([clean], inv2, root)[0]
    assert r2.status == C.INCOMPLETE and not C.overall([r2])["pass"]
    assert INV.check_v2_against_inventory([clean], INV.empty_inventory(), root)[0].status == C.INCOMPLETE


def test_non_text_layouts_are_compared_by_all_string_leaves(tmp_path):
    p = tmp_path / "pairs.jsonl"
    p.write_text(json.dumps({"prompt": "Harbour authorities publish tide tables every quarter for pilots", "chosen": "x", "rejected": "y"}) + "\n")
    src = C.FileTrainingCorpus("pairs", p)
    item = {"item_id": "gce2-" + "2" * 24, "category": "research", "prompt": "Harbour authorities publish tide tables every quarter for pilots", "input": {}, "system": None}
    assert C.check_training_corpora([item], {"pairs": src}, required=("pairs",), declared_complete=True)[0].status == C.FAIL


# ---------------------------------------------------------------- the committed inventory
INV_FILE = ROOT / INV.INVENTORY_PATH


def test_committed_inventory_is_schema_valid_and_realistically_reviewed():
    inv = json.loads(INV_FILE.read_text())
    assert INV.validate(inv) == []                                                 # structurally valid even without a signing key available
    att = inv["completeness_attestation"]
    assert att["status"] == "NOT_ATTESTED"                                          # no OWNER authority key is registered yet to sign it
    assert att["record"]["completeness_status"] == "COMPLETE_WITH_DECLARED_UNAVAILABLE"
    assert att["record"]["unresolved_classes"] == ["external_uploaded_datasets"]
    assert att["record"]["signature"] is None
    assert att["record"]["corpus_inventory_digest"] == INV.inventory_digest(inv)
    assert len(inv["corpora"]) >= 60


def test_committed_inventory_lists_every_known_public_corpus_with_matching_hash():
    inv = json.loads(INV_FILE.read_text())
    by_loc = {c["storage"]["location"]: c for c in inv["corpora"] if c["storage"]["kind"] == "REPO_PATH"}
    sft = json.loads((ROOT / "docs/orneur/phase-21/PUBLIC_SFT_DATASET_CLASSIFICATION.json").read_text())["files"]
    for rel, e in sft.items():
        assert by_loc[rel]["manifest_id_or_sha256"] == e["sha256"] and by_loc[rel]["classification"] == "PUBLIC" and by_loc[rel]["status"] == "PRESENT", rel
    for f in ("pilot_train.jsonl", "dev.jsonl", "holdout.jsonl"):
        rel = f"eval_private/genesis_capability_eval_v1/{f}"
        v1 = json.loads((ROOT / "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V1_STATUS_RECORD.json").read_text())["exposed_files_sha256"][rel]
        assert by_loc[rel]["manifest_id_or_sha256"] == v1, rel
    assert by_loc["eval_private/genesis_capability_eval_v1/holdout.jsonl"]["corpus_class"] == "public_benchmark_v1"
    assert "FORBIDDEN" in by_loc["eval_private/genesis_capability_eval_v1/holdout.jsonl"]["permitted_lifecycle"]


def test_committed_inventory_classes_reviewed_absent_vs_genuinely_unresolved():
    inv = json.loads(INV_FILE.read_text())
    classes = {c["corpus_class"] for c in inv["corpora"]}
    assert {"public_sft_datasets", "private_sft_datasets", "instruction_tuning_datasets", "preference_dpo_data", "synthetic_generation_corpora", "distillation_data",
            "evaluation_derived_adaptation_data", "manually_authored_internal_examples", "public_benchmark_v1", "public_pilot_train_v1", "external_uploaded_datasets"} <= classes
    assert set(inv["class_coverage"]) == set(INV.CORPUS_CLASSES)
    reviewed_absent = {k for k, v in inv["class_coverage"].items() if v["declaration"] == "NONE_DECLARED_OWNER_REVIEWED"}
    assert {"reasoning_datasets", "coding_datasets", "tool_use_datasets", "rlhf_rlaif_data", "prompt_tuning_few_shot_stores", "retrieval_corpora",
            "router_expert_training_data", "future_fine_tuning_datasets", "candidate_specific_adaptation_sets"} <= reviewed_absent
    assert not any(v["declaration"] == "NONE_KNOWN_UNATTESTED" for v in inv["class_coverage"].values())          # nothing left as a mere placeholder
    ext = next(c for c in inv["corpora"] if c["corpus_id"] == "external-kaggle-uploaded-datasets")
    assert ext["status"] == "UNAVAILABLE"                                            # a real unresolved risk is preserved, never guessed into absence
    assert all(c["contamination_check_status"] == "PENDING_V2_CORPUS" for c in inv["corpora"])
    assert all(c["visible_during_screen"] is False and c["visible_during_qualification_holdout"] is False for c in inv["corpora"])


def test_committed_inventory_never_evaluates_to_pass_and_keeps_contamination_false(tmp_path):
    inv = json.loads(INV_FILE.read_text())
    ci = INV.evaluate(inv, ROOT, tmp_path / "no-orca-home")                      # CI-like environment: machine-local corpora absent
    assert ci.status != C.PASS
    here = INV.evaluate(inv, ROOT, None)
    assert here.status != C.PASS                                                  # unsigned attestation + unresolved external datasets: never PASS
    st = json.loads((ROOT / "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_STATUS.json").read_text())
    assert st["freeze_prerequisites"]["contamination_controls_pass"] is False and st["corpus_inventory"]["attested_complete"] is False
    assert st["component_states"]["corpus_inventory"] == "IMPLEMENTED_POPULATED_REVIEWED_UNSIGNED_DRAFT_ATTESTATION"


def test_committed_inventory_carries_no_content():
    inv = json.loads(INV_FILE.read_text())
    for c in inv["corpora"]:
        assert not set(c) & {"text", "prompt", "response", "records", "content"}, c["corpus_id"]
