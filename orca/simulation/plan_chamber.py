"""
Multi-action AgentPlan simulation (Phase 11.1 spec §2-11). Real bounded
simulation of an AgentPlan's actions IN DEPENDENCY ORDER, with each
action's projected effects feeding the next action's simulated
starting state (spec §4) -- never each action simulated independently
against the original live state.

The real WorldState is NEVER touched -- only a projected copy
(`orca.simulation.worldstate_projection`) accumulates predicted changes
across the whole plan, exactly as Phase 11's single-action chamber
already guaranteed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from orca.agent.contracts import AgentPlan
from orca.deliberation.contracts import WorldState
from orca.simulation.contracts import (
    Assumption,
    BlastRadius,
    CompensationPlan,
    PredictedEffect,
    Reversibility,
    SimulationVerdict,
    _new_id,
)
from orca.simulation.filesystem_sim import apply_action_to_sandbox, open_sandbox
from orca.simulation.integrity import apply_plan_result_signature
from orca.simulation.worldstate_projection import project_worldstate

MAX_SIMULATION_ACTIONS = 5    # spec §6: hard bound, checked BEFORE simulation begins
MAX_SIMULATION_BRANCHES = 2   # spec §13: enforced in branching.py

_BLAST_RADIUS_RANK = {
    BlastRadius.SINGLE_OBJECT: 0, BlastRadius.MULTIPLE_OBJECTS: 1, BlastRadius.WORKSPACE_OR_PROJECT: 2,
    BlastRadius.TENANT: 3, BlastRadius.EXTERNAL_RECIPIENTS: 4, BlastRadius.PRODUCTION_SYSTEM: 5, BlastRadius.UNKNOWN: 3,
}
_REVERSIBILITY_RANK = {Reversibility.REVERSIBLE: 0, Reversibility.COMPENSATABLE: 1, Reversibility.UNKNOWN: 2, Reversibility.IRREVERSIBLE: 3}
_VERDICT_PRECEDENCE = [SimulationVerdict.BLOCK, SimulationVerdict.INCONCLUSIVE, SimulationVerdict.REVISE, SimulationVerdict.PASS_WITH_WARNINGS, SimulationVerdict.PASS]


class PlanDependencyError(ValueError):
    """Cycle or invalid/missing dependency reference -- fails
    structurally, never silently falls back to list order."""


@dataclass
class PlanActionOutcome:
    action_id: str
    task_id: str
    status: str                     # "SIMULATED" | "BLOCKED_BY_DEPENDENCY" | "REJECTED_OVER_BOUND"
    verdict: SimulationVerdict | None = None
    predicted_effects: list[PredictedEffect] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    block_reasons: list[str] = field(default_factory=list)


@dataclass
class PlanSimulationResult:
    plan_simulation_id: str = field(default_factory=lambda: _new_id("plansim"))
    plan_id: str = ""
    action_order: list[str] = field(default_factory=list)
    per_action: list[PlanActionOutcome] = field(default_factory=list)
    projected_world_state: WorldState = field(default_factory=WorldState)
    aggregate_effects: list[PredictedEffect] = field(default_factory=list)
    aggregate_assumptions: list[Assumption] = field(default_factory=list)
    aggregate_warnings: list[str] = field(default_factory=list)
    aggregate_verdict: SimulationVerdict = SimulationVerdict.INCONCLUSIVE
    aggregate_blast_radius: BlastRadius = BlastRadius.UNKNOWN
    aggregate_reversibility: Reversibility = Reversibility.UNKNOWN
    compensation_chain: list[CompensationPlan] = field(default_factory=list)
    partial: bool = False
    block_reasons: list[str] = field(default_factory=list)
    result_hash: str = ""

    def can_proceed(self) -> bool:
        return self.aggregate_verdict in (SimulationVerdict.PASS, SimulationVerdict.PASS_WITH_WARNINGS)


def _topological_order(plan: AgentPlan) -> list:
    """Kahn's algorithm over `AgentTask.dependencies`. Raises
    `PlanDependencyError` on a cycle or a dependency referencing a
    task_id not present in the plan -- fails structurally, spec §3."""
    task_ids = {t.task_id for t in plan.tasks}
    for task in plan.tasks:
        for dep in task.dependencies:
            if dep not in task_ids:
                raise PlanDependencyError(f"task {task.task_id!r} depends on unknown task {dep!r}")

    in_degree = {t.task_id: len(t.dependencies) for t in plan.tasks}
    dependents: dict[str, list[str]] = {t.task_id: [] for t in plan.tasks}
    for t in plan.tasks:
        for dep in t.dependencies:
            dependents[dep].append(t.task_id)

    ready = [tid for tid, deg in in_degree.items() if deg == 0]
    ordered_task_ids = []
    while ready:
        ready.sort()  # deterministic order among independent tasks
        tid = ready.pop(0)
        ordered_task_ids.append(tid)
        for dependent in dependents[tid]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                ready.append(dependent)

    if len(ordered_task_ids) != len(plan.tasks):
        raise PlanDependencyError("dependency cycle detected among plan tasks")

    task_order_index = {tid: i for i, tid in enumerate(ordered_task_ids)}
    return sorted(plan.actions, key=lambda a: task_order_index.get(a.task_id, len(ordered_task_ids)))


def _aggregate_blast_radius(effects: list[PredictedEffect]) -> BlastRadius:
    if not effects:
        return BlastRadius.UNKNOWN
    worst = max(effects, key=lambda e: _BLAST_RADIUS_RANK[e.blast_radius]).blast_radius
    distinct_resources = {e.resource for e in effects}
    if worst == BlastRadius.SINGLE_OBJECT and len(distinct_resources) > 1:
        return BlastRadius.MULTIPLE_OBJECTS  # spec §9: escalate, never just take the first action's radius
    return worst


def _aggregate_reversibility(effects: list[PredictedEffect]) -> Reversibility:
    if not effects:
        return Reversibility.UNKNOWN
    return max(effects, key=lambda e: _REVERSIBILITY_RANK[e.reversibility]).reversibility


def _aggregate_verdict(per_action: list[PlanActionOutcome], partial: bool) -> SimulationVerdict:
    verdicts = [o.verdict for o in per_action if o.verdict is not None]
    if any(o.status == "BLOCKED_BY_DEPENDENCY" for o in per_action) or any(o.status == "REJECTED_OVER_BOUND" for o in per_action):
        verdicts.append(SimulationVerdict.BLOCK if any(o.status == "REJECTED_OVER_BOUND" for o in per_action) else SimulationVerdict.INCONCLUSIVE)
    if not verdicts:
        return SimulationVerdict.INCONCLUSIVE
    for candidate in _VERDICT_PRECEDENCE:
        if candidate in verdicts:
            return candidate
    return SimulationVerdict.INCONCLUSIVE


def _simulate_one_action(action, task, blocked_task_ids: set, sandbox_root, projected_ws):
    """
    Pure-ish per-action step shared by the sync and async entry points --
    returns `(PlanActionOutcome, new_projected_ws)`; mutates
    `blocked_task_ids` in place (the one piece of loop-carried state that
    isn't naturally returned). Factored out so `simulate_plan()` and
    `simulate_plan_async()` run the EXACT SAME per-action logic, never
    two copies that could silently drift apart.
    """
    from orca.simulation.contracts import SimulationAction

    if task is not None and any(dep in blocked_task_ids for dep in task.dependencies):
        blocked_task_ids.add(task.task_id)
        return PlanActionOutcome(action_id=action.action_id, task_id=action.task_id, status="BLOCKED_BY_DEPENDENCY", block_reasons=["a dependency's simulation was BLOCKed -- not simulated as if it had succeeded"]), projected_ws

    sim_action = SimulationAction(action_id=action.action_id, tool_id=action.tool_id, arguments=action.arguments, resource_scope=action.arguments.get("resource_scope", action.tool_id), operation_scope=action.arguments.get("operation_scope", action.tool_id))

    if sandbox_root is not None and "operation" in action.arguments:
        outcome = apply_action_to_sandbox(sandbox_root=sandbox_root, action=sim_action)
        if outcome.blocked:
            blocked_task_ids.add(action.task_id)
            return PlanActionOutcome(action_id=action.action_id, task_id=action.task_id, status="SIMULATED", verdict=SimulationVerdict.BLOCK, block_reasons=[outcome.block_reason or "blocked"]), projected_ws
        warnings = [f"predicted effect on {e.resource!r} is IRREVERSIBLE" for e in outcome.predicted_effects if e.reversibility == Reversibility.IRREVERSIBLE]
        verdict = SimulationVerdict.PASS_WITH_WARNINGS if warnings else SimulationVerdict.PASS
        new_ws = project_worldstate(projected_ws, source_action_id=action.action_id, predicted_effects=outcome.predicted_effects, assumption_ids=[a.assumption_id for a in outcome.assumptions]).projected_state
        return PlanActionOutcome(action_id=action.action_id, task_id=action.task_id, status="SIMULATED", verdict=verdict, predicted_effects=outcome.predicted_effects, warnings=warnings), new_ws

    return PlanActionOutcome(action_id=action.action_id, task_id=action.task_id, status="SIMULATED", verdict=SimulationVerdict.INCONCLUSIVE, warnings=["no sandbox/preview mechanism was wired for this action"]), projected_ws


def _finalize(result: PlanSimulationResult, projected_ws) -> PlanSimulationResult:
    result.projected_world_state = projected_ws
    result.aggregate_blast_radius = _aggregate_blast_radius(result.aggregate_effects)
    result.aggregate_reversibility = _aggregate_reversibility(result.aggregate_effects)
    result.aggregate_verdict = _aggregate_verdict(result.per_action, result.partial)

    for effect in result.aggregate_effects:
        if effect.reversibility == Reversibility.COMPENSATABLE:
            result.compensation_chain.append(CompensationPlan(
                original_effect_id=effect.effect_id, compensating_action_description=f"inverse of {effect.effect_type.value} on {effect.resource}",
                preconditions=["prior effects in the plan remain applied", "target resource not modified by an unrelated actor since simulation"],
                limitations=["not atomic rollback -- each compensation is a best-effort proposal, not a guarantee"],
            ))
        elif effect.reversibility == Reversibility.IRREVERSIBLE:
            result.compensation_chain.append(CompensationPlan(
                original_effect_id=effect.effect_id, compensating_action_description="none -- effect is irreversible",
                limitations=[f"no compensating action exists for the {effect.effect_type.value} on {effect.resource!r}"],
            ))
    return apply_plan_result_signature(result)


def _prepare(plan: AgentPlan) -> tuple[PlanSimulationResult | None, list]:
    """Shared setup: dependency ordering + MAX_SIMULATION_ACTIONS bound.
    Returns `(early_result, ordered_actions)` -- `early_result` is
    non-None (and the caller should return it immediately, signed) if
    simulation cannot even begin."""
    result = PlanSimulationResult(plan_id=plan.plan_id)
    try:
        ordered_actions = _topological_order(plan)
    except PlanDependencyError as e:
        result.aggregate_verdict = SimulationVerdict.BLOCK
        result.block_reasons = [str(e)]
        return apply_plan_result_signature(result), []

    if len(ordered_actions) > MAX_SIMULATION_ACTIONS:
        result.partial = True
        result.block_reasons.append(f"plan has {len(ordered_actions)} actions, exceeding MAX_SIMULATION_ACTIONS={MAX_SIMULATION_ACTIONS} -- rejected, never silently truncated and reported as full-plan PASS")
        result.aggregate_verdict = SimulationVerdict.BLOCK
        return apply_plan_result_signature(result), []

    return None, ordered_actions


def simulate_plan(plan: AgentPlan, *, filesystem_root: Path | None = None, live_world_state: WorldState | None = None) -> PlanSimulationResult:
    """
    Real bounded multi-action simulation. `filesystem_root` (optional):
    when given, every action whose `arguments` contains an `operation`
    key is simulated against ONE shared sandbox for the whole plan (spec
    §4's projected-state-chain requirement); actions without a
    filesystem shape are recorded as `SIMULATED` with no filesystem
    effect (out of this function's real-mechanism scope, matching the
    single-action chamber's own honesty about unavailable mechanisms).

    Synchronous entry point -- thin wrapper preserved for existing
    callers/tests. See `simulate_plan_async()` for the real, genuinely
    cancellable implementation this delegates to.
    """
    import asyncio
    return asyncio.run(simulate_plan_async(plan, filesystem_root=filesystem_root, live_world_state=live_world_state))


async def simulate_plan_async(
    plan: AgentPlan, *, filesystem_root: Path | None = None, live_world_state: WorldState | None = None,
    budget_ledger=None, cancellation_check=None,
) -> PlanSimulationResult:
    """
    Real async entry point (Phase 11.1 spec §26). A cooperative
    cancellation checkpoint (`await asyncio.sleep(0)`) runs BETWEEN each
    action -- a caller's `task.cancel()` genuinely interrupts here.
    Honest limitation (spec §33): the per-action filesystem work itself
    (`apply_action_to_sandbox`) is synchronous, fast, real disk I/O --
    Python cannot abort a blocking filesystem call mid-syscall, so an
    action that has already STARTED always finishes; cancellation takes
    effect before the NEXT action begins, never mid-write. This is
    documented behavior, not a limitation this function pretends not to
    have.

    On cancellation: caught internally (never re-raised, matching
    `orca.agent.runtime.AgentRuntime.execute_async()`'s own established
    pattern) -- returns a structured result with
    `aggregate_verdict=INCONCLUSIVE`, the actions already recorded kept
    exactly as they are (never retroactively marked as if they hadn't
    run), and remaining actions never started. Unused budget reservations
    for actions that never began are never taken in the first place
    (this function reserves ONE unit per action actually attempted, not
    up front for the whole plan) -- see `_reserve_action_budget()`.
    """
    import asyncio

    early_result, ordered_actions = _prepare(plan)
    if early_result is not None:
        return early_result

    result = PlanSimulationResult(plan_id=plan.plan_id)
    live_ws = live_world_state or WorldState()
    projected_ws = live_ws
    task_map = {t.task_id: t for t in plan.tasks}
    blocked_task_ids: set[str] = set()
    cancelled = False

    sandbox_ctx = open_sandbox(filesystem_root) if filesystem_root is not None else None
    sandbox_root = sandbox_ctx.__enter__() if sandbox_ctx is not None else None
    try:
        for action in ordered_actions:
            try:
                await asyncio.sleep(0)  # cooperative cancellation checkpoint, spec §26/§29
                if cancellation_check is not None and cancellation_check():
                    cancelled = True
                    break
            except asyncio.CancelledError:
                cancelled = True
                break

            if not _reserve_action_budget(budget_ledger):
                result.block_reasons.append(f"simulation budget exhausted before action {action.action_id} could be simulated")
                break

            result.action_order.append(action.action_id)
            task = task_map.get(action.task_id)
            outcome, projected_ws = _simulate_one_action(action, task, blocked_task_ids, sandbox_root, projected_ws)
            result.per_action.append(outcome)
            result.aggregate_effects.extend(outcome.predicted_effects)
            result.aggregate_warnings.extend(outcome.warnings)
    finally:
        if sandbox_ctx is not None:
            sandbox_ctx.__exit__(None, None, None)

    result = _finalize(result, projected_ws)
    if cancelled:
        result.aggregate_verdict = SimulationVerdict.INCONCLUSIVE
        result.block_reasons.append("simulation cancelled -- partial result, remaining actions never started")
        result = apply_plan_result_signature(result)

    # Live WorldState was NEVER touched -- verified structurally: this
    # function never calls apply_update() against `live_world_state`
    # itself, only against copies made by project_worldstate().
    assert projected_ws is not live_ws or live_world_state is None

    return result


def _reserve_action_budget(budget_ledger) -> bool:
    """One reservation per action ACTUALLY attempted -- never a single
    upfront reservation for the whole plan (spec §32: unused reservations
    for actions that never began are never taken, so there is nothing to
    'release' for them; only consumed reservations for actions that did
    run are ever real)."""
    if budget_ledger is None:
        return True
    from orca.cognitive.errors import CognitiveBudgetExhaustedError
    try:
        budget_ledger.reserve("simulation_operations", 1)
        return True
    except CognitiveBudgetExhaustedError:
        return False
