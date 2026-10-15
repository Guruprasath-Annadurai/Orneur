"""Lexical / structural / semantic diversity and category balance (synthetic data only)."""
import pytest

from orca.dataquality import balance as B
from orca.dataquality import diversity as DV
from orca.eval.genesis_v2.semantic import FeatureHashEmbedder
from tests.dataquality_support import chatml, distinct_records, lines_of


def test_distinct_n_and_type_token_match_hand_computation(tmp_path):
    # bodies (system excluded): "a b a b" and "a b c" -> tokens [a b a b], [a b c]
    lines = lines_of(tmp_path, [{"prompt": "a b a b", "response": "x"}, {"prompt": "a b c", "response": "x"}])
    # real bodies are prompt+response: [a,b,a,b,x] and [a,b,c,x]
    r = DV.lexical_structural(lines)
    lex = r["lexical"]
    assert r["tokens_total"] == 9 and lex["vocabulary_size"] == 4
    assert lex["type_token_ratio_corpus"] == round(4 / 9, 4)
    assert lex["distinct_1"] == {"total": 9, "distinct": 4, "ratio": round(4 / 9, 4)}
    # bigrams: (a,b),(b,a),(a,b),(b,x) | (a,b),(b,c),(c,x) => 7 total, distinct = ab, ba, bx, bc, cx = 5
    assert lex["distinct_2"] == {"total": 7, "distinct": 5, "ratio": round(5 / 7, 4)}


def test_repetitive_corpus_scores_lower_than_diverse_corpus(tmp_path):
    rep = lines_of(tmp_path, [chatml("the cat sat on the mat", "the cat sat on the mat")] * 10, "rep.jsonl")
    div = lines_of(tmp_path, distinct_records(10), "div.jsonl")
    a, b = DV.lexical_structural(rep), DV.lexical_structural(div)
    assert a["lexical"]["distinct_2"]["ratio"] < b["lexical"]["distinct_2"]["ratio"]
    assert a["structural"]["skeleton_normalized_entropy"] == 0.0 < b["structural"]["opening_skeleton"]["normalized_entropy"]


def test_minimum_thresholds_can_fail_the_check(tmp_path):
    rep = lines_of(tmp_path, [chatml("the cat sat on the mat", "the cat sat on the mat")] * 10)
    r = DV.lexical_structural(rep, min_distinct_2=0.9, min_skeleton_norm_entropy=0.5)
    assert r["status"] == "FAIL" and set(r["failing_conditions"]) == {"distinct_2_below_minimum", "skeleton_normalized_entropy_below_minimum"}
    assert DV.lexical_structural(rep)["status"] == "PASS"   # descriptive when no minimum is requested; documented in the report


def test_semantic_diversity_is_not_evaluated_without_a_local_semantic_embedder(tmp_path):
    lines = lines_of(tmp_path, distinct_records(5))
    assert DV.semantic(lines, None)["status"] == "NOT_EVALUATED"
    lexical = DV.semantic(lines, FeatureHashEmbedder())
    assert lexical["status"] == "NOT_EVALUATED" and "lexical proxy" in lexical["reason"]


def test_semantic_diversity_runs_only_with_an_accepted_injected_embedder(tmp_path):
    class Fake:   # test double honouring the contract of orca.eval.genesis_v2.semantic.Embedder; NOT a real semantic model
        model_id, model_sha256, local_only, semantic_capable = "fake", "ab" * 32, True, True

        def embed(self, texts):
            return [[1.0, 0.0] if i % 2 == 0 else [0.0, 1.0] for i, _ in enumerate(texts)]

    r = DV.semantic(lines_of(tmp_path, distinct_records(4)), Fake())
    assert r["status"] == "PASS" and r["mean_nearest_neighbour_cosine"] == 1.0   # each vector's nearest neighbour is its same-parity twin
    bad = Fake()
    bad.model_sha256 = "short"
    assert DV.semantic(lines_of(tmp_path, distinct_records(4)), bad)["status"] == "NOT_EVALUATED"


def test_no_text_is_not_evaluated(tmp_path):
    assert DV.lexical_structural([])["status"] == "NOT_EVALUATED"


# ------------------------------------------------------------------ balance
def labeled(cat, i):
    r = chatml(f"q {i}", f"a {i}")
    r["category"] = cat
    return r


def test_counts_ratios_and_min_share_flags(tmp_path):
    recs = [labeled("alpha", i) for i in range(8)] + [labeled("beta", i) for i in range(8, 11)] + [labeled("gamma", 99)]
    r = B.balance(lines_of(tmp_path, recs), min_share=0.15)
    rows = {c["category"]: c for c in r["categories"]}
    assert rows["alpha"]["count"] == 8 and rows["alpha"]["share"] == round(8 / 12, 4)
    assert r["flagged_below_min_share"] == ["gamma"] and r["status"] == "FAIL" and "categories_below_min_share" in r["failing_conditions"]
    assert r["max_to_min_ratio"] == 8.0


def test_balanced_labeled_dataset_passes(tmp_path):
    recs = [labeled(c, i) for i, c in enumerate("ab" * 10)]
    assert B.balance(lines_of(tmp_path, recs))["status"] == "PASS"


def test_unlabeled_records_fail_and_no_labels_is_not_evaluated(tmp_path):
    recs = [labeled("a", 1), labeled("b", 2), chatml("no label", "x")]
    r = B.balance(lines_of(tmp_path, recs), min_share=0.0)
    assert r["status"] == "FAIL" and r["unlabeled"] == 1
    none = B.balance(lines_of(tmp_path, [chatml("a", "b")] * 3))
    assert none["status"] == "NOT_EVALUATED" and "never inferred" in none["reason"]


def test_sidecar_labels_and_nested_field(tmp_path):
    recs = [chatml("a", "b"), chatml("c", "d"), {**chatml("e", "f"), "meta": {"subtype": "m1"}}]
    r = B.balance(lines_of(tmp_path, recs), labels={"1": "x", "2": "y"}, min_share=0.1)
    assert {c["category"] for c in r["categories"]} == {"x", "y", "m1"} and r["status"] == "PASS"


def test_single_category_fails_min_categories(tmp_path):
    assert "too_few_categories" in B.balance(lines_of(tmp_path, [labeled("a", i) for i in range(5)]))["failing_conditions"]


def test_bad_min_share_rejected(tmp_path):
    with pytest.raises(ValueError):
        B.balance(lines_of(tmp_path, [labeled("a", 1)]), min_share=2)
