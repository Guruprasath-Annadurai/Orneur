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
from orca.truth.contradiction import detect_contradictions, detect_evidence_contradictions
from orca.truth.contracts import CorrectiveRound, CounterEvidenceResult, CounterEvidenceStatus
from orca.truth.corrective import is_repeat_query, reform_query
from orca.truth.counter_evidence import find_counter_evidence
from orca.truth.decomposition import decompose_query
from orca.truth.errors import TruthBudgetExhaustedError, TruthTimeoutError
from orca.truth.fetch import FETCH_TIMEOUT_S, extract_text, fetch_document, sanitize_extracted_text
from orca.truth.graph import EvidenceGraph
from orca.truth.planner import MAX_TOTAL_RETRIEVAL_QUERIES, build_retrieval_plan
from orca.truth.provenance import annotate_independence
from orca.truth.search_provider import DuckDuckGoProvider, SearchProvider, _domain_of
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

        deadline = time.monotonic() + OVERALL_DEADLINE_S
        try:
            evidence, sources, queries_issued = await asyncio.wait_for(
                self._retrieve(plan, doc_store=doc_store, budget=budget), timeout=OVERALL_DEADLINE_S,
            )
        except asyncio.TimeoutError:
            raise TruthTimeoutError(internal_detail=f"exceeded OVERALL_DEADLINE_S={OVERALL_DEADLINE_S}")

        issued_queries = [plan.queries[0].text]

        def _prelim_state(ev: list[Evidence], src: list[EvidenceSource]) -> EvidenceState:
            coverage = 1.0 if ev else 0.0
            return compute_evidence_state(
                citation_coverage_ratio=coverage, contradictions=[], sources=src,
                evidence_freshness=[e.freshness for e in ev], freshness_required=plan.freshness_required,
                authority_required=plan.authority_required,
            )

        evidence_state = _prelim_state(evidence, sources)
        corrective_rounds: list[CorrectiveRound] = []
        stop_reason = "initial_retrieval_sufficient" if evidence_state == EvidenceState.SUFFICIENT else ""

        # Real corrective retrieval loop (spec §8-11) -- Phase 4 only
        # planned corrective_rounds as metadata; this executes it, bounded
        # by plan.corrective_rounds AND the shared multi-hop/corrective
        # query cap (MAX_TOTAL_RETRIEVAL_QUERIES) so a RAG_5_RESEARCH
        # request's multi-hop subqueries don't leave no room for
        # corrective rounds (spec §11).
        round_index = 0
        while (
            plan.corrective_rounds > round_index
            and evidence_state in (EvidenceState.INSUFFICIENT, EvidenceState.LOW_AUTHORITY, EvidenceState.STALE)
            and queries_issued < MAX_TOTAL_RETRIEVAL_QUERIES
            and time.monotonic() < deadline
        ):
            gap_reason = {
                EvidenceState.INSUFFICIENT: "no matching evidence found for the query",
                EvidenceState.LOW_AUTHORITY: "evidence found but lacks an official/primary source",
                EvidenceState.STALE: "evidence found but is not fresh enough for this request",
            }[evidence_state]
            try:
                if budget is not None:
                    _consume_or_raise(budget, BudgetDimension.MODEL_CALLS, 1)
            except TruthBudgetExhaustedError:
                stop_reason = "budget_exhausted"
                break
            try:
                reformed = await asyncio.wait_for(reform_query(plan.queries[0].text, gap_reason), timeout=SEARCH_TIMEOUT_S)
            except asyncio.TimeoutError:
                stop_reason = "reform_query_unavailable"
                break
            if reformed is None:
                stop_reason = "reform_query_unavailable"
                break
            if is_repeat_query(reformed["reformed_query"], issued_queries):
                stop_reason = "repeated_query"
                break

            round_index += 1
            try:
                new_evidence, new_sources, new_queries_issued = await asyncio.wait_for(
                    self._retrieve(plan, doc_store=doc_store, budget=budget, query_override=reformed["reformed_query"], web_allowed=False),
                    timeout=RETRIEVAL_TIMEOUT_S,
                )
            except TruthBudgetExhaustedError:
                stop_reason = "budget_exhausted"
                break
            except asyncio.TimeoutError:
                stop_reason = "corrective_retrieval_timeout"
                break

            issued_queries.append(reformed["reformed_query"])
            queries_issued += new_queries_issued
            merged_evidence, merged_sources, added = _merge_evidence(evidence, sources, new_evidence, new_sources)
            corrective_rounds.append(CorrectiveRound(
                round_index=round_index, original_query=plan.queries[0].text, rewritten_query=reformed["reformed_query"],
                reason=reformed["reason"], evidence_gap=reformed["evidence_gap"],
                evidence_state_before=evidence_state, new_evidence_count=added,
            ))
            evidence, sources = merged_evidence, merged_sources
            evidence_state = _prelim_state(evidence, sources)

            if added == 0:
                stop_reason = "no_new_evidence_discovered"
                break
            if evidence_state == EvidenceState.SUFFICIENT:
                stop_reason = "evidence_became_sufficient"
                break
        else:
            if not stop_reason:
                if round_index >= plan.corrective_rounds:
                    stop_reason = "max_corrective_rounds_reached" if plan.corrective_rounds else "no_corrective_rounds_planned"
                elif queries_issued >= MAX_TOTAL_RETRIEVAL_QUERIES:
                    stop_reason = "shared_query_budget_exhausted"
                elif time.monotonic() >= deadline:
                    stop_reason = "deadline_reached"
                else:
                    stop_reason = "evidence_already_sufficient"

        annotate_independence(sources, evidence)
        graph = self._build_graph(evidence, sources)

        # Evidence-vs-evidence contradiction detection (spec §12-15) --
        # runs pre-generation, over the retrieved evidence itself, not
        # just post-generation over what the model happened to say.
        evidence_contradictions = await detect_evidence_contradictions(evidence)
        if evidence_contradictions:
            evidence_state = compute_evidence_state(
                citation_coverage_ratio=(1.0 if evidence else 0.0), contradictions=evidence_contradictions, sources=sources,
                evidence_freshness=[e.freshness for e in evidence], freshness_required=plan.freshness_required,
                authority_required=plan.authority_required,
            )

        return TruthResult(
            request_id=request.request_id, trace_id=request.trace_id, evidence_state=evidence_state,
            retrieval_plan_id=plan.plan_id, evidence=evidence, sources=sources,
            context_block=_format_context(evidence), contradictions=evidence_contradictions,
            warnings=[] if evidence else ["retrieval found no evidence for this request"],
            latency_ms=(time.monotonic() - start) * 1000,
            corrective_rounds=corrective_rounds, retrieval_stop_reason=stop_reason,
        )

    async def verify_answer(
        self,
        answer_text: str,
        prior_result: TruthResult,
        *,
        budget: CognitiveBudget | None = None,
        tier: str = "nano",
        run_counter_evidence: bool = False,
    ) -> TruthResult:
        """`run_counter_evidence=True` (the Kernel passes this for
        AUDIT_GRADE requests -- spec §16) triggers the bounded
        FIND_COUNTER_EVIDENCE hook against the single highest-confidence
        SUPPORTED claim, if any. Never runs for every claim -- one bounded
        adversarial search per verify_answer() call, at most."""
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

        answer_contradictions = await detect_contradictions(claims, tier=tier)
        # Evidence-vs-evidence contradictions already found in assess_evidence
        # remain visible here too -- verification never drops a known
        # source conflict just because the model's answer didn't repeat it.
        contradictions = list(prior_result.contradictions) + answer_contradictions
        citation_verdicts = citation_mod.build_citations(claim_supports)
        coverage = citation_mod.compute_citation_coverage(claims, claim_supports)

        evidence_state = compute_evidence_state(
            citation_coverage_ratio=coverage["citation_coverage_ratio"], contradictions=contradictions,
            sources=prior_result.sources, evidence_freshness=[ev.freshness for ev in prior_result.evidence],
            freshness_required=FreshnessLevel.STATIC, authority_required=False,
        )

        counter_evidence: CounterEvidenceResult | None = None
        if run_counter_evidence:
            from orca.truth.contracts import ClaimSupportState
            supported_claims = [c for c, s in zip(claims, claim_supports) if s.support_state == ClaimSupportState.SUPPORTED]
            if not supported_claims:
                counter_evidence = CounterEvidenceResult(status=CounterEvidenceStatus.NOT_RUN)
            else:
                counter_evidence = await find_counter_evidence(supported_claims[0].text, self._search_provider, budget=budget)

        return TruthResult(
            request_id=prior_result.request_id, trace_id=prior_result.trace_id, evidence_state=evidence_state,
            retrieval_plan_id=prior_result.retrieval_plan_id, evidence=prior_result.evidence, sources=prior_result.sources,
            claims=claims, claim_supports=claim_supports,
            citation_verdicts=citation_mod.reject_unsupported(citation_verdicts),
            contradictions=contradictions, context_block=prior_result.context_block, citation_coverage=coverage,
            latency_ms=(time.monotonic() - start) * 1000, counter_evidence=counter_evidence,
        )

    async def _retrieve(
        self, plan, *, doc_store, budget, query_override: str | None = None, web_allowed: bool = True,
    ) -> tuple[list[Evidence], list[EvidenceSource], int]:
        """Returns (evidence, sources, queries_issued). `query_override`
        (used by the corrective-retrieval loop) replaces the plan's own
        query text and skips multi-hop decomposition -- a corrective round
        retries with ONE reformed query, not a fresh multi-hop fan-out.
        `web_allowed=False` (also corrective-round-only) skips re-querying
        the web provider on every corrective round -- only the initial
        pass re-searches the web."""
        evidence: list[Evidence] = []
        sources: list[EvidenceSource] = []
        queries_issued = 0

        from orca.truth.contracts import RetrievalSourceType

        needs_dense = RetrievalSourceType.DENSE in plan.sources or RetrievalSourceType.SPARSE in plan.sources
        if needs_dense and doc_store is not None and doc_store.count() > 0:
            if query_override is not None:
                queries = [query_override]
            elif plan.mode in (RetrievalMode.RAG_3_MULTI_HOP, RetrievalMode.RAG_5_RESEARCH):
                queries = decompose_query(plan.queries[0].text)
            else:
                queries = [plan.queries[0].text]
            for q in queries:
                if budget is not None:
                    _consume_or_raise(budget, BudgetDimension.RETRIEVAL_CALLS, 1)
                queries_issued += 1
                try:
                    chunks = await asyncio.wait_for(asyncio.to_thread(doc_store.retrieve, q, plan.max_documents), timeout=RETRIEVAL_TIMEOUT_S)
                except asyncio.TimeoutError:
                    continue
                for chunk in chunks:
                    ev, src = evidence_mod.evidence_from_document_chunk(chunk, session_id="truth-fabric")
                    evidence.append(ev)
                    sources.append(src)

        if web_allowed and RetrievalSourceType.WEB in plan.sources:
            if budget is not None:
                _consume_or_raise(budget, BudgetDimension.RETRIEVAL_CALLS, 1)
            queries_issued += 1
            web_query = query_override or plan.queries[0].text
            try:
                results = await asyncio.wait_for(
                    asyncio.to_thread(self._search_provider.search, web_query, 5), timeout=SEARCH_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                results = []
            for i, result in enumerate(results):
                # Safe-fetch cutover (spec §3, §33): the SSRF-hardened
                # fetch_document() boundary now becomes reachable for real
                # for RAG_5_RESEARCH -- bounded to the TOP search result
                # only (never every result; a full-page fetch per result
                # would multiply cost and untrusted-content surface far
                # beyond what a snippet-only pass needs). Every other
                # result still uses snippet-only evidence, same as before.
                if i == 0 and plan.mode == RetrievalMode.RAG_5_RESEARCH and result.url:
                    fetched_ev = await self._safe_fetch_evidence(result, budget)
                    if fetched_ev is not None:
                        ev, src = fetched_ev
                        evidence.append(ev)
                        sources.append(src)
                        continue
                ev, src = evidence_mod.evidence_from_search_result(result)
                evidence.append(ev)
                sources.append(src)

        return evidence[: plan.max_documents], sources[: plan.max_documents], queries_issued

    async def _safe_fetch_evidence(self, result, budget) -> tuple[Evidence, EvidenceSource] | None:
        """Fetches ONE search result's full page through the SSRF-hardened
        orca/truth/fetch.py boundary (URL/DNS/redirect validation, bounded
        size, streamed read), sanitizes it for prompt-injection patterns,
        and returns typed Evidence -- or None on any failure/refusal/
        flagged content, in which case the caller falls back to the
        snippet-only path rather than treating a fetch failure as a
        retrieval failure."""
        try:
            if budget is not None:
                _consume_or_raise(budget, BudgetDimension.RETRIEVAL_CALLS, 1)
            doc = await asyncio.wait_for(asyncio.to_thread(fetch_document, result.url), timeout=FETCH_TIMEOUT_S)
        except Exception:
            return None
        text = extract_text(doc.raw_html)
        sanitized = sanitize_extracted_text(text)
        if sanitized.flagged or not sanitized.text.strip():
            return None
        return evidence_mod.evidence_from_fetched_passage(
            url=doc.final_url, domain=_domain_of(doc.final_url), passage_text=sanitized.text, location="full_page_fetch",
        )

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


def _merge_evidence(
    existing_evidence: list[Evidence], existing_sources: list[EvidenceSource],
    new_evidence: list[Evidence], new_sources: list[EvidenceSource],
) -> tuple[list[Evidence], list[EvidenceSource], int]:
    """Merges a corrective round's new evidence into the running set,
    deduplicating by content_hash (spec §8: "merge/dedupe evidence") --
    the same passage retrieved twice (e.g. the reformed query re-surfaces
    a chunk already found) is not double-counted. Returns the added
    count so the caller can detect a round that found nothing new."""
    known_hashes = {ev.content_hash for ev in existing_evidence if ev.content_hash}
    added_evidence, added_sources, added = list(existing_evidence), list(existing_sources), 0
    known_source_ids = {s.source_id for s in existing_sources}
    for ev, src in zip(new_evidence, new_sources):
        if ev.content_hash and ev.content_hash in known_hashes:
            continue
        added_evidence.append(ev)
        if src.source_id not in known_source_ids:
            added_sources.append(src)
            known_source_ids.add(src.source_id)
        if ev.content_hash:
            known_hashes.add(ev.content_hash)
        added += 1
    return added_evidence, added_sources, added
