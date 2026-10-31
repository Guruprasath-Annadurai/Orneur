"""
Document vector store — ChromaDB-backed RAG storage with Ollama embeddings.

Each session has its own ChromaDB collection: docs_{session_id[:8]}
Documents persist across server restarts.

Embedding strategy:
  1. Ollama /api/embeddings with nomic-embed-text (best quality, small)
  2. Fallback: sentence hash → BM25-style keyword index (no deps needed)
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.request
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from orca.config import ORCA_HOME

DOCS_DIR = ORCA_HOME / "docs"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

EMBED_MODEL = "nomic-embed-text"   # pulled via: ollama pull nomic-embed-text
EMBED_DIM   = 768

# Per-session doc metadata registry (so we can list/delete docs)
_REGISTRY_FILE = DOCS_DIR / "registry.json"


def _load_registry() -> dict:
    if _REGISTRY_FILE.exists():
        try:
            return json.loads(_REGISTRY_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_registry(reg: dict) -> None:
    # Atomic replace: a crash or a concurrent reader never sees a half-written registry.
    tmp = _REGISTRY_FILE.with_name(_REGISTRY_FILE.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(reg, indent=2))
    os.replace(tmp, _REGISTRY_FILE)


_registry_lock = threading.RLock()


@contextlib.contextmanager
def _registry_txn():
    """Serialises every read-modify-write of the registry across threads (RLock) and, where available, processes (flock),
    so two concurrent uploads can never overwrite each other's entry."""
    with _registry_lock:
        lock_fd = None
        try:
            import fcntl

            DOCS_DIR.mkdir(parents=True, exist_ok=True)
            lock_fd = os.open(str(_REGISTRY_FILE) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except (ImportError, OSError):
            lock_fd = None
        try:
            yield
        finally:
            if lock_fd is not None:
                os.close(lock_fd)        # closing releases the flock


def _ollama_embed(texts: list[str], host: str = "http://localhost:11434") -> list[list[float]] | None:
    """Embed a list of texts via Ollama. Returns None if unavailable."""
    try:
        embeddings = []
        for text in texts:
            payload = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode()
            req = urllib.request.Request(
                f"{host}/api/embeddings",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            embeddings.append(data["embedding"])
        return embeddings
    except Exception:
        return None


def _bm25_score(query_terms: list[str], doc_text: str) -> float:
    """Simple BM25-inspired TF-IDF score for keyword fallback."""
    k1, b = 1.5, 0.75
    doc_words = re.findall(r"\w+", doc_text.lower())
    avg_len = 200  # assumed average doc length
    tf_counts = Counter(doc_words)
    score = 0.0
    for term in query_terms:
        tf = tf_counts.get(term.lower(), 0)
        if tf == 0:
            continue
        norm_tf = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * len(doc_words) / avg_len))
        score += norm_tf
    return score


