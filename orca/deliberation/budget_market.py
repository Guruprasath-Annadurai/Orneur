"""
Cognitive Budget Market -- foundation (Phase 6 spec §32-34). NOT an
economic-token simulation: a deterministic, testable allocator deciding
how remaining cognitive budget is distributed across
retrieval/reasoning/falsification/verification/counter-evidence/
simulation/agents, based on uncertainty, risk, evidence conflict, and
complexity. A future phase may make this learned; this phase's bar is
"deterministic and testable" (spec §33).
"""
from __future__ import annotations

from dataclasses import dataclass

from orca.cognitive.contracts import ComplexityLevel, RiskLevel

_DIMENSIONS = ("retrieval", "reasoning", "falsification", "verification", "counter_evidence", "simulation", "agents")

_BASE_WEIGHTS = {
    "retrieval": 0.20, "reasoning": 0.30, "falsification": 0.15, "verification": 0.15,
    "counter_evidence": 0.10, "simulation": 0.05, "agents": 0.05,
}

# A remaining-latency budget below this threshold is "low" -- optional
# deliberation work (falsification/simulation/counter-evidence) gets
# squeezed out first, since it's the most skippable under time pressure.
_LOW_LATENCY_THRESHOLD_MS = 5000.0


@dataclass
class BudgetAllocation:
    retrieval: float
    reasoning: float
    falsification: float
    verification: float
    counter_evidence: float
    simulation: float
    agents: float

    def as_dict(self) -> dict[str, float]:
        return {d: getattr(self, d) for d in _DIMENSIONS}


def allocate_budget(
    uncertainty: float, risk: RiskLevel, evidence_conflict: bool, complexity: ComplexityLevel,
    remaining_latency_ms: float | None = None,
) -> BudgetAllocation:
    """`uncertainty` is 0.0 (fully confident) to 1.0 (highly uncertain) --
    callers derive this from hypothesis count/spread, not from this
    module. Weights always sum to 1.0 (renormalized after every rule)."""
    weights = dict(_BASE_WEIGHTS)

    # LOW uncertainty -> more budget to answer generation (spec §33).
    if uncertainty < 0.3:
        _shift(weights, frm=("retrieval", "falsification"), to="reasoning", amount=0.10)

    # HIGH evidence conflict -> more to retrieval/falsification.
    if evidence_conflict:
        _shift(weights, frm=("reasoning", "agents"), to=("retrieval", "falsification"), amount=0.12)

    # HIGH risk -> more to verification.
    if risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
        _shift(weights, frm=("reasoning", "agents", "simulation"), to="verification", amount=0.12)

    # Complexity DEEP/HIGH with real uncertainty -> a bit more to
    # falsification/simulation (there's more to actually falsify/model).
    if complexity in (ComplexityLevel.HIGH, ComplexityLevel.DEEP) and uncertainty >= 0.3:
        _shift(weights, frm=("reasoning",), to=("falsification", "simulation"), amount=0.08)

    # LOW remaining latency -> reduce optional deliberation.
    if remaining_latency_ms is not None and remaining_latency_ms < _LOW_LATENCY_THRESHOLD_MS:
        _shift(weights, frm=("falsification", "simulation", "counter_evidence"), to="reasoning", amount=0.15)

    weights = _renormalize(weights)
    return BudgetAllocation(**weights)


def _shift(weights: dict[str, float], frm, to, amount: float) -> None:
    frm = (frm,) if isinstance(frm, str) else frm
    to = (to,) if isinstance(to, str) else to
    per_source = amount / len(frm)
    per_target = amount / len(to)
    for f in frm:
        taken = min(weights[f], per_source)
        weights[f] -= taken
        for t in to:
            weights[t] += taken / len(to)


def _renormalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        return dict(_BASE_WEIGHTS)
    return {k: round(v / total, 4) for k, v in weights.items()}
