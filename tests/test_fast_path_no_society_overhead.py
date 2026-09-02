"""
Phase 7.1 spec §45: simple conversational requests must not build a
SocietyPlan, populate WorldState, replan, or invoke Court. Proven
directly: `CognitiveCourt.run()` (the only place WorldState/SocietyPlan
are built) is never called for a DIRECT-mode request, verified by
monkeypatching it to raise if called at all.
"""
from __future__ import annotations

import time

import pytest

from orca.cognitive.contracts import ComplexityLevel, EvidenceLevel, RiskLevel
from orca.deliberation.compiler import compile_reasoning_plan


def test_simple_request_does_not_require_court():
    plan = compile_reasoning_plan("Thanks, that's helpful!", ComplexityLevel.LOW, RiskLevel.LOW, EvidenceLevel.NONE)
    assert not plan.requires_court
    assert plan.mode.value == "DIRECT"


@pytest.mark.asyncio
async def test_kernel_never_calls_court_for_a_direct_request(monkeypatch):
    """If CognitiveCourt.run() were ever invoked for this request, it
    would build a WorldState and a SocietyPlan -- this test proves that
    code path is never reached at all for a simple objective, by making
    CognitiveCourt.run() raise if called."""
    import orca.deliberation.court as court_mod
    import orca.truth.truth_fabric as truth_mod
    import orca.cognitive.kernel as kernel_mod

    async def _must_not_be_called(self, *args, **kwargs):
        raise AssertionError("CognitiveCourt.run() must not be called for a simple/direct request")

    monkeypatch.setattr(court_mod.CognitiveCourt, "run", _must_not_be_called)

    async def fake_answer_directly(self, objective, tier, trace_id):
        return "Hi there!", "orneur-genesis", {"prompt_tokens": 1, "completion_tokens": 1}

    monkeypatch.setattr(kernel_mod.CognitiveKernel, "_answer_directly", fake_answer_directly)

    from orca.cognitive.kernel import CognitiveKernel
    from orca.cognitive.contracts import CognitiveRequest

    kernel = CognitiveKernel()
    req = CognitiveRequest(objective="Thanks, that's helpful!")
    result = await kernel.execute(req)  # no doc_store -> plain direct-answer path, not even Truth Fabric
    assert result.status is not None  # completes without ever touching Court


def test_reasoning_compiler_overhead_is_negligible_for_direct_mode():
    samples = []
    for _ in range(200):
        t0 = time.perf_counter()
        compile_reasoning_plan("Thanks, that's helpful!", ComplexityLevel.LOW, RiskLevel.LOW, EvidenceLevel.NONE)
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    p50 = samples[len(samples) // 2]
    assert p50 < 1.0  # sub-millisecond, matching Phase 6/7's own measured baseline
