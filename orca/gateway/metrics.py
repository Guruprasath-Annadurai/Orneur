"""
Model Gateway observability -- same style/pattern as orca/serve/metrics.py
(in-memory, single-instance, never raises, thread-locked bounded counters)
rather than a separate, incompatible observability island. A future pass
can fold these into that module's /metrics Prometheus output; kept
separate for now so gateway.py has no import-time dependency on the
serve/ package (the gateway is meant to be usable independent of the HTTP
layer).
"""
from __future__ import annotations

import threading
from collections import defaultdict, deque

_lock = threading.Lock()

_request_count: dict[str, int] = defaultdict(int)          # keyed by deployment_id
_success_count: dict[str, int] = defaultdict(int)
_failure_count: dict[str, int] = defaultdict(int)
_cancellation_count: dict[str, int] = defaultdict(int)
_timeout_count: dict[str, int] = defaultdict(int)
_retry_count: dict[str, int] = defaultdict(int)
_queue_latency_ms: dict[str, deque] = defaultdict(lambda: deque(maxlen=2000))
_total_latency_ms: dict[str, deque] = defaultdict(lambda: deque(maxlen=2000))
_ttft_ms: dict[str, deque] = defaultdict(lambda: deque(maxlen=2000))
_tokens_generated: dict[str, int] = defaultdict(int)
_circuit_state_changes: dict[str, int] = defaultdict(int)


def record_request(deployment_id: str) -> None:
    try:
        with _lock:
            _request_count[deployment_id] += 1
    except Exception:
        pass


def record_success(deployment_id: str, total_latency_ms: float, queue_latency_ms: float, completion_tokens: int) -> None:
    try:
        with _lock:
            _success_count[deployment_id] += 1
            _total_latency_ms[deployment_id].append(total_latency_ms)
            _queue_latency_ms[deployment_id].append(queue_latency_ms)
            _tokens_generated[deployment_id] += completion_tokens
    except Exception:
        pass


def record_failure(deployment_id: str, error_code: str) -> None:
    try:
        with _lock:
            _failure_count[f"{deployment_id}:{error_code}"] += 1
    except Exception:
        pass


def record_cancellation(deployment_id: str) -> None:
    try:
        with _lock:
            _cancellation_count[deployment_id] += 1
    except Exception:
        pass


def record_timeout(deployment_id: str, timeout_category: str) -> None:
    try:
        with _lock:
            _timeout_count[f"{deployment_id}:{timeout_category}"] += 1
    except Exception:
        pass


def record_retry(deployment_id: str) -> None:
    try:
        with _lock:
            _retry_count[deployment_id] += 1
    except Exception:
        pass


def record_ttft(deployment_id: str, ttft_ms: float) -> None:
    try:
        with _lock:
            _ttft_ms[deployment_id].append(ttft_ms)
    except Exception:
        pass


def record_circuit_state_change(deployment_id: str) -> None:
    try:
        with _lock:
            _circuit_state_changes[deployment_id] += 1
    except Exception:
        pass


def _avg(samples: deque) -> float:
    return round(sum(samples) / len(samples), 2) if samples else 0.0


def get_snapshot() -> dict:
    with _lock:
        deployments = set(_request_count) | set(_success_count) | set(_total_latency_ms)
        return {
            "per_deployment": {
                d: {
                    "requests": _request_count.get(d, 0),
                    "successes": _success_count.get(d, 0),
                    "cancellations": _cancellation_count.get(d, 0),
                    "retries": _retry_count.get(d, 0),
                    "tokens_generated": _tokens_generated.get(d, 0),
                    "avg_total_latency_ms": _avg(_total_latency_ms.get(d, deque())),
                    "avg_queue_latency_ms": _avg(_queue_latency_ms.get(d, deque())),
                    "avg_ttft_ms": _avg(_ttft_ms.get(d, deque())),
                }
                for d in deployments
            },
            "failures_by_code": dict(_failure_count),
            "timeouts_by_category": dict(_timeout_count),
        }


def reset() -> None:
    """Test-only helper -- mirrors orca/serve/metrics.py's reset()."""
    with _lock:
        for d in (_request_count, _success_count, _failure_count, _cancellation_count,
                  _timeout_count, _retry_count, _tokens_generated, _circuit_state_changes):
            d.clear()
        for d in (_queue_latency_ms, _total_latency_ms, _ttft_ms):
            d.clear()
