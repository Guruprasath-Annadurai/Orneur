"""
Phase 14B.2: a narrow, reusable cancellation contract for Godmode
authority operations (spec Steps 1-2 of the cancellation-closure spec).

Cancellation here is COOPERATIVE and FAIL-SAFE. A cancellation request
means "stop at the next safe cancellation boundary" -- it never means:
roll back an already-committed external side effect, refund a consumed
lease, erase audit history, bypass authorization, or convert an UNKNOWN
outcome into success. See `orca.godmode.resolution.resolve_and_consume_lease()`'s
docstring for the exact checkpoint semantics this contract is checked
against.

Godmode itself is synchronous today and must stay framework-agnostic:
this module has NO import of `asyncio` at module scope (only inside
`current_task_cancellation_signal()`, which is the one asyncio-specific
adapter, kept deliberately separate) so the contract works unmodified
from synchronous code, threads, or a future cross-process RPC boundary
-- not just from an asyncio event loop.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol, runtime_checkable


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@runtime_checkable
class CancellationSignal(Protocol):
    """Structural contract every cancellation-aware call site checks.
    Deliberately minimal -- `is_cancelled()` is the only method callers
    may rely on being present; `reason`/`cancelled_at`/`request_id` are
    read as plain attributes (present on every concrete implementation
    below, defaulting to None) purely for diagnostics, never for control
    flow."""

    def is_cancelled(self) -> bool: ...


@dataclass
class NoCancellation:
    """The default, always-false signal. Every existing caller of
    `resolve_and_consume_lease()` that omits `cancellation` gets exactly
    this -- current behavior is fully preserved."""

    reason: str | None = None
    cancelled_at: str | None = None
    request_id: str | None = None

    def is_cancelled(self) -> bool:
        return False


_NO_CANCELLATION = NoCancellation()


class ThreadCancellationSignal:
    """Wraps a `threading.Event` -- safe to hand to another thread (or
    to a future cross-process worker via a serialized `request_id`/
    `cancellation_epoch`, see Step 12) so that caller can signal
    cancellation asynchronously relative to the thread actually running
    the Godmode call."""

    def __init__(self, event: threading.Event | None = None, *, reason: str | None = None, request_id: str | None = None) -> None:
        self._event = event or threading.Event()
        self.reason = reason
        self.request_id = request_id
        self.cancelled_at: str | None = None

    def cancel(self, *, reason: str | None = None) -> None:
        if reason is not None:
            self.reason = reason
        self.cancelled_at = _now_iso()
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


class CallableCancellationSignal:
    """The thinnest possible adapter: wraps an arbitrary zero-argument
    callable returning bool. This is what `current_task_cancellation_signal()`
    below returns, and is the natural shape for any future adapter
    (a polled RPC cancellation-epoch check, a deadline-derived check,
    etc.) that doesn't need its own stateful class."""

    def __init__(self, check: Callable[[], bool], *, reason: str | None = None, request_id: str | None = None) -> None:
        self._check = check
        self.reason = reason
        self.request_id = request_id
        self.cancelled_at: str | None = None

    def is_cancelled(self) -> bool:
        cancelled = bool(self._check())
        if cancelled and self.cancelled_at is None:
            self.cancelled_at = _now_iso()
        return cancelled


def current_task_cancellation_signal() -> CallableCancellationSignal:
    """The one asyncio-specific adapter (Step 11): reflects the
    CURRENTLY-RUNNING asyncio Task's own cancellation-requested state
    into the synchronous `CancellationSignal` contract Godmode
    understands, without making `orca.godmode` itself asyncio-specific.
    `import asyncio` is local to this function precisely so that the
    rest of this module (and everything in `resolution.py` that only
    type-checks against the `CancellationSignal` Protocol) never needs
    asyncio to be importable.

    Uses `Task.cancelling()` (Python 3.11+): the count of `cancel()`
    calls made against this task that have not yet resulted in the task
    finishing -- i.e. "a cancellation has been REQUESTED," which is
    exactly what a cooperative checkpoint needs to observe BEFORE the
    `CancelledError` is actually delivered/raised. Falls back to the
    coarser `Task.cancelled()` (true only once the task has actually
    finished due to cancellation) on older Pythons that lack
    `cancelling()`, which is weaker but never wrong in the direction
    that matters here (it can only be a false negative, never a false
    positive)."""
    import asyncio

    def _check() -> bool:
        try:
            task = asyncio.current_task()
        except RuntimeError:
            return False
        if task is None:
            return False
        cancelling = getattr(task, "cancelling", None)
        if cancelling is not None:
            return cancelling() > 0
        return task.cancelled()

    return CallableCancellationSignal(_check)


def is_cancelled(signal: "CancellationSignal | None") -> bool:
    """Uniform null-safe check -- every checkpoint in `resolution.py`
    calls this instead of repeating the `signal is not None and
    signal.is_cancelled()` guard."""
    return signal is not None and signal.is_cancelled()


def check_and_record_pre_side_effect_cancellation(
    *, cancellation: "CancellationSignal | None", tenant_id: str, lease_id: str | None,
    capability: str = "", resource_scope: str = "", operation_scope: str = "",
    principal_id: str | None = None, trace_id: str | None = None,
) -> bool:
    """Spec Step 5's mandatory caller-side final gate. A
    cancellation-capable caller MUST call this between an ALLOW/
    COMMITTED authorization decision and executing the actual
    privileged side effect -- otherwise a cancellation arriving in that
    exact window would still execute, since `resolve_and_consume_lease()`
    itself has already returned by then and cannot observe anything
    that happens after it.

    Returns True if the caller may proceed to execute the side effect,
    False if it must not (a cancellation was observed here). Never
    rewrites the already-durable `AUTHORIZATION_COMMITTED` event --
    that event means "authorization was durably granted," not "the
    side effect definitely occurred," and those two facts stay
    separate. On a positive (blocking) result, durably records a
    SEPARATE `EXECUTION_CANCELLED_BEFORE_SIDE_EFFECT` event (best
    effort -- a failure to record this diagnostic marker still blocks
    the side effect; the return value alone is authoritative)."""
    if not is_cancelled(cancellation):
        return True

    from orca.godmode.contracts import ElevationAuditEvent, ElevationAuditEventType
    from orca.godmode.durable_audit import record_event_durable

    event = ElevationAuditEvent(
        event_type=ElevationAuditEventType.EXECUTION_CANCELLED_BEFORE_SIDE_EFFECT,
        principal_id=principal_id or "", tenant_id=tenant_id, lease_id=lease_id,
        capability=capability, resource_scope=resource_scope, operation_scope=operation_scope,
        trace_id=trace_id, result="CANCELLED",
    )
    try:
        record_event_durable(event)
    except Exception:
        pass  # best-effort diagnostic only -- blocking the side effect below is unconditional either way
    return False
