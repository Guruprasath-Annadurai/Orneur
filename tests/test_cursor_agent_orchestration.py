"""Synthetic agent orchestration. No model processes are started."""
from __future__ import annotations

import pytest

from orca.pretrain_foundation.agents import (
    AgentIdentity,
    BudgetExhausted,
    DependencyCycle,
    Orchestrator,
    PermissionDenied,
    QueueSaturated,
    ResultRejected,
    ShutdownError,
    TaskSpec,
    TaskState,
)


def _orch(**kwargs) -> Orchestrator:
    orch = Orchestrator(max_concurrent=2, queue_bound=8, **kwargs)
    orch.register_agent(AgentIdentity("root", None, frozenset({"read", "write"}), 5))
    orch.register_handler("ok", lambda payload, ctx: {"echo": payload["n"]}, "read")
    return orch


def _task(task_id: str, **kwargs) -> TaskSpec:
    values = dict(
        task_id=task_id,
        agent_id="root",
        handler="ok",
        payload={"n": task_id},
        idempotency_key=task_id,
        cost_units=1,
    )
    values.update(kwargs)
    return TaskSpec(**values)


def test_child_cannot_gain_permissions_or_budget():
    orch = _orch()
    with pytest.raises(PermissionDenied, match="subset"):
        orch.register_agent(AgentIdentity("child", "root", frozenset({"read", "admin"}), 1))
    with pytest.raises(PermissionDenied, match="budget"):
        orch.register_agent(AgentIdentity("child", "root", frozenset({"read"}), 9))


def test_permission_denied_handler_and_budget_and_queue():
    orch = _orch()
    orch.register_handler("secret", lambda payload, ctx: {"ok": True}, "admin")
    with pytest.raises(PermissionDenied):
        orch.submit(_task("t", handler="secret"))
    for index in range(5):
        orch.submit(_task(f"b{index}", idempotency_key=f"b{index}", cost_units=1))
    with pytest.raises(BudgetExhausted):
        orch.submit(_task("overflow", idempotency_key="overflow"))
    small = Orchestrator(max_concurrent=1, queue_bound=1)
    small.register_agent(AgentIdentity("root", None, frozenset({"read"}), 10))
    small.register_handler("ok", lambda payload, ctx: {"echo": 1}, "read")
    small.submit(_task("only"))
    with pytest.raises(QueueSaturated):
        small.submit(_task("second", idempotency_key="second"))


def test_duplicate_idempotency_key_does_not_run_twice():
    calls = {"n": 0}

    def handler(payload, ctx):
        calls["n"] += 1
        return {"echo": payload["n"]}

    orch = _orch()
    orch.register_handler("ok", handler, "read")
    first = orch.submit(_task("same", idempotency_key="same-key"))
    second = orch.submit(_task("other-id", idempotency_key="same-key"))
    assert first == second
    orch.run_until_idle()
    assert calls["n"] == 1
    assert orch.tasks[first].status == "SUCCEEDED"


def test_cancellation_cascades_and_shutdown_rejects_new_work():
    orch = _orch()
    parent = orch.submit(_task("parent"))
    child = orch.submit(_task("child", idempotency_key="child", parent_task_id=parent, depends_on=("parent",)))
    orch.cancel("parent")
    assert orch.tasks[parent].status == "CANCELLED"
    assert orch.tasks[child].status == "CANCELLED"
    orch.shutdown()
    with pytest.raises(ShutdownError):
        orch.submit(_task("after", idempotency_key="after"))


def test_slow_worker_times_out_without_failing_a_sibling():
    def slow(payload, ctx):
        return {"defer": True}

    def fast(payload, ctx):
        return {"ok": True}

    orch = Orchestrator(max_concurrent=2, queue_bound=4)
    orch.register_agent(AgentIdentity("root", None, frozenset({"read"}), 5))
    orch.register_handler("slow", slow, "read")
    orch.register_handler("fast", fast, "read")
    orch.submit(_task("slow", handler="slow", idempotency_key="slow", timeout_ticks=2))
    orch.submit(_task("fast", handler="fast", idempotency_key="fast"))
    orch.run_until_idle()
    assert orch.tasks["slow"].status == "FAILED"
    assert orch.tasks["slow"].error == "timeout"
    assert orch.tasks["fast"].status == "SUCCEEDED"


def test_malicious_tool_output_fails_the_task():
    orch = _orch()
    orch.register_handler("bad", lambda payload, ctx: {"blob": "x" * (20 * 1024)}, "read")
    orch.submit(_task("bad", handler="bad", idempotency_key="bad"))
    orch.run_until_idle()
    assert orch.tasks["bad"].status == "FAILED"
    assert "bytes" in orch.tasks["bad"].error


def test_partial_failure_does_not_fail_an_independent_task():
    def boom(payload, ctx):
        raise RuntimeError("nope")

    orch = _orch()
    orch.register_handler("boom", boom, "read")
    orch.submit(_task("boom", handler="boom", idempotency_key="boom"))
    orch.submit(_task("ok"))
    orch.run_until_idle()
    assert orch.tasks["boom"].status == "FAILED"
    assert orch.tasks["ok"].status == "SUCCEEDED"


def test_dependency_cycle_is_rejected():
    orch = _orch()
    orch.tasks["a"] = TaskState(spec=_task("a", depends_on=("b",)), status="QUEUED")
    with pytest.raises(DependencyCycle):
        orch.submit(_task("b", idempotency_key="b", depends_on=("a",)))


def test_non_object_result_is_rejected_by_the_contract():
    with pytest.raises(ResultRejected):
        from orca.pretrain_foundation.agents import _accept_result
        _accept_result(["not", "an", "object"])
