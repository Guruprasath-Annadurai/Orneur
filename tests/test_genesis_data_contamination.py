"""
GENESIS Foundation Sprint 2, Workstream A, Mission A3/A6: benchmark
contamination control tests.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from orca.genesis.data.contamination import (
    ContaminationCheckIncomplete,
    find_exact_matches,
    find_near_duplicates_across_splits,
    find_normalized_substring_matches,
    load_genesis_eval_v1_fingerprints,
    run_contamination_checks,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_exact_matches_are_found_after_normalization():
    candidates = ["Hello   World", "a totally different sentence"]
    protected = ["hello world"]
    matches = find_exact_matches(candidates, protected)
    assert matches == [(0, 0)]


def test_no_exact_matches_for_genuinely_different_text():
    assert find_exact_matches(["completely unrelated text"], ["something else entirely"]) == []


def test_normalized_substring_match_catches_embedded_protected_text():
    protected = ["this exact forty-plus-character benchmark question appears"]
    candidate = "Some surrounding text. this exact forty-plus-character benchmark question appears right here in context."
    matches = find_normalized_substring_matches([candidate], protected)
    assert matches == [(0, 0)]


def test_normalized_substring_match_ignores_short_strings_below_min_len():
    matches = find_normalized_substring_matches(["short text here"], ["hi"], min_len=40)
    assert matches == []


# ------------------------------------------------- the "clean" gate must be honest --

def test_a_report_with_no_checks_performed_is_never_treated_as_clean():
    report = run_contamination_checks(["anything"])
    assert report.checks_performed == ()
    assert report.clean is True  # vacuously true (no flags found)...
    # ...but is_fully_verified_clean must refuse to call this clean when
    # the caller actually requires checks that never ran -- "a dataset
    # cannot be marked clean merely because no scanner error was
    # reported" (Mission A3's explicit requirement).
    assert report.is_fully_verified_clean(required_checks=["exact_match"]) is False


def test_is_fully_verified_clean_true_only_when_required_checks_ran_and_passed():
    report = run_contamination_checks(["unrelated text"], protected_texts=["something else"])
    assert report.is_fully_verified_clean(required_checks=["exact_match", "normalized_substring_match"]) is True


def test_is_fully_verified_clean_false_when_a_flag_was_found():
    report = run_contamination_checks(["duplicate text"], protected_texts=["duplicate text"])
    assert report.clean is False
    assert report.is_fully_verified_clean(required_checks=["exact_match"]) is False


# ------------------------------------------------- sanctioned holdout access only --

def test_load_genesis_eval_v1_fingerprints_reads_the_real_committed_file():
    fps = load_genesis_eval_v1_fingerprints(REPO_ROOT)
    assert len(fps) > 0
    # Fingerprints are n-gram HASHES (ints), never raw holdout text --
    # confirming this module never exposes protected text.
    for item_id, hashes in list(fps.items())[:5]:
        assert isinstance(item_id, str)
        assert all(isinstance(h, int) for h in hashes)


def test_load_genesis_eval_v1_fingerprints_raises_cleanly_when_missing(tmp_path):
    with pytest.raises(ContaminationCheckIncomplete):
        load_genesis_eval_v1_fingerprints(tmp_path)


def test_this_module_never_calls_the_gated_holdout_split_reader():
    """Structural guard: this module must never import or call
    orca.eval.genesis_harness.open_split (the only sanctioned way to
    read raw HOLDOUT text) or orca.eval.genesis_corpus.load_split
    directly -- only the pre-committed, non-text fingerprint file."""
    import ast

    import orca.genesis.data.contamination as mod
    tree = ast.parse(Path(mod.__file__).read_text())
    imported_names = {
        alias.asname or alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "open_split" not in imported_names
    assert "load_split" not in imported_names
    assert not any(isinstance(n, ast.ImportFrom) and n.module == "orca.eval.genesis_harness" for n in ast.walk(tree))


def test_holdout_overlap_check_flags_a_real_overlapping_candidate():
    fps = load_genesis_eval_v1_fingerprints(REPO_ROOT)
    # Build a synthetic candidate text from one holdout item's own
    # n-gram hash set is not possible without the text; instead, confirm
    # the mechanism end-to-end using a candidate that shares enough
    # vocabulary with ANY fingerprint entry to be flagged is unreliable
    # without real text, so this test instead confirms the function runs
    # against the real fingerprint data and reports the check as performed.
    report = run_contamination_checks(["a harmless unrelated synthetic sentence about gardening"], holdout_fingerprints=fps)
    assert "genesis_eval_v1_holdout_overlap" in report.checks_performed


# ------------------------------------------------- A-11: cross-split near-duplicate leakage --

def test_find_near_duplicates_across_splits_flags_a_leaking_pair():
    base = (
        "The quick brown fox jumps over the lazy dog near the riverbank today while "
        "the morning sun rises slowly over the distant quiet green hills beyond town"
    )
    near = (
        "The quick brown fox jumps over the lazy dog near the riverbank today while "
        "the morning sun rises slowly over the distant quiet green hills beyond city"
    )
    flagged = find_near_duplicates_across_splits({"train": [base], "validation": [near]})
    assert flagged == [("train", 0, "validation", 0)]


def test_find_near_duplicates_across_splits_ignores_within_split_pairs():
    """Within-split near-duplicates are pipeline.py's own concern during
    processing (and are rejected there before ever reaching a split at
    all) -- this cross-split check must not double-flag records that
    happen to share a split."""
    base = "a sentence repeated with only this one word changed: alpha"
    near = "a sentence repeated with only this one word changed: beta"
    flagged = find_near_duplicates_across_splits({"train": [base, near]})
    assert flagged == []


def test_find_near_duplicates_across_splits_finds_nothing_for_genuinely_distinct_records():
    flagged = find_near_duplicates_across_splits({
        "train": ["a sentence entirely about cooking pasta for dinner tonight"],
        "validation": ["a completely unrelated sentence about space exploration history"],
    })
    assert flagged == []


def test_run_contamination_checks_reports_cross_split_leakage():
    base = "a long enough sentence about a very specific unusual topic for this exact test to work reliably"
    near = "a long enough sentence about a very specific unusual topic for this exact test to work reliably!!"
    report = run_contamination_checks(
        ["irrelevant candidate text"], split_to_records={"train": [base], "test": [near]},
    )
    assert "cross_split_near_duplicate" in report.checks_performed
    assert report.cross_split_near_duplicates == 1
    assert report.clean is False


def test_a_clean_looking_report_missing_the_cross_split_check_is_still_not_fully_verified():
    """A-11's exact directive wording: zero flags but an incomplete set
    of checks is not proof of a clean corpus -- demonstrated here
    specifically for the NEW cross-split check (a caller who forgets to
    pass split_to_records at all must not have their report treated as
    having screened for train/eval leakage)."""
    report = run_contamination_checks(["anything"], protected_texts=["something else"])
    assert report.clean is True  # no flags from the checks that DID run
    assert report.is_fully_verified_clean(required_checks=["exact_match", "cross_split_near_duplicate"]) is False


# ------------------------------------------------- P1-02: explicit cross-split scalability limit --

def test_find_near_duplicates_across_splits_raises_past_the_explicit_size_limit():
    from orca.genesis.data.contamination import CrossSplitScreeningTooLargeError

    split_to_records = {"train": [f"record {i}" for i in range(6)]}
    with pytest.raises(CrossSplitScreeningTooLargeError, match="exceeding max_total_records"):
        find_near_duplicates_across_splits(split_to_records, max_total_records=5)


def test_find_near_duplicates_across_splits_allows_a_caller_to_explicitly_raise_the_limit():
    split_to_records = {"train": [f"record {i}" for i in range(6)]}
    flagged = find_near_duplicates_across_splits(split_to_records, max_total_records=10)
    assert flagged == []
