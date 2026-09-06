"""
TruthFabric._retrieve execution across retrieval modes -- hybrid
(DENSE+WEB), multi-hop query bounding, and the documented scope limit on
corrective rounds (Phase 4 spec §9-11, §46). Uses a fake DocStore/
SearchProvider rather than live Ollama -- this tests retrieval EXECUTION
logic (which queries get issued, how many, from which sources), not
generation quality, so it doesn't need a model.
"""
from __future__ import annotations

import pytest

from orca.cognitive.contracts import CognitiveBudget, ComplexityLevel, EvidenceLevel, FreshnessLevel
from orca.cognitive.intent import compile_intent
from orca.truth.contracts import RetrievalMode, TruthRequest
from orca.truth.planner import MAX_SUBQUERIES, build_retrieval_plan
from orca.truth.search_provider import SearchResultMetadata
from orca.truth.truth_fabric import TruthFabric


class _FakeDocStore:
    def __init__(self, chunks: list[dict]):
        self._chunks = chunks
        self.queries: list[str] = []

    def count(self) -> int:
        return len(self._chunks)

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        self.queries.append(query)
        return self._chunks[:top_k]


class _FakeSearchProvider:
    def __init__(self, results: list[SearchResultMetadata]):
        self._results = results
        self.calls = 0

    def search(self, query: str, n: int = 5, domain_filter: str | None = None):
        self.calls += 1
        return self._results


def _chunk(text: str, idx: int) -> dict:
    return {"text": text, "filename": "f.txt", "chunk_idx": idx}


@pytest.mark.asyncio
async def test_hybrid_retrieval_pulls_from_both_dense_and_web():
    """RAG_2_HYBRID: evidence_requirement=SUPPORTED with explicit
    retrieval+search intent -- expects both the DocStore (DENSE) and the
    SearchProvider (WEB) to be queried, and evidence from both to end up
    in the combined result (spec §9: hybrid retrieval)."""
    objective = "Search the web and summarize the file I attached about rate limits"
    intent = compile_intent(objective)
    assert intent.requires_retrieval and intent.requires_search
    plan = build_retrieval_plan(objective, intent, ComplexityLevel.MEDIUM, EvidenceLevel.SUPPORTED, FreshnessLevel.STATIC)
    assert plan.mode == RetrievalMode.RAG_2_HYBRID

    doc_store = _FakeDocStore([_chunk("The rate limit is 100 req/min.", 0)])
    search_provider = _FakeSearchProvider([
        SearchResultMetadata(title="Rate limits", url="https://docs.example.com/limits", snippet="100 requests per minute", domain="docs.example.com"),
    ])
    fabric = TruthFabric(search_provider=search_provider)
    evidence, sources, _queries_issued = await fabric._retrieve(plan, doc_store=doc_store, budget=None)

    assert doc_store.queries, "dense source was never queried"
    assert search_provider.calls == 1, "web source was never queried"
    assert len(evidence) == 2
    source_types = {s.source_type.value for s in sources}
    assert "UPLOADED_DOCUMENT" in source_types
    assert any(t.startswith("WEB_") for t in source_types)


@pytest.mark.asyncio
async def test_multi_hop_retrieval_issues_bounded_subqueries():
    """RAG_3_MULTI_HOP: complexity=DEEP + secondary intents -- the number
    of DENSE queries issued must be decompose_query's own bounded output,
    never more than MAX_SUBQUERIES (spec §10: bounded multi-hop, no
    unbounded research loop)."""
    objective = " and ".join(f"compare feature{i}" for i in range(10))
    intent = compile_intent(objective)
    plan = build_retrieval_plan(objective, intent, ComplexityLevel.DEEP, EvidenceLevel.STRICT, FreshnessLevel.STATIC)
    assert plan.mode in (RetrievalMode.RAG_3_MULTI_HOP, RetrievalMode.RAG_4_CORRECTIVE)

    doc_store = _FakeDocStore([_chunk("Some fact.", 0)])
    fabric = TruthFabric(search_provider=_FakeSearchProvider([]))
    await fabric._retrieve(plan, doc_store=doc_store, budget=None)

    if plan.mode == RetrievalMode.RAG_3_MULTI_HOP:
        assert 1 <= len(doc_store.queries) <= MAX_SUBQUERIES
    else:
        # RAG_4_CORRECTIVE issues exactly the single original query per
        # retrieval pass -- see module docstring below on corrective scope.
        assert len(doc_store.queries) == 1


@pytest.mark.asyncio
async def test_retrieval_calls_are_budget_metered():
    """Every retrieval pass (dense or web) consumes BudgetDimension.
    RETRIEVAL_CALLS -- a budget with zero retrieval capacity must raise
    TruthBudgetExhaustedError rather than silently retrieving for free."""
    from orca.truth.errors import TruthBudgetExhaustedError

    objective = "Search for real-time information about a live event"
    intent = compile_intent(objective)
    plan = build_retrieval_plan(objective, intent, ComplexityLevel.LOW, EvidenceLevel.SUPPORTED, FreshnessLevel.STATIC)
    doc_store = _FakeDocStore([_chunk("fact", 0)])
    fabric = TruthFabric(search_provider=_FakeSearchProvider([]))
    exhausted = CognitiveBudget(max_retrieval_calls=0)

    with pytest.raises(TruthBudgetExhaustedError):
        await fabric._retrieve(plan, doc_store=doc_store, budget=exhausted)


def test_corrective_rounds_are_planned_but_not_yet_a_retry_loop():
    """HONEST SCOPE (Phase 4 spec explicitly permits a corrective
    retrieval FOUNDATION, not a full implementation): RetrievalPlan.
    corrective_rounds is real, bounded planning metadata (see
    tests/test_truth_planner.py), but TruthFabric._retrieve does not yet
    re-query based on a corrective round when preliminary evidence is
    thin -- that re-query loop is left for a later phase. This test pins
    down that documented limitation so a future change to _retrieve is a
    deliberate decision, not a silent regression discovered later."""
    objective = "Research the topic and cite sources."
    intent = compile_intent(objective)
    plan = build_retrieval_plan(objective, intent, ComplexityLevel.LOW, EvidenceLevel.STRICT, FreshnessLevel.STATIC)
    assert plan.mode == RetrievalMode.RAG_4_CORRECTIVE
    assert plan.corrective_rounds > 0  # planned...
    import inspect

    from orca.truth import truth_fabric
    source = inspect.getsource(truth_fabric.TruthFabric._retrieve)
    assert "corrective_rounds" not in source  # ...but not yet consumed by _retrieve
