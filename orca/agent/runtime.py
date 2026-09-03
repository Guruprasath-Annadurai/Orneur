"""
Agent Runtime execution loop (Phase 8 spec §1, §7, §13, §20, §24-27).
Canonical flow, never model->tool direct (spec §13):

  ActionRequest -> capability check -> policy check -> budget reservation
  -> execution -> result validation -> Observation -> WorldState update

PLAN -> AUTHORIZE -> EXECUTE -> OBSERVE -> UPDATE WORLD STATE -> VERIFY
-> REPLAN IF REQUIRED -> STOP, bounded by MAX_AGENT_REPLANS, a deadline,
and the shared CognitiveBudget (via SocietyBudgetLedger's `tool_execution`
purpose, TOOL_CALLS dimension -- never MODEL_CALLS, per Phase 7.2's
dimension discipline).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from orca.agent.capability import check_capabilities
from orca.agent.contracts import (
    ActionAuthorization,
    ActionRequest,
    AgentAction,
    AgentGoal,
    AgentPlan,
    AgentRun,
    AgentRunStatus,
    AgentTask,
    AgentTrace,
    Capability,
    ExecutionStopReason,
    Observation,
    ObservationTrustClass,
    PolicyDecisionState,
    SideEffectClass,
    TaskStatus,
    ToolInvocation,
)
from orca.agent.policy import evaluate_policy
from orca.agent.tool_registry import AgentToolRegistry
from orca.cognitive.contracts import CognitiveBudget
from orca.cognitive.errors import CognitiveBudgetExhaustedError
from orca.deliberation.contracts import WorldState
from orca.deliberation.worldstate_ops import WorldStateOp, WorldStateUpdate, apply_update

MAX_AGENT_REPLANS = 2

# Exception class names treated as transient (spec §26) -- a real,
# bounded classification, never a blind "retry everything." Permission/
# schema/destructive-policy denials are never in this set.
_TRANSIENT_ERROR_CLASSES = {"TimeoutError", "ConnectionError", "TimeoutExpired"}
_MAX_ACTION_RETRIES = 1


@dataclass
class ReplanTrigger:
    task_id: str
    reason: str


class AgentRuntime:
    def __init__(
        self,
        *,
        registry: AgentToolRegistry,
        goal: AgentGoal,
        capabilities: frozenset[Capability],
        budget: CognitiveBudget | None = None,
        deadline_s: float = 120.0,
        replan_fn=None,
    ):
        """
        `replan_fn`, when given, is called as
        `replan_fn(plan, failed_task, world_state) -> AgentPlan | None`
        to produce a LOCAL revision (spec §25's "prefer local revisions")
        after a bounded, classified failure -- returning None means no
        revision is possible and the run stops honestly. Never regenerates
        the whole strategy by default; callers that want that pass a
        `replan_fn` that does so explicitly.
        """
        self.registry = registry
        self.goal = goal
        self.capabilities = capabilities
        self.budget = budget
        self.deadline_s = deadline_s
        self.replan_fn = replan_fn
        self._idempotency_seen: set[str] = set()

        self.ledger = None
        if budget is not None:
            from orca.cognitive.budget import remaining as _remaining_budget
            from orca.cognitive.contracts import BudgetDimension, ComplexityLevel, RiskLevel
            from orca.deliberation.budget_market import allocate_budget
            from orca.society.budget_ledger import SocietyBudgetLedger
            allocation = allocate_budget(uncertainty=0.5, risk=RiskLevel.LOW, evidence_conflict=False, complexity=ComplexityLevel.MEDIUM)
            self.ledger = SocietyBudgetLedger(budget=budget, allocation=allocation)
            # tool_execution is effectively the sole TOOL_CALLS consumer
            # within one AgentRuntime run's own scope -- same reasoning,
            # and the same premature-exhaustion bug class, as Phase 7.2's
            # "verification"/"retrieval" cap fixes (see BUDGET_EXECUTION.md).
            remaining_tool_calls = _remaining_budget(budget, BudgetDimension.TOOL_CALLS)
            if remaining_tool_calls is not None:
                self.ledger.caps["tool_execution"] = max(self.ledger.caps["tool_execution"], int(remaining_tool_calls))

    def _authorize(self, action: AgentAction) -> tuple[ActionAuthorization, object]:
        spec = self.registry.get_spec(action.tool_id)
        if spec is None:
            return ActionAuthorization(authorized=False), None
        cap_decision = check_capabilities(self.capabilities, spec)
        policy_decision = evaluate_policy(
            goal=self.goal, tool_spec=spec, capability_decision=cap_decision,
            resolved_side_effect_class=action.expected_side_effect,
        )
        auth = ActionAuthorization(
            decision=policy_decision, capability_decision=cap_decision,
            authorized=policy_decision.state in (PolicyDecisionState.ALLOW, PolicyDecisionState.ALLOW_WITH_RESTRICTIONS),
        )
        return auth, spec

    def _to_observation(self, action: AgentAction, tool_result) -> Observation:
        if tool_result.success:
            facts = [tool_result.output[:2000]]
            status = "OK"
            error = None
        else:
            facts = []
            status = "ERROR"
            error = tool_result.output[:500]
        return Observation(
            action_id=action.action_id, source=action.tool_id, facts=facts, status=status,
            error=error, trust_class=ObservationTrustClass.SYSTEM_VERIFIED,
        )

    def _apply_observation(self, world_state: WorldState, action: AgentAction, observation: Observation) -> None:
        """Only typed operations mutate WorldState (spec §22) -- an
        observation's raw text becomes a fact tagged with the tool as its
        source_ref, never asserted without provenance."""
        if observation.status == "OK" and observation.facts:
            apply_update(
                world_state,
                WorldStateUpdate(op=WorldStateOp.ADD_OBSERVATION, value=observation.facts[0][:500], source_ref=f"tool:{action.tool_id}:{action.action_id}"),
            )
            observation.world_state_changes.append(f"ADD_OBSERVATION:tool:{action.tool_id}")

    def execute(self, plan: AgentPlan, world_state: WorldState | None = None) -> tuple[AgentRun, AgentTrace, WorldState]:
        run = AgentRun(goal=self.goal, capabilities=self.capabilities, deadline_s=self.deadline_s, status=AgentRunStatus.RUNNING)
        trace = AgentTrace(run_id=run.run_id)
        world_state = world_state or WorldState()
        trace.world_state_ids.append(world_state.world_state_id)

        start = time.monotonic()
        task_map: dict[str, AgentTask] = {t.task_id: t for t in plan.tasks}
        actions = list(plan.actions)
        replans_used = 0

        idx = 0
        while idx < len(actions):
            if time.monotonic() - start > self.deadline_s:
                run.status = AgentRunStatus.FAILED
                run.stop_reason = ExecutionStopReason.TIMEOUT
                break

            action = actions[idx]
            task = task_map.get(action.task_id)
            trace.action_ids.append(action.action_id)

            if task is not None and any(
                task_map[dep].status not in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
                for dep in task.dependencies if dep in task_map
            ):
                task.status = TaskStatus.BLOCKED
                run.blocked_task_ids.append(task.task_id)
                idx += 1
                continue

            auth, spec = self._authorize(action)
            trace.authorization_ids.append(auth.authorization_id)

            if spec is None:
                if task is not None:
                    task.status = TaskStatus.FAILED
                run.stop_reason = ExecutionStopReason.DEPENDENCY_FAILED
                idx += 1
                continue

            if not auth.capability_decision.granted:
                if task is not None:
                    task.status = TaskStatus.FAILED
                run.status = AgentRunStatus.PARTIAL
                run.stop_reason = ExecutionStopReason.CAPABILITY_MISSING
                idx += 1
                continue

            if auth.decision.state == PolicyDecisionState.DENY:
                if task is not None:
                    task.status = TaskStatus.FAILED
                run.status = AgentRunStatus.PARTIAL
                run.stop_reason = ExecutionStopReason.POLICY_DENIED
                idx += 1
                continue

            if auth.decision.state == PolicyDecisionState.REQUIRE_APPROVAL:
                if task is not None:
                    task.status = TaskStatus.BLOCKED
                    run.blocked_task_ids.append(task.task_id)
                run.status = AgentRunStatus.BLOCKED
                run.stop_reason = ExecutionStopReason.APPROVAL_REQUIRED
                idx += 1
                continue

            # Budget reservation BEFORE execution (spec §13/§45-46).
            reservation = None
            if self.ledger is not None:
                try:
                    reservation = self.ledger.reserve("tool_execution", 1)
                except CognitiveBudgetExhaustedError:
                    run.status = AgentRunStatus.PARTIAL
                    run.stop_reason = ExecutionStopReason.BUDGET_EXHAUSTED
                    if task is not None:
                        task.status = TaskStatus.BLOCKED
                    break

            # Idempotency (spec §27): a non-idempotent tool is never
            # invoked twice for the same key within one run.
            idem_key = f"{action.tool_id}:{sorted(action.arguments.items())}"
            if not spec.idempotent and idem_key in self._idempotency_seen:
                observation = Observation(action_id=action.action_id, source=action.tool_id, status="DEDUPED", facts=["deduplicated -- already executed this run"])
            else:
                invocation = ToolInvocation(tool_id=action.tool_id, arguments=action.arguments, idempotency_key=idem_key)
                tool_result = self.registry.invoke(invocation)
                retries = 0
                while not tool_result.success and tool_result.error_class in _TRANSIENT_ERROR_CLASSES and retries < _MAX_ACTION_RETRIES:
                    retries += 1
                    tool_result = self.registry.invoke(invocation)
                tool_result.retries = retries
                if not spec.idempotent:
                    self._idempotency_seen.add(idem_key)
                trace.tool_invocation_ids.append(invocation.invocation_id)
                observation = self._to_observation(action, tool_result)

            trace.observation_ids.append(observation.observation_id)
            self._apply_observation(world_state, action, observation)

            if observation.status == "ERROR":
                if task is not None:
                    task.status = TaskStatus.FAILED
                if self.replan_fn is not None and replans_used < MAX_AGENT_REPLANS:
                    revised = self.replan_fn(plan, task, world_state)
                    replans_used += 1
                    trace.replan_events.append(f"replan:{replans_used}:{action.tool_id}_failed")
                    if revised is not None:
                        for new_action in revised.actions:
                            if new_action.task_id not in [a.task_id for a in actions[:idx + 1]]:
                                actions.append(new_action)
                                task_map.setdefault(new_action.task_id, AgentTask(task_id=new_action.task_id))
                        idx += 1
                        continue
                run.status = AgentRunStatus.PARTIAL
                run.stop_reason = ExecutionStopReason.TOOL_ERROR
                idx += 1
                continue

            if task is not None:
                task.status = TaskStatus.COMPLETED
                run.completed_task_ids.append(task.task_id)
            idx += 1

        if run.stop_reason is None:
            all_completed = all(t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED) for t in plan.tasks) if plan.tasks else True
            run.status = AgentRunStatus.COMPLETED if all_completed else AgentRunStatus.PARTIAL
            run.stop_reason = ExecutionStopReason.GOAL_ACHIEVED if all_completed else ExecutionStopReason.DEPENDENCY_FAILED

        trace.stop_reason = run.stop_reason.value if run.stop_reason else None
        trace.plan_versions.append(plan.version)
        trace.task_ids = list(task_map.keys())
        return run, trace, world_state
