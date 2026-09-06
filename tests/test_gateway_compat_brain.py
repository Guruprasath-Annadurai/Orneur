"""
GatewayBrain must satisfy the EXACT interface orca.brain.providers.OrcaBrain
already exposes to AgentLoop -- .complete() returns a plain str, .stream()
yields plain str chunks (not InferenceChunk objects), .is_available()
returns bool, .name/.model are properties. These tests verify interface
compatibility using a fake gateway/runtime (deterministic), plus one real
end-to-end test through the actual OllamaRuntime against this machine's
live Ollama instance (skipped if unreachable).
"""
from __future__ import annotations

import httpx
import pytest

from orca.gateway.compat_brain import GatewayBrain
from orca.gateway.deployment import DeploymentHealth, ModelDeployment
from orca.gateway.gateway import ModelGateway
from orca.gateway.ollama_runtime import OllamaRuntime
from orca.registry.model_spec import LifecycleState
from tests.ollama_test_support import retry_transient
from tests.test_gateway_model_gateway import _FakeRuntime


def _gw_with_deployment(runtime, lifecycle=LifecycleState.EXPERIMENTAL.value):
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_deployment(ModelDeployment(
        deployment_id="dep-1", model_id="orneur-novus", model_version="fake-checkpoint",
        artifact_id="fake-checkpoint", runtime="fake", runtime_endpoint="fake://local",
        hardware_profile="test", lifecycle=lifecycle, health=DeploymentHealth.READY.value,
        warmup_completed=True, context_limit=8192,
    ))
    return gw


def test_complete_returns_plain_string():
    runtime = _FakeRuntime()
    gw = _gw_with_deployment(runtime)
    brain = GatewayBrain(gw, "orneur-novus")

    result = brain.complete([{"role": "user", "content": "hi"}])
    assert isinstance(result, str)
    assert result == "hello world"


def test_stream_yields_plain_string_chunks_not_objects():
    runtime = _FakeRuntime(chunks=["a", "b", "c"])
    gw = _gw_with_deployment(runtime)
    brain = GatewayBrain(gw, "orneur-novus")

    chunks = list(brain.stream([{"role": "user", "content": "hi"}]))
    assert all(isinstance(c, str) for c in chunks)
    assert "".join(chunks) == "abc"


def test_is_available_true_for_routable_deployment():
    runtime = _FakeRuntime()
    gw = _gw_with_deployment(runtime)
    brain = GatewayBrain(gw, "orneur-novus")
    assert brain.is_available() is True


def test_is_available_false_for_unroutable_model():
    gw = ModelGateway()  # no deployments registered at all -- Aeternum-shaped
    brain = GatewayBrain(gw, "orneur-aeternum", allow_experimental=False)
    assert brain.is_available() is False


def test_is_available_false_when_production_required_but_only_experimental_exists():
    runtime = _FakeRuntime()
    gw = _gw_with_deployment(runtime, lifecycle=LifecycleState.EXPERIMENTAL.value)
    strict_brain = GatewayBrain(gw, "orneur-novus", allow_experimental=False)
    assert strict_brain.is_available() is False

    lenient_brain = GatewayBrain(gw, "orneur-novus", allow_experimental=True)
    assert lenient_brain.is_available() is True


def test_name_and_model_properties():
    runtime = _FakeRuntime()
    gw = _gw_with_deployment(runtime)
    brain = GatewayBrain(gw, "orneur-novus", model_version="fake-checkpoint")
    assert brain.model == "fake-checkpoint"
    assert brain.name == "fake-checkpoint"


def test_complete_raises_when_model_not_routable():
    from orca.gateway.errors import InferenceError
    gw = ModelGateway()
    brain = GatewayBrain(gw, "orneur-aeternum", allow_experimental=False)
    with pytest.raises(InferenceError):
        brain.complete([{"role": "user", "content": "hi"}])


# --------------------------------------------------------------- live test --

async def _ollama_reachable() -> bool:
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("http://localhost:11434/api/tags", timeout=2)
            return r.status_code == 200
    except Exception:
        return False


