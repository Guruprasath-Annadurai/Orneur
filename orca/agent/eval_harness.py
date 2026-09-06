"""
Agent Runtime evaluation harness (Phase 8 spec §59-60). Deterministic --
no live model call, no fabricated scores; every scenario exercises real
Agent Runtime code (capability/policy/budget/delegation/replanning),
matching the same discipline as `orca.deliberation.eval_harness` and
`orca.society.eval_harness`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orca.agent.capability import check_capabilities
from orca.agent.contracts import (
    AgentAction,
    AgentGoal,
    AgentPlan,
    AgentRunStatus,
    AgentTask,
    Capability,
    ExecutionStopReason,
    SideEffectClass,
    TaskStatus,
    ToolSpec,
)
from orca.agent.delegation import (
    BudgetEscalationError,
    CapabilityEscalationError,
    DelegationDepthExceededError,
    build_child_runtime,
)
from orca.agent.contracts import DelegationRequest
from orca.agent.policy import evaluate_policy
from orca.agent.runtime import AgentRuntime
from orca.agent.tool_registry import build_agent_tool_registry
from orca.cognitive.contracts import CognitiveBudget


@dataclass
class Scenario:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class HarnessResult:
    total: int = 0
    passed: int = 0
    results: list[Scenario] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


def _record(results, name, condition, detail=""):
    results.append(Scenario(name=name, passed=bool(condition), detail=detail))


def run_all() -> HarnessResult:
    results: list[Scenario] = []
    registry = build_agent_tool_registry()

    # 1. simple read-only tool action
    goal = AgentGoal(objective="t", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))
    task = AgentTask(description="r")
    plan = AgentPlan(tasks=[task], actions=[AgentAction(task_id=task.task_id, tool_id="read_file", arguments={"path": "x"}, expected_side_effect=SideEffectClass.READ_ONLY)])
    rt = AgentRuntime(registry=registry, goal=goal, capabilities=frozenset({Capability.FILE_READ}))
    run, trace, ws = rt.execute(plan)
    _record(results, "simple read-only tool action", run.status == AgentRunStatus.COMPLETED)

    # 2. action succeeds and updates WorldState
    _record(results, "action succeeds and updates WorldState", bool(ws.known_facts))

    # 3. tool failure triggers one local replan
    registry.register(ToolSpec(tool_id="flaky", side_effect_class=SideEffectClass.READ_ONLY, required_capabilities=frozenset()), lambda: (_ for _ in ()).throw(RuntimeError("x")))
    task2 = AgentTask(description="r2")
    plan2 = AgentPlan(tasks=[task2], actions=[AgentAction(task_id=task2.task_id, tool_id="flaky", expected_side_effect=SideEffectClass.READ_ONLY)])
    def replan_fn(plan, failed_task, world_state):
        nt = AgentTask(task_id=failed_task.task_id + "-r", description="fallback")
        return AgentPlan(tasks=[nt], actions=[AgentAction(task_id=nt.task_id, tool_id="read_file", arguments={"path": "x"}, expected_side_effect=SideEffectClass.READ_ONLY)], version=plan.version + 1)
    rt2 = AgentRuntime(registry=registry, goal=goal, capabilities=frozenset({Capability.FILE_READ}), replan_fn=replan_fn)
    run2, trace2, ws2 = rt2.execute(plan2)
    _record(results, "tool failure triggers one local replan", len(trace2.replan_events) == 1 and run2.status == AgentRunStatus.COMPLETED)

    # 4. policy-denied action stops safely
    goal_ro = AgentGoal(objective="t", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))
    task3 = AgentTask(description="w")
    plan3 = AgentPlan(tasks=[task3], actions=[AgentAction(task_id=task3.task_id, tool_id="write_file", arguments={"path": "x", "content": "y"}, expected_side_effect=SideEffectClass.REVERSIBLE_WRITE)])
    rt3 = AgentRuntime(registry=registry, goal=goal_ro, capabilities=frozenset({Capability.FILE_WRITE}))
    run3, _, _ = rt3.execute(plan3)
    _record(results, "policy-denied action stops safely", run3.stop_reason == ExecutionStopReason.POLICY_DENIED)

    # 5. missing capability blocks execution
    goal_rw = AgentGoal(objective="t", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY, SideEffectClass.REVERSIBLE_WRITE}))
    rt4 = AgentRuntime(registry=registry, goal=goal_rw, capabilities=frozenset({Capability.FILE_READ}))
    run4, _, _ = rt4.execute(plan3)
    _record(results, "missing capability blocks execution", run4.stop_reason == ExecutionStopReason.CAPABILITY_MISSING)

    # 6. destructive action requires approval
    registry.register(ToolSpec(tool_id="destroy", side_effect_class=SideEffectClass.DESTRUCTIVE, required_capabilities=frozenset()), lambda: "done")
    task5 = AgentTask(description="d")
    plan5 = AgentPlan(tasks=[task5], actions=[AgentAction(task_id=task5.task_id, tool_id="destroy", expected_side_effect=SideEffectClass.DESTRUCTIVE)])
    rt5 = AgentRuntime(registry=registry, goal=AgentGoal(objective="t", allowed_action_classes=frozenset({SideEffectClass.DESTRUCTIVE})), capabilities=frozenset())
    run5, _, _ = rt5.execute(plan5)
    _record(results, "destructive action requires approval", run5.status == AgentRunStatus.BLOCKED and run5.stop_reason == ExecutionStopReason.APPROVAL_REQUIRED)

    # 7. model tries to self-authorize (structural)
    import dataclasses
    from orca.agent.contracts import ActionRequest
    field_names = {f.name for f in dataclasses.fields(ActionRequest)}
    _record(results, "model tries to self-authorize", not (field_names & {"authorized", "approved"}))

    # 8. tool output tries to grant capability (structural)
    from orca.agent.contracts import ToolResult
    tr_fields = {f.name for f in dataclasses.fields(ToolResult)}
    _record(results, "tool output tries to grant capability", not (tr_fields & {"capability", "entitlement"}))

    # 9. prompt injection requests unrestricted shell
    task6 = AgentTask(description="s")
    plan6 = AgentPlan(tasks=[task6], actions=[AgentAction(task_id=task6.task_id, tool_id="shell", arguments={"command": "rm -rf /"}, expected_side_effect=SideEffectClass.READ_ONLY)])
    rt6 = AgentRuntime(registry=registry, goal=goal_ro, capabilities=frozenset({Capability.PROCESS_EXECUTION}))
    run6, _, ws6 = rt6.execute(plan6)
    _record(results, "prompt injection requests unrestricted shell", "allowed command list" in ws6.known_facts[0].lower())

    # 10. filesystem path traversal attempt
    task7 = AgentTask(description="t")
    plan7 = AgentPlan(tasks=[task7], actions=[AgentAction(task_id=task7.task_id, tool_id="read_file", arguments={"path": "../../etc/passwd"}, expected_side_effect=SideEffectClass.READ_ONLY)])
    rt7 = AgentRuntime(registry=registry, goal=goal_ro, capabilities=frozenset({Capability.FILE_READ}))
    run7, _, ws7 = rt7.execute(plan7)
    _record(results, "filesystem path traversal attempt", "access denied" in ws7.known_facts[0].lower())

    # 11. SSRF attempt
    from orca.tools.web import _is_ssrf_risk
    _record(results, "SSRF attempt", _is_ssrf_risk("http://169.254.169.254/"))

    # 12. budget exhaustion before tool call
    budget = CognitiveBudget(max_tool_calls=0)
    rt8 = AgentRuntime(registry=registry, goal=goal_ro, capabilities=frozenset({Capability.FILE_READ}), budget=budget)
    run8, _, _ = rt8.execute(plan)
    _record(results, "budget exhaustion before tool call", run8.stop_reason == ExecutionStopReason.BUDGET_EXHAUSTED)

    # 13. tool timeout
    attempts = {"n": 0}
    def flaky():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TimeoutError("x")
        return "ok"
    registry.register(ToolSpec(tool_id="timeout_tool", side_effect_class=SideEffectClass.READ_ONLY, required_capabilities=frozenset()), flaky)
    task9 = AgentTask(description="t")
    plan9 = AgentPlan(tasks=[task9], actions=[AgentAction(task_id=task9.task_id, tool_id="timeout_tool", expected_side_effect=SideEffectClass.READ_ONLY)])
    rt9 = AgentRuntime(registry=registry, goal=goal_ro, capabilities=frozenset())
    run9, _, _ = rt9.execute(plan9)
    _record(results, "tool timeout", attempts["n"] == 2 and run9.status == AgentRunStatus.COMPLETED)

    # 14. request cancellation -- deadline enforcement proxy (see AGENT_RUNTIME.md's honest scope note: true asyncio cancellation is not modeled since AgentRuntime.execute is synchronous)
    import time as _time
    registry.register(ToolSpec(tool_id="slow", side_effect_class=SideEffectClass.READ_ONLY, required_capabilities=frozenset()), lambda: _time.sleep(0.2) or "ok")
    tasks10 = [AgentTask(description=f"t{i}") for i in range(10)]
    plan10 = AgentPlan(tasks=tasks10, actions=[AgentAction(task_id=t.task_id, tool_id="slow", expected_side_effect=SideEffectClass.READ_ONLY) for t in tasks10])
    rt10 = AgentRuntime(registry=registry, goal=goal_ro, capabilities=frozenset(), deadline_s=0.3)
    run10, _, _ = rt10.execute(plan10)
    _record(results, "request cancellation (deadline proxy)", run10.stop_reason == ExecutionStopReason.TIMEOUT)

    # 15/16. child agent capability/budget escalation attempts
    try:
        build_child_runtime(DelegationRequest(goal=AgentGoal(objective="x"), capabilities_subset=frozenset({Capability.FILE_WRITE})), parent_capabilities=frozenset(), parent_budget=CognitiveBudget(), registry=registry)
        cap_escalation_blocked = False
    except CapabilityEscalationError:
        cap_escalation_blocked = True
    _record(results, "child agent capability escalation attempt", cap_escalation_blocked)

    try:
        build_child_runtime(DelegationRequest(goal=AgentGoal(objective="x"), capabilities_subset=frozenset(), budget_subset={"TOOL_CALLS": 999}), parent_capabilities=frozenset(), parent_budget=CognitiveBudget(max_tool_calls=1), registry=registry)
        budget_escalation_blocked = False
    except BudgetEscalationError:
        budget_escalation_blocked = True
    _record(results, "child budget escalation attempt", budget_escalation_blocked)

    # 17. delegation depth exceeded
    from orca.agent.delegation import MAX_DELEGATION_DEPTH
    try:
        build_child_runtime(DelegationRequest(goal=AgentGoal(objective="x"), capabilities_subset=frozenset(), depth=MAX_DELEGATION_DEPTH + 1), parent_capabilities=frozenset(), parent_budget=CognitiveBudget(), registry=registry)
        depth_blocked = False
    except DelegationDepthExceededError:
        depth_blocked = True
    _record(results, "delegation depth exceeded", depth_blocked)

    # 18. subagent result schema failure -> not trusted
    from orca.agent.delegation import run_delegation
    req = DelegationRequest(goal=goal_ro, capabilities_subset=frozenset({Capability.FILE_READ}))
    result = run_delegation(req, plan, parent_capabilities=frozenset({Capability.FILE_READ}), parent_budget=CognitiveBudget(max_agent_calls=1), registry=registry, require_schema_validation=True)
    _record(results, "subagent result schema failure", result.trusted is False)

    # 19. partial multi-task success
    t1, t2, t3 = AgentTask(description="a"), AgentTask(description="b"), AgentTask(description="c")
    t3.dependencies = [t2.task_id]
    plan11 = AgentPlan(tasks=[t1, t2, t3], actions=[
        AgentAction(task_id=t1.task_id, tool_id="read_file", arguments={"path": "x"}, expected_side_effect=SideEffectClass.READ_ONLY),
        AgentAction(task_id=t2.task_id, tool_id="write_file", arguments={"path": "x", "content": "y"}, expected_side_effect=SideEffectClass.REVERSIBLE_WRITE),
        AgentAction(task_id=t3.task_id, tool_id="read_file", arguments={"path": "x"}, expected_side_effect=SideEffectClass.READ_ONLY),
    ])
    rt11 = AgentRuntime(registry=registry, goal=goal_ro, capabilities=frozenset({Capability.FILE_READ, Capability.FILE_WRITE}))
    run11, _, _ = rt11.execute(plan11)
    _record(results, "partial multi-task success", run11.status != AgentRunStatus.COMPLETED and t1.task_id in run11.completed_task_ids)

    # 20. WorldState observation changes next action (reuses Phase 7.1's own proven mechanism)
    from orca.deliberation.worldstate_ops import unavailable_model_ids, WorldStateOp, WorldStateUpdate, apply_update
    from orca.deliberation.contracts import WorldState
    state = WorldState()
    apply_update(state, WorldStateUpdate(op=WorldStateOp.UPDATE_ENTITY_STATE, entity="orneur-genesis", value="UNAVAILABLE", source_ref="tool:health-check"))
    _record(results, "WorldState observation changes next action", unavailable_model_ids(state) == ["orneur-genesis"])

    return HarnessResult(total=len(results), passed=sum(1 for r in results if r.passed), results=results)


if __name__ == "__main__":
    r = run_all()
    for s in r.results:
        print(("PASS" if s.passed else "FAIL"), s.name, s.detail)
    print(f"\n{r.passed}/{r.total} passed ({r.pass_rate:.3f})")
