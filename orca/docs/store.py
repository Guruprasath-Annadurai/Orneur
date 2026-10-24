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
import fcntl
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

    def __init__(self, session_id: str, ollama_host: str = "http://localhost:11434"):
        self.session_id = session_id
        self.ollama_host = ollama_host
        self._col_name = f"docs_{session_id[:12].replace('-', '')}"
        self._chroma = None
        self._collection = None
        self._fallback_file = DOCS_DIR / f"kw_{session_id[:8]}.jsonl"
        self._use_embeddings = False
        self._init_store()

    def _init_store(self):
        try:
            import chromadb
            db_path = DOCS_DIR / "vectors"
            db_path.mkdir(parents=True, exist_ok=True)
            self._chroma = chromadb.PersistentClient(path=str(db_path))
            self._collection = self._chroma.get_or_create_collection(
                name=self._col_name,
                metadata={"hnsw:space": "cosine"},
            )
            # Check if Ollama embeddings are available
            test = _ollama_embed(["test"], self.ollama_host)
            self._use_embeddings = test is not None
        except ImportError:
            pass  # ChromaDB not installed — use keyword fallback

    def add_chunks(self, chunks, doc_id: str, filename: str) -> int:
        """Embed and store chunks. Returns number of chunks stored."""
        if not chunks:
            return 0

        texts = [c.text for c in chunks]

        if self._collection is not None:
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

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """Retrieve most relevant chunks for a query."""
        if self._collection is not None:
            try:
                if self._use_embeddings:
                    q_emb = _ollama_embed([query], self.ollama_host)
                    if q_emb:
                        results = self._collection.query(
                            query_embeddings=q_emb, n_results=min(top_k, self._collection.count() or 1),
                        )
                    else:
                        results = self._collection.query(
                            query_texts=[query], n_results=min(top_k, self._collection.count() or 1),
                        )
                else:
                    count = self._collection.count()
                    if count == 0:
                        return []
                    results = self._collection.query(
                        query_texts=[query], n_results=min(top_k, count),
                    )
                docs  = results.get("documents", [[]])[0]
                metas = results.get("metadatas", [[]])[0]
                return [{"text": d, "filename": m.get("filename", ""), "chunk_idx": m.get("chunk_idx", 0)}
                        for d, m in zip(docs, metas)]
            except Exception:
                pass

        # Keyword fallback
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
        return [{"text": e["text"], "filename": e["filename"], "chunk_idx": e["chunk_idx"]}
                for _, e in scored[:top_k]]

    @contextlib.contextmanager
    def _fallback_txn(self):
        """Serialize fallback rewrites in this process and across processes on one host.

        The file lock is not a multi-host guarantee. The replace is not a
        cross-store transaction with the vector collection.
        """
        lock = getattr(self, "_fallback_thread_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._fallback_thread_lock = lock
        with lock:
            fd = None
            try:
                self._fallback_file.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(str(self._fallback_file) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
                fcntl.flock(fd, fcntl.LOCK_EX)
            except OSError:
                fd = None
            try:
                yield
            finally:
                if fd is not None:
                    os.close(fd)

    def _fallback_has_doc(self, doc_id: str) -> bool:
        if not self._fallback_file.exists():
            return False
        with open(self._fallback_file) as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if entry.get("doc_id") == doc_id:
                    return True
        return False

    def _purge_fallback(self, doc_id: str) -> bool:
        """Rewrite the fallback without this document. The old file stays until replace."""
        path = self._fallback_file
        if not path.exists():
            return True
        kept = []
        with open(path) as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except Exception:
                    kept.append(line if line.endswith("\n") else line + "\n")
                    continue
                if entry.get("doc_id") == doc_id:
                    continue
                kept.append(line if line.endswith("\n") else line + "\n")
        tmp = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
        with open(tmp, "w") as handle:
            handle.writelines(kept)
            handle.flush()
            os.fsync(handle.fileno())
        hook = getattr(self, "_before_fallback_replace", None)
        if callable(hook):
            hook(tmp, path)
        os.replace(tmp, path)
        return not self._fallback_has_doc(doc_id)

    def delete_doc(self, doc_id: str) -> bool:
        """Remove one document from the collection and the keyword fallback.

        A collection error leaves the fallback unchanged so a retry can finish
        both. This is not an atomic commit across the authorized index.
        `last_delete_state` reports the stores that actually changed.
        """
        state = {
            "complete": False,
            "atomic": False,
            "collection": "absent",
            "fallback": "absent",
            "fallback_contains": False,
        }
        self.last_delete_state = state
        if not doc_id:
            state["collection"] = "rejected"
            state["fallback"] = "rejected"
            return False
        with self._fallback_txn():
            if self._collection is not None:
                try:
                    self._collection.delete(where={"doc_id": doc_id})
                    state["collection"] = "removed"
                except Exception:
                    state["collection"] = "failed"
                    state["fallback"] = "unchanged"
                    state["fallback_contains"] = self._fallback_has_doc(doc_id)
                    return False
            try:
                purged = self._purge_fallback(doc_id)
            except Exception:
                state["fallback"] = "failed"
                state["fallback_contains"] = self._fallback_has_doc(doc_id)
                return False
            remains = self._fallback_has_doc(doc_id)
            state["fallback"] = "removed" if not remains else "remains"
            state["fallback_contains"] = remains
            state["complete"] = bool(purged and not remains)
            return state["complete"]

    def count(self) -> int:
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
                self._chroma.delete_collection(self._col_name)
                self._collection = self._chroma.get_or_create_collection(
                    name=self._col_name, metadata={"hnsw:space": "cosine"},
                )
            except Exception:
                pass
        if self._fallback_file.exists():
            self._fallback_file.unlink()


# ── Registry helpers ──────────────────────────────────────────────────────────

def register_doc(session_id: str, doc_id: str, filename: str, chunk_count: int, size_bytes: int):
    with _registry_txn():
        reg = _load_registry()
        if session_id not in reg:
            reg[session_id] = []
        reg[session_id].append({
            "doc_id":      doc_id,
            "filename":    filename,
            "chunk_count": chunk_count,
            "size_bytes":  size_bytes,
            "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        _save_registry(reg)


def unregister_doc(session_id: str, doc_id: str):
    with _registry_txn():
        reg = _load_registry()
        if session_id in reg:
            reg[session_id] = [d for d in reg[session_id] if d["doc_id"] != doc_id]
        _save_registry(reg)


def list_docs(session_id: str) -> list[dict]:
    reg = _load_registry()
    return reg.get(session_id, [])