class DocStore:
    """
    Per-session document store.
    Stores chunks in ChromaDB with Ollama embeddings (or keyword fallback).
    """

    def __init__(self, session_id: str, ollama_host: str = "http://localhost:11434", *, enforce_registry: bool = False):
        self.session_id = session_id
        # L02-02: when True, ``retrieve`` returns only chunks of documents that are currently REGISTERED (and not being deleted) for this session.
        # An orphaned chunk (registry entry removed, delete half-finished, stale embedding) can then never reach a prompt or a citation.
        self.enforce_registry = enforce_registry
        self.ollama_host = ollama_host
        self._col_name = f"docs_{session_id[:12].replace('-', '')}"
        self.degraded = None                                    # why the vector index is not in use for this instance (None = in use or not installed)
        self._inited = False                                    # L03: the vector index (and the embedding-service probe) are opened on first use, not while a request builds a session
        self._init_lock = threading.Lock()
        self._chroma_v = None                                   # a vectorstore.Store when the index is usable
        self._collection_v = None
        self._fallback_file = DOCS_DIR / f"kw_{session_id[:8]}.jsonl"
        self._use_embeddings_v = False
        self._lexical_only_v = False

    def _lazy(self):
        if not self._inited:
            with self._init_lock:
                if not self._inited:
                    try:
                        self._init_store()
                    finally:
                        self._inited = True

    @property
    def _chroma(self):
        self._lazy()
        return self._chroma_v

    @_chroma.setter
    def _chroma(self, v):
        self._chroma_v = v

    @property
    def _collection(self):
        self._lazy()
        return self._collection_v

    @_collection.setter
    def _collection(self, v):
        self._inited = True                                     # a caller (a test) that installs its own collection owns the index
        self._collection_v = v

    @property
    def _use_embeddings(self):
        self._lazy()
        return self._use_embeddings_v

    @_use_embeddings.setter
    def _use_embeddings(self, v):
        self._use_embeddings_v = v

    @property
    def _lexical_only(self):
        self._lazy()
        return self._lexical_only_v

    @_lexical_only.setter
    def _lexical_only(self, v):
        self._lexical_only_v = v

    def _init_store(self):
        self._lexical_only_v = False
        from orca import vectorstore as vs

        if not vs.available():
            return                                              # ChromaDB not installed -- use keyword fallback
        db_path = DOCS_DIR / "vectors"
        db_path.mkdir(parents=True, exist_ok=True)
        try:
            from orca.serve import deletions

            if deletions.is_tombstoned(self.session_id):        # a deleted conversation has no index to open (fails closed)
                self.degraded = "tombstoned"
                return
            store = vs.Store(db_path)
            col, info = store.open_collection(self._col_name, {"hnsw:space": "cosine"}, binding=vs.session_binding(self.session_id))
        except vs.VectorError as exc:
            # The index is unreachable (timeout / busy / restarting). Documents stay answerable from the keyword index of THIS conversation; nothing is borrowed from anywhere else.
            self.degraded = type(exc).__name__
            return
        if info.get("status") == "mismatch":
            self.degraded = "ownership"                         # the collection belongs to another conversation: not read, not written
            return
        self._chroma_v, self._collection_v = store, col
        # Check if Ollama embeddings are available
        test = _ollama_embed(["test"], self.ollama_host)
        service_up = test is not None
        # L02-02: the collection already lives in ONE embedding space (the service's, or chroma's default). Whatever the service is doing right now, this
        # instance must keep talking to that space, or a query vector of the wrong dimension makes every search fail silently.
        stored_dim = self._stored_dimension(col)
        in_service_space = stored_dim is not None and stored_dim == EMBED_DIM
        self._use_embeddings_v = service_up and (stored_dim is None or in_service_space)
        self._lexical_only_v = in_service_space and not service_up

    def _stored_dimension(self, col=None) -> int | None:
        try:
            peek = (col or self._collection).peek(1)
            emb = peek.get("embeddings") if isinstance(peek, dict) else None
            if emb is not None and len(emb) > 0:
                return len(emb[0])
        except Exception:
            pass
        return None

    def add_chunks(self, chunks, doc_id: str, filename: str) -> int:
        """Embed and store chunks. Returns number of chunks stored."""
        if not chunks:
            return 0

        texts = [c.text for c in chunks]

        if self._collection is not None and not self._lexical_only:
            if self._use_embeddings:
                embeddings = _ollama_embed(texts, self.ollama_host)
            else:
                embeddings = None  # ChromaDB will auto-embed using its default

            ids = [f"{doc_id}_{c.chunk_idx}" for c in chunks]
            metadatas = [c.to_metadata() for c in chunks]

            try:
                if embeddings:
                    self._collection.add(documents=texts, embeddings=embeddings,
                                        ids=ids, metadatas=metadatas)
                else:
                    self._collection.add(documents=texts, ids=ids, metadatas=metadatas)
                return len(chunks)
            except Exception:
                pass

        # Keyword fallback
        with open(self._fallback_file, "a") as f:
            for c in chunks:
                f.write(json.dumps({
                    "doc_id": doc_id, "filename": filename,
                    "chunk_idx": c.chunk_idx, "text": c.text,
                }) + "\n")
        return len(chunks)

    def _authorized_doc_ids(self) -> set[str] | None:
        return {d["doc_id"] for d in list_docs(self.session_id)} if self.enforce_registry else None

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """Retrieve most relevant chunks for a query. Each hit carries its ``doc_id`` (chunk identity = doc_id + chunk_idx)."""
        from orca.serve import deletions

        if self.degraded == "tombstoned" or deletions.is_tombstoned(self.session_id):       # a deleted conversation retrieves nothing, through any path (fails closed)
            return []
        allowed = self._authorized_doc_ids()
        if allowed is not None and not allowed:
            return []
        want = top_k if allowed is None else top_k * 3          # over-fetch: unauthorized chunks are dropped below
        hits = self._retrieve_raw(query, want)
        if allowed is not None:
            hits = [h for h in hits if h.get("doc_id") in allowed]
        return hits[:top_k]

    def _retrieve_raw(self, query: str, top_k: int) -> list[dict]:
        """Ranked hits from every index that can hold this conversation's chunks: the vector collection (dense), or - when it cannot be queried in its own embedding
        space right now - a lexical scan of the collection's stored text; plus the keyword file (chunks written while the collection was unusable). De-duplicated
        by (doc_id, chunk_idx), dense hits first."""
        hits: list[dict] = []
        if self._collection is not None:
            hits = self._dense_hits(query, top_k)
            if hits is None:                                    # unusable in this mode / errored: do not lose the documents, rank their stored text instead
                hits = self._collection_lexical_hits(query, top_k)
        seen = {(h.get("doc_id", ""), h.get("chunk_idx", 0)) for h in hits}
        for h in self._keyword_file_hits(query, top_k):
            key = (h.get("doc_id", ""), h.get("chunk_idx", 0))
            if key not in seen:
                hits.append(h)
                seen.add(key)
        return hits[:top_k] if len(hits) > top_k and self._collection is None else hits

    def _dense_hits(self, query: str, top_k: int):
        if self._lexical_only:
            return None
        try:
            count = self._collection.count()
            if count == 0:
                return []
            if self._use_embeddings:
                q_emb = _ollama_embed([query], self.ollama_host)
                if q_emb:
                    results = self._collection.query(query_embeddings=q_emb, n_results=min(top_k, count))
                else:
                    results = self._collection.query(query_texts=[query], n_results=min(top_k, count))
            else:
                results = self._collection.query(query_texts=[query], n_results=min(top_k, count))
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            return [{"text": d, "filename": m.get("filename", ""), "chunk_idx": m.get("chunk_idx", 0), "doc_id": m.get("doc_id", "")}
                    for d, m in zip(docs, metas)]
        except Exception:
            return None

    def _collection_lexical_hits(self, query: str, top_k: int) -> list[dict]:
        try:
            got = self._collection.get(limit=5000, include=["documents", "metadatas"])
        except Exception:
            return []
        terms = re.findall(r"\w+", query.lower())
        scored = []
        for d, m in zip(got.get("documents") or [], got.get("metadatas") or []):
            score = _bm25_score(terms, d or "")
            if score > 0:
                scored.append((score, {"text": d, "filename": (m or {}).get("filename", ""), "chunk_idx": (m or {}).get("chunk_idx", 0), "doc_id": (m or {}).get("doc_id", "")}))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k]]

    def _keyword_file_hits(self, query: str, top_k: int) -> list[dict]:
        if not self._fallback_file.exists():
            return []
        query_terms = re.findall(r"\w+", query.lower())
        scored = []
        with open(self._fallback_file) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    score = _bm25_score(query_terms, entry["text"])
                    if score > 0:
                        scored.append((score, entry))
                except Exception:
                    continue
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"text": e["text"], "filename": e["filename"], "chunk_idx": e["chunk_idx"], "doc_id": e.get("doc_id", "")}
                for _, e in scored[:top_k]]

    def delete_doc_detailed(self, doc_id: str, *, reclaim: bool = True) -> dict:
        """Remove a document from EVERY store that can serve it, and say exactly what happened.

        L02-01: the vector collection and the keyword fallback are both retrieval paths (``retrieve`` falls back to the keyword file whenever the
        collection errors), so a document is deleted only when BOTH confirm. Each store is attempted independently: a collection outage must not
        leave the fallback copy behind. The fallback is rewritten through a temporary file + ``os.replace`` so a crash can never truncate other
        documents' text. Per-store values: ``ok`` | ``failed`` | ``absent`` (no such store / nothing to remove). Internal error text is never returned.
        """
        out = {"collection": "absent", "fallback": "absent"}
        if self._collection is not None:
            try:
                self._collection.delete(where={"doc_id": doc_id})
                out["collection"] = "ok"
            except Exception:
                out["collection"] = "failed"
        if self._fallback_file.exists():
            try:
                kept: list[str] = []
                with open(self._fallback_file) as f:
                    for line in f:
                        try:
                            if json.loads(line).get("doc_id") == doc_id:
                                continue
                        except Exception:
                            pass                                    # an unparseable line is not ours to drop
                        kept.append(line)
                tmp = self._fallback_file.with_name(self._fallback_file.name + f".{os.getpid()}.tmp")
                with open(tmp, "w") as f:
                    f.writelines(kept)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self._fallback_file)
                out["fallback"] = "ok"
            except Exception:
                out["fallback"] = "failed"
        out["ok"] = "failed" not in (out["collection"], out["fallback"])
        # L03: logical removal is not physical erasure. The deleted chunks' text stays in freed pages of the shared vector database until it is rewritten; say what happened.
        out["bytes"] = reclaim_doc_vectors(self._col_name, doc_id) if (reclaim and out["collection"] == "ok") else ("not_attempted" if out["collection"] == "ok" else "n/a")
        return out

    def delete_doc(self, doc_id: str) -> bool:
        """True only when every store confirmed the removal (see ``delete_doc_detailed``)."""
        return bool(self.delete_doc_detailed(doc_id)["ok"])

    def count(self) -> int:
        if self.enforce_registry:
            # L02-02: "does this conversation have documents" is decided by what is REGISTERED and not being deleted, not by stray chunks.
            return sum(int(d.get("chunk_count", 0) or 0) for d in list_docs(self.session_id))
        if self._collection is not None:
            try:
                return self._collection.count()
            except Exception:
                pass
        if self._fallback_file.exists():
            return sum(1 for _ in open(self._fallback_file))
        return 0

    def clear(self) -> None:
        if self._collection is not None:
            try:
                from orca import vectorstore as vs

                self._chroma.delete_collection(self._col_name)
                self._collection = self._chroma.open_collection(self._col_name, {"hnsw:space": "cosine"}, binding=vs.session_binding(self.session_id))[0]
            except Exception:
                pass
        if self._fallback_file.exists():
            self._fallback_file.unlink()


