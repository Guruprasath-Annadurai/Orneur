"""Authenticated document task: upload, retrieve, cite, evidence, delete.

This is not a live Deep RAG call. Keyword retrieval runs on the caller's
bytes. Citations are only those passages. Deletion removes the upload;
it does not claim other replicas are gone.
"""

from __future__ import annotations

from types import SimpleNamespace

from orca.docs.extractor import extract
from orca.serve.citations import build_sources
from orca.serve.uploads import UploadError, delete, read, store
from orca.specialists.handlers import retrieval_handler
from orca.sovereign_mission.verify import sha256_bytes


class DocumentTaskError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _chunks(text: str, size: int = 400) -> list[str]:
    body = text.strip()
    if not body:
        return []
    return [body[i : i + size] for i in range(0, len(body), size)]


def run(*, user_id: str, filename: str, data: bytes, question: str) -> dict:
    if not user_id:
        raise DocumentTaskError("unauthenticated")
    try:
        stored = store(user_id, filename, data)
    except UploadError as exc:
        raise DocumentTaskError(exc.code) from exc
    text = extract(filename, data)
    documents = [
        {
            "tenant_id": user_id,
            "doc_id": stored["sha256"][:16],
            "text": chunk,
            "locator": index,
            "synthetic": False,
        }
        for index, chunk in enumerate(_chunks(text))
    ]
    retrieved = retrieval_handler({"tenant_id": user_id, "query": question, "documents": documents})
    dna = {}
    for index, cite in enumerate(retrieved.output.get("citations") or [], start=1):
        dna[f"D{index}"] = {
            "text": cite["excerpt"],
            "chunk_idx": cite["locator"],
            "filename": filename,
            "synthetic": False,
        }
    rag = SimpleNamespace(
        citation_dna=dna,
        retrieval_rounds=1,
        sufficiency_confidence=1.0 if dna else 0.0,
        used_fallback=True,
    )
    sources = build_sources(answer="see " + " ".join(f"[D{i}]" for i in range(1, len(dna) + 1)), session_id=None, rag_result=rag)
    evidence = []
    for row in sources["sources"]:
        supplied = dna[row["ref"]]["text"]
        evidence.append(
            {
                "ref": row["ref"],
                "excerpt_sha256": row["excerpt_sha256"],
                "match": row["excerpt_sha256"] == sha256_bytes(supplied.encode()),
                "synthetic": row["synthetic"],
            }
        )
    return {
        "upload": stored,
        "retrieval_status": retrieved.status,
        "sources": sources["sources"],
        "evidence": evidence,
        "verified": bool(evidence) and all(item["match"] for item in evidence),
        "method": "keyword_retrieval",
        "deep_rag": False,
    }


def remove(*, user_id: str, filename: str) -> dict:
    try:
        body = delete(user_id, filename)
    except UploadError as exc:
        raise DocumentTaskError(exc.code) from exc
    missing = False
    try:
        read(user_id, filename)
    except UploadError as exc:
        missing = exc.code == "not_found"
    return {"deleted": body["deleted"], "local_absent": missing, "replicas_claimed": False}
