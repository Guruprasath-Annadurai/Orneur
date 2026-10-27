"""Honest model availability. Native families are never implied by an Ollama tag."""

from __future__ import annotations

from orca.rse.imp1.locks import spending_authorized
from orca.serve.registry import resolve_tier_backend
from orca.serve.usage import PAID_BACKENDS, NATIVE_FAMILIES

NOT_AVAILABLE = "NOT_AVAILABLE"


def native_status(family: str) -> str:
    name = (family or "").strip().lower()
    if name in NATIVE_FAMILIES:
        return NOT_AVAILABLE
    return "unknown_family"


def discover(*, installed: list[str] | None = None, resolver=None) -> dict:
    families = {name: native_status(name) for name in sorted(NATIVE_FAMILIES)}
    ollama = list(installed) if installed is not None else []
    return {
        "genesis": families["genesis"],
        "novus": families["novus"],
        "aeternum": families["aeternum"],
        "ollama_installed": ollama,
        "ollama_status": "available" if ollama else NOT_AVAILABLE,
        "paid_fallback": "refused" if not spending_authorized() else "authorized",
        "spending_authorized": bool(spending_authorized()),
    }


def resolve_honest(tier: str, *, resolver=None) -> dict:
    """Resolve a serving target or return NOT_AVAILABLE. Never renames a backend as GENESIS."""
    call = resolver or resolve_tier_backend
    try:
        resolution = call(tier)
    except Exception:
        return {
            "status": NOT_AVAILABLE,
            "reason": "provider_unavailable",
            "requested_tier": tier,
            "served_model": None,
            "backend": None,
            "native_family": None,
        }
    backend = getattr(resolution, "backend", None) or resolution.get("backend")
    model = getattr(resolution, "model", None) or resolution.get("model")
    if backend in PAID_BACKENDS and not spending_authorized():
        return {
            "status": NOT_AVAILABLE,
            "reason": "paid_backend_refused",
            "requested_tier": tier,
            "served_model": None,
            "backend": backend,
            "native_family": None,
        }
    return {
        "status": "available",
        "reason": None,
        "requested_tier": tier,
        "served_model": model,
        "backend": backend,
        "native_family": None,
        "data_left_infrastructure": bool(getattr(resolution, "data_left_infrastructure", False)),
    }
