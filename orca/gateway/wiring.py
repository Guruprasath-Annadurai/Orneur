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

import logging
import threading

from orca.config import CONFIG, orneur_env
from orca.gateway.compat_brain import GatewayBrain
from orca.gateway.deployment import DeploymentHealth, ModelDeployment
from orca.gateway.frontier_runtime import FrontierRuntime
from orca.gateway.gateway import ModelGateway
from orca.gateway.ollama_runtime import OllamaRuntime
from orca.registry.model_spec import LifecycleState
from orca.society.lifecycle import LEGACY_PRODUCTION_SERVING

log = logging.getLogger(__name__)

_TRUTHY = ("1", "true", "yes")


def public_edge_enabled() -> bool:
    """Same switch the API uses (`ORNEUR_PUBLIC_EDGE`): this deployment is, or will be, reachable by the public."""
    return orneur_env("PUBLIC_EDGE", "").strip().lower() in _TRUTHY


def experimental_serving_acknowledged() -> bool:
    """`ORNEUR_ALLOW_EXPERIMENTAL_SERVING` is **reported, never honoured**: an environment variable is not evidence, so it cannot authorize an
    unqualified model for public use. Public serving of an EXPERIMENTAL self-hosted model requires a signed public-serving grant
    (orca/gateway/serving_authority.py)."""
    return orneur_env("ALLOW_EXPERIMENTAL_SERVING", "").strip().lower() in _TRUTHY


def experimental_self_hosted_allowed() -> bool:
    """Blanket policy for self-hosted (Ollama) models whose lifecycle is EXPERIMENTAL.

    * Local / private deployments (no public edge): allowed, as before -- developers run what they have.
    * Public edge: NOT allowed as a blanket policy under any flag. A specific model/artifact/user may still be served under a verified
      public-serving grant; that decision is made per request in `brain_for_tier_resolution`.
    Frontier backends are unaffected: they are not ORNEUR-trained and already carry a per-response transparency notice."""
    return not public_edge_enabled()


def serving_policy() -> dict:
    from orca.gateway import serving_authority as sa

    registry, grants, _revoked = sa.load_trust_files()
    n_grants = len(grants.get("grants", [])) if isinstance(grants, dict) else 0
    return {
        "public_edge": public_edge_enabled(),
        "experimental_self_hosted_models_served": experimental_self_hosted_allowed(),
        "operator_acknowledged_experimental_serving": experimental_serving_acknowledged(),
        "experimental_flag_has_authorizing_effect": False,
        "public_serving_grants_on_file": n_grants,
        "note": ("EXPERIMENTAL self-hosted models are not served on a public edge unless a signed, unexpired public-serving grant matches the "
                 "exact model artifact and user; ORNEUR_ALLOW_EXPERIMENTAL_SERVING is ignored; no ORNEUR model has been promoted to PRODUCTION."),
    }


_DIGEST_TTL_SECONDS = 15.0
_digest_cache: tuple | None = None   # (monotonic_ts, host, {tag -> "sha256:<hex>"})


def installed_digests(host: str) -> dict | None:
    """Digest Ollama reports for each installed tag (cached briefly). None = runtime unreachable -> callers fail closed."""
    import time

    import httpx

    global _digest_cache
    now = time.monotonic()
    if _digest_cache and _digest_cache[1] == host and now - _digest_cache[0] < _DIGEST_TTL_SECONDS:
        return _digest_cache[2]
    try:
        r = httpx.get(f"{host.rstrip('/')}/api/tags", timeout=5)
        r.raise_for_status()
        out = {}
        for m in r.json().get("models", []):
            d = str(m.get("digest") or "")
            out[m["name"]] = d if d.startswith("sha256:") else f"sha256:{d}"
    except Exception:
        return None
    _digest_cache = (now, host, out)
    return out


def _digest_for(host: str, tag: str) -> str | None:
    digests = installed_digests(host)
    if not digests:
        return None
    return digests.get(tag) or digests.get(f"{tag}:latest")


def _viewer_for(user_id: str | None):
    from orca.gateway.serving_authority import Viewer

    if not user_id:
        return Viewer()
    try:
        from orca.auth.store import get_user_by_id

        u = get_user_by_id(user_id)
        return Viewer(user_id=user_id, signup_seq=u.signup_seq if u else None)
    except Exception:
        return Viewer(user_id=user_id)


def public_serving_decision(tier: str, ollama_tag: str, viewer_user_id: str | None = None):
    """What may be said and served for this tier/tag right now (also used to tell `/api/models` clients the truth)."""
    from orca.gateway import serving_authority as sa

    model_family = TIER_TO_MODEL_ID.get(tier, "orneur-novus")
    edge = public_edge_enabled()
    legacy = tier == "nano" and model_family == sa.LEGACY_GENESIS_FAMILY and ollama_tag in sa.LEGACY_GENESIS_ARTIFACTS
    digest = _digest_for(CONFIG.ollama.host, ollama_tag) if (edge and not legacy) else None
    return sa.decide_self_hosted(
        model_family=model_family, tier=tier, ollama_tag=ollama_tag, public_edge=edge, viewer=_viewer_for(viewer_user_id), installed_digest=digest,
    )


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


def brain_for_tier_resolution(resolution, gateway: ModelGateway | None = None, viewer_user_id: str | None = None) -> GatewayBrain:
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
        # The lifecycle is decided from verified identity, not from the tier name (see orca/gateway/serving_authority.py): only the pinned
        # legacy Genesis artifact keeps the disclosed LEGACY_PRODUCTION_SERVING classification (PR #25 founder decision); every other
        # self-hosted model is EXPERIMENTAL and, on a public edge, is served only under a verified public-serving grant.
        decision = public_serving_decision(resolution.tier, resolution.model, viewer_user_id)
        deployment_lifecycle = LEGACY_PRODUCTION_SERVING if decision.lifecycle == "LEGACY_PRODUCTION_SERVING" else LifecycleState.EXPERIMENTAL.value
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
        allow_experimental = decision.allowed
        if not decision.allowed:
            log.warning("not serving %r (tier %s) on a public edge: %s", resolution.model, resolution.tier, decision.reason)
        elif public_edge_enabled() and deployment_lifecycle == LifecycleState.EXPERIMENTAL.value:
            log.warning("serving EXPERIMENTAL model %r on a PUBLIC edge under grant %s (label: %s)", resolution.model, decision.grant_id, decision.label)
        return GatewayBrain(gw, model_id, resolution.model, allow_experimental=allow_experimental)

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
