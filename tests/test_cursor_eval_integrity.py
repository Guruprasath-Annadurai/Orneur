"""Synthetic evaluation integrity. No model and no secret items."""
from __future__ import annotations

import pytest

from orca.genesis.eval.integrity import (
    EvalDefinition,
    EvalHarness,
    EvalIntegrityError,
    EvalItem,
    revise_threshold,
    scan_exact_contamination,
    seeded_item_order,
    wilson_interval,
)


def _definition() -> EvalDefinition:
    items = (
        EvalItem("b", "2+2", "4"),
        EvalItem("a", "1+1", "2", hidden_expected=True),
        EvalItem("c", "3+3", "6"),
    )
    return EvalDefinition(
        eval_id="synthetic-arith",
        version="v1",
        rubric_version="exact-v1",
        seed=7,
        items=items,
        pass_threshold=0.5,
    )


def test_run_keeps_failures_and_does_not_log_hidden_answers():
    harness = EvalHarness()
    definition = _definition()

    def predict(prompt: str):
        return {"1+1": "2", "2+2": "5", "3+3": None}[prompt]

    report = harness.run(definition, predict)
    assert [row.status for row in report.results] == ["FAIL", "PASS", "MISSING"]
    assert report.counts()["FAIL"] == 1
    assert report.accuracy() == 0.5
    log = harness.public_log(definition, report)
    assert "2" not in log.splitlines()[2]
    assert "<hidden>" in log
    assert "4" in log  # the failed item's expected answer is not hidden


def test_threshold_change_requires_a_new_version():
    definition = _definition()
    with pytest.raises(EvalIntegrityError, match="new eval version"):
        revise_threshold(definition, 0.9, "v1")
    revised = revise_threshold(definition, 0.9, "v2")
    assert revised.version == "v2"
    assert revised.pass_threshold == 0.9
    assert definition.pass_threshold == 0.5


def test_contamination_screen_flags_an_exact_overlap():
    definition = _definition()
    flagged = scan_exact_contamination(definition.items, ["  1+1  "])
    assert flagged == ["a"]


def test_missing_and_errors_are_not_counted_as_passes():
    harness = EvalHarness()
    definition = _definition()

    def predict(prompt: str):
        if prompt == "2+2":
            raise RuntimeError("boom")
        return None

    report = harness.run(definition, predict)
    assert report.n_pass == 0
    assert report.accuracy() is None
    assert report.counts()["ERROR"] == 1
    assert report.counts()["MISSING"] == 2


def test_wilson_interval_on_a_known_proportion():
    low, high = wilson_interval(1, 1)
    assert 0.0 <= low <= 1.0 <= high or high == 1.0
    assert low < 1.0
    assert wilson_interval(0, 0) is None


def test_paired_comparison_uses_the_same_items():
    harness = EvalHarness()
    definition = _definition()
    left = harness.run(definition, lambda prompt: "4" if prompt == "2+2" else "0")
    right = harness.run(definition, lambda prompt: "2" if prompt == "1+1" else "0")
    paired = harness.paired_comparison(left, right)
    assert paired["n_excluded"] == 0
    assert paired["only_left"] == 1
    assert paired["only_right"] == 1
    assert paired["paired_difference"] == 0


def test_seeded_order_is_stable_and_complete():
    definition = _definition()
    assert seeded_item_order(definition) == seeded_item_order(definition)
    assert sorted(seeded_item_order(definition)) == ["a", "b", "c"]
