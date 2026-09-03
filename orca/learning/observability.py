"""
Phase 12 observability counters (spec §85). Low-cardinality only -- no
per-user, per-tenant, or free-text-derived label ever becomes a counter
key, matching the spec's explicit "avoid sensitive high-cardinality
labels."
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class LearningObservability:
    failure_events_total: int = 0
    verified_failures_total: int = 0
    dismissed_failures_total: int = 0
    candidate_counts_total: int = 0
    candidate_distribution: Counter = field(default_factory=Counter)   # by failure_type only -- bounded enum, not free text
    dataset_versions_total: int = 0
    training_runs_total: int = 0
    eval_results_total: int = 0
    promotion_rejects_total: int = 0
    security_regressions_total: int = 0

    def record_failure_event(self, verified: bool, dismissed: bool) -> None:
        self.failure_events_total += 1
        if verified:
            self.verified_failures_total += 1
        if dismissed:
            self.dismissed_failures_total += 1

    def record_candidate(self, failure_type_value: str) -> None:
        self.candidate_counts_total += 1
        self.candidate_distribution[failure_type_value] += 1

    def record_dataset_version(self) -> None:
        self.dataset_versions_total += 1

    def record_training_run(self) -> None:
        self.training_runs_total += 1

    def record_eval_result(self) -> None:
        self.eval_results_total += 1

    def record_promotion_reject(self) -> None:
        self.promotion_rejects_total += 1

    def record_security_regression(self) -> None:
        self.security_regressions_total += 1

    def snapshot(self) -> dict:
        return {
            "failure_events_total": self.failure_events_total,
            "verified_failures_total": self.verified_failures_total,
            "dismissed_failures_total": self.dismissed_failures_total,
            "candidate_counts_total": self.candidate_counts_total,
            "candidate_distribution": dict(self.candidate_distribution),
            "dataset_versions_total": self.dataset_versions_total,
            "training_runs_total": self.training_runs_total,
            "eval_results_total": self.eval_results_total,
            "promotion_rejects_total": self.promotion_rejects_total,
            "security_regressions_total": self.security_regressions_total,
        }


OBSERVABILITY = LearningObservability()
