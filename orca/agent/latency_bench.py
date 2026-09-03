"""
Agent Runtime performance (Phase 8 spec §68). Real measurements, no
fabricated numbers. All deterministic -- no model call in this benchmark
(the "planning" measured here is the deterministic Policy/Capability/
budget/WorldState machinery, not LLM-driven plan generation, which is
out of scope for a runtime-overhead measurement).

Run directly: `.venv/bin/python -m orca.agent.latency_bench`.
"""
from __future__ import annotations

import statistics
import time

from orca.agent.capability import check_capabilities
from orca.agent.contracts import AgentAction, AgentGoal, AgentPlan, AgentTask, Capability, SideEffectClass
from orca.agent.delegation import build_child_runtime
from orca.agent.contracts import DelegationRequest
from orca.agent.policy import evaluate_policy
from orca.agent.runtime import AgentRuntime
from orca.agent.tool_registry import build_agent_tool_registry
from orca.cognitive.contracts import CognitiveBudget

REPS = 200


def _p50(samples: list[float]) -> float:
    return round(statistics.median(samples), 4)


def bench_tool_registry_lookup() -> dict:
    registry = build_agent_tool_registry()
    samples = []
    for _ in range(REPS):
        t0 = time.perf_counter()
        registry.get_spec("read_file")
        samples.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": _p50(samples), "reps": REPS}


def bench_capability_check() -> dict:
    registry = build_agent_tool_registry()
    spec = registry.get_spec("write_file")
    caps = frozenset({Capability.FILE_WRITE, Capability.FILE_READ})
    samples = []
    for _ in range(REPS):
        t0 = time.perf_counter()
        check_capabilities(caps, spec)
        samples.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": _p50(samples), "reps": REPS}


def bench_policy_decision() -> dict:
    registry = build_agent_tool_registry()
    spec = registry.get_spec("write_file")
    goal = AgentGoal(objective="x", allowed_action_classes=frozenset({SideEffectClass.REVERSIBLE_WRITE}))
    cap_decision = check_capabilities(frozenset({Capability.FILE_WRITE}), spec)
    samples = []
    for _ in range(REPS):
        t0 = time.perf_counter()
        evaluate_policy(goal=goal, tool_spec=spec, capability_decision=cap_decision)
        samples.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": _p50(samples), "reps": REPS}


def bench_full_run_read_only() -> dict:
    """One full PLAN->AUTHORIZE->EXECUTE->OBSERVE->WORLDSTATE cycle for a
    single read-only action -- the smallest real end-to-end unit,
    including budget reservation and WorldState update."""
    registry = build_agent_tool_registry()
    goal = AgentGoal(objective="x", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))
    samples = []
    for _ in range(REPS):
        task = AgentTask(description="r")
        plan = AgentPlan(tasks=[task], actions=[AgentAction(task_id=task.task_id, tool_id="read_file", arguments={"path": "x"}, expected_side_effect=SideEffectClass.READ_ONLY)])
        budget = CognitiveBudget(max_tool_calls=6)
        rt = AgentRuntime(registry=registry, goal=goal, capabilities=frozenset({Capability.FILE_READ}), budget=budget)
        t0 = time.perf_counter()
        rt.execute(plan)
        samples.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": _p50(samples), "reps": REPS}


def bench_delegation_overhead() -> dict:
    registry = build_agent_tool_registry()
    samples = []
    for _ in range(REPS):
        req = DelegationRequest(goal=AgentGoal(objective="x"), capabilities_subset=frozenset({Capability.FILE_READ}), budget_subset={"TOOL_CALLS": 1})
        t0 = time.perf_counter()
        build_child_runtime(req, parent_capabilities=frozenset({Capability.FILE_READ}), parent_budget=CognitiveBudget(max_tool_calls=6), registry=registry)
        samples.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": _p50(samples), "reps": REPS}


def bench_plan_schema_validation() -> dict:
    """Phase 8.1: plan schema validation overhead, excluding any model
    call (the raw dict is already in hand -- this measures ONLY
    `_validate_and_build_plan`'s own framework cost)."""
    from orca.agent.planner import _validate_and_build_plan
    registry = build_agent_tool_registry()
    specs = {"read_file": registry.get_spec("read_file")}
    raw = {"tasks": [{"description": "t"}], "actions": [{"task_index": 0, "tool_id": "read_file", "arguments": {"path": "x"}}]}
    samples = []
    for _ in range(REPS):
        t0 = time.perf_counter()
        _validate_and_build_plan(raw, specs)
        samples.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": _p50(samples), "reps": REPS}


def bench_memory_hook_overhead() -> dict:
    """Real recall() + Firewall filter cost against an empty/small local
    store -- excludes any model call (Memory hooks are model-free)."""
    from orca.agent.memory_hook import recall_advisory_context
    samples = []
    for _ in range(REPS):
        t0 = time.perf_counter()
        recall_advisory_context("some objective", scope_id="latency-bench-scope")
        samples.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": _p50(samples), "reps": REPS}


def bench_court_trigger_policy() -> dict:
    """`should_request_court_review()`'s own deterministic decision cost
    -- excludes any actual Court invocation."""
    from orca.agent.contracts import AgentGoal
    from orca.agent.court_hook import should_request_court_review
    goal = AgentGoal(objective="x", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))
    samples = []
    for _ in range(REPS):
        t0 = time.perf_counter()
        should_request_court_review(goal)
        samples.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": _p50(samples), "reps": REPS}


if __name__ == "__main__":
    import json
    print(json.dumps({
        "tool_registry_lookup": bench_tool_registry_lookup(),
        "capability_check": bench_capability_check(),
        "policy_decision": bench_policy_decision(),
        "full_run_read_only_action": bench_full_run_read_only(),
        "delegation_overhead": bench_delegation_overhead(),
        "plan_schema_validation": bench_plan_schema_validation(),
        "memory_hook_overhead": bench_memory_hook_overhead(),
        "court_trigger_policy": bench_court_trigger_policy(),
    }, indent=2))
