"""
ReasoningCompiler (Phase 6 spec §5-6). Pure, deterministic, synchronous
-- no I/O, no model calls, mirroring orca/cognitive/planner.py's own
"pure planning" charter and orca/truth/planner.py's RetrievalPlanner.

Decides reasoning MODE from uncertainty/risk/evidence-conflict/ambiguity/
consequence -- explicitly NOT "complexity=HIGH implies Court" (spec §6).
"""
from __future__ import annotations

import re

from orca.cognitive.contracts import ComplexityLevel, EvidenceLevel, RiskLevel
from orca.deliberation.contracts import EvidenceNeed, ReasoningMode, ReasoningPlan

MAX_HYPOTHESES = 4
MAX_ROUNDS_DEFAULT = 1
MAX_ROUNDS_DELIBERATIVE = 2
MAX_ROUNDS_COURT = 3

_CAUSAL_RE = re.compile(r"\b(why did|what caused|what is causing|root cause of|reason for)\b", re.IGNORECASE)
_COUNTERFACTUAL_RE = re.compile(r"\b(what if|had (not )?(happened|occurred)|would (have|still))\b", re.IGNORECASE)
_AMBIGUOUS_RE = re.compile(
    r"\b(could be|might be|not sure|unclear|either .* or|possibly|diagnos(e|is)|which (one|option|cause))\b",
    re.IGNORECASE,
)


def compile_reasoning_plan(
    objective: str,
    complexity: ComplexityLevel,
    risk: RiskLevel,
    evidence_requirement: EvidenceLevel,
    truth_result=None,          # orca.truth.contracts.TruthResult | None -- loosely typed, avoids a hard import here
    memory_recall_result=None,  # orca.memory.contracts.MemoryRecallResult | None
) -> ReasoningPlan:
    reasons: list[str] = []
    mode = ReasoningMode.DIRECT

    is_causal = bool(_CAUSAL_RE.search(objective))
    is_counterfactual = bool(_COUNTERFACTUAL_RE.search(objective))
    is_ambiguous = bool(_AMBIGUOUS_RE.search(objective))
    # Only a DIRECT_CONTRADICTION counts as a real "evidence conflict"
    # signal here -- TEMPORALLY_RECONCILABLE/SCOPE_DIFFERENCE/
    # LIKELY_CONFLICT are Truth Fabric's own honest "not actually a
    # standing conflict" classifications (see orca/truth/contradiction.py)
    # and must not, on their own, force every such request into Court
    # review. This also protects against the documented nano-tier judge
    # false-positive class (docs/orneur/phase-4/EVALUATION_V2.md) turning
    # an otherwise-clean STRICT request into an unnecessary abstention.
    evidence_conflict = any(
        getattr(getattr(c, "relationship", None), "value", "") == "DIRECT_CONTRADICTION"
        for c in (getattr(truth_result, "contradictions", None) or [])
    )
    high_consequence = risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    audit_grade = evidence_requirement == EvidenceLevel.AUDIT_GRADE

    requires_hypotheses = False
    requires_falsification = False
    requires_counterfactual = False
    requires_court = False
    max_rounds = MAX_ROUNDS_DEFAULT
    evidence_needs: list[EvidenceNeed] = []

    if is_causal:
        mode = ReasoningMode.CAUSAL
        reasons.append("causal language detected -- correlation-vs-causation distinction required")

    if is_counterfactual:
        mode = ReasoningMode.COUNTERFACTUAL
        requires_counterfactual = True
        reasons.append("counterfactual language detected")

    if is_ambiguous or evidence_conflict:
        requires_hypotheses = True
        if mode == ReasoningMode.DIRECT:
            mode = ReasoningMode.MULTI_HYPOTHESIS
        reasons.append("ambiguity or evidence conflict detected -- multiple competing hypotheses required" if is_ambiguous else "evidence conflict detected -- competing hypotheses required")
        if evidence_conflict:
            evidence_needs.append(EvidenceNeed(question="What observation would resolve the detected evidence conflict?"))

    # High-stakes triggers Court explicitly -- never derived from
    # complexity alone (spec §6/§41).
    if audit_grade or high_consequence or evidence_conflict:
        requires_court = True
        requires_falsification = True
        mode = ReasoningMode.COURT_REVIEW
        max_rounds = MAX_ROUNDS_COURT
        if audit_grade:
            reasons.append("AUDIT_GRADE evidence requirement -- Court review required")
        if high_consequence:
            reasons.append(f"risk={risk.value} -- Court review required")
    elif complexity in (ComplexityLevel.HIGH, ComplexityLevel.DEEP) and evidence_requirement in (EvidenceLevel.STRICT, EvidenceLevel.SUPPORTED):
        if mode in (ReasoningMode.DIRECT, ReasoningMode.MULTI_HYPOTHESIS):
            mode = ReasoningMode.DELIBERATIVE
        requires_falsification = True
        max_rounds = MAX_ROUNDS_DELIBERATIVE
        reasons.append(f"complexity={complexity.value} with evidence_requirement={evidence_requirement.value} -- deliberative review")
    elif mode == ReasoningMode.DIRECT and not is_ambiguous and complexity == ComplexityLevel.LOW and risk == RiskLevel.LOW:
        reasons.append("low complexity/risk, no ambiguity, no conflict -- direct answer")
    elif mode == ReasoningMode.DIRECT:
        mode = ReasoningMode.ANALYTICAL
        reasons.append("moderate complexity/evidence needs -- analytical review, no Court")

    completion_conditions = ["output_produced", "budget_exhausted", "deadline_reached"]
    if requires_hypotheses:
        completion_conditions.append("hypotheses_resolved_or_max_rounds")
    if requires_court:
        completion_conditions.append("court_verdict_reached")

    return ReasoningPlan(
        goal=objective, mode=mode, subproblems=[], requires_hypotheses=requires_hypotheses,
        evidence_needs=evidence_needs, requires_falsification=requires_falsification,
        requires_counterfactual=requires_counterfactual, requires_court=requires_court,
        max_rounds=max_rounds, max_hypotheses=MAX_HYPOTHESES,
        completion_conditions=completion_conditions, reasons=reasons,
    )
