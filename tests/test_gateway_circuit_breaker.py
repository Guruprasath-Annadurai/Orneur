from __future__ import annotations

from orca.gateway.circuit_breaker import CircuitBreaker, CircuitState


def test_starts_closed():
    cb = CircuitBreaker(failure_threshold=3, open_duration_s=10)
    assert cb.state("dep-1") == CircuitState.CLOSED
    assert cb.allow_request("dep-1") is True


def test_opens_after_threshold_failures():
    cb = CircuitBreaker(failure_threshold=3, open_duration_s=10)
    for _ in range(3):
        cb.record_failure("dep-1")
    assert cb.state("dep-1") == CircuitState.OPEN
    assert cb.allow_request("dep-1") is False


def test_success_resets_failure_count():
    cb = CircuitBreaker(failure_threshold=3, open_duration_s=10)
    cb.record_failure("dep-1")
    cb.record_failure("dep-1")
    cb.record_success("dep-1")
    cb.record_failure("dep-1")
    # Only 1 failure since the reset -- must still be closed.
    assert cb.state("dep-1") == CircuitState.CLOSED


def test_transitions_to_half_open_after_duration(monkeypatch):
    cb = CircuitBreaker(failure_threshold=1, open_duration_s=0.0)
    cb.record_failure("dep-1")
    assert cb.state("dep-1") == CircuitState.OPEN
    # open_duration_s=0 -- next allow_request check sees the duration elapsed.
    assert cb.allow_request("dep-1") is True
    assert cb.state("dep-1") == CircuitState.HALF_OPEN


def test_half_open_probe_failure_reopens():
    cb = CircuitBreaker(failure_threshold=1, open_duration_s=0.0)
    cb.record_failure("dep-1")
    cb.allow_request("dep-1")  # transitions to HALF_OPEN, consumes the probe slot
    assert cb.state("dep-1") == CircuitState.HALF_OPEN
    cb.record_failure("dep-1")
    assert cb.state("dep-1") == CircuitState.OPEN


def test_half_open_probe_success_closes():
    cb = CircuitBreaker(failure_threshold=1, open_duration_s=0.0)
    cb.record_failure("dep-1")
    cb.allow_request("dep-1")
    cb.record_success("dep-1")
    assert cb.state("dep-1") == CircuitState.CLOSED


def test_half_open_only_allows_one_probe_at_a_time():
    cb = CircuitBreaker(failure_threshold=1, open_duration_s=0.0)
    cb.record_failure("dep-1")
    assert cb.allow_request("dep-1") is True   # first probe allowed
    assert cb.allow_request("dep-1") is False  # second concurrent probe rejected


def test_breakers_are_isolated_per_deployment():
    cb = CircuitBreaker(failure_threshold=1, open_duration_s=100)
    cb.record_failure("dep-A")
    assert cb.state("dep-A") == CircuitState.OPEN
    assert cb.state("dep-B") == CircuitState.CLOSED
    assert cb.allow_request("dep-B") is True
