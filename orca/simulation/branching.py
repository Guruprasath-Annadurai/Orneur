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
from orca.simulation.plan_chamber import MAX_SIMULATION_BRANCHES, PlanSimulationResult, simulate_plan, simulate_plan_async

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
    cancelled: bool = False
    active_branch_ids_at_cancel: list[str] = field(default_factory=list)
    completed_branch_ids: list[str] = field(default_factory=list)
    cancelled_branch_ids: list[str] = field(default_factory=list)
    # Forensic trace (spec §10): the partial PlanSimulationResult each
    # cancelled branch had produced at the moment it was interrupted --
    # e.g. which actions it had already recorded -- kept separately from
    # `branches` (which only ever holds branches that ran to a genuine
    # conclusion) so a debugger can see exactly how far a cancelled
    # branch got without that partial data being mistaken for a real,
    # complete branch outcome.
    cancelled_branch_partial_results: dict = field(default_factory=dict)


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


async def run_bounded_branches_async(
    plan: AgentPlan, *, filesystem_root: Path | None = None, live_world_state: WorldState | None = None,
    budget_ledger=None, force_branch: bool = False, on_action_start=None,
) -> BranchedSimulationResult:
    """
    Phase 11.2: genuinely CONCURRENT branch execution using
    `asyncio.TaskGroup` (structured concurrency -- every child task is
    owned by the group; there is no detached/fire-and-forget
    `create_task()` anywhere here). When the enclosing task running this
    coroutine is cancelled, `TaskGroup.__aexit__` cancels EVERY branch
    task still running, awaits all of them to actually finish (never
    returns with a child still pending), and only then re-raises
    `CancelledError` -- which this function catches to build a
    structured, honest `BranchedSimulationResult` instead of propagating
    a bare exception.

    `force_branch` (test/caller-driven, since the real "does this need a
    second branch" judgment in `run_bounded_branches()` depends on the
    FIRST branch's own outcome -- inherently sequential, and therefore
    unusable for a genuinely concurrent launch): when True, both branches
    are launched together upfront rather than one waiting on the other's
    result. This is a disclosed, deliberate difference from the
    sequential `run_bounded_branches()`'s outcome-based decision -- used
    when a caller already knows both branches are worth running
    concurrently (e.g. this module's own cancellation tests).

    `on_action_start(label, action_id)` (optional): forwarded per-branch
    into `simulate_plan_async()` -- lets a caller/test prove genuine
    concurrent activity (e.g. via per-branch `asyncio.Event`s) before
    triggering cancellation.
    """
    import asyncio

    granted = _reserve_branch_budget(budget_ledger, min(2, MAX_SIMULATION_BRANCHES))
    if granted < 1:
        return BranchedSimulationResult(branches=[], worst_case_verdict=SimulationVerdict.INCONCLUSIVE, critical_uncertainty="simulation budget exhausted before any branch could run")

    want_two = force_branch and granted >= 2 and len(plan.actions) > 1
    truncated_plan = AgentPlan(plan_id=plan.plan_id, tasks=plan.tasks, actions=plan.actions[:-1]) if want_two else None

    def _hook_for(label: BranchLabel):
        if on_action_start is None:
            return None
        async def _hook(action_id: str) -> None:
            await on_action_start(label, action_id)
        return _hook

    tasks: dict[BranchLabel, "asyncio.Task"] = {}
    partial_results: dict = {}
    cancelled = False
    try:
        async with asyncio.TaskGroup() as tg:
            tasks[BranchLabel.EXPECTED_SUCCESS] = tg.create_task(
                simulate_plan_async(plan, filesystem_root=filesystem_root, live_world_state=live_world_state, on_action_start=_hook_for(BranchLabel.EXPECTED_SUCCESS)),
                name="branch-EXPECTED_SUCCESS",
            )
            if want_two:
                tasks[BranchLabel.EXPECTED_FAILURE] = tg.create_task(
                    simulate_plan_async(truncated_plan, filesystem_root=filesystem_root, live_world_state=live_world_state, on_action_start=_hook_for(BranchLabel.EXPECTED_FAILURE)),
                    name="branch-EXPECTED_FAILURE",
                )
    except asyncio.CancelledError:
        cancelled = True

    branches: list[BranchOutcome] = []
    completed_ids, cancelled_ids, active_at_cancel = [], [], []
    for label, task in tasks.items():
        if task.cancelled():
            # The task's own asyncio.CancelledError propagated all the
            # way out (never internally caught) -- a "hard" cancellation.
            cancelled_ids.append(label.value)
            active_at_cancel.append(label.value)
            continue
        exc = task.exception() if task.done() else None
        if exc is not None:
            raise exc  # a genuine, non-cancellation error must never be swallowed
        result = task.result()
        # simulate_plan_async() catches its OWN CancelledError internally
        # (matching orca.agent.runtime.AgentRuntime.execute_async()'s
        # established pattern) and returns a normal, structured result
        # rather than propagating -- so a branch interrupted mid-flight
        # shows up here as a "completed" task whose OWN result honestly
        # reports the interruption (INCONCLUSIVE + a cancellation
        # block_reason), never a silent PASS. Classify it as cancelled
        # for THIS function's own bookkeeping so callers/tests see the
        # real outcome, not an artifact of where the CancelledError was
        # actually caught.
        was_internally_cancelled = result.aggregate_verdict == SimulationVerdict.INCONCLUSIVE and any("cancel" in r.lower() for r in result.block_reasons)
        if was_internally_cancelled:
            cancelled_ids.append(label.value)
            active_at_cancel.append(label.value)
            partial_results[label.value] = result
            continue
        completed_ids.append(label.value)
        branches.append(BranchOutcome(label=label, result=result))

    all_resources = [{e.resource for e in b.result.aggregate_effects} for b in branches]
    shared = set.intersection(*all_resources) if all_resources else set()
    divergent = set.union(*all_resources) - shared if all_resources else set()

    worst_case = SimulationVerdict.INCONCLUSIVE if cancelled else SimulationVerdict.PASS
    for candidate in _VERDICT_PRECEDENCE:
        if any(b.result.aggregate_verdict == candidate for b in branches):
            worst_case = candidate
            break

    return BranchedSimulationResult(
        branches=branches, shared_effect_resources=sorted(shared), divergent_effect_resources=sorted(divergent),
        worst_case_verdict=worst_case, branch_count=len(branches), cancelled=cancelled,
        active_branch_ids_at_cancel=active_at_cancel, completed_branch_ids=completed_ids, cancelled_branch_ids=cancelled_ids,
        cancelled_branch_partial_results=partial_results,
    )
