"""
Orca Model Registry — resolves a tier name (nano/core/ultra) to a concrete
Ollama model that is actually installed right now, with a strict step-down
fallback when the configured model for a tier doesn't exist yet.

Why this exists: `OrcaBrain._resolve_model()` (orca/brain/providers.py) only
falls back to a best-available open model when NO model name is requested.
The serving path always resolves a concrete name first (via CONFIG.ollama.*),
so a misconfigured or not-yet-fine-tuned tier (e.g. ultra, before Aeternum's
fine-tune exists) previously hard-crashed the whole request with a
RuntimeError instead of degrading gracefully. This module is what
`_model_name_for_variant` in orca/serve/api.py should call instead of
reading CONFIG directly.

Fallback direction is deliberate: ultra -> core -> nano -> best open model,
never the reverse. A user who can't get ultra should get a working answer
from a lesser tier, not silence; a user asking for nano should never be
silently upgraded to a paid tier's model (that would be a plan-gating leak,
not a convenience).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

import httpx

from orca.config import CONFIG

# Order matters: index 0 is the most-preferred step-down target for ultra,
# etc. Nano has nowhere further to step down to except a generic open model.
_STEP_DOWN: dict[str, list[str]] = {
    "ultra": ["core", "nano"],
    "core":  ["nano"],
    "nano":  [],
}

_TAGS_CACHE_TTL_SECONDS = 15.0
_tags_cache: tuple[float, list[str]] | None = None


def _list_installed_models(host: str) -> list[str]:
    """Cached `ollama list` (via /api/tags) — avoids hitting Ollama on every
    single chat request just to re-verify what's already installed."""
    global _tags_cache
    now = time.monotonic()
    if _tags_cache is not None and (now - _tags_cache[0]) < _TAGS_CACHE_TTL_SECONDS:
        return _tags_cache[1]

    try:
        r = httpx.get(f"{host.rstrip('/')}/api/tags", timeout=5)
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        # Ollama unreachable — don't cache a failure, let the next call retry.
        return []

    _tags_cache = (now, names)
    return names


def _configured_model_for_tier(tier: str) -> str:
    if tier == "nano":
        return CONFIG.ollama.model_nano
    if tier == "ultra":
        return CONFIG.ollama.model_ultra
    return CONFIG.ollama.model_core


def _model_installed(model_name: str, installed: list[str]) -> bool:
    # Ollama tags carry a ":latest" suffix that a bare model name often omits.
    return model_name in installed or f"{model_name}:latest" in installed


