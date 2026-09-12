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

from orneur.intelligence.ocl.errors import InvalidNamespace

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
    if not registration.namespace or not registration.version:
        raise InvalidNamespace("a namespace registration requires a non-empty namespace and version")
    _REGISTRY[registration.namespace] = registration


def is_registered_namespace(namespace: str) -> bool:
    return namespace in _REGISTRY


def get_namespace(namespace: str) -> NamespaceRegistration | None:
    return _REGISTRY.get(namespace)


def unregister_namespace_for_tests(namespace: str) -> None:
    """Test-only helper -- never call from production code."""
    if namespace == CORE_NAMESPACE:
        raise InvalidNamespace("the core namespace cannot be unregistered")
    _REGISTRY.pop(namespace, None)
