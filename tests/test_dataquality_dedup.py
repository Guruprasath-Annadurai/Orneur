"""Exact / near duplicate detection, cluster metrics, template concentration, and the legacy quick_ratio reproduction (synthetic data only)."""
import json

import pytest

from orca.dataquality import dedup as D
from orca.dataquality._common import canonical_json, load_jsonl
from tests.dataquality_support import SYSTEM, chatml, distinct_records, lines_of, llama3, words, write_jsonl

Q = words(1)
A = words(2)


def run(tmp_path, recs, **kw):
    return D.analyze(lines_of(tmp_path, recs), **kw)


def test_distinct_corpus_passes_with_no_duplicates(tmp_path):
    r = run(tmp_path, distinct_records(30))
    assert r["status"] == "PASS" and r["exact_raw"]["duplicate_groups"] == 0 and r["near_duplicates"]["pairs_at_or_above_threshold"] == 0
    assert r["near_duplicates"]["pairs_total"] == 30 * 29 // 2 and r["near_duplicates"]["unique_records_after_dedup"] == 30


def test_exact_duplicate_reported_with_line_numbers(tmp_path):
    recs = distinct_records(5) + [distinct_records(1)[0]]
    r = run(tmp_path, recs)
    assert r["status"] == "FAIL" and "exact_normalized_duplicates_exceed_limit" in r["failing_conditions"]
    assert r["exact_raw"]["groups_by_line"] == [[1, 6]] and r["exact_normalized"]["redundant_records"] == 1


@pytest.mark.parametrize("variant", [
    lambda s: s.upper(),                                   # casing
    lambda s: "  " + s.replace(" ", "   ") + "\n\n",       # whitespace
    lambda s: s.replace("a", "а", 3),                      # Cyrillic a homoglyph
    lambda s: s.replace("o", "ο", 2),                      # Greek omicron homoglyph
    lambda s: s.replace(" ", "​ ", 4),                # zero-width spaces
    lambda s: " ".join([w[:2] + "\u200b" + w[2:] if len(w) > 3 else w for w in s.split(" ")]),   # zero-width chars INSIDE words
    lambda s: s + " .,;!",                                 # trailing punctuation
])
def test_obfuscated_exact_duplicates_are_caught_after_normalisation(tmp_path, variant):
    base = chatml(Q, A)
    dup = chatml(variant(Q), variant(A))
    r = run(tmp_path, [base, dup] + distinct_records(3, offset=50))
    assert r["exact_raw"]["duplicate_groups"] == 0, "the variant must be byte-different for this test to mean anything"
    assert r["exact_normalized"]["duplicate_groups"] == 1 and r["exact_normalized"]["groups_by_line"] == [[1, 2]]


def test_near_duplicate_with_changed_numbers_is_flagged_as_numeric_variant_and_near_dup(tmp_path):
    t = lambda a, b: chatml(f"{words(7, 20)} has {a} items costing {b} dollars in {words(8, 6)}", words(9, 25))
    recs = [t(12, 340), t(13, 341), t(99, 5)] + distinct_records(4, offset=200)
    r = run(tmp_path, recs, threshold=0.8)
    assert r["exact_normalized"]["duplicate_groups"] == 0
    assert r["numeric_variants"]["groups"] == 1 and r["numeric_variants"]["groups_by_line"] == [[1, 2, 3]]
    assert r["near_duplicates"]["clusters"] == 1 and r["near_duplicates"]["clusters_by_line"] == [[1, 2, 3]]
    assert r["near_duplicates"]["redundant_records_if_one_kept_per_cluster"] == 2


def test_threshold_is_configurable(tmp_path):
    shared = words(3, 20)
    recs = [chatml(shared + " " + words(4, 6), words(5)), chatml(shared + " " + words(6, 6), words(5, 25))] + distinct_records(3, offset=300)
    loose = run(tmp_path, recs, threshold=0.3)
    strict = run(tmp_path, recs, threshold=0.99)
    assert loose["near_duplicates"]["pairs_at_or_above_threshold"] >= 1 and strict["near_duplicates"]["pairs_at_or_above_threshold"] == 0
    with pytest.raises(ValueError):
        run(tmp_path, recs, threshold=0)


def test_shared_system_prompt_boilerplate_does_not_create_false_near_duplicates(tmp_path):
    long_sys = " ".join(words(i, 40) for i in range(10))
    recs = [chatml(words(i), words(i + 1000), system=long_sys) for i in range(12)] + [llama3(words(40 + i), words(60 + i), system=long_sys) for i in range(6)]
    r = run(tmp_path, recs)
    assert r["near_duplicates"]["pairs_at_or_above_threshold"] == 0 and r["status"] == "PASS"


