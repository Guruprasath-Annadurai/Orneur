"""
Phase 4.1: real bounded corrective retrieval, evidence-vs-evidence
contradiction detection (with temporal reconciliation), and the bounded
FIND_COUNTER_EVIDENCE hook. Deterministic -- Gateway-routed calls
(reform_query, the contradiction judge) are monkeypatched so these tests
run fast and don't need live Ollama; live-Ollama end-to-end coverage
stays in tests/test_truth_fabric_integration.py's existing style.
"""
from __future__ import annotations

import pytest

from orca.cognitive.contracts import CognitiveBudget, ComplexityLevel, EvidenceLevel, FreshnessLevel
from orca.cognitive.intent import compile_intent
from orca.truth import truth_fabric as truth_fabric_mod
from orca.truth.contracts import (
    ContradictionRelationship,
    CounterEvidenceStatus,
    Evidence,
    EvidencePassage,
    EvidenceSource,
    EvidenceState,
    SourceType,
    TruthRequest,
)
from orca.truth.contradiction import detect_evidence_contradictions
from orca.truth.corrective import is_repeat_query
from orca.truth.counter_evidence import find_counter_evidence
from orca.truth.planner import MAX_TOTAL_RETRIEVAL_QUERIES
from orca.truth.truth_fabric import TruthFabric, _merge_evidence


class _FakeDocStore:
    def __init__(self, responses: dict[str, list[dict]]):
        self._responses = responses
        self.queries: list[str] = []

    def count(self) -> int:
        return 1

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        self.queries.append(query)
        return self._responses.get(query, [])


class _FakeSearchProvider:
    def search(self, query, n=5, *, domain_filter=None):
        return []


def _evidence(text: str, ev_id: str, content_hash: str, published_at: str | None = None) -> Evidence:
    return Evidence(evidence_id=ev_id, source_id=f"src-{ev_id}", document_id="d", passage=EvidencePassage(text=text), content_hash=content_hash, published_at=published_at)


# ── Corrective retrieval loop ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_corrective_round_succeeds_after_reformed_query_finds_evidence(monkeypatch):
    async def _fake_reform(objective, missing_info, tier="nano"):
        return {"reformed_query": "better rate limit query", "reason": "too vague", "evidence_gap": "specific number"}

    monkeypatch.setattr(truth_fabric_mod, "reform_query", _fake_reform)

    doc_store = _FakeDocStore({
        "What is the limit?": [],  # initial query finds nothing -> INSUFFICIENT
        "better rate limit query": [{"text": "The rate limit is 100/min.", "filename": "f.txt", "chunk_idx": 0}],
    })
    fabric = TruthFabric(search_provider=_FakeSearchProvider())
    intent = compile_intent("What is the limit?")
    req = TruthRequest(objective="What is the limit?", evidence_requirement=EvidenceLevel.STRICT, freshness_requirement=FreshnessLevel.STATIC)
    result = await fabric.assess_evidence(req, intent, ComplexityLevel.LOW, doc_store=doc_store)

    assert len(result.corrective_rounds) == 1
    assert result.corrective_rounds[0].rewritten_query == "better rate limit query"
    assert result.corrective_rounds[0].new_evidence_count == 1
    assert result.retrieval_stop_reason == "evidence_became_sufficient"
    assert result.evidence_state == EvidenceState.SUFFICIENT


@pytest.mark.asyncio
async def test_corrective_round_stops_when_no_new_evidence_found(monkeypatch):
    async def _fake_reform(objective, missing_info, tier="nano"):
        return {"reformed_query": "still nothing query", "reason": "x", "evidence_gap": "y"}

    monkeypatch.setattr(truth_fabric_mod, "reform_query", _fake_reform)
    doc_store = _FakeDocStore({"What is the limit?": [], "still nothing query": []})
    fabric = TruthFabric(search_provider=_FakeSearchProvider())
    intent = compile_intent("What is the limit?")
    req = TruthRequest(objective="What is the limit?", evidence_requirement=EvidenceLevel.STRICT, freshness_requirement=FreshnessLevel.STATIC)
    result = await fabric.assess_evidence(req, intent, ComplexityLevel.LOW, doc_store=doc_store)

    assert result.retrieval_stop_reason == "no_new_evidence_discovered"
    assert len(result.corrective_rounds) == 1  # stopped after round 1, never tried a second


