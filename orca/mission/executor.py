"""
Phase 15.5 -- the boundary between the durable operation state machine
(orca.mission.operation_store) and an actual external side effect.

Separating these means the state machine's correctness (authorization,
idempotency, concurrency) can be proven without ever performing a real
destructive action (spec section 9: "Do NOT perform real destructive
production actions just to prove the authority engine"). Production
executors (a real deploy, a real migration) plug in behind the same
`Executor` protocol later; this module only ships the deterministic
test double used by Phase 15.5's own tests.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Protocol


class ExecutionFailed(Exception):
    """Raised by an Executor to signal the external side effect failed
    (as opposed to raising an unrelated bug) -- operation_store catches
    this specifically and records FAILED with the message as result_ref."""


class Executor(Protocol):
    def execute(self, *, operation_id: str, kind: str, mission_id: str | None) -> str:
        """Performs the real side effect. Returns a result reference
        string (never a secret value) on success. Raises
        ExecutionFailed on a real, expected failure."""
        ...


@dataclass
class RecordingTestExecutor:
    """Deterministic, harmless executor for tests: records exactly how
    many times (and with what arguments) it was invoked, thread-safe
    (used directly by the concurrency tests, which invoke it from
    multiple real threads). Never performs any real external action."""
    invocations: list[dict] = field(default_factory=list)
    fail_next: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def execute(self, *, operation_id: str, kind: str, mission_id: str | None) -> str:
        with self._lock:
            self.invocations.append({"operation_id": operation_id, "kind": kind, "mission_id": mission_id})
            should_fail = self.fail_next
            if should_fail:
                self.fail_next = False
        if should_fail:
            raise ExecutionFailed(f"RecordingTestExecutor: deliberate test failure for {operation_id}")
        return f"test-result:{operation_id}"

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self.invocations)
