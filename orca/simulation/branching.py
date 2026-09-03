"""
Bounded branching (Phase 11.1 spec §12-17). Never a combinatorial
explosion -- exactly two conceptual branches at most
(`EXPECTED_SUCCESS`/`EXPECTED_FAILURE`), only generated when real
uncertainty in the plan's own simulation result would materially change
the effects/verdict. Each branch is a REAL, independent
`simulate_plan()` run against its own fresh sandbox copy (never a
model-imagined future) -- `orca.simulation.plan_chamber.open_sandbox()`
already creates an isolated temp copy per call, so branch state
isolation is structural, not a separate mechanism to get right twice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from orca.agent.contracts import AgentPlan
from orca.deliberation.contracts import WorldState
from orca.simulation.contracts import EffectConfidence, SimulationVerdict, _new_id
from orca.simulation.plan_chamber import MAX_SIMULATION_BRANCHES, PlanSimulationResult, simulate_plan

_VERDICT_PRECEDENCE = [SimulationVerdict.BLOCK, SimulationVerdict.INCONCLUSIVE, SimulationVerdict.REVISE, SimulationVerdict.PASS_WITH_WARNINGS, SimulationVerdict.PASS]


class BranchLabel(str, Enum):
    EXPECTED_SUCCESS = "EXPECTED_SUCCESS"
    EXPECTED_FAILURE = "EXPECTED_FAILURE"


@dataclass
class BranchOutcome:
    branch_id: str = field(default_factory=lambda: _new_id("branch"))
    label: BranchLabel = BranchLabel.EXPECTED_SUCCESS
    result: PlanSimulationResult = None


@dataclass
class BranchedSimulationResult:
    branches: list[BranchOutcome] = field(default_factory=list)
    shared_effect_resources: list[str] = field(default_factory=list)
    divergent_effect_resources: list[str] = field(default_factory=list)
    worst_case_verdict: SimulationVerdict = SimulationVerdict.INCONCLUSIVE
    critical_uncertainty: str | None = None
    branch_count: int = 0


def _uncertainty_justifies_branching(result: PlanSimulationResult) -> bool:
    """
    spec §12: only branch when uncertainty MATERIALLY changes effects/
    verdict. Deterministic trigger -- never a model's own judgment call:
    a plan whose every effect is HIGH confidence and whose verdict is
    already PASS/BLOCK (nothing left ambiguous) is never branched;
    LOW/MEDIUM-confidence effects, or any per-action warning, indicate
    a real open question worth a second branch.
    """
    if result.aggregate_verdict in (SimulationVerdict.BLOCK,):
        return False  # already the worst outcome -- a second branch adds nothing
    if result.aggregate_warnings:
        return True
    return any(e.confidence != EffectConfidence.HIGH for e in result.aggregate_effects)


def _reserve_branch_budget(budget_ledger, n: int) -> int:
    """Each branch consumes from the SAME parent simulation budget
    (spec §14) -- no fresh independent allowance per branch. Returns how
    many of the `n` requested branch reservations actually succeeded;
    the caller must not run more branches than this."""
    if budget_ledger is None:
        return n
    from orca.cognitive.errors import CognitiveBudgetExhaustedError
    granted = 0
    for _ in range(n):
        try:
            budget_ledger.reserve("simulation_operations", 1)
            granted += 1
        except CognitiveBudgetExhaustedError:
            break
    return granted


def run_bounded_branches(
    plan: AgentPlan, *, filesystem_root: Path | None = None, live_world_state: WorldState | None = None, budget_ledger=None,
) -> BranchedSimulationResult:
    """
    Branch 1 (`EXPECTED_SUCCESS`) is always the real, full `simulate_plan()`
    result. Branch 2 (`EXPECTED_FAILURE`), only generated when
    `_uncertainty_justifies_branching()` and budget allows, re-simulates
    a TRUNCATED plan (the last action dropped) -- a real, honest model of
    "what if the most uncertain action never completed," not a
    fabricated alternate timeline. `MAX_SIMULATION_BRANCHES` bounds the
    total regardless of how many actions look uncertain.
    """
    granted = _reserve_branch_budget(budget_ledger, min(2, MAX_SIMULATION_BRANCHES))
    branches: list[BranchOutcome] = []

    if granted < 1:
        return BranchedSimulationResult(branches=[], worst_case_verdict=SimulationVerdict.INCONCLUSIVE, critical_uncertainty="simulation budget exhausted before any branch could run")

    success_result = simulate_plan(plan, filesystem_root=filesystem_root, live_world_state=live_world_state)
    branches.append(BranchOutcome(label=BranchLabel.EXPECTED_SUCCESS, result=success_result))

    critical_uncertainty = None
    if granted >= 2 and len(branches) < MAX_SIMULATION_BRANCHES and _uncertainty_justifies_branching(success_result) and len(plan.actions) > 1:
        truncated_plan = AgentPlan(plan_id=plan.plan_id, tasks=plan.tasks, actions=plan.actions[:-1])
        failure_result = simulate_plan(truncated_plan, filesystem_root=filesystem_root, live_world_state=live_world_state)
        # Represent the truncated outcome honestly as at least
        # INCONCLUSIVE -- the dropped action's real effect is genuinely
        # unknown in this branch, never silently reported as if the
        # shorter plan were the intended, complete one.
        if failure_result.aggregate_verdict == SimulationVerdict.PASS:
            failure_result.aggregate_verdict = SimulationVerdict.INCONCLUSIVE
        branches.append(BranchOutcome(label=BranchLabel.EXPECTED_FAILURE, result=failure_result))
        critical_uncertainty = f"final action(s) beyond the truncation point carry {'warnings' if success_result.aggregate_warnings else 'sub-HIGH-confidence effects'}"

    assert len(branches) <= MAX_SIMULATION_BRANCHES

    all_resources = [{e.resource for e in b.result.aggregate_effects} for b in branches]
    shared = set.intersection(*all_resources) if all_resources else set()
    divergent = set.union(*all_resources) - shared if all_resources else set()

    worst_case = SimulationVerdict.PASS
    for candidate in _VERDICT_PRECEDENCE:
        if any(b.result.aggregate_verdict == candidate for b in branches):
            worst_case = candidate
            break

    return BranchedSimulationResult(
        branches=branches, shared_effect_resources=sorted(shared), divergent_effect_resources=sorted(divergent),
        worst_case_verdict=worst_case, critical_uncertainty=critical_uncertainty, branch_count=len(branches),
    )
