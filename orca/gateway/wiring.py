"""
Connects the EXISTING Orneur router (orca/serve/registry.py's
resolve_tier_backend/resolve_tier_model -- unchanged, untouched by this
phase) to the Model Gateway. This is the one and only place the live
serving path (orca/serve/api.py) touches to get a GatewayBrain instead of
constructing OrcaBrain/Backend directly.

Deliberate design: a single process-wide ModelGateway instance
(_SHARED_GATEWAY), with ModelDeployment records registered lazily/
idempotently on first use for whatever (backend, model) pair the existing
router resolves to. This preserves "the existing router chooses cognitive/
model policy; the gateway chooses eligible deployment/runtime" (per
instruction) without requiring a static startup bootstrap list -- the set
of models in play is already entirely config-driven (ORNEUR_*_MODEL env
vars, step-down fallback), so deployments are registered on demand instead
of duplicating that config here.
"""
from __future__ import annotations

import threading

from orca.config import CONFIG
from orca.gateway.compat_brain import GatewayBrain
from orca.gateway.deployment import DeploymentHealth, ModelDeployment
from orca.gateway.frontier_runtime import FrontierRuntime
from orca.gateway.gateway import ModelGateway
from orca.gateway.ollama_runtime import OllamaRuntime
from orca.registry.model_spec import LifecycleState
from orca.society.lifecycle import LEGACY_PRODUCTION_SERVING

TIER_TO_MODEL_ID = {"nano": "orneur-genesis", "core": "orneur-novus", "ultra": "orneur-aeternum"}

_lock = threading.Lock()
_gateway: ModelGateway | None = None
_ollama_runtime_registered = False
_frontier_runtimes_registered: set[str] = set()
# Phase 7.1 (spec §25-26): deployment_ids already persisted to disk this
# process -- `.save()` once per unique deployment, not on every single
# resolved request (this function runs on every live model call; an
# unconditional disk write per call would be real, needless I/O cost for
# a record that doesn't change between calls).
_deployments_persisted: set[str] = set()


def get_shared_gateway() -> ModelGateway:
    """
    The one ModelGateway instance the live serving path uses. Built lazily
    (not at import time) so tests can construct their own isolated
    ModelGateway instances without touching this module-level singleton at
    all -- only orca/serve/api.py's real request path calls this.
    """
    global _gateway, _ollama_runtime_registered
    with _lock:
        if _gateway is None:
            _gateway = ModelGateway()
        if not _ollama_runtime_registered:
            _gateway.register_runtime("ollama", OllamaRuntime(host=CONFIG.ollama.host))
            _ollama_runtime_registered = True
        return _gateway


def _ensure_frontier_runtime(gateway: ModelGateway, backend_name: str) -> None:
    with _lock:
        if backend_name in _frontier_runtimes_registered:
            return
        api_key = (
            CONFIG.backends.openai_api_key if backend_name == "openai"
            else CONFIG.backends.anthropic_api_key
        )
        gateway.register_runtime(backend_name, FrontierRuntime(backend_name, api_key))
        _frontier_runtimes_registered.add(backend_name)


def brain_for_tier_resolution(resolution, gateway: ModelGateway | None = None) -> GatewayBrain:
    """
    Takes a TierResolution (orca/serve/registry.py's existing output --
    tier/backend/model/data_left_infrastructure) and returns a GatewayBrain
    that will actually serve requests through the Model Gateway for that
    exact resolved backend+model.

    Registers (or re-registers -- idempotent) a ModelDeployment for this
    pair as EXPERIMENTAL lifecycle, honestly reflecting that nothing has
    cleared Phase 1's promotion gate yet (see
    docs/orneur/phase-2/LIVE_SERVING_CUTOVER.md's policy-decision section).
    Genesis/Novus/Aeternum's real family identity is preserved via
    TIER_TO_MODEL_ID -- this does NOT relabel a legacy 7B Genesis artifact
    as the canonical 3B target; it only tags which FAMILY is being served,
    the same distinction Phase 1's MODEL_SPECS already draws.
    """
    gw = gateway or get_shared_gateway()
    model_id = TIER_TO_MODEL_ID.get(resolution.tier, "orneur-novus")

    if resolution.backend == "ollama":
        deployment_id = f"ollama-{resolution.model}"
        # Phase 7.1 spec §25-26: Genesis's legacy checkpoint gets its own
        # truthful, disclosed lifecycle classification
        # (LEGACY_PRODUCTION_SERVING -- see orca.society.lifecycle's
        # docstring) rather than EXPERIMENTAL, precisely so that once this
        # record is persisted to disk (below) and Model Society's router
        # starts reading it, production requests for Genesis are NOT
        # suddenly rejected as "experimental lifecycle not permitted" --
        # that would be a real regression, not a safety improvement. Every
        # OTHER family (Novus, anything else) keeps the existing, correct
        # EXPERIMENTAL lifecycle -- this does not weaken Novus's gating.
        deployment_lifecycle = LEGACY_PRODUCTION_SERVING if model_id == "orneur-genesis" else LifecycleState.EXPERIMENTAL.value
        deployment = ModelDeployment(
            deployment_id=deployment_id,
            model_id=model_id,
            model_version=resolution.model,
            artifact_id=resolution.model,
            runtime="ollama",
            runtime_endpoint=CONFIG.ollama.host,
            # Honest -- no GPU/hardware claim is made; "local" only means
            # "this machine's local Ollama install," not a verified spec.
            hardware_profile="local",
            lifecycle=deployment_lifecycle,
            health=DeploymentHealth.READY.value,
            warmup_completed=True,
            max_concurrency=4,
            context_limit=CONFIG.brain.context_length,
        )
        gw.register_deployment(deployment)
        if deployment_id not in _deployments_persisted:
            deployment.save()
            _deployments_persisted.add(deployment_id)
        return GatewayBrain(gw, model_id, resolution.model, allow_experimental=True)

    _ensure_frontier_runtime(gw, resolution.backend)
    deployment_id = f"{resolution.backend}-{resolution.model}"
    gw.register_deployment(ModelDeployment(
        deployment_id=deployment_id,
        model_id=model_id,
        model_version=resolution.model,
        artifact_id=resolution.model,
        runtime=resolution.backend,
        runtime_endpoint=resolution.backend,
        hardware_profile="cloud-api",
        lifecycle=LifecycleState.EXPERIMENTAL.value,
        health=DeploymentHealth.READY.value,
        warmup_completed=True,
        max_concurrency=8,
        context_limit=128000,
    ))
    return GatewayBrain(gw, model_id, resolution.model, allow_experimental=True)


def reset_for_tests() -> None:
    """Test-only: clears the module-level singleton so tests don't leak
    registered runtimes/deployments across test files."""
    global _gateway, _ollama_runtime_registered, _frontier_runtimes_registered, _deployments_persisted
    with _lock:
        _gateway = None
        _ollama_runtime_registered = False
        _frontier_runtimes_registered = set()
        _deployments_persisted = set()