@pytest.mark.asyncio
async def test_live_gateway_brain_end_to_end_matches_orca_brain_interface():
    """
    The real, full chain: GatewayBrain -> ModelGateway -> OllamaRuntime ->
    real local Ollama, driven exactly the way AgentLoop actually calls it
    (synchronous .complete()/.stream(), from what will be the FastAPI
    request thread in production). Skipped if no Ollama instance is
    reachable.
    """
    if not await _ollama_reachable():
        pytest.skip("No local Ollama instance reachable -- skipping live integration test")

    import asyncio

    gw = ModelGateway()
    gw.register_runtime("ollama", OllamaRuntime(host="http://localhost:11434", timeout_s=90.0))
    gw.register_deployment(ModelDeployment(
        deployment_id="ollama-orca-nano-v7", model_id="orneur-genesis", model_version="orca-nano-v7",
        artifact_id="orca-nano-v7", runtime="ollama", runtime_endpoint="http://localhost:11434",
        hardware_profile="local", lifecycle=LifecycleState.EXPERIMENTAL.value,
        health=DeploymentHealth.READY.value, warmup_completed=True, context_limit=8192,
    ))
    brain = GatewayBrain(gw, "orneur-genesis", model_version="orca-nano-v7")

    # Run the SYNCHRONOUS calls the way AgentLoop actually does, from a
    # worker thread (asyncio.to_thread), matching orca/serve/api.py's real
    # usage pattern (`await asyncio.to_thread(lambda: sess.agent.stream(...))`).
    def _sync_complete():
        return brain.complete([{"role": "user", "content": "Say the word OK."}], max_tokens=5)

    # Phase 3.2 (docs/orneur/phase-3/OLLAMA_TEST_RELIABILITY.md): this
    # test constructs a brand-new ModelGateway/OllamaRuntime rather than
    # reusing the process-wide warm singleton, so if this exact model was
    # evicted since a prior test (Ollama's default keep_alive), the FIRST
    # call here pays a real cold-load cost from disk -- root-cause
    # analysis measured this occasionally exceeding the runtime's own
    # timeout under real memory pressure on this shared machine, despite
    # requesting only 5 tokens. Bounded, classified retry (2 attempts,
    # GenerationTimeoutError/QueueTimeoutError ONLY) rather than a longer
    # timeout, since the failure mode is "the first call happened to be
    # the unlucky cold one," not "90s is too short for 5 tokens."
    result = await asyncio.to_thread(lambda: retry_transient(_sync_complete, attempts=2, label="compat_brain_e2e"))
    assert isinstance(result, str)

    def _sync_stream():
        return list(brain.stream([{"role": "user", "content": "Count to three."}], max_tokens=10))

    chunks = await asyncio.to_thread(_sync_stream)
    assert all(isinstance(c, str) for c in chunks)


# ── Phase 3.2 regression: background work must not contend at INTERACTIVE priority ──

def test_complete_defaults_to_interactive_priority_unchanged():
    """Every existing caller that doesn't pass `priority` must see byte-
    for-byte the same InferenceRequest.priority as before this phase."""
    from orca.gateway.contracts import RequestPriority

    runtime = _FakeRuntime()
    gw = _gw_with_deployment(runtime)
    brain = GatewayBrain(gw, "orneur-novus")

    brain.complete([{"role": "user", "content": "hi"}])
    assert runtime.last_request.priority == RequestPriority.INTERACTIVE


def test_complete_honors_explicit_background_priority():
    from orca.gateway.contracts import RequestPriority

    runtime = _FakeRuntime()
    gw = _gw_with_deployment(runtime)
    brain = GatewayBrain(gw, "orneur-novus")

    brain.complete([{"role": "user", "content": "hi"}], priority="BACKGROUND")
    assert runtime.last_request.priority == RequestPriority.BACKGROUND


def test_knowledge_graph_extraction_defaults_to_background_priority():
    """The actual bug found in Phase 3.2 root-cause analysis: fire-and-
    forget KG extraction (orca/serve/api.py) previously contended for a
    deployment's bounded concurrency permits at the SAME priority as real
    foreground user requests. extract_and_add() must now default to
    BACKGROUND so it never elevates itself to INTERACTIVE by omission."""
    from orca.brain.knowledge_graph import KnowledgeGraph
    from orca.gateway.contracts import RequestPriority

    runtime = _FakeRuntime(chunks=["[]"])
    gw = _gw_with_deployment(runtime)
    brain = GatewayBrain(gw, "orneur-novus")

    kg = KnowledgeGraph(session_id="test-session")
    kg.extract_and_add("some conversation text", "chat", brain)

    assert runtime.last_request.priority == RequestPriority.BACKGROUND
