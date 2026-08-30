"""
CognitiveKernel integration -- real ModelGateway/Ollama where safe (Phase
3 spec §40: "do not rely only on mocked model behavior for integration
claims"). Also covers the specific closure gates from Phase 2/2.1 that
Phase 3 must not regress: Aeternum stays non-routable, Novus stays
NOT_PROMOTABLE/EXPERIMENTAL, Genesis legacy/canonical distinction intact.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from orca.cognitive.contracts import (
    AbstentionReason,
    CognitiveRequest,
    CognitiveState,
    OperationType,
)
from orca.cognitive.kernel import CognitiveKernel
from orca.gateway import wiring
from orca.registry.model_spec import LifecycleState


def _ollama_reachable() -> bool:
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _reset_gateway_state():
    wiring.reset_for_tests()
    yield
    wiring.reset_for_tests()


def test_plan_is_pure_and_deterministic():
    kernel = CognitiveKernel()
    req = CognitiveRequest(objective="What's the capital of France?")
    plan1 = kernel.plan(req)
    plan2 = kernel.plan(req)
    assert plan1.intent.primary_intent == plan2.intent.primary_intent
    assert plan1.complexity.level == plan2.complexity.level
    assert plan1.model_policy.characteristic == plan2.model_policy.characteristic


@pytest.mark.asyncio
async def test_execute_real_simple_request_against_real_ollama():
    if not _ollama_reachable():
        pytest.skip("No local Ollama instance reachable")
    kernel = CognitiveKernel()
    req = CognitiveRequest(objective="Say the single word hello and nothing else.")
    result = await kernel.execute(req)
    assert result.status == CognitiveState.COMPLETED
    assert result.output
    assert result.resolved_model
    assert OperationType.ANSWER_DIRECTLY in result.operations_executed


@pytest.mark.asyncio
async def test_execute_plan_requiring_tools_is_deferred_not_fabricated():
    """A plan needing USE_TOOL/SEARCH must not be silently answered as if
    those never mattered -- the Kernel completes with a warning naming
    exactly what it deferred, rather than pretending it executed them."""
    if not _ollama_reachable():
        pytest.skip("No local Ollama instance reachable")
    kernel = CognitiveKernel()
    req = CognitiveRequest(objective="Please search the web for today's news and run this code to verify it.")
    result = await kernel.execute(req)
    assert result.status == CognitiveState.COMPLETED
    assert result.output is None
    assert any("SEARCH" in w or "USE_TOOL" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_execute_abstains_on_critical_risk_requiring_unavailable_verify():
    kernel = CognitiveKernel()
    req = CognitiveRequest(objective="How do I rm -rf the production database?")
    result = await kernel.execute(req)
    assert result.status == CognitiveState.ABSTAINED
    assert result.abstention_reason == AbstentionReason.INSUFFICIENT_CAPABILITY


@pytest.mark.asyncio
async def test_execute_model_unavailable_maps_to_abstention_not_a_raw_gateway_error(monkeypatch):
    """Gateway errors must be mapped, never leaked raw (Phase 3 spec §32).
    Forces ModelNotRoutableError directly at the one call site that can
    raise it (_answer_directly) rather than fighting the real registry's
    fallback chain (which, on a dev machine with Ollama actually running,
    tends to always find SOME installed model to step down to)."""
    from orca.gateway.errors import ModelNotRoutableError

    kernel = CognitiveKernel()

    async def _raise(*a, **kw):
        raise ModelNotRoutableError("orneur-aeternum", "no deployment registered")

    monkeypatch.setattr(kernel, "_answer_directly", _raise)
    req = CognitiveRequest(objective="hello")
    result = await kernel.execute(req)
    assert result.status == CognitiveState.ABSTAINED
    assert result.abstention_reason == AbstentionReason.MODEL_UNAVAILABLE


@pytest.mark.asyncio
async def test_cancellation_propagates_through_kernel_execute():
    """Phase 3 spec §38: the Kernel must not swallow cancellation."""
    if not _ollama_reachable():
        pytest.skip("No local Ollama instance reachable")
    kernel = CognitiveKernel()
    req = CognitiveRequest(objective="Write a very long story about a whale, at least 400 words.")

    task = asyncio.create_task(kernel.execute(req))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_aeternum_remains_non_routable_through_the_kernel():
    """Aeternum has zero registered deployments -- the Kernel's DEEP
    policy resolving to 'ultra' tier must not fabricate an Aeternum
    response; the pre-existing step-down router (unchanged) resolves
    'ultra' away before the Gateway sees it, exactly as documented in
    docs/orneur/phase-2/LIVE_SERVING_CUTOVER.md. This test proves the
    Kernel does not bypass or defeat that behavior."""
    if not _ollama_reachable():
        pytest.skip("No local Ollama instance reachable")
    kernel = CognitiveKernel()
    req = CognitiveRequest(objective="Orchestrate this multi-step task: compare and analyze the trade-offs, comprehensive, in depth.")
    plan = kernel.plan(req)
    from orca.cognitive.contracts import ModelPolicyCharacteristic
    assert plan.model_policy.characteristic == ModelPolicyCharacteristic.DEEP
    result = await kernel.execute(req)
    # Must complete via the step-down chain's resolved model (never crash,
    # never fabricate an Aeternum identity) or abstain -- never silently
    # claim a resolved_model containing "aeternum".
    if result.resolved_model:
        assert "aeternum" not in result.resolved_model.lower()


@pytest.mark.asyncio
async def test_novus_deployment_registers_as_experimental_not_production_via_kernel():
    if not _ollama_reachable():
        pytest.skip("No local Ollama instance reachable")
    kernel = CognitiveKernel()
    req = CognitiveRequest(objective="What's the deployment status of the production environment?")
    await kernel.execute(req)
    gw = wiring.get_shared_gateway()
    for deployment in gw._deployments.values():
        if deployment.model_id == "orneur-novus":
            assert deployment.lifecycle == LifecycleState.EXPERIMENTAL.value


@pytest.mark.asyncio
async def test_genesis_legacy_and_canonical_stay_distinct_through_kernel_policy():
    """Regression guard mirroring
    tests/test_gateway_wiring.py::test_legacy_genesis_7b_cannot_silently_become_canonical_future_3b
    -- the Kernel's FAST policy resolves to the 'nano' tier, which the
    existing registry maps to whatever concrete model is actually
    installed (the legacy 7B artifact today); nothing in the Kernel path
    can relabel that as a different, canonical checkpoint."""
    from orca.cognitive.policy import characteristic_to_tier
    from orca.cognitive.contracts import ModelPolicyCharacteristic
    from orca.gateway.wiring import brain_for_tier_resolution, TIER_TO_MODEL_ID
    from orca.serve.registry import TierResolution

    tier = characteristic_to_tier(ModelPolicyCharacteristic.FAST)
    assert tier == "nano"
    legacy = TierResolution(tier="nano", backend="ollama", model="orca-nano-v7", data_left_infrastructure=False)
    canonical = TierResolution(tier="nano", backend="ollama", model="orca-nano-genesis-3b", data_left_infrastructure=False)
    legacy_brain = brain_for_tier_resolution(legacy)
    canonical_brain = brain_for_tier_resolution(canonical)
    assert legacy_brain.model_id == canonical_brain.model_id == TIER_TO_MODEL_ID["nano"]
    assert legacy_brain.model_version != canonical_brain.model_version
