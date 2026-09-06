from __future__ import annotations

from orca.society.eval_harness import run_all


def test_harness_runs_all_scenarios_deterministically():
    result = run_all()
    assert result.total >= 10
    assert result.pass_rate == 1.0, [r for r in result.results if not r.passed]


def test_harness_names_scenarios_covered_elsewhere_rather_than_faking_them():
    result = run_all()
    assert result.covered_elsewhere  # non-empty: explicit disclosure, not silent omission