def reclaim_doc_vectors(collection: str | None = None, doc_id: str | None = None, timeout_s: float = 2.0) -> str:
    """Make a deletion PHYSICAL for the document vector store. With ``collection``: rebuild it without ``doc_id`` (drops the write-ahead log rows that still hold the deleted text),
    then rewrite the shared database and remove orphaned segment directories. RECLAIMED only when every step completed; otherwise DEFERRED, recorded durably (counted in the
    operator backlog) and retried by the maintenance sweep. Never raises."""
    from orca import vectorstore as vs
    from orca.vectorstore import pending

    if not vs.available():
        return "NOT_APPLICABLE"
    root = DOCS_DIR / "vectors"
    try:
        store = vs.Store(root)
        if collection:
            try:
                store.rebuild_without(collection, "doc_id" if doc_id else None, doc_id, deadline_s=60.0)
            except vs.VectorNotFound:
                pass                                                   # the collection is already gone: nothing left to purge
        status = store.vacuum(timeout_s=timeout_s, deadline_s=timeout_s + 3.0)
    except vs.VectorError:
        status = vs.DEFERRED
    if status == vs.DEFERRED:
        pending.record(root, collection or "docs", "physical reclamation did not complete")
    elif status == vs.RECLAIMED and not collection:
        pending.clear_all(root)
    elif status == vs.RECLAIMED:
        pending.clear_key(root, collection)
    return status


