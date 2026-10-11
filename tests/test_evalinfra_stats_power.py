"""Power / MDE / sample size for paired binary outcomes, checked against PRETRAINING_FOUNDATION_QUALIFICATION_BLUEPRINT.md section 6.6 and cross-checked by
exact enumeration and by seeded simulation."""
import re
from pathlib import Path

import pytest

from orca.evalinfra import stats_power as PW
from orca.evalinfra.errors import SchemaViolation

ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = ROOT / "docs/orneur/status/PRETRAINING_FOUNDATION_QUALIFICATION_BLUEPRINT.md"

TABLE = {0.03: (870, 1742, 2614), 0.05: (312, 626, 940), 0.08: (120, 243, 366), 0.10: (76, 155, 233)}     # blueprint 6.6, p_d = 0.10 / 0.20 / 0.30
MDE = {40: 19.2, 80: 13.8, 100: 12.4, 120: 11.3, 420: 6.1, 1000: 4.0}                                      # pts at p_d = 0.20


def test_sample_size_table_reproduces_blueprint_section_6_6():
    for d, row in TABLE.items():
        assert tuple(PW.required_n(d, p, rounding="nearest") for p in (0.10, 0.20, 0.30)) == row, d
        ceil = tuple(PW.required_n(d, p) for p in (0.10, 0.20, 0.30))
        assert all(0 <= c - b <= 1 for c, b in zip(ceil, row)), d              # the safe (ceil) value never undershoots the blueprint and differs by at most 1
    # the three cells where the blueprint rounded to nearest (down) instead of up: ceil is the safe value
    assert [PW.required_n(d, p) for d, p in ((0.08, 0.10), (0.10, 0.10), (0.10, 0.30))] == [121, 77, 234]
    assert [PW.required_n(d, p, rounding="nearest") for d, p in ((0.08, 0.10), (0.10, 0.10), (0.10, 0.30))] == [120, 76, 233]
    assert PW.required_n(0.05, 0.20) == 626                                    # the headline number in the task statement


def test_mde_table_reproduces_blueprint_section_6_6():
    for n, pts in MDE.items():
        assert round(PW.mde(n, 0.20) * 100, 1) == pts, n
    assert round(PW.mde(420, 0.20) * 100, 1) == 6.1


def test_bonferroni_eight_comparisons_needs_about_1020_items():
    assert PW.required_n(0.05, 0.20, alpha=PW.bonferroni_alpha(0.05, 8)) == 1020
    assert PW.bonferroni_alpha(0.05, 8) == pytest.approx(0.00625)


def test_the_blueprint_document_still_states_the_numbers_this_module_reproduces():
    text = BLUEPRINT.read_text()
    for needle in ("| 5 pts | 312 | 626 | 940 |", "**n=420 → 6.1**", "≈1,020 items"):
        assert needle in text
    assert re.search(r"n=40 → 19\.2", text)


def test_mde_is_the_inverse_of_required_n():
    for n in (100, 420, 1000):
        d = PW.mde(n, 0.2)
        assert PW.required_n_raw(d, 0.2) == pytest.approx(n, rel=1e-6)
    assert PW.mde(5, 0.2) is None                                              # too small to detect anything at all


def test_monotonicity():
    assert PW.required_n(0.05, 0.1) < PW.required_n(0.05, 0.2) < PW.required_n(0.05, 0.3)
    assert PW.required_n(0.10, 0.2) < PW.required_n(0.05, 0.2) < PW.required_n(0.03, 0.2)
    assert PW.required_n(0.05, 0.2, power=0.9) > PW.required_n(0.05, 0.2, power=0.8)
    assert PW.mde(1000, 0.2) < PW.mde(420, 0.2) < PW.mde(100, 0.2)


def test_invalid_parameters_refused():
    for args in ((0, 0.2), (-0.1, 0.2), (0.3, 0.2), (0.05, 0), (0.05, 1.5)):
        with pytest.raises(SchemaViolation):
            PW.required_n(*args)
    with pytest.raises(SchemaViolation):
        PW.required_n(0.05, 0.2, alpha=0)
    with pytest.raises(SchemaViolation):
        PW.required_n(0.05, 0.2, power=1.0)
    with pytest.raises(SchemaViolation):
        PW.bonferroni_alpha(0.05, 0)


def test_exact_power_at_the_closed_form_sample_size_is_close_to_target():
    # the exact test is slightly conservative relative to the normal approximation
    p = PW.exact_power(626, 0.20, 0.05)
    assert 0.74 <= p <= 0.82
    assert PW.exact_power(312, 0.10, 0.05) > 0.72
    assert PW.exact_power(2000, 0.20, 0.05) > 0.99
    assert PW.exact_power(20, 0.20, 0.05) < 0.2


def test_exact_power_is_monotone_in_n_and_effect():
    assert PW.exact_power(200, 0.2, 0.05) < PW.exact_power(400, 0.2, 0.05) < PW.exact_power(800, 0.2, 0.05)
    assert PW.exact_power(300, 0.2, 0.03) < PW.exact_power(300, 0.2, 0.08)


@pytest.mark.parametrize("n,pd,delta", [(626, 0.20, 0.05), (312, 0.10, 0.05), (243, 0.20, 0.08)])
def test_simulation_cross_check_agrees_with_exact_power_and_closed_form(n, pd, delta):
    sim = PW.simulate_power(n, pd, delta, reps=3000, seed=20260101)
    exact = PW.exact_power(n, pd, delta)
    assert abs(sim - exact) < 0.035                                            # ~3.5 Monte-Carlo SEs at 3000 reps
    assert abs(sim - 0.80) < 0.07                                              # and both sit near the 0.80 the closed form was solved for


def test_simulation_is_seeded_and_reproducible():
    a = PW.simulate_power(120, 0.2, 0.08, reps=500, seed=1)
    assert a == PW.simulate_power(120, 0.2, 0.08, reps=500, seed=1)


def test_type_one_error_of_the_exact_test_is_controlled():
    # delta -> 0 limit (use a tiny effect): rejection probability must not exceed alpha
    assert PW.simulate_power(200, 0.2, 1e-9, reps=3000, seed=5) <= 0.05 + 0.02
    assert PW.exact_power(200, 0.2, 1e-9) <= 0.05 + 1e-9


def test_tables_helpers():
    assert PW.sample_size_table()[0.05][0.20] == 626 and PW.sample_size_table(rounding='nearest')[0.08][0.10] == 120
    assert round(PW.mde_table()[420] * 100, 1) == 6.1
