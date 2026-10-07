"""RSE-IMP-1 registry and Crown checks. Synthetic rehearsal only."""

from orca.rse.imp1.locks import (
    corpus_generation_authorized,
    gpu_authorized,
    model_selection_authorized,
    provider_authorized,
    qualification_authorized,
    spending_authorized,
    training_authorized,
)

__all__ = [
    "corpus_generation_authorized",
    "qualification_authorized",
    "model_selection_authorized",
    "gpu_authorized",
    "provider_authorized",
    "spending_authorized",
    "training_authorized",
]
