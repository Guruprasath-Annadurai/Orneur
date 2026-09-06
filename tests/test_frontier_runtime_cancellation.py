"""
Phase 13 §24: verify or disprove the Phase-11.2-analogous
CancelledError -> RequestCancelledError risk in
orca/gateway/frontier_runtime.py, rather than assuming the Ollama fix
automatically applies.

Finding (see docs/orneur/phase-13/FINDINGS.md for the full writeup):
frontier_runtime.py's generate() has NO `except asyncio.CancelledError`
clause at all -- its only except clause is `except Exception as e:`, and
since Python 3.8 `asyncio.CancelledError` is a `BaseException` subclass,
NOT an `Exception` subclass, that broad except cannot catch it. A genuine
`asyncio.CancelledError` therefore propagates untouched through
`generate()`, so an enclosing `asyncio.wait_for()`'s own deadline-to-
TimeoutError conversion works correctly here -- this is the DISPROVED
case, confirmed with a real timing test below (not just static reading),
not a bug carried over from ollama_runtime.py.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from orca.gateway.contracts import InferenceRequest
from orca.gateway.errors import RequestCancelledError, RuntimeExecutionError
from orca.gateway.frontier_runtime import FrontierRuntime


class _SlowBackend:
    name = "fake-slow-backend"

    def generate(self, prompt, system="", max_tokens=1024, temperature=0.7):
        time.sleep(2.0)  # genuinely blocks the worker thread past the test's short timeout
        from orca.brain.backends import BackendResponse
        return BackendResponse(
            text="late response", backend="openai", model="fake-model",
            input_tokens=1, output_tokens=1, cost_usd=0.0, latency_ms=2000.0,
            data_left_infrastructure=True,
        )


def _req(**overrides):
    defaults = dict(request_id="req-frontier-1", model_id="gpt-test", messages=[{"role": "user", "content": "hi"}], max_tokens=5)
    defaults.update(overrides)
    return InferenceRequest(**defaults)


@pytest.mark.asyncio
async def test_outer_wait_for_timeout_produces_real_timeout_not_a_cancelled_error_disguise(monkeypatch):
    """The core Phase 13 §24 question: does an enclosing asyncio.wait_for()
    deadline correctly become asyncio.TimeoutError, or does it get
    disguised as RequestCancelledError the way ollama_runtime.py's old bug
    did? Real timing, real thread, real cancellation -- not a mock of
    asyncio's own behavior."""
    import orca.gateway.frontier_runtime as frontier_mod
    monkeypatch.setattr(frontier_mod, "build_backend", lambda *a, **kw: _SlowBackend())

    runtime = FrontierRuntime(backend_name="openai", api_key="fake-key")
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(runtime.generate(_req()), timeout=0.1)


@pytest.mark.asyncio
async def test_explicit_task_cancel_produces_real_cancelled_error_not_disguised(monkeypatch):
    """A direct task.cancel() (not a wait_for deadline) must also surface
    as genuine asyncio.CancelledError, not RequestCancelledError or
    RuntimeExecutionError -- distinguishing CANCELLED from TIMEOUT per
    spec §24's explicit requirement."""
    import orca.gateway.frontier_runtime as frontier_mod
    monkeypatch.setattr(frontier_mod, "build_backend", lambda *a, **kw: _SlowBackend())

    runtime = FrontierRuntime(backend_name="openai", api_key="fake-key")
    task = asyncio.create_task(runtime.generate(_req(request_id="req-frontier-2")))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_explicit_pre_check_cancellation_still_raises_request_cancelled_error(monkeypatch):
    """The ONE genuine cancellation path frontier_runtime.py implements:
    a request_id explicitly marked via .cancel() BEFORE generate() starts.
    This is deliberate application-level cancellation, correctly
    RequestCancelledError -- distinct from the two tests above, which
    prove asyncio-level cancellation is NOT disguised as this."""
    import orca.gateway.frontier_runtime as frontier_mod
    monkeypatch.setattr(frontier_mod, "build_backend", lambda *a, **kw: _SlowBackend())

    runtime = FrontierRuntime(backend_name="openai", api_key="fake-key")
    await runtime.cancel("req-frontier-3")
    with pytest.raises(RequestCancelledError):
        await runtime.generate(_req(request_id="req-frontier-3"))


@pytest.mark.asyncio
async def test_genuine_backend_exception_still_raises_runtime_execution_error(monkeypatch):
    """Confirms the except Exception clause still does its intended job
    for a REAL (non-cancellation) backend failure -- proving the fix
    analysis isn't just "nothing is caught," but that Exception-derived
    errors are still correctly wrapped."""
    class _BrokenBackend:
        name = "broken"

        def generate(self, prompt, system="", max_tokens=1024, temperature=0.7):
            raise ValueError("simulated real backend failure")

    import orca.gateway.frontier_runtime as frontier_mod
    monkeypatch.setattr(frontier_mod, "build_backend", lambda *a, **kw: _BrokenBackend())

    runtime = FrontierRuntime(backend_name="openai", api_key="fake-key")
    with pytest.raises(RuntimeExecutionError):
        await runtime.generate(_req(request_id="req-frontier-4"))
