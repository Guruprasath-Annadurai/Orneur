"""
Simulation observability (Phase 11 spec §79). Structured counters only
-- no raw payloads, no chain-of-thought.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orca.simulation.contracts import RealityDiffStatus, SimulationResult, SimulationVerdict


@dataclass
class SimulationMetrics:
    requested: int = 0
    by_mode: dict[str, int] = field(default_factory=dict)
    by_verdict: dict[str, int] = field(default_factory=dict)
    warnings_total: int = 0
    block_count: int = 0
    inconclusive_count: int = 0
    stale_count: int = 0
    reality_diff_mismatches: int = 0
    unexpected_effects: int = 0
    budget_exhausted_count: int = 0
    cancelled_count: int = 0


_METRICS = SimulationMetrics()


def record_result(result: SimulationResult) -> None:
    _METRICS.requested += 1
    _METRICS.by_mode[result.mode_used.value] = _METRICS.by_mode.get(result.mode_used.value, 0) + 1
    _METRICS.by_verdict[result.verdict.value] = _METRICS.by_verdict.get(result.verdict.value, 0) + 1
    _METRICS.warnings_total += len(result.warnings)
    if result.verdict == SimulationVerdict.BLOCK:
        _METRICS.block_count += 1
    if result.verdict == SimulationVerdict.INCONCLUSIVE:
        _METRICS.inconclusive_count += 1
    if result.failure_reason and result.failure_reason.value == "BUDGET_EXHAUSTED":
        _METRICS.budget_exhausted_count += 1
    if result.failure_reason and result.failure_reason.value == "CANCELLED":
        _METRICS.cancelled_count += 1
    if result.failure_reason and result.failure_reason.value == "STALE_INPUT":
        _METRICS.stale_count += 1


def record_reality_diff(status: RealityDiffStatus) -> None:
    if status not in (RealityDiffStatus.MATCHED,):
        _METRICS.reality_diff_mismatches += 1
    if status == RealityDiffStatus.UNEXPECTED_EFFECT:
        _METRICS.unexpected_effects += 1


def snapshot() -> SimulationMetrics:
    return SimulationMetrics(**vars(_METRICS))


def reset_for_tests() -> None:
    global _METRICS
    _METRICS = SimulationMetrics()
