"""Evaluation schema + manifest validation: fail closed on unknown fields, duplicates, missing commitments, V1 material, LLM judges, content-bearing keys."""
import copy

import pytest

from orca.evalinfra import schema as SC
from orca.evalinfra import synthetic as SY
from orca.evalinfra.errors import SchemaViolation


@pytest.fixture(scope="module")
def base():
    items = SY.make_items(3, (3, 10), {"SCREEN": 3, "QUALIFICATION_HOLDOUT": 4, "DEV": 2, "TRAIN": 3})
    return SY.make_manifest(items)


def code(m):
    with pytest.raises(SchemaViolation) as e:
        SC.validate_manifest(m)
    return e.value.code


def rehash(m):
    """Recompute partition + manifest hashes after a deliberate edit so the edit itself (not the hash) is what is being tested."""
    for p in m["partitions"]:
        rows = [i for i in m["items"] if i["split"] == p["split"]]
        p["partition_sha256"] = SC.partition_hash(p["split"], [r["commitment"] for r in rows])
    m["manifest_sha256"] = SC.manifest_hash(m)
    return m


def test_valid_manifest_passes_and_carries_no_content(base):
    SC.validate_manifest(base)
    assert set(base["items"][0]) == {"id", "category", "split", "scorer", "commitment"}
    assert base["synthetic"] is True and base["eval_version"].startswith("SYNTHETIC")
    assert {p["split"] for p in base["partitions"]} == set(SC.SPLITS)


def test_unknown_field_at_every_level_refused(base):
    for path in (("",), ("categories", 0), ("scorers", 0), ("partitions", 0), ("items", 0)):
        m = copy.deepcopy(base)
        tgt = m if path == ("",) else m[path[0]][path[1]]
        tgt["surprise"] = 1
        assert code(m) == "UNKNOWN_FIELD", path


def test_missing_field_refused(base):
    for key in ("items", "taxonomy", "synthetic", "manifest_sha256"):
        m = copy.deepcopy(base)
        del m[key]
        assert code(m) == "MISSING_FIELD"
    m = copy.deepcopy(base)
    del m["items"][0]["commitment"]
    assert code(m) == "MISSING_FIELD"


def test_item_with_bad_or_absent_commitment_refused(base):
    for bad in ("", None, "abc", "Z" * 64, "A" * 64, 5):
        m = copy.deepcopy(base)
        m["items"][0]["commitment"] = bad
        assert code(rehash(m)) == "MISSING_OR_BAD_COMMITMENT"


def test_duplicate_item_id_refused(base):
    m = copy.deepcopy(base)
    m["items"][1]["id"] = m["items"][0]["id"]
    assert code(rehash(m)) == "DUPLICATE_ITEM_ID"


def test_duplicate_commitment_within_or_across_splits_refused(base):
    m = copy.deepcopy(base)
    other = next(i for i in m["items"] if i["split"] != m["items"][0]["split"])
    other["commitment"] = m["items"][0]["commitment"]
    assert code(rehash(m)) == "DUPLICATE_COMMITMENT"


def test_duplicate_category_and_scorer_ids_refused(base):
    m = copy.deepcopy(base)
    m["categories"].append(copy.deepcopy(m["categories"][0]))
    assert code(m) == "DUPLICATE_CATEGORY"
    m = copy.deepcopy(base)
    m["scorers"].append(copy.deepcopy(m["scorers"][0]))
    assert code(m) == "DUPLICATE_SCORER"


def test_unknown_category_scorer_and_split_refused(base):
    m = copy.deepcopy(base)
    m["items"][0]["category"] = 99
    assert code(rehash(m)) == "UNKNOWN_CATEGORY"
    m = copy.deepcopy(base)
    m["items"][0]["category"] = [1, 2]                       # unhashable must not crash the validator
    assert code(rehash(m)) == "UNKNOWN_CATEGORY"
    m = copy.deepcopy(base)
    m["categories"][0]["scorer"] = "nope"
    assert code(m) == "UNKNOWN_SCORER"
    m = copy.deepcopy(base)
    m["items"][0]["split"] = "PILOT_TRAIN"
    assert code(rehash(m)) == "BAD_SPLIT"
    m = copy.deepcopy(base)
    m["items"][0]["scorer"] = "unit_test" if m["items"][0]["scorer"] != "unit_test" else "exact_match"
    assert code(rehash(m)) == "SCORER_CATEGORY_MISMATCH"


