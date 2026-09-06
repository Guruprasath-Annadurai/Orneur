"""
Cognitive Court review for high-risk simulations (Phase 11.1 spec
§35-36). Mirrors `orca.agent.court_hook`'s exact discipline -- Court is
advisory only; `orca.simulation.execution_gate.evaluate_execution_gate()`
and the real, unmodified Capability/Policy chain remain the sole
authorization boundary. `orca/simulation/chamber.py` and
`plan_chamber.py` never import this module themselves (Court review is
opt-in, invoked explicitly by a caller that decides it's warranted) --
structurally proven in `tests/test_simulation_fast_path.py`.
"""
from __future__ import annotations

from orca.simulation.contracts import SimulationVerdict


def should_request_court_review(verdict: SimulationVerdict, *, is_high_risk: bool = False) -> bool:
    """Real, structured triggers only (spec §35): BLOCK, INCONCLUSIVE,
    or high-risk -- never "the plan looks complex" alone."""
    return verdict in (SimulationVerdict.BLOCK, SimulationVerdict.INCONCLUSIVE) or is_high_risk


async def request_simulation_court_review(objective: str, *, risk_level=None, budget=None):
    """
    Runs ONE bounded Cognitive Court round -- the SAME
    `orca.deliberation.court.CognitiveCourt`, consuming the caller's
    real shared `CognitiveBudget` (never a fresh simulation-only
    deliberation allocation). Returns the real `CourtVerdict`. The
    caller MUST NOT treat `ACCEPT` as permission to execute -- Court
    verdict remains advisory, recorded for audit only.
    """
    from orca.cognitive.contracts import RiskLevel
    from orca.deliberation.court import CognitiveCourt

    court = CognitiveCourt()
    case, verdict, stop_reason = await court.run(objective, risk_level=risk_level or RiskLevel.LOW, budget=budget)
    return case, verdict, stop_reason
