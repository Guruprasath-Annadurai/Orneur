"""Bounded DAG dispatch over the specialist registry. Not a mission engine.

Thread-pool handlers are not forcibly killed. A deadline or cancel sets a
flag; a blocked thread may keep running. The result never claims those
threads were terminated.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Callable

from orca.specialists.contracts import SpecialistError, SpecialistResult, TaskNode
from orca.specialists.registry import SpecialistRegistry, default_registry
from orca.sovereign_mission.store import digest


class Orchestrator:
    def __init__(
        self,
        *,
        tenant_id: str,
        capabilities: frozenset[str],
        registry: SpecialistRegistry | None = None,
        max_workers: int = 2,
        deadline_s: float = 8.0,
    ):
        if not tenant_id:
            raise SpecialistError("tenant_required")
        if max_workers < 1 or max_workers > 8:
            raise SpecialistError("concurrency_refused")
        if deadline_s <= 0 or deadline_s > 120:
            raise SpecialistError("deadline_refused")
        self.tenant_id = tenant_id
        self.capabilities = capabilities
        self.registry = registry or default_registry()
        self.max_workers = max_workers
        self.deadline_s = deadline_s
        self._cancel = threading.Event()
        self._started: dict[str, float] = {}

    def cancel(self) -> None:
        self._cancel.set()

    def run(self, tasks: list[TaskNode], *, parent_capabilities: frozenset[str] | None = None) -> dict:
        granted = parent_capabilities if parent_capabilities is not None else self.capabilities
        by_id = {}
        for task in tasks:
            if task.task_id in by_id:
                raise SpecialistError("duplicate_task")
            by_id[task.task_id] = task
            extra = task.capabilities - granted
            if extra:
                raise SpecialistError("privilege_escalation")
        for task in tasks:
            missing = [dep for dep in task.depends_on if dep not in by_id]
            if missing:
                raise SpecialistError("unknown_dependency")

        results: dict[str, SpecialistResult] = {}
        errors: dict[str, str] = {}
        pending = set(by_id)
        inflight: dict = {}
        still_running: list[str] = []
        deadline_at = time.monotonic() + self.deadline_s

        def remaining() -> float:
            return deadline_at - time.monotonic()

        def invoke(task: TaskNode) -> SpecialistResult:
            if self._cancel.is_set():
                raise SpecialistError("cancelled")
            spec = self.registry.get(task.role)
            needed = spec.capabilities
            if not needed.issubset(granted) or not task.capabilities.issubset(granted):
                raise SpecialistError("privilege_escalation")
            payload = dict(task.payload)
            payload.setdefault("tenant_id", self.tenant_id)
            if payload.get("tenant_id") != self.tenant_id:
                raise SpecialistError("tenant_mismatch")
            if task.irreversible and not payload.get("receipt"):
                return SpecialistResult(
                    role=task.role,
                    status="unknown",
                    output={"reason": "irreversible_without_receipt"},
                    evidence={"status": "unknown", "role": task.role},
                    tenant_id=self.tenant_id,
                    error="outcome_unknown",
                )
            handler: Callable = self.registry.handler(task.role)
            return handler(payload)

        def abort(code: str) -> None:
            self._cancel.set()
            for future, task_id in list(inflight.items()):
                future.cancel()
                if future.running():
                    still_running.append(task_id)
            err = SpecialistError(code)
            err.still_running = list(still_running)
            err.handlers_forcibly_stopped = False
            err.partial_results = {key: _as_dict(results[key]) for key in results}
            raise err

        pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="orneur-spec")
        try:
            while pending or inflight:
                if remaining() <= 0:
                    abort("deadline_exceeded")
                if self._cancel.is_set():
                    abort("cancelled")
                ready = [
                    task_id
                    for task_id in list(pending)
                    if all(
                        dep in results
                        and results[dep].status in {"completed", "verified", "empty", "fixture_only", "unavailable"}
                        for dep in by_id[task_id].depends_on
                    )
                    and all(dep not in errors for dep in by_id[task_id].depends_on)
                ]
                blocked = [
                    task_id
                    for task_id in list(pending)
                    if any(
                        dep in errors
                        or (dep in results and results[dep].status in {"failed", "refused", "unverified", "unknown"})
                        for dep in by_id[task_id].depends_on
                    )
                ]
                for task_id in blocked:
                    pending.remove(task_id)
                    errors[task_id] = "dependency_failed"
                while ready and len(inflight) < self.max_workers:
                    task_id = ready.pop(0)
                    pending.remove(task_id)
                    future = pool.submit(invoke, by_id[task_id])
                    inflight[future] = task_id
                    self._started[task_id] = time.monotonic()
                if not inflight:
                    if pending:
                        raise SpecialistError("cycle_refused")
                    break
                wait_s = remaining()
                if wait_s <= 0:
                    abort("deadline_exceeded")
                done, _ = wait(inflight, timeout=wait_s, return_when=FIRST_COMPLETED)
                if not done:
                    abort("deadline_exceeded")
                for future in done:
                    task_id = inflight.pop(future)
                    try:
                        result = future.result()
                    except SpecialistError as exc:
                        if exc.code in {"tenant_mismatch", "privilege_escalation", "cancelled"}:
                            abort(exc.code)
                        errors[task_id] = exc.code
                        continue
                    results[task_id] = result
                    if result.status in {"failed", "refused", "unverified", "unknown"}:
                        errors[task_id] = result.error or result.status
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        if self._cancel.is_set():
            abort("cancelled")
        evidence = [results[key].evidence for key in sorted(results)]
        return {
            "tenant_id": self.tenant_id,
            "registry_version": self.registry.version,
            "results": {key: _as_dict(results[key]) for key in sorted(results)},
            "errors": errors,
            "cancelled": False,
            "cancel_requested": False,
            "handlers_forcibly_stopped": False,
            "handlers_still_running": [],
            "evidence_sha256": digest({"evidence": evidence}),
            "evidence": evidence,
        }


def _as_dict(result: SpecialistResult) -> dict:
    return {
        "role": result.role,
        "status": result.status,
        "output": result.output,
        "evidence": result.evidence,
        "tenant_id": result.tenant_id,
        "synthetic": result.synthetic,
        "error": result.error,
    }
