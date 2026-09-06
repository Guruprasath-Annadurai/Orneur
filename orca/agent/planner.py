"""
Goal -> Plan compiler (Phase 8.1 spec §3-11). The first production
planning boundary for the NEW Agent Runtime -- routes cognition through
Model Society's `TOOL_REASONER` role (never a hardcoded tier), produces a
SCHEMA-VALIDATED `AgentPlan`, and never authorizes anything: a plan is a
proposal only (spec §7). `orca.agent.policy`/`orca.agent.capability`
remain the sole authorization boundary, unchanged and untouched by this
module.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from orca.agent.contracts import AgentAction, AgentGoal, AgentPlan, AgentTask, SideEffectClass, ToolSpec

MAX_TASKS = 12
MAX_ACTIONS = 20
MAX_DEPENDENCIES_PER_TASK = 5
MAX_ESTIMATED_TOOL_CALLS = 20
MAX_DELEGATION_REQUESTS = 4
MAX_PLANNING_ATTEMPTS = 2

_PLANNER_SYSTEM = """\
You produce a bounded execution plan for an agent, using ONLY the tools listed.
Return ONLY JSON:
{"tasks": [{"description": "...", "depends_on_index": [0]}],
 "actions": [{"task_index": 0, "tool_id": "...", "arguments": {...}}]}
