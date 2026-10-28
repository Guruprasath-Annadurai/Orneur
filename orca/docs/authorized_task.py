"""Authenticated document task: upload, retrieve, cite, and split verification claims.

Keyword retrieval on the caller's bytes is not Deep RAG and is not proof that
an AI answer was grounded. Extraction runs before persistence so a failed
parse does not leave an object.
"""

from __future__ import annotations

from types import SimpleNamespace

from orca.auth.store import User
from orca.docs.extractor import extract
from orca.serve.citations import build_sources
from orca.serve.uploads import UploadError, delete_for, read_for, store_for
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


def _user(user) -> User:
    if isinstance(user, (str, bytes, bytearray, dict)):
        raise DocumentTaskError("unauthenticated")
    uid = getattr(user, "id", None)
    if not isinstance(uid, str) or not uid.strip():
        raise DocumentTaskError("unauthenticated")
    return user


def run(*, user: User, filename: str, data: bytes, question: str) -> dict:
    owner = _user(user)
    if not isinstance(question, str) or not question.strip():
        raise DocumentTaskError("query_refused")
    try:
        text = extract(filename, data)
    except Exception as exc:
        raise DocumentTaskError("extract_failed") from exc
    if not text.strip():
        raise DocumentTaskError("extract_failed")
    try:
        stored = store_for(owner, filename, data)
    except UploadError as exc:
        raise DocumentTaskError(exc.code) from exc
    upload_ok = stored["sha256"] == sha256_bytes(bytes(data))
    extracted_sha = sha256_bytes(text.encode())
    try:
        documents = [
            {
                "tenant_id": owner.id,
                "doc_id": stored["sha256"][:16],
                "text": chunk,
                "locator": index,
                "synthetic": False,
            }
            for index, chunk in enumerate(_chunks(text))
        ]
        retrieved = retrieval_handler({"tenant_id": owner.id, "query": question, "documents": documents})
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
        cited = "see " + " ".join(f"[D{i}]" for i in range(1, len(dna) + 1))
        sources = build_sources(answer=cited, session_id=None, rag_result=rag)
        excerpt_rows = []
        for row in sources["sources"]:
            supplied = dna[row["ref"]]["text"]
            excerpt_rows.append(
                {
                    "ref": row["ref"],
                    "excerpt_sha256": row["excerpt_sha256"],
                    "match": row["excerpt_sha256"] == sha256_bytes(supplied.encode()),
                    "synthetic": row["synthetic"],
                }
            )
        citation_ok = bool(excerpt_rows) and all(item["match"] for item in excerpt_rows)
        return {
            "upload": stored,
            "retrieval_status": retrieved.status,
            "sources": sources["sources"],
            "evidence": excerpt_rows,
            "method": "keyword_retrieval",
            "deep_rag": False,
            "claims": {
                "upload_integrity": "verified" if upload_ok else "failed",
                "extracted_text_integrity": "recorded",
                "extracted_sha256": extracted_sha,
                "citation_excerpt_consistency": "verified" if citation_ok else "unverified",
                "source_provenance": "local_upload",
                "answer_grounding": "not_performed",
                "independent_external": "not_performed",
            },
        }
    except Exception:
        try:
            delete_for(owner, filename)
        except UploadError:
            pass
        raise


def remove(*, user: User, filename: str) -> dict:
    owner = _user(user)
    try:
        body = delete_for(owner, filename)
    except UploadError as exc:
        raise DocumentTaskError(exc.code) from exc
    missing = False
    try:
        read_for(owner, filename)
    except UploadError as exc:
        missing = exc.code == "not_found"
    return {
        "deleted": body["deleted"],
        "local_absent": missing,
        "replicas_claimed": False,
        "replicas_removed": body.get("replicas_removed", "unknown"),
        "other_indexes": body.get("other_indexes", "not_reconciled"),
        "scope": "local_object",
    }
