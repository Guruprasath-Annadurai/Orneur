"""Bounded orchestration for synthetic agents.

A task is a registered Python callable plus a JSON payload. This module
does not spawn model servers, does not call a provider, and does not
represent N tasks as N native models.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


class OrchestratorError(Exception):
    """Base class for orchestration failures."""


class PermissionDenied(OrchestratorError):
    """The agent is not allowed to run that handler or to delegate that scope."""


class BudgetExhausted(OrchestratorError):
    """The agent does not have enough remaining budget units."""


class QueueSaturated(OrchestratorError):
    """The queue bound has been reached."""


class DependencyCycle(OrchestratorError):
    """The dependency graph contains a cycle."""


class UnknownTask(OrchestratorError):
    """No such task or handler."""


class IdempotencyConflict(OrchestratorError):
    """The idempotency key is already bound to a different request.

    The error does not carry the previously registered task id.
    """


class ResultRejected(OrchestratorError):
    """Handler output failed the result contract. The task is not a success."""


class ShutdownError(OrchestratorError):
    """The orchestrator is shut down and refuses new work."""


_MAX_RESULT_BYTES = 16 * 1024


@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    parent_id: str | None
    permissions: frozenset[str]
    budget_units: int


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    agent_id: str
    handler: str
    payload: dict
    idempotency_key: str
    depends_on: tuple[str, ...] = ()
    parent_task_id: str | None = None
    cost_units: int = 1
    timeout_ticks: int = 5


@dataclass
class TaskState:
    spec: TaskSpec
    status: str  # QUEUED, RUNNING, DEFERRED, SUCCEEDED, FAILED, CANCELLED
    result: dict | None = None
    error: str | None = None
    ticks_running: int = 0
    attempts: int = 0


@dataclass
class Orchestrator:
    max_concurrent: int
    queue_bound: int
    agents: dict[str, AgentIdentity] = field(default_factory=dict)
    spent: dict[str, int] = field(default_factory=dict)
    handlers: dict[str, tuple] = field(default_factory=dict)
    tasks: dict[str, TaskState] = field(default_factory=dict)
    idempotency: dict[str, "_IdempotencyBinding"] = field(default_factory=dict)
    children: dict[str, list[str]] = field(default_factory=dict)
    traces: list[dict] = field(default_factory=list)
    closed: bool = False

    def __post_init__(self) -> None:
        if self.max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        if self.queue_bound < 1:
            raise ValueError("queue_bound must be >= 1")

    def register_agent(self, identity: AgentIdentity) -> None:
        if not identity.agent_id:
            raise PermissionDenied("agent_id is required")
        if identity.budget_units < 0:
            raise PermissionDenied("budget_units must be non-negative")
        if identity.parent_id is not None:
            parent = self.agents.get(identity.parent_id)
            if parent is None:
                raise PermissionDenied(f"parent {identity.parent_id} is not registered")
            if not identity.permissions <= parent.permissions:
                raise PermissionDenied("child permissions must be a subset of the parent's")
            if identity.budget_units > parent.budget_units:
                raise PermissionDenied("child budget cannot exceed the parent budget")
        self.agents[identity.agent_id] = identity
        self.spent.setdefault(identity.agent_id, 0)

    def register_handler(self, name: str, fn, permission: str) -> None:
        if not name or not permission:
            raise PermissionDenied("handler name and permission are required")
        self.handlers[name] = (fn, permission)

    def submit(self, spec: TaskSpec) -> str:
        if self.closed:
            raise ShutdownError("orchestrator is shut down")
        if not spec.idempotency_key:
            raise OrchestratorError("idempotency_key is required")
        binding = self.idempotency.get(spec.idempotency_key)
        if binding is not None:
            return self._replay(spec, binding)
        if sum(1 for task in self.tasks.values() if task.status in {"QUEUED", "RUNNING", "DEFERRED"}) >= self.queue_bound:
            raise QueueSaturated(f"queue bound {self.queue_bound} reached")
        agent = self.agents.get(spec.agent_id)
        if agent is None:
            raise PermissionDenied(f"unknown agent {spec.agent_id}")
        if spec.handler not in self.handlers:
            raise UnknownTask(f"unknown handler {spec.handler}")
        _fn, permission = self.handlers[spec.handler]
        if permission not in agent.permissions:
            raise PermissionDenied(f"agent {agent.agent_id} lacks permission {permission}")
        if spec.cost_units < 0:
            raise BudgetExhausted("cost_units must be non-negative")
        if self.spent[agent.agent_id] + spec.cost_units > agent.budget_units:
            raise BudgetExhausted(f"agent {agent.agent_id} budget exhausted")
        self._require_acyclic(spec)
        for dep in spec.depends_on:
            if dep not in self.tasks:
                raise UnknownTask(f"dependency {dep} is not a known task")
        if spec.parent_task_id is not None and spec.parent_task_id not in self.tasks:
            raise UnknownTask(f"parent task {spec.parent_task_id} is not known")
        self.tasks[spec.task_id] = TaskState(spec=spec, status="QUEUED")
        self.idempotency[spec.idempotency_key] = _IdempotencyBinding(
            agent_id=spec.agent_id,
            intent_digest=_intent_digest(spec),
            task_id=spec.task_id,
        )
        self.spent[agent.agent_id] += spec.cost_units
        if spec.parent_task_id is not None:
            self.children.setdefault(spec.parent_task_id, []).append(spec.task_id)
        self.traces.append({"event": "submit", "task_id": spec.task_id, "agent_id": spec.agent_id})
        return spec.task_id

    def _replay(self, spec: TaskSpec, binding: "_IdempotencyBinding") -> str:
        """Return the original task id only for the same principal and the same intent.

        A different agent, a different payload, or a caller who no longer holds
        the handler permission gets an error that does not include the
        original task id. A matching retry does not enqueue a second task and
        does not spend the budget again.
        """
        if binding.agent_id != spec.agent_id:
            raise PermissionDenied("idempotency key is bound to a different principal")
        if _intent_digest(spec) != binding.intent_digest:
            raise IdempotencyConflict("idempotency key does not match this request")
        agent = self.agents.get(spec.agent_id)
        if agent is None:
            raise PermissionDenied(f"unknown agent {spec.agent_id}")
        if spec.handler not in self.handlers:
            raise UnknownTask(f"unknown handler {spec.handler}")
        _fn, permission = self.handlers[spec.handler]
        if permission not in agent.permissions:
            raise PermissionDenied(f"agent {agent.agent_id} lacks permission {permission}")
        return binding.task_id

    def _require_acyclic(self, spec: TaskSpec) -> None:
        visiting: set[str] = set()

        def walk(task_id: str) -> None:
            if task_id in visiting:
                raise DependencyCycle(f"cycle detected at {task_id}")
            visiting.add(task_id)
            state = self.tasks.get(task_id)
            if state is None:
                return
            for dep in state.spec.depends_on:
                walk(dep)
            visiting.remove(task_id)

        visiting.add(spec.task_id)
        for dep in spec.depends_on:
            if dep == spec.task_id:
                raise DependencyCycle(f"{spec.task_id} depends on itself")
            walk(dep)

    def cancel(self, task_id: str) -> list[str]:
        """Cancel `task_id` and every direct or indirect child still open.

        Returns the task ids that moved to CANCELLED. A task that already
        succeeded is left as SUCCEEDED; cancellation does not rewrite history.
        """
        if task_id not in self.tasks:
            raise UnknownTask(task_id)
        cancelled: list[str] = []
        stack = [task_id]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            state = self.tasks[current]
            if state.status in {"QUEUED", "RUNNING", "DEFERRED"}:
                state.status = "CANCELLED"
                state.error = "cancelled"
                cancelled.append(current)
                self.traces.append({"event": "cancel", "task_id": current})
            stack.extend(self.children.get(current, []))
        return cancelled

    def shutdown(self) -> None:
        """Refuse new submits and cancel queued work. Running tasks stop on the next tick."""
        self.closed = True
        for task_id, state in list(self.tasks.items()):
            if state.status == "QUEUED":
                self.cancel(task_id)

    def tick(self) -> list[str]:
        """Advance every ready task by one deterministic step.

        Handlers may return `{"defer": true}` to stay in progress without
        finishing. After `timeout_ticks` deferrals the task fails. A handler
        exception fails that task only. Other ready tasks still run.
        """
        progressed: list[str] = []
        running = sum(1 for task in self.tasks.values() if task.status in {"RUNNING", "DEFERRED"})
        ready = [
            state
            for state in self.tasks.values()
            if state.status == "QUEUED" and self._deps_succeeded(state.spec)
        ]
        for state in ready:
            if running >= self.max_concurrent:
                break
            if any(self.tasks[dep].status == "CANCELLED" for dep in state.spec.depends_on):
                state.status = "CANCELLED"
                state.error = "dependency cancelled"
                progressed.append(state.spec.task_id)
                continue
            if any(self.tasks[dep].status == "FAILED" for dep in state.spec.depends_on):
                state.status = "FAILED"
                state.error = "dependency failed"
                progressed.append(state.spec.task_id)
                continue
            state.status = "RUNNING"
            running += 1
        for state in list(self.tasks.values()):
            if state.status not in {"RUNNING", "DEFERRED"}:
                continue
            if state.status == "CANCELLED":
                continue
            outcome = self._invoke(state)
            progressed.append(state.spec.task_id)
            if outcome == "done":
                running -= 1
        return progressed

    def _deps_succeeded(self, spec: TaskSpec) -> bool:
        return all(self.tasks[dep].status == "SUCCEEDED" for dep in spec.depends_on)

    def _invoke(self, state: TaskState) -> str:
        fn, _permission = self.handlers[state.spec.handler]
        state.attempts += 1
        state.ticks_running += 1
        try:
            raw = fn(dict(state.spec.payload), {"task_id": state.spec.task_id, "tick": state.ticks_running})
        except Exception as exc:  # noqa: BLE001 -- isolated failure of one handler
            state.status = "FAILED"
            state.error = type(exc).__name__
            self.traces.append({"event": "fail", "task_id": state.spec.task_id, "error": state.error})
            return "done"
        if isinstance(raw, dict) and raw.get("defer") is True:
            if set(raw) != {"defer"}:
                state.status = "FAILED"
                state.error = "defer mixed with a result payload"
                self.traces.append({"event": "reject", "task_id": state.spec.task_id})
                return "done"
            if state.ticks_running >= state.spec.timeout_ticks:
                state.status = "FAILED"
                state.error = "timeout"
                self.traces.append({"event": "timeout", "task_id": state.spec.task_id})
                return "done"
            state.status = "DEFERRED"
            self.traces.append({"event": "defer", "task_id": state.spec.task_id, "tick": state.ticks_running})
            return "deferred"
        try:
            checked = _accept_result(raw)
        except ResultRejected as exc:
            state.status = "FAILED"
            state.error = str(exc)
            self.traces.append({"event": "reject", "task_id": state.spec.task_id})
            return "done"
        state.result = checked
        state.status = "SUCCEEDED"
        self.traces.append({"event": "succeed", "task_id": state.spec.task_id})
        return "done"

    def run_until_idle(self, max_ticks: int = 100) -> None:
        for _ in range(max_ticks):
            open_tasks = [
                task for task in self.tasks.values() if task.status in {"QUEUED", "RUNNING", "DEFERRED"}
            ]
            if not open_tasks:
                return
            before = [(task.spec.task_id, task.status, task.ticks_running) for task in open_tasks]
            self.tick()
            after = [(task.spec.task_id, task.status, task.ticks_running) for task in open_tasks]
            if before == after:
                raise OrchestratorError("tick made no progress; refusing to spin")
        raise OrchestratorError("run_until_idle exceeded max_ticks")


@dataclass(frozen=True)
class _IdempotencyBinding:
    agent_id: str
    intent_digest: str
    task_id: str


def _intent_digest(spec: TaskSpec) -> str:
    """Canonical identity of a request, excluding task_id and agent_id.

    `task_id` may differ on a legitimate retry. `agent_id` is compared
    separately so a cross-principal collision is not reported as a payload mismatch.
    """
    body = {
        "handler": spec.handler,
        "payload": spec.payload,
        "depends_on": list(spec.depends_on),
        "parent_task_id": spec.parent_task_id,
        "cost_units": spec.cost_units,
        "timeout_ticks": spec.timeout_ticks,
    }
    try:
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise OrchestratorError("payload is not JSON-serializable") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _accept_result(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ResultRejected("handler result must be a JSON object")
    if "defer" in raw:
        raise ResultRejected("defer is only valid as the sole control signal and was mixed into a result")
    try:
        encoded = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ResultRejected("handler result is not JSON-serializable") from exc
    if len(encoded) > _MAX_RESULT_BYTES:
        raise ResultRejected(f"handler result is {len(encoded)} bytes, over {_MAX_RESULT_BYTES}")
    return json.loads(encoded)
