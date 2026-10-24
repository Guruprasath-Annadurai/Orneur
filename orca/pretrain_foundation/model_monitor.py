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


class ModelMonitorError(Exception):
    """A model operation was refused."""


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


def diagnose(family: str) -> dict:
    """Serving, tokenizer, checkpoint, and inference status for one family.

    Every field is an observation gap. This does not load or train a model.
    """
    if family not in FAMILIES:
        raise ModelMonitorError("unknown model family")
    contract = monitoring_contracts()[family]
    return {
        "family": family,
        "registry_status": contract["registry_status"],
        "serving": "NOT_RUN",
        "tokenizer_regression": "NOT_OBSERVED",
        "checkpoint_provenance": "UNVERIFIED",
        "inference_health": "NOT_OBSERVED",
        "rollback": "REFUSED",
        "rollback_reason": "no trained checkpoint is registered",
        "model_loaded": False,
        "trained": False,
        "repaired": False,
    }


def request_rollback(family: str, target_digest: str) -> dict:
    """Refuse rollback. No checkpoint and no release authority are enrolled."""
    diagnose(family)
    if not isinstance(target_digest, str) or not target_digest:
        raise ModelMonitorError("rollback requires a target digest")
    raise ModelMonitorError("rollback refused: no trained checkpoint and no release authority")
