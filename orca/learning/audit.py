"""
Phase 12 audit counters (spec §90). Each counter is incremented only at
its own dedicated real detection point elsewhere in this package -- never
inferred after the fact. All must be 0 in a healthy system; a nonzero
counter is a real, actionable governance violation.
"""
from __future__ import annotations

from collections import Counter

COUNTER_NAMES = (
    "UNVERIFIED_FAILURE_TRAINING_ADMISSION",
    "RUNTIME_FAILURE_MISCLASSIFIED_AS_MODEL",
    "TENANT_DATA_GLOBAL_TRAINING_LEAK",
    "SECRET_IN_CURRICULUM",
    "TRAIN_TEST_LEAKAGE",
    "HOLDOUT_EXPOSURE",
    "DATASET_MUTATION_AFTER_FREEZE",
    "UNAPPROVED_DATASET_TRAINING",
    "UNREGISTERED_CHECKPOINT",
    "CHECKPOINT_INTEGRITY_BYPASS",
    "AUTOMATIC_MODEL_PROMOTION",
    "MODEL_SELF_APPROVAL",
    "AUTOMATIC_PRODUCTION_WEIGHT_UPDATE",
    "CURRICULUM_PROMPT_INJECTION_BYPASS",
    "RAW_CHAIN_OF_THOUGHT_STORAGE",
)


class LearningAuditCounters:
    def __init__(self) -> None:
        self._counts: Counter = Counter({name: 0 for name in COUNTER_NAMES})

    def record(self, name: str) -> None:
        if name not in COUNTER_NAMES:
            raise ValueError(f"Unknown audit counter '{name}'. Known: {COUNTER_NAMES}")
        self._counts[name] += 1

    def value(self, name: str) -> int:
        return self._counts[name]

    def all_zero(self) -> bool:
        return all(v == 0 for v in self._counts.values())

    def report(self) -> dict:
        return dict(self._counts)


AUDIT = LearningAuditCounters()