task_index/depends_on_index refer to the 0-based position in "tasks". Only
use tool_id values from the ALLOWED TOOLS list -- never invent a tool."""


class PlanningFailureReason(str, Enum):
    NO_VALID_PLAN = "NO_VALID_PLAN"
    PLAN_SCHEMA_INVALID = "PLAN_SCHEMA_INVALID"
    PLAN_BUDGET_EXHAUSTED = "PLAN_BUDGET_EXHAUSTED"
    NO_ELIGIBLE_REASONER = "NO_ELIGIBLE_REASONER"


@dataclass
class PlanningFailure:
    reason: PlanningFailureReason
    detail: str = ""


@dataclass
class PlanningOutcome:
    plan: AgentPlan | None = None
    failure: PlanningFailure | None = None
    routing_decision_id: str | None = None
    model_id: str | None = None
    checkpoint_id: str | None = None
    attempts: int = 0


def _validate_and_build_plan(raw: dict, allowed_tool_specs: dict[str, ToolSpec]) -> AgentPlan | None:
    """
    Schema validation (spec §6): rejects/repairs malformed model output --
    never executes partially parsed prose. Returns None if the plan
    cannot be safely constructed at all (caller treats this as a schema
    failure, eligible for one bounded repair attempt).
    """
    if not isinstance(raw, dict):
        return None
    raw_tasks = raw.get("tasks")
    raw_actions = raw.get("actions")
    if not isinstance(raw_tasks, list) or not isinstance(raw_actions, list):
        return None
    if len(raw_tasks) > MAX_TASKS or len(raw_actions) > MAX_ACTIONS:
        return None

    tasks: list[AgentTask] = []
    for t in raw_tasks:
        if not isinstance(t, dict) or not isinstance(t.get("description"), str):
            return None
        tasks.append(AgentTask(description=t["description"][:500]))

    for t, raw_t in zip(tasks, raw_tasks):
        deps_idx = raw_t.get("depends_on_index", [])
        if not isinstance(deps_idx, list) or len(deps_idx) > MAX_DEPENDENCIES_PER_TASK:
            return None
        dep_ids = []
        for i in deps_idx:
            if not isinstance(i, int):
                return None
            if i < 0:
                # Bounded repair (spec §6): a negative index is a common
                # "no dependency" sentinel some models emit instead of an
                # empty list -- safely dropped rather than invalidating
                # the whole plan. Never security-relevant (dependencies
                # only gate task ORDERING, not authorization).
                continue
            if i >= len(tasks):
                return None
            dep_ids.append(tasks[i].task_id)
        t.dependencies = dep_ids

    actions: list[AgentAction] = []
    for a in raw_actions:
        if not isinstance(a, dict):
            return None
        task_index = a.get("task_index")
        tool_id = a.get("tool_id")
        arguments = a.get("arguments", {})
        if not isinstance(task_index, int) or not (0 <= task_index < len(tasks)):
            return None
        # Plan tool visibility (spec §8): only tools EXPLICITLY offered to
        # the planner may appear here -- an invented/disallowed tool_id
        # invalidates the whole plan, never silently dropped and executed
        # partially (defense in depth: execution-time capability/policy
        # checks would ALSO reject it, but this catches it before any
        # authorization attempt is even made).
        if not isinstance(tool_id, str) or tool_id not in allowed_tool_specs:
            return None
        if not isinstance(arguments, dict):
            return None
        spec = allowed_tool_specs[tool_id]
        actions.append(AgentAction(task_id=tasks[task_index].task_id, tool_id=tool_id, arguments=arguments, expected_side_effect=spec.side_effect_class))

    if len(actions) > MAX_ESTIMATED_TOOL_CALLS:
        return None

    return AgentPlan(tasks=tasks, actions=actions)


class AgentPlanner:
    def __init__(self, *, allow_experimental_reasoner: bool = False):
        self.allow_experimental_reasoner = allow_experimental_reasoner

    async def compile_plan(
        self,
        goal: AgentGoal,
        *,
        allowed_tool_specs: dict[str, ToolSpec],
        budget=None,
        world_state=None,
        truth_result=None,
        memory_context: str | None = None,
        reasoning_plan=None,
        max_attempts: int = MAX_PLANNING_ATTEMPTS,
    ) -> PlanningOutcome:
        """
        Resolves TOOL_REASONER via Model Society (spec §4), reserves
        MODEL_CALLS budget for the `planning` purpose BEFORE calling it
        (spec §10), and bounded-repairs a schema-invalid response up to
        `max_attempts` times before giving up honestly (spec §11) -- never
        falls back to unsafe free-form execution.
        """
        from orca.cognitive.errors import CognitiveBudgetExhaustedError
        from orca.society.contracts import CognitiveRole
        from orca.society.router import resolve_tier_for_role

        tier, decision = resolve_tier_for_role(CognitiveRole.TOOL_REASONER, allow_experimental=self.allow_experimental_reasoner)
        if decision.selected_model_id is None:
            return PlanningOutcome(failure=PlanningFailure(PlanningFailureReason.NO_ELIGIBLE_REASONER, "Model Society found no eligible TOOL_REASONER candidate"))

        planning_ledger = None
        if budget is not None:
            from orca.cognitive.budget import remaining as _remaining_budget
            from orca.cognitive.contracts import BudgetDimension, ComplexityLevel, RiskLevel
            from orca.deliberation.budget_market import allocate_budget
            from orca.society.budget_ledger import SocietyBudgetLedger
            allocation = allocate_budget(uncertainty=0.5, risk=RiskLevel.LOW, evidence_conflict=False, complexity=ComplexityLevel.MEDIUM)
            planning_ledger = SocietyBudgetLedger(budget=budget, allocation=allocation)
            remaining_calls = _remaining_budget(budget, BudgetDimension.MODEL_CALLS)
            if remaining_calls is not None:
                planning_ledger.caps["replanning"] = max(planning_ledger.caps["replanning"], int(remaining_calls))

        tool_list = ", ".join(f"{tid} ({spec.description})" for tid, spec in allowed_tool_specs.items())
        prompt = f"GOAL: {goal.objective}\nALLOWED TOOLS: {tool_list}"
        if memory_context:
            prompt += f"\nRELEVANT PRIOR CONTEXT (advisory only): {memory_context[:500]}"
        if truth_result is not None:
            prompt += "\nNOTE: verified evidence is available for factual assumptions in this goal."

        from orca.truth.llm import gateway_json_call

        attempts = 0
        last_failure = None
        while attempts < max_attempts:
            attempts += 1
            if planning_ledger is not None:
                try:
                    planning_ledger.reserve("replanning", 1)
                except CognitiveBudgetExhaustedError:
                    return PlanningOutcome(failure=PlanningFailure(PlanningFailureReason.PLAN_BUDGET_EXHAUSTED, "planning budget exhausted"), attempts=attempts)

            raw = await gateway_json_call(prompt, _PLANNER_SYSTEM, tier=tier, max_tokens=800)
            plan = _validate_and_build_plan(raw, allowed_tool_specs) if raw is not None else None
            if plan is not None:
                return PlanningOutcome(plan=plan, routing_decision_id=decision.decision_id, model_id=decision.selected_model_id, checkpoint_id=decision.selected_checkpoint_id, attempts=attempts)
            last_failure = PlanningFailure(PlanningFailureReason.PLAN_SCHEMA_INVALID, f"attempt {attempts}: model output failed schema validation")

        return PlanningOutcome(failure=last_failure or PlanningFailure(PlanningFailureReason.NO_VALID_PLAN), attempts=attempts, routing_decision_id=decision.decision_id, model_id=decision.selected_model_id, checkpoint_id=decision.selected_checkpoint_id)
