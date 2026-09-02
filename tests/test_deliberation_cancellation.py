"""
Phase 6 spec §49: cancellation must propagate through Constructor/
Falsifier/Court, no orphan tasks. Court is a plain `async def` awaiting
ModelGateway calls directly, so a cancelled asyncio.Task propagates
CancelledError the same way Truth Fabric/Memory Continuum's own async
work already does (Phase 4's proven pattern) -- verified directly.
"""
from __future__ import annotations

import asyncio

import pytest

from orca.cognitive.contracts import RiskLevel
from orca.deliberation.court import CognitiveCourt
from orca.gateway import wiring as gateway_wiring
from tests.ollama_test_support import require_ollama, warm_model

pytestmark = pytest.mark.live_ollama_smoke


@pytest.fixture(autouse=True)
def _reset_gateway():
    gateway_wiring.reset_for_tests()
    yield
    gateway_wiring.reset_for_tests()


@pytest.mark.asyncio
async def test_cancellation_propagates_through_court():
    require_ollama()
    warm_model("nano")
    court = CognitiveCourt()
    task = asyncio.create_task(court.run("Where is the Eiffel Tower located?", truth_result=None, risk_level=RiskLevel.LOW))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
