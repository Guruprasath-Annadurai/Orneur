from __future__ import annotations

from orca.specialists.contracts import SpecialistError, SpecialistSpec
from orca.specialists.handlers import HANDLERS

REGISTRY_VERSION = "orneur.specialists/1"

_SPECS = (
    SpecialistSpec("research", "1", frozenset({"research.read"}), "none", "Decompose a query and label authorized sources."),
    SpecialistSpec("planning", "1", frozenset({"plan.write"}), "none", "Order a task DAG and refuse cycles."),
    SpecialistSpec("coding", "1", frozenset({"code.read"}), "none", "Parse Python with ast; never execute."),
    SpecialistSpec("data_analysis", "1", frozenset({"data.read"}), "none", "Compute statistics on numeric tables."),
    SpecialistSpec("retrieval", "1", frozenset({"retrieval.read"}), "none", "Tenant-scoped keyword retrieval with citations."),
    SpecialistSpec("evidence_verification", "1", frozenset({"evidence.read"}), "none", "Recompute evidence digests."),
    SpecialistSpec("security_analysis", "1", frozenset({"security.read"}), "none", "Scan text for secrets and SSRF hosts."),
    SpecialistSpec("documentation", "1", frozenset({"docs.write"}), "none", "Extract signatures and docstrings."),
    SpecialistSpec("tool_execution", "1", frozenset({"tool.hash"}), "none", "Local hash/json/token tools only."),
    SpecialistSpec("mission_coordination", "1", frozenset({"mission.read"}), "none", "Inspect mission state without dispatch."),
)


class SpecialistRegistry:
    def __init__(self, *, version: str = REGISTRY_VERSION, enabled: frozenset[str] | None = None):
        self.version = version
        self._specs = {spec.role: spec for spec in _SPECS}
        self._enabled = enabled if enabled is not None else frozenset(self._specs)

    def get(self, role: str) -> SpecialistSpec:
        if role not in self._specs:
            raise SpecialistError("role_unavailable")
        if role not in self._enabled:
            raise SpecialistError("role_unavailable")
        return self._specs[role]

    def handler(self, role: str):
        self.get(role)
        return HANDLERS[role]

    def roles(self) -> list[str]:
        return sorted(role for role in self._specs if role in self._enabled)

    def unavailable(self, role: str) -> bool:
        return role not in self._enabled or role not in self._specs


def default_registry() -> SpecialistRegistry:
    return SpecialistRegistry()