def drop_session_collection(session_id: str) -> str:
    """Session deletion: remove the conversation's whole document collection (its log goes with it), then reclaim the bytes. Returns the reclamation status."""
    from orca import vectorstore as vs

    if not vs.available():
        return "NOT_APPLICABLE"                                        # no chromadb: only the keyword index exists
    root = DOCS_DIR / "vectors"
    name = f"docs_{session_id[:12].replace('-', '')}"
    try:
        res = vs.Store(root).delete_collection(name, deadline_s=10.0, binding=vs.session_binding(session_id))
        if res.get("refused") == "not_owner":
            return "NOT_APPLICABLE"
        if not res.get("removed"):
            raise vs.VectorUnavailable("collection still present")
    except vs.VectorNotFound:
        pass
    return reclaim_doc_vectors()


def retry_pending_doc_reclamation() -> dict:
    from orca.vectorstore import pending

    entries = pending.load(DOCS_DIR / "vectors")
    results = {}
    for e in entries:
        key = e.get("key", "docs")
        results[key] = reclaim_doc_vectors(None if key == "docs" else key, None)
    return {"pending_before": len(entries), "results": results}


# ── Registry helpers ──────────────────────────────────────────────────────────

class DocLimitExceeded(Exception):
    pass


def find_doc_by_sha(session_id: str, sha256: str) -> dict | None:
    for d in list_docs(session_id, include_deleting=True):
        if d.get("sha256") == sha256 and d.get("state") not in ("deleting", "deletion_failed"):
            return d
    return None


