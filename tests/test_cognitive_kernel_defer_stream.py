"""G-026: Kernel may plan a direct answer without calling generate()."""
from __future__ import annotations

import pytest

from orca.cognitive.contracts import CognitiveRequest, CognitiveState
from orca.cognitive.kernel import CognitiveKernel


@pytest.mark.asyncio
async def test_defer_direct_generation_does_not_call_generate(monkeypatch):
    kernel = CognitiveKernel()

    def boom(*_a, **_k):
        raise AssertionError("ModelGateway.generate must not run when generation is deferred")

    monkeypatch.setattr(kernel._gateway(), "generate", boom)
    result = await kernel.execute(
        CognitiveRequest(objective="hello there"),
        defer_direct_generation=True,
    )
    assert result.status == CognitiveState.COMPLETED
    assert result.output is None
    assert result.pending_direct_generation is True
    assert result.pending_direct_objective
    assert result.resolved_tier


