"""G-027 -- the structured source contract (`orneur.sources/1`).

A "source" here is a passage that was ACTUALLY retrieved and placed in the model's context for this answer; nothing is added afterwards and nothing is
inferred from the answer text. The answer is only ever described as grounded in sources when it really cites one:

  grounding = "none"                 no retrieval was performed (or nothing was retrieved) -- the UI must not say "based on your documents"
            = "retrieved_not_cited"  passages were supplied to the model but the answer cites none of them ([D#] markers) -- show them as "consulted"
            = "cited"                at least one supplied passage is cited by the answer
            = "evidence_state_only"  the Truth Fabric answered; it reports an evidence state / coverage but not per-passage records, so no source
                                     cards are invented

Per source: `ref` (the [D#] marker in the answer), `kind`, `filename`, `doc_id` (only when the session has exactly one document of that name),
`locator` (chunk index, 0-based), `excerpt` + `excerpt_sha256` (so a client can verify what was shown), `retrieved_at`, `cited_in_answer`.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

SCHEMA = "orneur.sources/1"
_EXCERPT_CHARS = 300


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _doc_id_for(session_id: str | None, filename: str) -> str | None:
    if not session_id:
        return None
    try:
        from orca.docs.store import list_docs

        matches = [d["doc_id"] for d in list_docs(session_id) if d.get("filename") == filename]
        return matches[0] if len(matches) == 1 else None
    except Exception:
        return None


def _locator(location: str) -> dict:
    m = re.fullmatch(r"chunk#(\d+)", location or "")
    if m:
        return {"type": "chunk", "chunk_index": int(m.group(1))}
    return {"type": "opaque", "value": location or ""}


def build_sources(*, answer: str, session_id: str | None, rag_result=None, evidence_state: str | None = None,
                  citation_coverage: dict | None = None, evidence_passages: list | None = None, retrieved_at: str | None = None) -> dict:
    """Returns {"summary": {...}, "sources": [...]}. Pure function of what was really retrieved."""
    when = retrieved_at or _now()
    dna = (getattr(rag_result, "citation_dna", None) or {}) if rag_result is not None else {}
    sources = []
    for ref, info in dna.items():
        text = info.get("text", "") or ""
        idx = int(info.get("chunk_idx", 0) or 0)
        filename = info.get("filename", "") or ""
        sources.append({
            "ref": ref,
            "kind": "uploaded_document",
            "filename": filename,
            "doc_id": _doc_id_for(session_id, filename),
            "locator": {"type": "chunk", "chunk_index": idx},
            "excerpt": text[:_EXCERPT_CHARS],
            "excerpt_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "retrieved_at": when,
            "cited_in_answer": bool(re.search(rf"\[{re.escape(ref)}\]", answer or "")),
        })

    for ev in evidence_passages or []:                       # Truth Fabric path: the passages it really supplied, in [D#] order
        text = ev.get("text", "") or ""
        ref = ev.get("ref", "")
        identity = ev.get("identity", "") or ""
        is_doc = identity.startswith("session:")
        sources.append({
            "ref": ref,
            "kind": "uploaded_document" if is_doc else "web_page",
            "filename": ev.get("document_id", "") if is_doc else "",
            "url": None if is_doc else identity,
            "doc_id": _doc_id_for(session_id, ev.get("document_id", "")) if is_doc else None,
            "locator": _locator(ev.get("location", "")),
            "excerpt": text[:_EXCERPT_CHARS],
            "excerpt_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "retrieved_at": ev.get("retrieved_at") or when,
            "cited_in_answer": bool(re.search(rf"\[{re.escape(ref)}\]", answer or "")),
        })

    if sources:
        grounding = "cited" if any(s["cited_in_answer"] for s in sources) else "retrieved_not_cited"
        retrieval_performed = True
    elif evidence_state is not None:
        grounding, retrieval_performed = "evidence_state_only", True        # Truth Fabric ran but supplied no passages: no source cards are invented
    else:
        grounding, retrieval_performed = "none", rag_result is not None   # retrieval ran but returned nothing -> still "none"

    summary = {
        "schema": SCHEMA,
        "retrieval_performed": retrieval_performed,
        "grounding": grounding,
        "source_count": len(sources),
        "retrieved_at": when if retrieval_performed else None,
    }
    if rag_result is not None:
        summary["retrieval"] = {"method": "deep_rag", "rounds": rag_result.retrieval_rounds, "sufficiency_confidence": rag_result.sufficiency_confidence,
                                "used_fallback": rag_result.used_fallback}
    if evidence_state is not None:
        summary["evidence_state"] = evidence_state
        if citation_coverage is not None:
            summary["citation_coverage"] = citation_coverage
    return {"summary": summary, "sources": sources}
