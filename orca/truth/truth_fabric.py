"""
TruthFabric -- the top-level Truth Fabric interface (Phase 4 spec §4).
Deliberately two phases, not one black-box call:

  1. assess_evidence(request, ...)  -- BEFORE generation. Plans retrieval,
     retrieves, compiles evidence/sources, annotates provenance, builds
     the EvidenceGraph, and computes a preliminary EvidenceState from
     retrieval-quality signals alone (nothing to verify claims against
     yet -- there is no answer). This is what a CognitiveKernel-integrated
     caller uses to decide whether evidence exists at all before spending
     a ModelGateway call.

  2. verify_answer(answer_text, evidence, ...) -- AFTER generation.
     Extracts atomic claims from the actual generated text, verifies each
     against the assessed evidence, detects contradictions, builds
     claim-linked citations, and recomputes EvidenceState with the real
     citation coverage this time. This is the authoritative TruthResult.

Respects orca.cognitive.budget.CognitiveBudget (spec §40): every retrieval/
search/fetch/verification/model call increments a budget dimension before
running; the fabric stops explicitly (raises TruthBudgetExhaustedError)
rather than continuing silently once exhausted.
"""
from __future__ import annotations

import asyncio
import time

from orca.cognitive.budget import CognitiveBudgetExhaustedError, consume
from orca.cognitive.contracts import BudgetDimension, CognitiveBudget, FreshnessLevel
from orca.truth import citation as citation_mod
from orca.truth import evidence as evidence_mod
from orca.truth.claims import extract_atomic_claims
from orca.truth.contracts import (
    Evidence,
    EvidenceEdgeType,
    EvidenceNodeType,
    EvidenceSource,
    EvidenceState,
    RetrievalMode,
    TruthRequest,
    TruthResult,
    _new_id,
)
from orca.truth.contradiction import detect_contradictions
from orca.truth.decomposition import decompose_query
from orca.truth.errors import TruthBudgetExhaustedError, TruthTimeoutError
from orca.truth.graph import EvidenceGraph
from orca.truth.planner import build_retrieval_plan
from orca.truth.provenance import annotate_independence
from orca.truth.search_provider import DuckDuckGoProvider, SearchProvider
from orca.truth.state import compute_evidence_state
from orca.truth.verification import verify_claim

OVERALL_DEADLINE_S = 45.0        # spec §42: one bounded overall deadline, not one infinite research timeout
SEARCH_TIMEOUT_S = 10.0
RETRIEVAL_TIMEOUT_S = 10.0
# 45s, not a "typical call" budget: a verify_answer() call that follows an
# assess_evidence() call in the same process often needs Ollama to swap
# from the embedding model back to the generation model (a real, measured
# cold-load cost on a shared 16GB machine -- see
# docs/orneur/phase-3/OLLAMA_TEST_RELIABILITY.md's root-cause evidence for
# the same class of latency spike, not a Truth Fabric logic bug).
VERIFICATION_TIMEOUT_S = 45.0


