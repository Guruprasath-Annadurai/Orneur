"""
Centralized live-Ollama test support (Phase 3.2, see
docs/orneur/phase-3/OLLAMA_TEST_RELIABILITY.md). Replaces the same
`_ollama_reachable()` helper duplicated across 9 test files with one
shared implementation, and adds the two things root-cause analysis showed
were actually missing: a deliberate warmup step (so cold-load latency is
absorbed here, not charged against an arbitrary test's own timeout
budget) and a narrow, classified, bounded retry for genuinely transient
Gateway errors -- never a blind "retry until green."
"""
from __future__ import annotations

import time
from typing import Callable, TypeVar

import httpx
import pytest

from orca.gateway.errors import GenerationTimeoutError, QueueTimeoutError

_OLLAMA_HOST = "http://localhost:11434"
T = TypeVar("T")

# The only two InferenceErrorCode classes root-cause analysis
# (OLLAMA_TEST_RELIABILITY.md) actually observed under real resource
# contention on this shared machine -- genuinely transient (a retry can
# plausibly succeed), as opposed to e.g. MODEL_NOT_ROUTABLE or
# INVALID_PARAMETERS, which are deterministic application-logic outcomes
# a retry would never fix and must never be masked.
_TRANSIENT_ERRORS = (GenerationTimeoutError, QueueTimeoutError)


def ollama_reachable() -> bool:
    try:
        r = httpx.get(f"{_OLLAMA_HOST}/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def require_ollama() -> None:
    """Call at the top of a live-Ollama test body to skip (never fail)
    when no local Ollama instance is reachable."""
    if not ollama_reachable():
        pytest.skip("No local Ollama instance reachable")


def warm_model(tier: str = "nano", timeout: float = 90.0) -> None:
    """
    Deterministic readiness: issues one small, real, BACKGROUND-priority
    generation against the given tier BEFORE a test's own real assertions
    run, so a cold model load (evicted since a prior test, or never
    loaded this session) happens here -- in a dedicated, generously-timed
    warmup step -- rather than being silently absorbed into whichever
    test happens to run first and eating into its own timeout budget.
    Never raises: a warmup failure just means the test proceeds cold; the
    test's own real call still surfaces any genuine problem honestly.
    """
    try:
        from orca.gateway.wiring import brain_for_tier_resolution, get_shared_gateway
        from orca.serve.registry import resolve_tier_backend

        resolution = resolve_tier_backend(tier)
        brain = brain_for_tier_resolution(resolution, gateway=get_shared_gateway())
        brain.complete([{"role": "user", "content": "hi"}], max_tokens=4, timeout=timeout, priority="BACKGROUND")
    except Exception:
        pass


def retry_transient(fn: Callable[[], T], attempts: int = 2, backoff_s: float = 2.0, label: str = "") -> T:
    """
    Bounded, classified retry -- NOT a blind "retry 3 times" around an
    assertion (Phase 3.2 spec §8 explicitly forbids that). Retries ONLY
    when `fn()` raises one of `_TRANSIENT_ERRORS` (a real
    InferenceErrorCode this project's own Gateway already classifies as
    a timeout, not an application-logic failure). `attempts` is the total
    number of tries (default 2: one real attempt, one bounded retry);
    every retry is logged to stdout (pytest captures it, visible with
    -s or on failure) so a retry is never silent. Still raises -- the
    test still fails -- if the transient threshold is exceeded, or if
    `fn()` raises anything else at all.
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except _TRANSIENT_ERRORS as e:
            last_exc = e
            print(f"[retry_transient{f' {label}' if label else ''}] attempt {attempt}/{attempts} hit "
                  f"{type(e).__name__} ({e.code.value}) -- classified transient, "
                  f"{'retrying after backoff' if attempt < attempts else 'threshold exceeded, failing'}")
            if attempt < attempts:
                time.sleep(backoff_s)
    raise last_exc
