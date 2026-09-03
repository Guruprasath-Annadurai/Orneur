from __future__ import annotations

from orca.agent.eval_harness import run_all


def test_agent_eval_harness_all_scenarios_pass():
    result = run_all()
    assert result.pass_rate == 1.0, [s for s in result.results if not s.passed]
    assert result.total >= 20