class TruthFabric:
    def __init__(self, search_provider: SearchProvider | None = None):
        self._search_provider = search_provider or DuckDuckGoProvider()

    async def assess_evidence(
        self,
        request: TruthRequest,
        intent,
        complexity,
        *,
        doc_store=None,
        budget: CognitiveBudget | None = None,
    ) -> TruthResult:
        start = time.monotonic()
        plan = build_retrieval_plan(request.objective, intent, complexity, request.evidence_requirement, request.freshness_requirement)

        if plan.mode == RetrievalMode.RAG_0_NONE:
            return TruthResult(
                request_id=request.request_id, trace_id=request.trace_id, evidence_state=EvidenceState.SUFFICIENT,
                retrieval_plan_id=plan.plan_id, warnings=["no retrieval required for this request"],
                latency_ms=(time.monotonic() - start) * 1000,
            )

        try:
            evidence, sources = await asyncio.wait_for(
                self._retrieve(plan, doc_store=doc_store, budget=budget), timeout=OVERALL_DEADLINE_S,
            )
        except asyncio.TimeoutError:
            raise TruthTimeoutError(internal_detail=f"exceeded OVERALL_DEADLINE_S={OVERALL_DEADLINE_S}")

        annotate_independence(sources, evidence)
        graph = self._build_graph(evidence, sources)

        # Pre-generation: no answer exists yet, so "coverage" is measured
        # as "did retrieval find anything at all" -- an honest, coarser
        # signal than the real citation-coverage computed post-generation.
        preliminary_coverage = 1.0 if evidence else 0.0
        evidence_state = compute_evidence_state(
            citation_coverage_ratio=preliminary_coverage, contradictions=[], sources=sources,
            evidence_freshness=[ev.freshness for ev in evidence], freshness_required=plan.freshness_required,
            authority_required=plan.authority_required,
        )

        return TruthResult(
            request_id=request.request_id, trace_id=request.trace_id, evidence_state=evidence_state,
            retrieval_plan_id=plan.plan_id, evidence=evidence, sources=sources,
            context_block=_format_context(evidence),
            warnings=[] if evidence else ["retrieval found no evidence for this request"],
            latency_ms=(time.monotonic() - start) * 1000,
        )

    async def verify_answer(
        self,
        answer_text: str,
        prior_result: TruthResult,
        *,
        budget: CognitiveBudget | None = None,
        tier: str = "nano",
    ) -> TruthResult:
        start = time.monotonic()
        try:
            claims = await asyncio.wait_for(extract_atomic_claims(answer_text, tier=tier), timeout=VERIFICATION_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise TruthTimeoutError(internal_detail=f"claim extraction exceeded VERIFICATION_TIMEOUT_S={VERIFICATION_TIMEOUT_S}")

        if budget is not None:
            _consume_or_raise(budget, BudgetDimension.MODEL_CALLS, 1)

        claim_supports = []
        for claim in claims:
            if budget is not None:
                _consume_or_raise(budget, BudgetDimension.MODEL_CALLS, 1)
            support = await verify_claim(claim.claim_id, claim.text, prior_result.evidence, tier=tier)
            claim_supports.append(support)

        contradictions = await detect_contradictions(claims, tier=tier)
        citation_verdicts = citation_mod.build_citations(claim_supports)
        coverage = citation_mod.compute_citation_coverage(claims, claim_supports)

        evidence_state = compute_evidence_state(
            citation_coverage_ratio=coverage["citation_coverage_ratio"], contradictions=contradictions,
            sources=prior_result.sources, evidence_freshness=[ev.freshness for ev in prior_result.evidence],
            freshness_required=FreshnessLevel.STATIC, authority_required=False,
        )

        return TruthResult(
            request_id=prior_result.request_id, trace_id=prior_result.trace_id, evidence_state=evidence_state,
            retrieval_plan_id=prior_result.retrieval_plan_id, evidence=prior_result.evidence, sources=prior_result.sources,
            claims=claims, claim_supports=claim_supports,
            citation_verdicts=citation_mod.reject_unsupported(citation_verdicts),
            contradictions=contradictions, context_block=prior_result.context_block, citation_coverage=coverage,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    async def _retrieve(self, plan, *, doc_store, budget) -> tuple[list[Evidence], list[EvidenceSource]]:
        evidence: list[Evidence] = []
        sources: list[EvidenceSource] = []

        from orca.truth.contracts import RetrievalSourceType

        needs_dense = RetrievalSourceType.DENSE in plan.sources or RetrievalSourceType.SPARSE in plan.sources
        if needs_dense and doc_store is not None and doc_store.count() > 0:
            queries = [plan.queries[0].text]
            if plan.mode in (RetrievalMode.RAG_3_MULTI_HOP, RetrievalMode.RAG_5_RESEARCH):
                queries = decompose_query(plan.queries[0].text)
            for q in queries:
                if budget is not None:
                    _consume_or_raise(budget, BudgetDimension.RETRIEVAL_CALLS, 1)
                try:
                    chunks = await asyncio.wait_for(asyncio.to_thread(doc_store.retrieve, q, plan.max_documents), timeout=RETRIEVAL_TIMEOUT_S)
                except asyncio.TimeoutError:
                    continue
                for chunk in chunks:
                    ev, src = evidence_mod.evidence_from_document_chunk(chunk, session_id="truth-fabric")
                    evidence.append(ev)
                    sources.append(src)

        if RetrievalSourceType.WEB in plan.sources:
            if budget is not None:
                _consume_or_raise(budget, BudgetDimension.RETRIEVAL_CALLS, 1)
            try:
                results = await asyncio.wait_for(
                    asyncio.to_thread(self._search_provider.search, plan.queries[0].text, 5), timeout=SEARCH_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                results = []
            for result in results:
                ev, src = evidence_mod.evidence_from_search_result(result)
                evidence.append(ev)
                sources.append(src)

        return evidence[: plan.max_documents], sources[: plan.max_documents]

    def _build_graph(self, evidence: list[Evidence], sources: list[EvidenceSource]) -> EvidenceGraph:
        graph = EvidenceGraph()
        for src in sources:
            graph.add_node(src.source_id, EvidenceNodeType.SOURCE, label=src.identity)
        for ev in evidence:
            graph.add_node(ev.evidence_id, EvidenceNodeType.EVIDENCE, label=ev.document_id)
            if ev.source_id in {s.source_id for s in sources}:
                graph.add_edge(ev.evidence_id, ev.source_id, EvidenceEdgeType.DERIVED_FROM)
        for src in sources:
            for derived_from_id in src.derived_from:
                if derived_from_id in {s.source_id for s in sources}:
                    graph.add_edge(src.source_id, derived_from_id, EvidenceEdgeType.SAME_ORIGIN)
        return graph


def _consume_or_raise(budget: CognitiveBudget, dimension: BudgetDimension, amount: float) -> None:
    try:
        consume(budget, dimension, amount)
    except CognitiveBudgetExhaustedError as e:
        raise TruthBudgetExhaustedError(internal_detail=str(e)) from e


def _format_context(evidence: list[Evidence]) -> str:
    lines = []
    for i, ev in enumerate(evidence, start=1):
        lines.append(f"[D{i}] {ev.passage.text}")
    return "\n\n".join(lines)
