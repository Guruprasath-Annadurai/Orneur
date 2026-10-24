"""Hardware scenario labels for later capacity decisions.

No throughput, token price, or latency number in this module was
measured. The labels only separate classes of work so a workstation
quote is not read as frontier pretraining capacity.

Published free-tier pages are observations. They are not enrolled
capacity and they are not a price of zero.
"""
from __future__ import annotations

QUALIFICATION = "COMPUTE_NOT_QUALIFIED"
PRICE = "UNKNOWN"

# Retrieved 2026-10-24 from the publisher pages named on each row.
# Hugging Face's two official pricing URLs disagreed about a free-user
# credit, so that amount is UNKNOWN rather than either published figure.
FREE_TIER_OBSERVATIONS = (
    {
        "provider": "google_colab",
        "source": "https://research.google.com/colaboratory/faq.html",
        "retrieved": "2026-10-24",
        "published_claim": "free of charge; GPU access heavily restricted; usage limits not published; free notebooks at most 12 hours",
        "enrolled_for_orneur": False,
        "qualification": QUALIFICATION,
        "price": PRICE,
    },
    {
        "provider": "kaggle_notebooks",
        "source": "https://www.kaggle.com/docs/efficient-gpu-usage",
        "retrieved": "2026-10-24",
        "published_claim": "weekly GPU quota of 30 hours or sometimes higher, depending on demand; not enrolled here",
        "enrolled_for_orneur": False,
        "qualification": QUALIFICATION,
        "price": PRICE,
    },
    {
        "provider": "huggingface_inference_providers",
        "source": "https://huggingface.co/docs/inference-providers/pricing",
        "conflicting_source": "https://huggingface.co/docs/inference-providers/main/en/pricing",
        "retrieved": "2026-10-24",
        "published_claim": "one page listed free users as None and another listed 0.10 USD subject to change",
        "enrolled_for_orneur": False,
        "qualification": QUALIFICATION,
        "price": PRICE,
    },
)

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
            found = dict(row)
            found["qualification"] = QUALIFICATION
            found["price"] = PRICE
            found["throughput_measured"] = False
            found["free_tier_enrolled"] = False
            return found
    raise KeyError(scenario_id)


def frontier_pretraining_available() -> bool:
    """Always false in this package. Kept as a function so callers cannot
    flip a constant in a scenario row and have a helper agree."""
    return False
