"""Honest model availability. Native families are never implied by an Ollama tag.

A populated installed-name list is not inference. Live reachability is a
separate probe and still does not mean a generate call succeeded.
"""

from __future__ import annotations

from orca.rse.imp1.locks import spending_authorized
from orca.serve.registry import resolve_tier_backend
from orca.serve.usage import NATIVE_FAMILIES, PAID_BACKENDS

NOT_AVAILABLE = "NOT_AVAILABLE"


def native_status(family: str) -> str:
    name = (family or "").strip().lower()
    if name in NATIVE_FAMILIES:
        return NOT_AVAILABLE
    return "unknown_family"


def probe_ollama(*, host: str, timeout_s: float = 2.0, transport=None) -> dict:
    """Reachability and tag listing only. Does not generate tokens."""
    url = host.rstrip("/") + "/api/tags"
    try:
        if transport is not None:
            payload = transport(url, timeout_s)
        else:
            import httpx

            response = httpx.get(url, timeout=timeout_s)
            response.raise_for_status()
            payload = response.json()
        names = [row.get("name") for row in (payload.get("models") or []) if row.get("name")]
        return {
            "status": "reachable",
            "reason": None,
            "installed": names,
            "inference": False,
            "streaming_probed": False,
        }
    except TimeoutError:
        return {"status": NOT_AVAILABLE, "reason": "provider_timeout", "installed": [], "inference": False, "streaming_probed": False}
    except Exception as exc:
        name = type(exc).__name__
        reason = "provider_timeout" if "timeout" in name.lower() or "timeout" in str(exc).lower() else "unreachable"
        return {"status": NOT_AVAILABLE, "reason": reason, "installed": [], "inference": False, "streaming_probed": False}


def discover(*, installed: list[str] | None = None, host: str | None = None, probe: bool = False, transport=None) -> dict:
    families = {name: native_status(name) for name in sorted(NATIVE_FAMILIES)}
    live = None
    if probe:
        from orca.config import CONFIG

        live = probe_ollama(host=host or CONFIG.ollama.host, transport=transport)
    supplied = list(installed) if installed is not None else []
    ollama_status = NOT_AVAILABLE
    if live is not None and live["status"] == "reachable":
        ollama_status = "reachable_not_inferred"
    return {
        "genesis": families["genesis"],
        "novus": families["novus"],
        "aeternum": families["aeternum"],
        "ollama_installed_supplied": supplied,
        "ollama_installed": live["installed"] if live is not None else [],
        "ollama_status": ollama_status,
        "live_probe": live["status"] if live is not None else "not_probed",
        "live_reason": None if live is None else live.get("reason"),
        "inference": False,
        "paid_fallback": "refused" if not spending_authorized() else "authorized",
        "spending_authorized": bool(spending_authorized()),
        "data_routing_consent": "not_granted",
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
            "inference": False,
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
            "inference": False,
        }
    return {
        "status": "resolved_not_inferred",
        "reason": None,
        "requested_tier": tier,
        "served_model": model,
        "backend": backend,
        "native_family": None,
        "data_left_infrastructure": bool(getattr(resolution, "data_left_infrastructure", False)),
        "inference": False,
    }