def register_doc(session_id: str, doc_id: str, filename: str, chunk_count: int, size_bytes: int, *, sha256: str | None = None, max_docs: int | None = None):
    """Add a registry entry. With ``max_docs`` the limit is checked INSIDE the registry transaction (two concurrent uploads cannot both squeeze under it); with
    ``sha256`` an identical document already in the conversation is returned instead of being added twice (``DocLimitExceeded`` / the existing entry)."""
    with _registry_txn():
        reg = _load_registry()
        if session_id not in reg:
            reg[session_id] = []
        if sha256:
            for d in reg[session_id]:
                if d.get("sha256") == sha256 and d.get("state") not in ("deleting", "deletion_failed"):
                    return d
        if max_docs is not None and len(reg[session_id]) >= max_docs:
            raise DocLimitExceeded()
        entry = {
            "doc_id":      doc_id,
            "filename":    filename,
            "chunk_count": chunk_count,
            "size_bytes":  size_bytes,
            "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if sha256:
            entry["sha256"] = sha256
        reg[session_id].append(entry)
        _save_registry(reg)
        return entry


def mark_doc_deleting(session_id: str, doc_id: str) -> bool:
    """L02-02: take a document out of every serving path BEFORE its chunks are physically removed. It stays in the registry (so a retry can find it)
    but ``list_docs`` and retrieval no longer see it."""
    with _registry_txn():
        reg = _load_registry()
        found = False
        for d in reg.get(session_id, []):
            if d["doc_id"] == doc_id:
                d["state"] = "deleting"
                found = True
        if found:
            _save_registry(reg)
        return found


DOC_DELETE_MAX_ATTEMPTS = 8


def pending_document_deletions() -> list[dict]:
    """Every registry entry whose deletion has not completed (``deleting``, or ``deletion_failed`` once retries were exhausted). Diagnostic + sweep input."""
    out = []
    for sid, docs in _load_registry().items():
        for d in docs:
            if d.get("state") in ("deleting", "deletion_failed"):
                out.append({"session_id": sid, "doc_id": d["doc_id"], "state": d["state"], "attempts": int(d.get("delete_attempts", 0))})
    return out


def sweep_document_deletions(ollama_host: str = "http://localhost:11434", limit: int = 20) -> dict:
    """L02-02g: bounded recovery for documents left ``deleting``. Each pass retries the dual-store removal (idempotent; the document is already out of every
    serving path, so a retry can never resurrect anything), unregisters on success, counts attempts, and after ``DOC_DELETE_MAX_ATTEMPTS`` marks the
    entry ``deletion_failed`` -- still hidden, no longer retried automatically, and visible through ``pending_document_deletions()`` / the health report."""
    done, failed, escalated = [], [], []
    for item in pending_document_deletions()[: int(limit)]:
        if item["state"] != "deleting":
            continue
        sid, doc_id = item["session_id"], item["doc_id"]
        try:
            ok = DocStore(sid, ollama_host).delete_doc_detailed(doc_id)["ok"]
        except Exception:
            ok = False
        if ok:
            unregister_doc(sid, doc_id)
            done.append(doc_id)
            continue
        with _registry_txn():
            reg = _load_registry()
            for d in reg.get(sid, []):
                if d["doc_id"] == doc_id:
                    d["delete_attempts"] = int(d.get("delete_attempts", 0)) + 1
                    d["last_delete_attempt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if d["delete_attempts"] >= DOC_DELETE_MAX_ATTEMPTS:
                        d["state"] = "deletion_failed"
                        escalated.append(doc_id)
            _save_registry(reg)
        failed.append(doc_id)
    return {"deleted": done, "retry_later": failed, "escalated": escalated}


def unregister_doc(session_id: str, doc_id: str):
    with _registry_txn():
        reg = _load_registry()
        if session_id in reg:
            reg[session_id] = [d for d in reg[session_id] if d["doc_id"] != doc_id]
        _save_registry(reg)


def list_docs(session_id: str, *, include_deleting: bool = False) -> list[dict]:
    reg = _load_registry()
    docs = reg.get(session_id, [])
    return docs if include_deleting else [d for d in docs if d.get("state") not in ("deleting", "deletion_failed")]
