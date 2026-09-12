"""
OCL namespace/extension registry (spec section 16). A controlled
extension mechanism: `core` is always registered; any other namespace
(e.g. `software`, `medical`) must be explicitly registered with a version
before any atom/relation may use it. This is architecture only -- Phase 17
does not build out full domain taxonomies (YAGNI), just the mechanism plus
one small proof-of-concept extension (see tests).
"""
from __future__ import annotations

from dataclasses import dataclass

from orneur.intelligence.ocl.errors import ExtensionNamespaceConflict, InvalidNamespace

CORE_NAMESPACE = "core"


@dataclass(frozen=True)
class NamespaceRegistration:
    namespace: str
    version: str
    producer: str
    description: str = ""


_REGISTRY: dict[str, NamespaceRegistration] = {
    CORE_NAMESPACE: NamespaceRegistration(
        namespace=CORE_NAMESPACE, version="1.0.0", producer="orneur.intelligence.ocl",
        description="OCL core vocabulary -- always registered.",
    ),
}


def register_namespace(registration: NamespaceRegistration) -> None:
    """Registers a new namespace. Corporate hardening (Phase 17 closure):
    this is NOT a silent-overwrite operation -- registering an ALREADY
    registered namespace with a different version/producer is rejected
    (`ExtensionNamespaceConflict`) rather than silently changing validation
    semantics for artifacts compiled concurrently against the old
    registration. Re-registering the exact same (namespace, version,
    producer) is idempotent and allowed. `core` can never be registered
    over (it is seeded at import time and this function never lets a
    caller replace it)."""
    if not registration.namespace or not registration.version:
        raise InvalidNamespace("a namespace registration requires a non-empty namespace and version")
    if registration.namespace == CORE_NAMESPACE:
        raise ExtensionNamespaceConflict("the core namespace cannot be re-registered or overwritten")

    existing = _REGISTRY.get(registration.namespace)
    if existing is not None and (existing.version, existing.producer) != (registration.version, registration.producer):
        raise ExtensionNamespaceConflict(
            f"namespace {registration.namespace!r} is already registered as "
            f"version={existing.version!r} producer={existing.producer!r} -- refusing to silently "
            f"change it to version={registration.version!r} producer={registration.producer!r}. "
            "Unregister it first if this is an intentional replacement."
        )
    _REGISTRY[registration.namespace] = registration


def is_registered_namespace(namespace: str) -> bool:
    return namespace in _REGISTRY


def snapshot_registry() -> dict[str, NamespaceRegistration]:
    """A stable point-in-time copy of the registry for one compile call to
    validate against -- so a concurrent register/unregister elsewhere
    cannot silently change validation semantics partway through validating
    a single artifact."""
    return dict(_REGISTRY)


def get_namespace(namespace: str) -> NamespaceRegistration | None:
    return _REGISTRY.get(namespace)


def unregister_namespace_for_tests(namespace: str) -> None:
    """Test-only helper -- never call from production code."""
    if namespace == CORE_NAMESPACE:
        raise InvalidNamespace("the core namespace cannot be unregistered")
    _REGISTRY.pop(namespace, None)
