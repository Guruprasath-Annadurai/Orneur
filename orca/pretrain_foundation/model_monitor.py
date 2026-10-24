"""Monitoring contracts for the three model families.

These records describe what this repository can observe. They do not load
a native model, and a probe result of NOT_OBSERVED is not a repair.
"""
from __future__ import annotations

from orca.genesis.model.family_registry import FAMILIES, default_registry

PROBES = (
    "availability",
    "routing",
    "tokenizer",
    "checkpoint_integrity",
    "inference_performance",
    "evaluation_regression",
)


def monitoring_contracts() -> dict[str, dict]:
    registry = default_registry()
    contracts = {}
    for family in FAMILIES:
        record = registry[family]
        contracts[family] = {
            "family": family,
            "registry_status": record.status,
            "architecture_id": record.architecture_id,
            "checkpoint_digest": None,
            "model_loaded": False,
            "repaired": False,
            "native_test_executed": False,
            "probes": {probe: "NOT_OBSERVED" for probe in PROBES},
            "reason": "no native model was loaded",
        }
    return contracts
