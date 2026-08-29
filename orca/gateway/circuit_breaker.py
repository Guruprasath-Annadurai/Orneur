"""
Bounded per-deployment circuit breaker. Repeated failures against ONE
deployment must not take down routing for every other deployment/model --
this is scoped per deployment_id, never a single global breaker.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class CircuitState(str, Enum):
    CLOSED = "CLOSED"        # normal operation
    OPEN = "OPEN"             # failing -- reject immediately without calling the runtime
    HALF_OPEN = "HALF_OPEN"   # probing -- allow one trial request through


@dataclass
class _BreakerState:
    state: str = CircuitState.CLOSED.value
    consecutive_failures: int = 0
    opened_at: float | None = None
    half_open_probe_in_flight: bool = False


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, open_duration_s: float = 30.0):
        self.failure_threshold = failure_threshold
        self.open_duration_s = open_duration_s
        self._breakers: dict[str, _BreakerState] = {}

    def _get(self, deployment_id: str) -> _BreakerState:
        if deployment_id not in self._breakers:
            self._breakers[deployment_id] = _BreakerState()
        return self._breakers[deployment_id]

    def allow_request(self, deployment_id: str) -> bool:
        b = self._get(deployment_id)
        if b.state == CircuitState.CLOSED.value:
            return True
        if b.state == CircuitState.OPEN.value:
            if b.opened_at is not None and (time.monotonic() - b.opened_at) >= self.open_duration_s:
                b.state = CircuitState.HALF_OPEN.value
                b.half_open_probe_in_flight = False
            else:
                return False
        if b.state == CircuitState.HALF_OPEN.value:
            # Only one probe request at a time in half-open -- everything
            # else keeps failing fast until the probe resolves.
            if b.half_open_probe_in_flight:
                return False
            b.half_open_probe_in_flight = True
            return True
        return False

    def record_success(self, deployment_id: str) -> None:
        b = self._get(deployment_id)
        b.consecutive_failures = 0
        b.state = CircuitState.CLOSED.value
        b.opened_at = None
        b.half_open_probe_in_flight = False

    def record_failure(self, deployment_id: str) -> None:
        b = self._get(deployment_id)
        if b.state == CircuitState.HALF_OPEN.value:
            # Probe failed -- reopen immediately, reset the clock.
            b.state = CircuitState.OPEN.value
            b.opened_at = time.monotonic()
            b.half_open_probe_in_flight = False
            return
        b.consecutive_failures += 1
        if b.consecutive_failures >= self.failure_threshold:
            b.state = CircuitState.OPEN.value
            b.opened_at = time.monotonic()

    def state(self, deployment_id: str) -> CircuitState:
        return CircuitState(self._get(deployment_id).state)