def test_llm_judge_scorer_refused(base):
    for t in ("llm_judge", "model_judge"):
        m = copy.deepcopy(base)
        m["scorers"][0]["type"] = t
        assert code(m) == "LLM_JUDGE_FORBIDDEN"


def test_content_bearing_keys_refused_anywhere(base):
    for k in ("prompt", "ground_truth", "answer", "seed", "salt", "expected"):
        m = copy.deepcopy(base)
        m["items"][0][k] = "x"
        assert code(m) == "CONTENT_BEARING_KEY", k
    m = copy.deepcopy(base)
    m["categories"][0]["meta"] = {"x": 1}
    assert code(m) == "CONTENT_BEARING_KEY"


def test_v1_ids_and_versions_refused(base):
    m = copy.deepcopy(base)
    m["items"][0]["id"] = "gce1-" + "ab" * 6
    assert code(rehash(m)) == "BAD_ITEM_ID"
    m = copy.deepcopy(base)
    m["eval_version"] = "genesis-capability-eval/1.0.0"
    m["synthetic"] = False
    assert code(m) == "V1_REFUSED"


def test_synthetic_and_real_version_labels_cannot_be_confused(base):
    m = copy.deepcopy(base)
    m["synthetic"] = False                                   # claims to be real but carries a SYNTHETIC version
    assert code(m) == "WRONG_EVAL_VERSION"
    m = copy.deepcopy(base)
    m["eval_version"] = "genesis-capability-eval/2.0.0"      # claims synthetic but carries the real version
    assert code(m) == "SYNTHETIC_VERSION_LABEL"


def test_tampered_hashes_and_counts_refused(base):
    m = copy.deepcopy(base)
    m["partitions"][0]["item_count"] += 1
    assert code(m) == "PARTITION_COUNT_MISMATCH"
    m = copy.deepcopy(base)
    m["partitions"][0]["partition_sha256"] = "0" * 64
    assert code(m) == "PARTITION_HASH_MISMATCH"
    m = copy.deepcopy(base)
    m["manifest_sha256"] = "0" * 64
    assert code(m) == "MANIFEST_HASH_MISMATCH"
    m = copy.deepcopy(base)
    m["items"].append(copy.deepcopy(m["items"][0]))
    m["items"][-1]["id"] = "syn-" + "cd" * 12
    m["items"][-1]["commitment"] = "e" * 64
    assert code(m) in ("PARTITION_COUNT_MISMATCH", "MANIFEST_HASH_MISMATCH")


def test_non_dict_and_empty_inputs_refused(base):
    for bad in (None, [], "x", 3):
        assert code(bad) == "NOT_AN_OBJECT"
    for key in ("items", "categories", "scorers"):
        m = copy.deepcopy(base)
        m[key] = []
        assert code(m) in ("NO_ITEMS", "NO_CATEGORIES", "NO_SCORERS")


def test_bool_is_not_an_integer_for_counts(base):
    m = copy.deepcopy(base)
    m["partitions"][0]["item_count"] = True
    assert code(m) in ("PARTITION_COUNT_MISMATCH",)


def test_build_manifest_is_deterministic_and_validated(base):
    items = SY.make_items(3, (3, 10), {"SCREEN": 3, "QUALIFICATION_HOLDOUT": 4, "DEV": 2, "TRAIN": 3})
    assert SY.make_manifest(items) == base
    with pytest.raises(SchemaViolation):
        SC.build_manifest(eval_id="x", eval_version="SYNTHETIC-1", synthetic=True, taxonomy="t", categories=base["categories"], scorers=base["scorers"],
                          items=base["items"] + [{"id": "syn-" + "11" * 6, "category": 3, "split": "DEV", "scorer": "exact_match"}])