@pytest.mark.asyncio
async def test_corrective_round_stops_on_repeated_query(monkeypatch):
    async def _fake_reform(objective, missing_info, tier="nano"):
        return {"reformed_query": objective, "reason": "x", "evidence_gap": "y"}  # "reforms" to the SAME query

    monkeypatch.setattr(truth_fabric_mod, "reform_query", _fake_reform)
    doc_store = _FakeDocStore({"What is the limit?": []})
    fabric = TruthFabric(search_provider=_FakeSearchProvider())
    intent = compile_intent("What is the limit?")
    req = TruthRequest(objective="What is the limit?", evidence_requirement=EvidenceLevel.STRICT, freshness_requirement=FreshnessLevel.STATIC)
    result = await fabric.assess_evidence(req, intent, ComplexityLevel.LOW, doc_store=doc_store)

    assert result.retrieval_stop_reason == "repeated_query"
    assert result.corrective_rounds == []


@pytest.mark.asyncio
async def test_corrective_round_bounded_by_max_rounds(monkeypatch):
    call_count = {"n": 0}

    async def _fake_reform(objective, missing_info, tier="nano"):
        call_count["n"] += 1
        return {"reformed_query": f"query attempt {call_count['n']}", "reason": "x", "evidence_gap": "y"}

    monkeypatch.setattr(truth_fabric_mod, "reform_query", _fake_reform)
    doc_store = _FakeDocStore({})  # every query, including reformed ones, finds nothing
    fabric = TruthFabric(search_provider=_FakeSearchProvider())
    intent = compile_intent("Research the topic and cite sources.")  # STRICT + this objective -> RAG_4_CORRECTIVE
    req = TruthRequest(objective="Research the topic and cite sources.", evidence_requirement=EvidenceLevel.STRICT, freshness_requirement=FreshnessLevel.STATIC)
    result = await fabric.assess_evidence(req, intent, ComplexityLevel.LOW, doc_store=doc_store)

    from orca.truth.planner import MAX_CORRECTIVE_ROUNDS
    assert len(result.corrective_rounds) <= MAX_CORRECTIVE_ROUNDS
    assert result.retrieval_stop_reason in ("no_new_evidence_discovered", "max_corrective_rounds_reached")


@pytest.mark.asyncio
async def test_multi_hop_and_corrective_share_one_query_budget(monkeypatch):
    """RAG_5_RESEARCH plans both multi-hop subqueries AND corrective
    rounds -- the shared MAX_TOTAL_RETRIEVAL_QUERIES cap must stop the
    combination well short of multi_hop_depth * corrective_rounds *
    subqueries (spec §11), never letting them multiply unbounded."""
    reform_calls = {"n": 0}

    async def _fake_reform(objective, missing_info, tier="nano"):
        reform_calls["n"] += 1
        return {"reformed_query": f"reformed {reform_calls['n']}", "reason": "x", "evidence_gap": "y"}

    monkeypatch.setattr(truth_fabric_mod, "reform_query", _fake_reform)
    doc_store = _FakeDocStore({})  # nothing ever found -- forces every possible corrective round to be attempted
    fabric = TruthFabric(search_provider=_FakeSearchProvider())
    objective = "Research and compare topic A and topic B and cite sources with full analysis"
    intent = compile_intent(objective)
    req = TruthRequest(objective=objective, evidence_requirement=EvidenceLevel.AUDIT_GRADE, freshness_requirement=FreshnessLevel.STATIC)
    result = await fabric.assess_evidence(req, intent, ComplexityLevel.DEEP, doc_store=doc_store)

    # Total dense queries actually issued (multi-hop subqueries + every
    # corrective round's single query) must never exceed the shared cap.
    total_queries_issued = len(doc_store.queries)
    assert total_queries_issued <= MAX_TOTAL_RETRIEVAL_QUERIES
    assert result.retrieval_stop_reason  # always records SOME reason, never silently stops


def test_is_repeat_query_normalizes_case_and_whitespace():
    assert is_repeat_query("  What Is The Limit?  ", ["what is the limit?"])
    assert not is_repeat_query("a genuinely different query", ["what is the limit?"])


# ── Evidence merge/dedupe ────────────────────────────────────────────────

def test_merge_evidence_dedupes_by_content_hash():
    ev_a = _evidence("same text", "e1", content_hash="hash1")
    src_a = EvidenceSource(source_id="src-e1", identity="s1", source_type=SourceType.WEB_SECONDARY)
    ev_b_dup = _evidence("same text", "e2", content_hash="hash1")  # same hash -- a duplicate
    ev_c_new = _evidence("different text", "e3", content_hash="hash2")
    src_c = EvidenceSource(source_id="src-e3", identity="s3", source_type=SourceType.WEB_SECONDARY)

    merged_ev, merged_src, added = _merge_evidence([ev_a], [src_a], [ev_b_dup, ev_c_new], [src_a, src_c])
    assert added == 1  # only ev_c_new counted -- ev_b_dup is a duplicate by content_hash
    assert len(merged_ev) == 2