def test_clusters_and_cluster_metrics(tmp_path):
    g1, g2 = words(20, 24), words(21, 24)
    recs = [chatml(g1, "x"), chatml(g1 + " tail", "x"), chatml(g1, "x extra"), chatml(g2, "y"), chatml(g2 + " tail", "y")] + distinct_records(5, offset=400)
    r = run(tmp_path, recs, threshold=0.6)
    nd = r["near_duplicates"]
    assert nd["clusters"] == 2 and nd["largest_cluster_size"] == 3 and nd["records_in_clusters"] == 5
    assert nd["cluster_size_histogram"] == {"2": 1, "3": 1} or nd["cluster_size_histogram"] == {2: 1, 3: 1}
    assert nd["record_fraction_in_clusters"] == 0.5 and r["status"] == "FAIL"


def test_template_concentration_templated_vs_diverse(tmp_path):
    templated = [chatml(f"Please rewrite the following sentence in passive voice: {words(i, 10)}", words(i + 500, 20)) for i in range(20)]
    diverse = distinct_records(20)
    t = run(tmp_path, templated, threshold=0.99)["template_concentration"]["opening_skeleton"]
    d = run(tmp_path, diverse, threshold=0.99)["template_concentration"]["opening_skeleton"]
    assert t["top1_share"] == 1.0 and t["normalized_entropy"] == 0.0 and t["distinct"] == 1
    assert d["top1_share"] < 0.5 and d["normalized_entropy"] > t["normalized_entropy"]


def test_structural_clones_detect_same_template_different_words(tmp_path):
    tpl = lambda i: chatml(f"Given the list of {words(i, 3)} items, compute the total of the values {i} and {i + 1} then reply with the result line only about {words(i + 9, 2)}", words(i + 70, 12))
    r = run(tmp_path, [tpl(i) for i in range(8)] + distinct_records(4, offset=600), threshold=0.99)
    assert r["structural_clones"]["status"] == "MEASURED" and r["structural_clones"]["pairs"] >= 1


def test_too_few_records_is_not_evaluated(tmp_path):
    assert run(tmp_path, [chatml("a b c", "d e f")])["status"] == "NOT_EVALUATED"


def test_output_is_deterministic_and_canonical(tmp_path):
    recs = distinct_records(10) + [chatml(Q, A), chatml(Q.upper(), A)]
    a = canonical_json(run(tmp_path, recs))
    b = canonical_json(run(tmp_path, recs))
    assert a == b and "generated_at" not in a


def test_lsh_path_finds_the_same_pairs_as_all_pairs(tmp_path, monkeypatch):
    recs = [chatml(words(30, 24), "x"), chatml(words(30, 24) + " tail", "x")] + distinct_records(10, offset=700)
    exact = run(tmp_path, recs, threshold=0.7)
    monkeypatch.setattr(D, "ALL_PAIRS_MAX", 2)
    lsh = run(tmp_path, recs, threshold=0.7)
    assert lsh["config"]["near_method"] == "minhash_lsh_candidates_exact_verified" and exact["config"]["near_method"] == "all_pairs_exact_jaccard"
    assert lsh["near_duplicates"]["clusters_by_line"] == exact["near_duplicates"]["clusters_by_line"] == [[1, 2]]


# ------------------------------------------------------------------ legacy quick_ratio reproduction
def test_legacy_quick_ratio_counts_pairs_and_distinguishes_ratio(tmp_path):
    # same characters, different order => quick_ratio (multiset) says identical, ratio() does not
    a = "abcdefghij" * 20
    b = "".join(reversed(a))
    c = "zyxwvutsrq" * 20
    mk = lambda body: {"text": "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\nSYS<|eot_id|>" + body}
    lines = lines_of(tmp_path, [mk(a), mk(b), mk(c)])
    res = D.legacy_quick_ratio({"g": lines})
    assert res["pairs_total"] == 3 and res["quick_ratio_pairs_over_threshold"] == 1 and res["ratio_pairs_over_threshold"] == 0
    assert "system-prompt" in res["text_compared"]


def test_legacy_quick_ratio_pools_groups_and_bounds_size(tmp_path):
    g1 = lines_of(tmp_path, distinct_records(3), "g1.jsonl")
    g2 = lines_of(tmp_path, distinct_records(2, offset=9), "g2.jsonl")
    assert D.legacy_quick_ratio({"a": g1, "b": g2})["pairs_total"] == 10
    assert D.legacy_quick_ratio({"a": lines_of(tmp_path, distinct_records(1), "g3.jsonl")})["status"] == "NOT_EVALUATED"


def test_documented_phase0_figure_192_of_666_is_reproduced_on_the_public_nano_files():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "notebooks/data"
    pool = {n: load_jsonl(root / n) for n in ("orca_nano_combined_train_v1.jsonl", "orca_nano_combined_eval_v1.jsonl")}
    res = D.legacy_quick_ratio(pool)
    assert (res["quick_ratio_pairs_over_threshold"], res["pairs_total"], res["records_pooled"]) == (192, 666, 37)
    assert res["quick_ratio_fraction"] == 0.2883
    assert res["ratio_pairs_over_threshold"] == 0   # the order-aware similarity finds none: the 29% is a character-multiset effect
