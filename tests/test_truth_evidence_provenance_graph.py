"""
Evidence compilation, source independence/provenance, and EvidenceGraph --
pure, deterministic, no I/O (Phase 4 spec §16-20).
"""
from __future__ import annotations

from orca.cognitive.contracts import FreshnessLevel
from orca.truth.contracts import EvidenceEdgeType, EvidenceNodeType, IndependenceState, SourceType
from orca.truth.evidence import classify_source_quality, evidence_from_document_chunk, evidence_from_search_result
from orca.truth.graph import EvidenceGraph
from orca.truth.provenance import annotate_independence, assess_independence
from orca.truth.search_provider import SearchResultMetadata


def test_evidence_from_document_chunk_retains_provenance():
    chunk = {"text": "Paris is the capital of France.", "filename": "facts.txt", "chunk_idx": 0}
    evidence, source = evidence_from_document_chunk(chunk, session_id="s1")
    assert evidence.source_id == source.source_id
    assert source.source_type == SourceType.UPLOADED_DOCUMENT
    assert evidence.content_hash
    assert evidence.passage.text == chunk["text"]


def test_evidence_from_search_result_classifies_source_type():
    result = SearchResultMetadata(title="Docs", url="https://docs.example.com/api", snippet="API reference.", domain="docs.example.com")
    evidence, source = evidence_from_search_result(result)
    assert source.source_type == SourceType.WEB_PRIMARY
    assert source.quality.is_official


def test_community_domain_classified_as_community():
    quality = classify_source_quality("reddit.com")
    assert quality.is_community
    assert not quality.is_official


# ── Independence ─────────────────────────────────────────────────────────

def _doc_evidence(text: str, domain: str):
    result = SearchResultMetadata(title="t", url=f"https://{domain}/page", snippet=text, domain=domain)
    return evidence_from_search_result(result)


def test_same_domain_is_likely_derived():
    ev_a, src_a = _doc_evidence("Some claim here.", "blog.example.com")
    ev_b, src_b = _doc_evidence("A different claim entirely, unrelated words.", "blog.example.com")
    assert assess_independence(ev_a, src_a, ev_b, src_b) == IndependenceState.LIKELY_DERIVED


def test_near_identical_passage_across_domains_is_likely_derived():
    text = "The new API rate limit is exactly 500 requests per minute for all paid tiers."
    ev_a, src_a = _doc_evidence(text, "blogA.com")
    ev_b, src_b = _doc_evidence(text, "blogB.com")
    assert assess_independence(ev_a, src_a, ev_b, src_b) == IndependenceState.LIKELY_DERIVED


def test_unrelated_content_different_domains_is_unknown_not_independent():
    """Spec §20: never claim perfect independence -- absence of a derived
    signal returns UNKNOWN, not INDEPENDENT."""
    ev_a, src_a = _doc_evidence("The stock market closed higher today.", "newsA.com")
    ev_b, src_b = _doc_evidence("A recipe for chocolate chip cookies.", "newsB.com")
    assert assess_independence(ev_a, src_a, ev_b, src_b) == IndependenceState.UNKNOWN


def test_annotate_independence_mutates_sources_in_place():
    text = "Blog A B C all derived from source S1 word for word here now."
    ev_a, src_a = _doc_evidence(text, "blogA.com")
    ev_b, src_b = _doc_evidence(text, "blogB.com")
    annotate_independence([src_a, src_b], [ev_a, ev_b])
    assert src_a.independence == IndependenceState.LIKELY_DERIVED
    assert src_b.independence == IndependenceState.LIKELY_DERIVED
    assert src_b.source_id in src_a.derived_from


# ── EvidenceGraph ────────────────────────────────────────────────────────

def test_graph_add_node_and_edge():
    graph = EvidenceGraph()
    graph.add_node("c1", EvidenceNodeType.CLAIM, label="claim text")
    graph.add_node("e1", EvidenceNodeType.EVIDENCE)
    graph.add_edge("c1", "e1", EvidenceEdgeType.SUPPORTS)
    assert graph.supporting_evidence_for("c1") == ["e1"]


def test_graph_add_edge_requires_existing_nodes():
    graph = EvidenceGraph()
    graph.add_node("c1", EvidenceNodeType.CLAIM)
    try:
        graph.add_edge("c1", "missing", EvidenceEdgeType.SUPPORTS)
        assert False, "should have raised"
    except ValueError:
        pass


def test_graph_contradicts_edges_distinct_from_supports():
    graph = EvidenceGraph()
    graph.add_node("c1", EvidenceNodeType.CLAIM)
    graph.add_node("c2", EvidenceNodeType.CLAIM)
    graph.add_edge("c1", "c2", EvidenceEdgeType.CONTRADICTS)
    assert graph.contradicting_claims_for("c1") == ["c2"]
    assert graph.supporting_evidence_for("c1") == []
