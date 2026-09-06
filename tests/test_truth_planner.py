"""
RetrievalPlanner: mode selection, bounded limits, decomposition. Pure,
deterministic, no I/O (Phase 4 spec §6-8).
"""
from __future__ import annotations

from orca.cognitive.contracts import ComplexityLevel, EvidenceLevel, FreshnessLevel
from orca.cognitive.intent import compile_intent
from orca.truth.contracts import RetrievalMode, RetrievalSourceType
from orca.truth.decomposition import decompose_query
from orca.truth.planner import MAX_CORRECTIVE_ROUNDS, MAX_MULTI_HOP_DEPTH, MAX_SUBQUERIES, build_retrieval_plan


def _plan(msg: str):
    intent = compile_intent(msg)
    return build_retrieval_plan(msg, intent, ComplexityLevel.MEDIUM, EvidenceLevel.SUPPORTED, FreshnessLevel.STATIC)


def test_no_retrieval_for_evidence_none():
    intent = compile_intent("hi")
    plan = build_retrieval_plan("hi", intent, ComplexityLevel.TRIVIAL, EvidenceLevel.NONE, FreshnessLevel.STATIC)
    assert plan.mode == RetrievalMode.RAG_0_NONE
    assert plan.max_documents == 0
    assert plan.sources == []


def test_audit_grade_always_research_mode():
    intent = compile_intent("What is the exact regulatory requirement?")
    plan = build_retrieval_plan("x", intent, ComplexityLevel.LOW, EvidenceLevel.AUDIT_GRADE, FreshnessLevel.STATIC)
    assert plan.mode == RetrievalMode.RAG_5_RESEARCH


def test_strict_evidence_uses_corrective_or_multihop():
    intent = compile_intent("Research the topic and cite sources.")
    plan = build_retrieval_plan("x", intent, ComplexityLevel.LOW, EvidenceLevel.STRICT, FreshnessLevel.STATIC)
    assert plan.mode in (RetrievalMode.RAG_4_CORRECTIVE, RetrievalMode.RAG_3_MULTI_HOP)
    assert plan.corrective_rounds > 0 or plan.multi_hop_depth > 0


def test_every_mode_has_a_bounded_document_cap():
    for evidence in EvidenceLevel:
        intent = compile_intent("Research and compare things and cite sources.")
        plan = build_retrieval_plan("x", intent, ComplexityLevel.DEEP, evidence, FreshnessLevel.STATIC)
        assert isinstance(plan.max_documents, int)
        assert plan.max_documents <= 24  # highest cap (RAG_5_RESEARCH)


def test_corrective_rounds_never_exceed_max():
    intent = compile_intent("Research the topic and cite sources.")
    plan = build_retrieval_plan("x", intent, ComplexityLevel.LOW, EvidenceLevel.AUDIT_GRADE, FreshnessLevel.STATIC)
    assert plan.corrective_rounds <= MAX_CORRECTIVE_ROUNDS
    assert plan.multi_hop_depth <= MAX_MULTI_HOP_DEPTH


def test_reasons_are_never_empty():
    plan = _plan("hello")
    assert plan.reasons


# ── Query decomposition ─────────────────────────────────────────────────

def test_decompose_compare_query():
    parts = decompose_query("Compare Python and Rust for systems programming")
    assert len(parts) == 2


def test_decompose_leaves_simple_query_unchanged():
    parts = decompose_query("What is the capital of France?")
    assert parts == ["What is the capital of France?"]


def test_decompose_bounded_by_max_subqueries():
    long_query = " and ".join(f"topic{i}" for i in range(10))
    parts = decompose_query(long_query)
    assert len(parts) <= MAX_SUBQUERIES
