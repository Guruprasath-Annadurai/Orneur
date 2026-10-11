"""Split separation across SCREEN / QUALIFICATION_HOLDOUT / DEV / TRAIN: exact, near-duplicate, structural, cluster and canary checks, over every pair."""
import copy

import pytest

from orca.evalinfra import splits as SPL
from orca.evalinfra import synthetic as SY
from orca.evalinfra.errors import SchemaViolation, SplitViolation

CATS = (3, 10)
COUNTS = {"SCREEN": 5, "QUALIFICATION_HOLDOUT": 6, "DEV": 3, "TRAIN": 6}


@pytest.fixture(scope="module")
def clean():
    return SY.make_items(11, CATS, COUNTS)


def first(items, split, cat=3):
    return next(i for i in items if i["split"] == split and i["category"] == cat)


def checks(items, **kw):
    rep = SPL.check_split_separation(items, **kw)
    return rep, {f["check"] for f in rep.findings}


def test_clean_synthetic_corpus_passes_every_pair(clean):
    rep, kinds = checks(clean)
    assert rep.status == SPL.PASS and kinds == set()
    assert len(rep.checked_pairs) == 6                       # all C(4,2) split pairs were actually compared


def _leak(clean, src_split, dst_split, **mutate):
    items = copy.deepcopy(clean)
    s, d = first(items, src_split), first(items, dst_split)
    d.update({"prompt": s["prompt"], **mutate})
    return items, s, d


@pytest.mark.parametrize("a,b", [("TRAIN", "QUALIFICATION_HOLDOUT"), ("SCREEN", "QUALIFICATION_HOLDOUT"), ("DEV", "QUALIFICATION_HOLDOUT"),
                                 ("TRAIN", "SCREEN"), ("DEV", "TRAIN"), ("DEV", "SCREEN")])
def test_exact_prompt_copy_is_caught_for_every_split_pair(clean, a, b):
    items, s, d = _leak(clean, a, b)
    rep, kinds = checks(items)
    assert rep.status == SPL.FAIL and "exact_prompt_text" in kinds
    f = next(x for x in rep.findings if x["check"] == "exact_prompt_text")
    assert set(f["splits"]) == {a, b}


def test_exact_item_id_and_content_fingerprint_caught(clean):
    items = copy.deepcopy(clean)
    first(items, "TRAIN")["item_id"] = first(items, "QUALIFICATION_HOLDOUT")["item_id"]
    assert "exact_item_id" in checks(items)[1]
    items = copy.deepcopy(clean)
    s, d = first(items, "TRAIN"), first(items, "QUALIFICATION_HOLDOUT")
    d.update({"prompt": s["prompt"], "ground_truth": s["ground_truth"]})
    assert "exact_content_fingerprint" in checks(items)[1]


def test_hidden_answer_overlap_caught(clean):
    items = copy.deepcopy(clean)
    first(items, "TRAIN")["ground_truth"] = {"answer": "an unmistakably long unique hidden answer string for the test"}
    first(items, "QUALIFICATION_HOLDOUT")["ground_truth"] = {"answer": "an unmistakably long unique hidden answer string for the test"}
    assert {"exact_hidden_answer", "answer_leaf"} <= checks(items)[1]


