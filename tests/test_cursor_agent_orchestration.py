"""Synthetic agent orchestration. No model processes are started."""
from __future__ import annotations

import pytest

from orca.pretrain_foundation.agents import (
    AgentIdentity,
    BudgetExhausted,
    DependencyCycle,
    IdempotencyConflict,
    Orchestrator,
    PermissionDenied,
    QueueSaturated,
    ResultRejected,
    ShutdownError,
    TaskIdentityConflict,
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
    payload = {"n": "same", "a": 1}
    first = orch.submit(_task("same", idempotency_key="same-key", payload=payload))
    second = orch.submit(_task("other-id", idempotency_key="same-key", payload={"a": 1, "n": "same"}))
    assert first == second == "same"
    orch.run_until_idle()
    assert calls["n"] == 1
    assert orch.tasks[first].status == "SUCCEEDED"
    third = orch.submit(_task("replayed-id", idempotency_key="same-key", payload=payload))
    assert third == first
    assert calls["n"] == 1


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


def test_idempotency_key_is_bound_to_principal_and_intent():
    victim_task = "VICTIM-TASK-9f3a"
    orch = _orch()
    orch.register_agent(AgentIdentity("intruder", None, frozenset({"read", "write"}), 5))
    orch.register_handler("other", lambda payload, ctx: {"ok": True}, "read")
    payload = {"n": "stable"}
    original = orch.submit(_task(victim_task, idempotency_key="replay-key", payload=payload))
    assert original == victim_task

    def _rejected(submit):
        with pytest.raises((PermissionDenied, IdempotencyConflict)) as caught:
            submit()
        text = f"{caught.value} {caught.value!r}"
        assert victim_task not in text
        assert "intruder-task" not in orch.tasks
        assert orch.spent["intruder"] == 0
        return caught.value

    _rejected(lambda: orch.submit(_task(
        "intruder-task", agent_id="intruder", idempotency_key="replay-key", payload=payload,
    )))
    _rejected(lambda: orch.submit(_task(
        "intruder-task", agent_id="intruder", idempotency_key="replay-key", payload=payload, handler="other",
    )))
    mismatch = _rejected(lambda: orch.submit(_task(
        "other-id", idempotency_key="replay-key", payload={"n": "altered"},
    )))
    assert isinstance(mismatch, IdempotencyConflict)
    handler_mismatch = _rejected(lambda: orch.submit(_task(
        "other-id", idempotency_key="replay-key", payload=payload, handler="other",
    )))
    assert isinstance(handler_mismatch, IdempotencyConflict)

    orch.agents["root"] = AgentIdentity("root", None, frozenset(), 5)
    with pytest.raises(PermissionDenied) as denied:
        orch.submit(_task("ignored", idempotency_key="replay-key", payload=payload))
    assert victim_task not in f"{denied.value} {denied.value!r}"
    assert orch.tasks[victim_task].status == "QUEUED"
    assert len(orch.tasks) == 1


def test_reused_task_id_with_a_new_key_does_not_overwrite():
    calls = {"n": 0}

    def handler(payload, ctx):
        calls["n"] += 1
        return {"echo": payload["n"]}

    orch = _orch()
    orch.register_handler("ok", handler, "read")
    orch.register_handler("other", lambda payload, ctx: {"ok": True}, "read")
    orch.register_handler("child-ok", lambda payload, ctx: {"ok": True}, "read")
    orch.register_agent(AgentIdentity("other-agent", None, frozenset({"read"}), 5))
    original = orch.submit(_task(
        "T1",
        agent_id="root",
        handler="ok",
        payload={"n": "original"},
        idempotency_key="K1-SECRET",
        cost_units=1,
    ))
    child = orch.submit(_task(
        "child",
        handler="child-ok",
        idempotency_key="child-key",
        parent_task_id="T1",
        depends_on=("T1",),
    ))
    assert original == "T1"
    assert orch.tasks["T1"].spec.payload == {"n": "original"}
    assert orch.tasks["T1"].spec.handler == "ok"
    assert orch.tasks["T1"].spec.idempotency_key == "K1-SECRET"
    assert orch.spent["root"] == 2
    assert orch.children["T1"] == [child]
    binding = orch.idempotency["K1-SECRET"]

    def _collision(**overrides):
        spent_root = orch.spent["root"]
        spent_other = orch.spent["other-agent"]
        fields = {"idempotency_key": "K2", "payload": {"n": "original"}}
        fields.update(overrides)
        with pytest.raises(TaskIdentityConflict) as caught:
            orch.submit(_task("T1", **fields))
        text = f"{caught.value} {caught.value!r}"
        assert "other-agent" not in text
        assert "K1-SECRET" not in text
        assert "root" not in text
        assert orch.tasks["T1"].spec.payload == {"n": "original"}
        assert orch.tasks["T1"].spec.handler == "ok"
        assert orch.tasks["T1"].spec.agent_id == "root"
        assert orch.tasks["T1"].spec.idempotency_key == "K1-SECRET"
        assert orch.tasks["T1"].status == "QUEUED"
        assert orch.idempotency["K1-SECRET"] == binding
        assert "K2" not in orch.idempotency
        assert orch.spent["root"] == spent_root
        assert orch.spent["other-agent"] == spent_other
        assert orch.children["T1"] == [child]
        assert len(orch.tasks) == 2

    _collision()
    _collision(payload={"n": "changed"})
    _collision(handler="other")
    _collision(agent_id="other-agent", payload={"n": "stolen"})

    replay = orch.submit(_task(
        "retry-id",
        idempotency_key="K1-SECRET",
        payload={"n": "original"},
    ))
    assert replay == "T1"
    assert calls["n"] == 0
    orch.run_until_idle()
    assert calls["n"] == 1
    assert orch.tasks["T1"].status == "SUCCEEDED"
    result = dict(orch.tasks["T1"].result)
    spent_after_success = orch.spent["root"]
    with pytest.raises(TaskIdentityConflict):
        orch.submit(_task("T1", idempotency_key="K3", payload={"n": "after-success"}))
    assert orch.tasks["T1"].status == "SUCCEEDED"
    assert orch.tasks["T1"].result == result
    assert orch.spent["root"] == spent_after_success
    assert "K3" not in orch.idempotency

    again = orch.submit(_task(
        "retry-after-success",
        idempotency_key="K1-SECRET",
        payload={"n": "original"},
    ))
    assert again == "T1"
    assert calls["n"] == 1

    fresh = Orchestrator(max_concurrent=1, queue_bound=4)
    fresh.register_agent(AgentIdentity("root", None, frozenset({"read"}), 4))
    fresh.register_handler("ok", lambda payload, ctx: {"echo": 1}, "read")
    fresh.submit(_task("T1", idempotency_key="K1-SECRET", payload={"n": "original"}))
    fresh.cancel("T1")
    assert fresh.tasks["T1"].status == "CANCELLED"
    with pytest.raises(TaskIdentityConflict):
        fresh.submit(_task("T1", idempotency_key="K4", payload={"n": "after-cancel"}))
    assert fresh.tasks["T1"].status == "CANCELLED"
    assert fresh.tasks["T1"].spec.payload == {"n": "original"}
    assert fresh.spent["root"] == 1
    assert "K4" not in fresh.idempotency


def test_non_object_result_is_rejected_by_the_contract():
    with pytest.raises(ResultRejected):
        from orca.pretrain_foundation.agents import _accept_result
        _accept_result(["not", "an", "object"])