# ── Evidence-vs-evidence contradiction ───────────────────────────────────

@pytest.mark.asyncio
async def test_detect_evidence_contradictions_flags_direct_conflict(monkeypatch):
    async def _fake_judge(prompt, system, tier="nano", max_tokens=150):
        return {"relationship": "DIRECT_CONTRADICTION", "subject": "API rate limit", "reason": "different numbers for the same limit"}

    monkeypatch.setattr("orca.truth.contradiction.gateway_json_call", _fake_judge)
    ev_a = _evidence("The API rate limit is 10,000 requests per day.", "e1", "h1")
    ev_b = _evidence("The API rate limit is 20,000 requests per day.", "e2", "h2")
    contradictions = await detect_evidence_contradictions([ev_a, ev_b])

    assert len(contradictions) == 1
    assert contradictions[0].relationship == ContradictionRelationship.DIRECT_CONTRADICTION
    assert contradictions[0].source_a_id == ev_a.source_id
    assert contradictions[0].source_b_id == ev_b.source_id
    assert contradictions[0].resolution_state == "UNRESOLVED"


@pytest.mark.asyncio
async def test_detect_evidence_contradictions_reclassifies_as_temporal(monkeypatch):
    """Spec §14: a judge-flagged DIRECT_CONTRADICTION between two pieces
    of evidence with different publication times is reclassified as
    TEMPORALLY_RECONCILABLE -- the judge's own date reasoning is not
    trusted, the deterministic timestamp comparison overrides it."""
    async def _fake_judge(prompt, system, tier="nano", max_tokens=150):
        return {"relationship": "DIRECT_CONTRADICTION", "subject": "API rate limit", "reason": "different numbers"}

    monkeypatch.setattr("orca.truth.contradiction.gateway_json_call", _fake_judge)
    ev_a = _evidence("The API rate limit is 100/min.", "e1", "h1", published_at="2024-03-01")
    ev_b = _evidence("The API rate limit is 500/min.", "e2", "h2", published_at="2024-09-01")
    contradictions = await detect_evidence_contradictions([ev_a, ev_b])

    assert contradictions[0].relationship == ContradictionRelationship.TEMPORALLY_RECONCILABLE


@pytest.mark.asyncio
async def test_detect_evidence_contradictions_never_auto_resolves_by_authority(monkeypatch):
    """Spec §15: contradictory evidence must remain visible until resolved
    -- resolution_state is never anything but UNRESOLVED from this
    detector, regardless of either source's authority."""
    async def _fake_judge(prompt, system, tier="nano", max_tokens=150):
        return {"relationship": "DIRECT_CONTRADICTION", "subject": "x", "reason": "y"}

    monkeypatch.setattr("orca.truth.contradiction.gateway_json_call", _fake_judge)
    ev_a = _evidence("Value is 10.", "e1", "h1")
    ev_b = _evidence("Value is 20.", "e2", "h2")
    contradictions = await detect_evidence_contradictions([ev_a, ev_b])
    assert all(c.resolution_state == "UNRESOLVED" for c in contradictions)


@pytest.mark.asyncio
async def test_detect_evidence_contradictions_below_two_pieces_is_noop():
    assert await detect_evidence_contradictions([]) == []
    assert await detect_evidence_contradictions([_evidence("x", "e1", "h1")]) == []


# ── Counter-evidence hook ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_counter_evidence_not_run_without_budget_pretense():
    """Spec §17: if budget can't afford it, record NOT_RUN/BUDGET_EXHAUSTED
    -- never silently skip with no trace, never pretend it ran."""
    exhausted = CognitiveBudget(max_retrieval_calls=0)
    result = await find_counter_evidence("The rate limit is 100/min.", _FakeSearchProvider(), budget=exhausted)
    assert result.status == CounterEvidenceStatus.BUDGET_EXHAUSTED
    assert result.evidence == []


@pytest.mark.asyncio
async def test_counter_evidence_runs_and_issues_one_bounded_query():
    class _CountingProvider:
        def __init__(self):
            self.calls = 0

        def search(self, query, n=5, *, domain_filter=None):
            self.calls += 1
            return []

    provider = _CountingProvider()
    result = await find_counter_evidence("The rate limit is 100/min.", provider, budget=None)
    assert result.status == CounterEvidenceStatus.RAN
    assert provider.calls == 1  # exactly one bounded adversarial query, never a family of follow-ups
    assert "evidence against" in result.query.lower()
