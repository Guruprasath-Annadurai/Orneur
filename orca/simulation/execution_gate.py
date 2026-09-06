"""
Simulation Execution Gate (Phase 11 spec §46). `ALLOW_TO_PROCEED_TO_AUTHORIZATION`
does NOT mean the action is authorized -- Capability/Policy/lease checks
(unchanged, Phase 8/9/10) still run after this, independently. This gate
answers exactly one question: "is it even sane to ASK for authorization
given what simulation found," never "is this authorized."
"""
from __future__ import annotations

from orca.simulation.contracts import ExecutionGateDecision, SimulationRequirement, SimulationResult, SimulationVerdict


def evaluate_execution_gate(
    *, requirement: SimulationRequirement, result: SimulationResult | None,
) -> ExecutionGateDecision:
    """
    spec §45: INCONCLUSIVE is fail-closed by default (`REQUIRE_REVIEW`),
    never treated as "no news is good news." A `REQUIRED` simulation
    that produced no result at all (never ran) is BLOCK, not silently
    skipped.
    """
    if requirement == SimulationRequirement.REQUIRED and result is None:
        return ExecutionGateDecision.BLOCK

    if result is None:
        return ExecutionGateDecision.ALLOW_TO_PROCEED_TO_AUTHORIZATION

    if result.verdict == SimulationVerdict.BLOCK:
        return ExecutionGateDecision.BLOCK

    if result.verdict == SimulationVerdict.REVISE:
        return ExecutionGateDecision.REVISE_PLAN

    if result.verdict == SimulationVerdict.INCONCLUSIVE:
        # Fail-closed default (spec §45) -- UNAVAILABLE_BUT_REVIEW_REQUIRED
        # requirement or an inconclusive REQUIRED simulation both land
        # here; only OPTIONAL/NOT_REQUIRED contexts would ever call this
        # gate with an inconclusive result for a genuinely low-stakes
        # action, and REQUIRE_REVIEW is still the safe default there too.
        return ExecutionGateDecision.REQUIRE_REVIEW

    if result.verdict in (SimulationVerdict.PASS, SimulationVerdict.PASS_WITH_WARNINGS):
        return ExecutionGateDecision.ALLOW_TO_PROCEED_TO_AUTHORIZATION

    return ExecutionGateDecision.REQUIRE_REVIEW
