"""Route a structured task to a qualified tool.

GENESIS, NOVUS, and AETERNUM stay unqualified while no weights are loaded
and no capability benchmark has been accepted. A refusal does not substitute
another model under a native family name.
"""
from __future__ import annotations

from orca.genesis.model.family_registry import FAMILIES, default_registry

NATIVE_UNQUALIFIED = "native_model_not_qualified"


def route(*, task_type: str, requested_family: str | None, budget_usd: float, capability_cost_usd: float = 0) -> dict:
    registry = default_registry()
    native = {
        name: {
            "status": record.status,
            "qualified_for_live_routing": False,
            "reason": "no_loaded_weights_and_no_accepted_capability_benchmark",
        }
        for name, record in registry.items()
    }
    base = {
        "schema": "orneur-model-route/1",
        "task_type": task_type,
        "native_families": native,
        "substituted_native_family": False,
        "synthetic": False,
    }
    if requested_family:
        family = requested_family.strip().upper()
        if family not in FAMILIES:
            return {**base, "decision": "refused", "code": "unknown_family", "tool": None}
        return {**base, "decision": "refused", "code": NATIVE_UNQUALIFIED, "tool": None, "requested_family": family}
    if capability_cost_usd > budget_usd:
        return {**base, "decision": "refused", "code": "budget_insufficient", "tool": None}
    if task_type == "structured_arithmetic":
        return {**base, "decision": "selected", "code": "ok", "tool": "deterministic.calculator"}
    if task_type == "natural_language":
        return {**base, "decision": "refused", "code": "language_understanding_unavailable", "tool": None}
    return {**base, "decision": "refused", "code": "no_qualified_tool", "tool": None}
