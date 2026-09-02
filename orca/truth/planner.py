"""
RetrievalPlanner -- consumes Cognitive Kernel outputs (evidence
requirement, freshness requirement, complexity, intent, risk) and emits a
bounded RetrievalPlan (Phase 4 spec §7). Deterministic, no I/O, no model
calls -- mirrors orca/cognitive/planner.py's own "pure planning" charter.

Never emits an unbounded plan: every numeric field has a hard, documented
cap, independent of what any downstream stage decides to actually use.
"""
from __future__ import annotations

from orca.cognitive.contracts import ComplexityLevel, EvidenceLevel, FreshnessLevel, IntentPlan
from orca.truth.contracts import RetrievalMode, RetrievalPlan, RetrievalQuery, RetrievalSourceType

# Hard caps -- Phase 4 spec §7/§8: "All limits must be bounded." /
# "No recursive unbounded research loop."
MAX_SUBQUERIES = 4
MAX_MULTI_HOP_DEPTH = 3
MAX_CORRECTIVE_ROUNDS = 2
MAX_DOCUMENTS_BY_MODE = {
    RetrievalMode.RAG_0_NONE: 0,
    RetrievalMode.RAG_1_SEMANTIC: 6,
    RetrievalMode.RAG_2_HYBRID: 10,
    RetrievalMode.RAG_3_MULTI_HOP: 16,
    RetrievalMode.RAG_4_CORRECTIVE: 12,
    RetrievalMode.RAG_5_RESEARCH: 24,
}
MAX_PASSAGES_BY_MODE = {mode: max(1, docs // 2) for mode, docs in MAX_DOCUMENTS_BY_MODE.items()}


def _select_mode(evidence: EvidenceLevel, complexity: ComplexityLevel, intent: IntentPlan) -> tuple[RetrievalMode, list[str]]:
    reasons: list[str] = []

    if evidence == EvidenceLevel.NONE:
        return RetrievalMode.RAG_0_NONE, ["evidence_requirement=NONE -- no retrieval needed"]

    if evidence == EvidenceLevel.AUDIT_GRADE:
        return RetrievalMode.RAG_5_RESEARCH, ["evidence_requirement=AUDIT_GRADE requires full research mode"]

    if evidence == EvidenceLevel.STRICT:
        if complexity in (ComplexityLevel.HIGH, ComplexityLevel.DEEP) and (intent.requires_agents or intent.secondary_intents):
            reasons.append(f"evidence_requirement=STRICT with complexity={complexity.value} -- multi-hop retrieval")
            return RetrievalMode.RAG_3_MULTI_HOP, reasons
        reasons.append("evidence_requirement=STRICT -- corrective retrieval to verify sufficiency")
        return RetrievalMode.RAG_4_CORRECTIVE, reasons

    if evidence == EvidenceLevel.SUPPORTED:
        if intent.requires_retrieval or intent.requires_search:
            reasons.append("evidence_requirement=SUPPORTED with explicit retrieval/search intent -- hybrid retrieval")
            return RetrievalMode.RAG_2_HYBRID, reasons
        reasons.append("evidence_requirement=SUPPORTED -- semantic retrieval")
        return RetrievalMode.RAG_1_SEMANTIC, reasons

    # LIGHT
    if intent.requires_retrieval or intent.requires_search:
        reasons.append("evidence_requirement=LIGHT with explicit retrieval/search intent -- semantic retrieval")
        return RetrievalMode.RAG_1_SEMANTIC, reasons
    reasons.append("evidence_requirement=LIGHT, no explicit retrieval signal -- no retrieval")
    return RetrievalMode.RAG_0_NONE, reasons


def _sources_for(mode: RetrievalMode, intent: IntentPlan) -> list[RetrievalSourceType]:
    if mode == RetrievalMode.RAG_0_NONE:
        return []
    sources = [RetrievalSourceType.DENSE]
    if mode in (RetrievalMode.RAG_2_HYBRID, RetrievalMode.RAG_3_MULTI_HOP, RetrievalMode.RAG_4_CORRECTIVE, RetrievalMode.RAG_5_RESEARCH):
        sources.append(RetrievalSourceType.SPARSE)
    if intent.requires_search or mode == RetrievalMode.RAG_5_RESEARCH:
        sources.append(RetrievalSourceType.WEB)
    if intent.requires_memory:
        sources.append(RetrievalSourceType.MEMORY)
    return sources


def build_retrieval_plan(
    objective: str,
    intent: IntentPlan,
    complexity: ComplexityLevel,
    evidence_requirement: EvidenceLevel,
    freshness_requirement: FreshnessLevel,
) -> RetrievalPlan:
    mode, reasons = _select_mode(evidence_requirement, complexity, intent)
    sources = _sources_for(mode, intent)

    queries = [RetrievalQuery(text=objective, source_types=sources or [RetrievalSourceType.DENSE])]

    multi_hop_depth = MAX_MULTI_HOP_DEPTH if mode == RetrievalMode.RAG_3_MULTI_HOP else 0
    corrective_rounds = MAX_CORRECTIVE_ROUNDS if mode in (RetrievalMode.RAG_4_CORRECTIVE, RetrievalMode.RAG_5_RESEARCH) else 0
    if mode == RetrievalMode.RAG_5_RESEARCH:
        multi_hop_depth = min(multi_hop_depth or MAX_MULTI_HOP_DEPTH, MAX_MULTI_HOP_DEPTH)

    return RetrievalPlan(
        mode=mode,
        queries=queries,
        sources=sources,
        max_documents=MAX_DOCUMENTS_BY_MODE[mode],
        max_passages=MAX_PASSAGES_BY_MODE[mode],
        rerank_required=mode != RetrievalMode.RAG_0_NONE and mode != RetrievalMode.RAG_1_SEMANTIC,
        freshness_required=freshness_requirement,
        authority_required=evidence_requirement in (EvidenceLevel.STRICT, EvidenceLevel.AUDIT_GRADE),
        multi_hop_depth=multi_hop_depth,
        corrective_rounds=corrective_rounds,
        reasons=reasons,
    )