def resolve_tier_model(
    tier: str,
    host: str | None = None,
    on_fallback: Optional[Callable[[str, str, str], None]] = None,
) -> str:
    """
    Returns the concrete Ollama model name to actually serve for a requested
    tier, stepping down through `_STEP_DOWN` if the configured model for
    that tier (and each fallback tier in turn) isn't installed.

    `on_fallback(requested_tier, requested_model, resolved_model)` is called
    once if a step-down happened, so callers can log/alert on it — silently
    serving a different model than the one requested is exactly the kind of
    thing that should be visible, not swallowed.

    Raises RuntimeError only if the requested tier AND every step-down
    candidate are unavailable — at that point there is genuinely nothing
    Orca-branded to serve, and OrcaBrain's own PREFERRED_OPEN_MODELS fallback
    (triggered by passing model=None) is the caller's next resort.
    """
    tier = (tier or "core").removeprefix("orca-")
    host = host or CONFIG.ollama.host
    installed = _list_installed_models(host)

    requested_model = _configured_model_for_tier(tier)
    if _model_installed(requested_model, installed):
        return requested_model

    for fallback_tier in _STEP_DOWN.get(tier, []):
        candidate = _configured_model_for_tier(fallback_tier)
        if _model_installed(candidate, installed):
            if on_fallback:
                on_fallback(tier, requested_model, candidate)
            return candidate

    raise RuntimeError(
        f"No installed Ollama model found for tier '{tier}' "
        f"(configured: '{requested_model}') or any of its fallback tiers "
        f"{_STEP_DOWN.get(tier, [])}. Installed models: {installed or 'none'}."
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Multi-backend resolution — "bring your own frontier model" (see
#  orca/brain/backends.py, docs/STARTUP_PLAN.md §2). A tier now resolves to
#  a (backend, model) pair, not just a model name. This is where the
#  data-sovereignty lock is actually enforced: a locked deployment must
#  never even construct a non-Ollama backend, let alone call one.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TierResolution:
    tier: str                       # the tier actually served (may differ from requested via step-down)
    backend: str                    # "ollama" | "openai" | "anthropic"
    model: str
    data_left_infrastructure: bool
    sovereignty_overridden: bool = False  # True if the lock forced ollama over a configured frontier backend


def _configured_backend_for_tier(tier: str) -> str:
    if tier == "nano":
        return CONFIG.backends.backend_nano
    if tier == "ultra":
        return CONFIG.backends.backend_ultra
    return CONFIG.backends.backend_core


def _configured_frontier_model(tier: str, backend: str) -> str:
    if backend == "openai":
        return CONFIG.backends.openai_model_ultra if tier == "ultra" else CONFIG.backends.openai_model_core
    if backend == "anthropic":
        return CONFIG.backends.anthropic_model_ultra if tier == "ultra" else CONFIG.backends.anthropic_model_core
    raise ValueError(f"'{backend}' is not a frontier backend")


def _frontier_backend_available(backend: str) -> bool:
    if backend == "openai":
        return bool(CONFIG.backends.openai_api_key)
    if backend == "anthropic":
        return bool(CONFIG.backends.anthropic_api_key)
    return False


def resolve_tier_backend(
    tier: str,
    host: str | None = None,
    on_fallback: Optional[Callable[[str, str, str], None]] = None,
    on_sovereignty_override: Optional[Callable[[str, str], None]] = None,
) -> TierResolution:
    """
    Resolves a tier to a concrete (backend, model) pair, trying the
    requested tier first and then stepping down the same _STEP_DOWN chain
    resolve_tier_model() uses — but now each step also has to clear TWO
    checks instead of one: is the configured backend actually usable
    (Ollama model installed, or frontier API key present), AND does the
    data-sovereignty lock allow it at all.

    The lock is checked FIRST and unconditionally on every step: if
    `CONFIG.backends.data_sovereignty_lock` is set, every tier in the chain
    is forced to "ollama" regardless of its configured backend — a locked
    deployment never constructs an OpenAIBackend/AnthropicBackend instance,
    let alone calls one. `on_sovereignty_override` fires once, the first
    time this override actually changes what would have been served, so
    it's visible (metrics/audit), not silent.
    """
    tier = (tier or "core").removeprefix("orca-")
    host = host or CONFIG.ollama.host
    chain = [tier] + _STEP_DOWN.get(tier, [])
    lock = CONFIG.backends.data_sovereignty_lock

    for i, candidate_tier in enumerate(chain):
        configured_backend = _configured_backend_for_tier(candidate_tier)
        effective_backend = "ollama" if lock else configured_backend
        overridden_by_lock = lock and configured_backend != "ollama"

        if effective_backend == "ollama":
            model = _configured_model_for_tier(candidate_tier)
            installed = _list_installed_models(host)
            if _model_installed(model, installed):
                if overridden_by_lock and on_sovereignty_override:
                    on_sovereignty_override(candidate_tier, configured_backend)
                if i > 0 and on_fallback:
                    on_fallback(tier, _configured_model_for_tier(tier), model)
                return TierResolution(
                    tier=candidate_tier, backend="ollama", model=model,
                    data_left_infrastructure=False, sovereignty_overridden=overridden_by_lock,
                )
        else:
            if _frontier_backend_available(effective_backend):
                model = _configured_frontier_model(candidate_tier, effective_backend)
                if i > 0 and on_fallback:
                    on_fallback(tier, _configured_backend_for_tier(tier), f"{effective_backend}:{model}")
                return TierResolution(
                    tier=candidate_tier, backend=effective_backend, model=model,
                    data_left_infrastructure=True,
                )

    raise RuntimeError(
        f"No usable backend found for tier '{tier}' or any of its fallback tiers "
        f"{_STEP_DOWN.get(tier, [])}. Checked: {[(_configured_backend_for_tier(t)) for t in chain]}"
        + (" (data sovereignty lock forced ollama-only)" if lock else "")
    )
