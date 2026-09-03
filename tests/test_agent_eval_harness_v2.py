from __future__ import annotations

from orca.agent.eval_harness import run_all
from orca.agent.eval_harness_v2 import run_closure_scenarios


def test_original_phase8_scenarios_remain_green():
    result = run_all()
    assert result.pass_rate == 1.0, [s for s in result.results if not s.passed]
    assert result.total == 20


def test_phase81_closure_scenarios_pass():
    result = run_closure_scenarios()
    assert result.pass_rate == 1.0, [s for s in result.results if not s.passed]
    assert result.total >= 16
