"""G-015 -- which model actually answered, stated truthfully.

`requested_*` is what the caller (or the UI default) asked for. `served_*` is what generated the text. They differ when the Cognitive Kernel routes a
simple question to a smaller tier, when an entitlement ceiling lowers the tier, when the tier's model is not installed and the registry falls back, or
when cost-aware routing escalates to an external provider. Every such difference is reported with a stable `substitution_reason`; nothing is rewritten
to look like the request was honoured.

`lifecycle` / `disclosure` come from the same authority that decides whether the model may be served at all (`orca.gateway.wiring.public_serving_decision`).
If that cannot be determined the value is "UNKNOWN" -- never a flattering default.
"""
from __future__ import annotations

REASONS = frozenset({"kernel_routing", "entitlement_limit", "registry_fallback", "cost_routing_escalation", "sovereignty_override"})


def normalize_tier(variant: str | None) -> str:
    return (variant or "core").removeprefix("orca-").strip().lower() or "core"


def tier_of_model(model_name: str | None) -> str | None:
    """Best-effort reverse map from an Ollama tag to a tier using the configured names; None when it does not match one (never guessed)."""
    if not model_name:
        return None
    from orca.config import CONFIG

    base = model_name.split(":")[0]
    for tier, configured in (("nano", CONFIG.ollama.model_nano), ("core", CONFIG.ollama.model_core), ("ultra", CONFIG.ollama.model_ultra)):
        if model_name == configured or base == configured.split(":")[0]:
            return tier
    return None


def _lifecycle(tier: str, served_model: str | None, viewer_user_id: str | None) -> tuple[str, str]:
    try:
        from orca.gateway.wiring import public_serving_decision

        d = public_serving_decision(tier, served_model or "", viewer_user_id)
        label = d.label or ("Experimental model -- not qualified." if d.lifecycle == "EXPERIMENTAL" else "")
        return d.lifecycle, label
    except Exception:
        return "UNKNOWN", ""


def model_identity(*, requested_variant: str | None, served_tier: str | None, served_model: str | None, backend: str = "ollama",
                   reason: str | None = None, fallback_from: str | None = None, viewer_user_id: str | None = None,
                   data_left_infrastructure: bool = False) -> dict:
    requested = normalize_tier(requested_variant)
    served = normalize_tier(served_tier) if served_tier else tier_of_model(served_model)
    substituted = bool(fallback_from) or reason is not None or (served is not None and served != requested)
    if substituted and reason is None:
        reason = "registry_fallback" if fallback_from else "kernel_routing"
    if reason is not None and reason not in REASONS:
        raise ValueError(f"unknown substitution reason: {reason}")
    if backend == "ollama" and served:
        lifecycle, disclosure = _lifecycle(served, served_model, viewer_user_id)
    else:
        lifecycle, disclosure = None, ("Answered by an external provider." if backend != "ollama" else "")
    return {
        "requested_tier": requested,
        "served_tier": served,                       # None = could not be determined; the UI must not invent one
        "served_model": served_model,
        "backend": backend,
        "substituted": substituted,
        "substitution_reason": reason if substituted else None,
        "fallback_from": fallback_from,
        "lifecycle": lifecycle,
        "disclosure": disclosure,
        "data_left_infrastructure": bool(data_left_infrastructure),
        # L02-08: who made the weights that answered. A frontier backend is someone else's model; a local runtime serves third-party open weights unless native
        # ORNEUR weights exist (none do). Derived from orca.serve.capability_truth, never from the tier label.
        **_provenance(backend, served or requested),
    }


def _provenance(backend: str, tier: str | None) -> dict:
    from orca.serve.capability_truth import native_weights_available

    native = backend == "ollama" and native_weights_available(tier)
    return {"weights_origin": "orneur" if native else "third_party", "native_orneur_weights": native, "runtime": "ollama" if backend == "ollama" else backend}
