from __future__ import annotations

from types import SimpleNamespace

from orca.serve.citations import build_sources


def test_synthetic_passages_stay_labeled_and_real_ones_do_not():
    rag = SimpleNamespace(
        citation_dna={
            "D1": {"text": "fixture excerpt", "chunk_idx": 0, "filename": "toy.txt", "synthetic": True},
            "D2": {"text": "uploaded excerpt", "chunk_idx": 1, "filename": "real.txt"},
        },
        retrieval_rounds=1,
        sufficiency_confidence=0.5,
        used_fallback=False,
    )
    body = build_sources(answer="see [D1] and [D2]", session_id=None, rag_result=rag)
    by_ref = {row["ref"]: row for row in body["sources"]}
    assert by_ref["D1"]["synthetic"] is True
    assert by_ref["D2"]["synthetic"] is False
    assert by_ref["D1"]["cited_in_answer"] is True
    unlabeled = build_sources(
        answer="x",
        session_id=None,
        rag_result=None,
        evidence_passages=[{"ref": "D3", "text": "web", "identity": "https://example.invalid", "synthetic": True}],
    )
    assert unlabeled["sources"][0]["synthetic"] is True
    assert unlabeled["sources"][0]["kind"] == "web_page"
