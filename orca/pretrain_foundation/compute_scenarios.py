"""Hardware scenario labels for later capacity decisions.

No throughput, token price, or latency number in this module was
measured. The labels only separate classes of work so a workstation
quote is not read as frontier pretraining capacity.
"""
from __future__ import annotations

SCENARIOS = (
    {
        "id": "synthetic_cpu",
        "hardware": "developer CPU, unit-test process",
        "suitable_for": "loss, gradient, scheduler, and pipeline contract tests on tiny tensors",
        "frontier_pretraining": False,
        "production_inference": False,
    },
    {
        "id": "single_workstation",
        "hardware": "one workstation, including a machine in the ₹2.5 lakh class",
        "suitable_for": "local development and small synthetic experiments",
        "frontier_pretraining": False,
        "production_inference": False,
        "note": "A single workstation in the ₹2.5 lakh class is not globally competitive frontier-model pretraining capacity.",
    },
    {
        "id": "experimental_finetune",
        "hardware": "not selected; requires a later hardware decision",
        "suitable_for": "a future authorized fine-tune, only after hardware and data gates",
        "frontier_pretraining": False,
        "production_inference": False,
    },
    {
        "id": "native_pretraining",
        "hardware": "not provisioned",
        "suitable_for": "future authorized native pretraining",
        "frontier_pretraining": False,
        "production_inference": False,
        "note": "No GPU is provisioned by this software and no training run is authorized.",
    },
    {
        "id": "frontier_scale",
        "hardware": "not provisioned",
        "suitable_for": "not available",
        "frontier_pretraining": False,
        "production_inference": False,
        "note": "Frontier-scale pretraining is a later investment decision, not a property of this repository.",
    },
    {
        "id": "global_inference",
        "hardware": "not provisioned",
        "suitable_for": "not available",
        "frontier_pretraining": False,
        "production_inference": False,
        "note": "Global production inference is not deployed.",
    },
)


def scenario(scenario_id: str) -> dict:
    for row in SCENARIOS:
        if row["id"] == scenario_id:
            return dict(row)
    raise KeyError(scenario_id)


def frontier_pretraining_available() -> bool:
    """Always false in this package. Kept as a function so callers cannot
    flip a constant in a scenario row and have a helper agree."""
    return False