def test_near_duplicate_with_light_edits_caught(clean):
    items = copy.deepcopy(clean)
    s = first(items, "TRAIN")
    words = s["prompt"].split()
    edited = words[:]
    edited[3] = "zzedit"
    edited[len(edited) // 2] = "qqedit"
    first(items, "QUALIFICATION_HOLDOUT")["prompt"] = " ".join(edited)
    rep, kinds = checks(items)
    assert "near_duplicate_text" in kinds and "exact_prompt_text" not in kinds
    f = next(x for x in rep.findings if x["check"] == "near_duplicate_text")
    assert 0.6 <= f["score"] < 1.0


def test_structural_clone_with_replaced_content_words_caught(clean):
    items = copy.deepcopy(clean)
    s = first(items, "SCREEN")
    toks = s["prompt"].split()
    func = SY.S.FUNCTION_WORDS
    clone = " ".join(t if t.strip(".").lower() in func else "zq" + chr(97 + i % 26) * 3 + ("." if t.endswith(".") else "") for i, t in enumerate(toks))
    first(items, "QUALIFICATION_HOLDOUT")["prompt"] = clone
    assert "structural_clone" in checks(items)[1]


def test_shared_cluster_in_same_category_caught_and_missing_cluster_flagged(clean):
    items = copy.deepcopy(clean)
    first(items, "TRAIN")["cluster"] = "shared-template"
    first(items, "QUALIFICATION_HOLDOUT")["cluster"] = "shared-template"
    assert "shared_cluster" in checks(items)[1]
    items = copy.deepcopy(clean)
    first(items, "DEV")["cluster"] = ""
    assert "cluster_label_missing" in checks(items)[1]


def test_canary_of_one_split_found_in_another_is_caught(clean):
    canaries = {"TRAIN": ["CANARY-TRAIN-7f3a9c1e5b2d4a60"], "QUALIFICATION_HOLDOUT": ["CANARY-HOLDOUT-0b8e6d4c2a1f9375"]}
    items = copy.deepcopy(clean)
    first(items, "TRAIN")["prompt"] += " canary-train-7f3a9c1e5b2d4a60"                 # in its OWN split: fine
    assert SPL.check_split_separation(items, canaries=canaries).passed
    first(items, "QUALIFICATION_HOLDOUT")["prompt"] += " [CANARY-TRAIN-7f3a9c1e5b2d4a60]"   # train canary leaked into the holdout
    rep = SPL.check_split_separation(items, canaries=canaries)
    assert rep.status == SPL.FAIL
    f = next(x for x in rep.findings if x["check"] == "canary")
    assert f["canary_split"] == "TRAIN" and f["found_in_split"] == "QUALIFICATION_HOLDOUT"
    items = copy.deepcopy(clean)
    first(items, "SCREEN")["ground_truth"] = {"answer": "x CANARY-HOLDOUT-0b8e6d4c2a1f9375 y"}   # canary inside an ANSWER field is caught too
    assert "canary" in checks(items, canaries=canaries)[1]


def test_short_canary_refused_to_avoid_false_matches(clean):
    with pytest.raises(SchemaViolation):
        SPL.check_split_separation(clean, canaries={"TRAIN": ["abc"]})
    with pytest.raises(SchemaViolation):
        SPL.check_split_separation(clean, canaries={"PILOT_TRAIN": ["CANARY-LONG-ENOUGH-1234"]})


def test_missing_required_split_is_incomplete_never_pass(clean):
    items = [i for i in clean if i["split"] != "TRAIN"]
    rep = SPL.check_split_separation(items)
    assert rep.status == SPL.INCOMPLETE and not rep.passed
    assert SPL.check_split_separation(items, required_splits=("SCREEN", "QUALIFICATION_HOLDOUT")).passed


def test_bad_items_refused(clean):
    items = copy.deepcopy(clean)
    items[0]["split"] = "PILOT_TRAIN"
    with pytest.raises(SchemaViolation):
        SPL.check_split_separation(items)
    items = copy.deepcopy(clean)
    items[1]["item_id"] = items[0]["item_id"]
    with pytest.raises(SchemaViolation):
        SPL.check_split_separation(items)


def test_assert_separated_raises_and_findings_never_contain_text(clean):
    items, s, d = _leak(clean, "TRAIN", "QUALIFICATION_HOLDOUT")
    with pytest.raises(SplitViolation):
        SPL.assert_separated(items)
    rep = SPL.check_split_separation(items)
    blob = repr(rep.findings)
    assert s["prompt"][:30] not in blob and s["ground_truth"]["answer"] not in blob
    assert SPL.assert_separated(clean).passed
