"""Vector storage for long-term memory and document retrieval.

Everything that touches chromadb goes through here. Two interchangeable transports execute the same operations on a ``ChromaHost``:

* ``service`` - the production server mode. Chroma runs in ONE supervised owner process per data directory; the application talks to it over a private Unix socket with
  per-call deadlines enforced on the socket, bounded admission and a supervisor that kills and replaces a stalled owner (see client.py / server.py and
  docs/orneur/landmarks/landmark-03/L03_VECTOR_ISOLATION_ARCHITECTURE.md). The application process never imports or runs chromadb.
* ``embedded`` - in-process (CLI tools, tests, platforms without AF_UNIX). Deadlines cannot be enforced here: a native call that blocks holds the process. This is the baseline
  behaviour and is reported as such by ``stats()``.

Mode: ``ORNEUR_VECTOR_MODE=service|embedded|auto``; ``auto`` (default) is ``service`` inside ``orca serve`` (set by the application lifespan) and ``embedded`` elsewhere.
"""
from __future__ import annotations

import importlib.util
import os
import threading
from pathlib import Path

from orca.vectorstore.errors import (VectorBusy, VectorError, VectorNotFound, VectorOwnershipError, VectorTimeout, VectorUnavailable)  # noqa: F401  (re-exported)
from orca.vectorstore.host import DEFERRED, NOT_APPLICABLE, RECLAIMED, ChromaHost  # noqa: F401

_lock = threading.Lock()
_server_mode = False
_embedded_host: ChromaHost | None = None
_service: dict[str, object] = {}


_BINDING_SALT = b"orneur-vector-binding-v1:"


def session_binding(session_id: str) -> str:
    """A hash of the FULL session id. Collection NAMES carry only a prefix of it (legacy naming), so two sessions can share a name; the binding says whose the collection is."""
    import hashlib

    return hashlib.sha256(_BINDING_SALT + session_id.encode()).hexdigest()


def available() -> bool:
    """chromadb can be used (by this process in embedded mode, or by the owner process in service mode). Does not import it."""
    return importlib.util.find_spec("chromadb") is not None


def enable_service_mode(on: bool = True) -> None:
    global _server_mode
    _server_mode = on


def mode() -> str:
    m = os.environ.get("ORNEUR_VECTOR_MODE", "auto").lower()
    if m == "auto":
        m = "service" if _server_mode else "embedded"
    if m == "service" and not hasattr(os, "fork"):                       # no Unix sockets / flock
        return "embedded"
    return m if m in ("service", "embedded") else "embedded"


def _home() -> Path:
    from orca import config

    return Path(config.ORCA_HOME)


class _EmbeddedTransport:
    def __init__(self):
        global _embedded_host
        with _lock:
            if _embedded_host is None:
                _embedded_host = ChromaHost(max_open=int(os.environ.get("ORNEUR_VECTOR_MAX_OPEN", "32")))
        self.host = _embedded_host

    def call(self, req: dict, deadline_s: float | None = None) -> dict:
        try:
            return self.host.execute(req)
        except Exception as exc:
            name = type(exc).__name__
            if "NotFound" in name or "does not exist" in str(exc).lower():
                raise VectorNotFound("no such collection") from None
            raise VectorUnavailable(f"vector operation failed ({name})") from None


def transport():
    if mode() == "service":
        from orca.vectorstore.client import ServiceTransport

        home = str(_home().resolve())
        with _lock:
            t = _service.get(home)
            if t is None:
                t = _service[home] = ServiceTransport(
                    Path(home), max_inflight=int(os.environ.get("ORNEUR_VECTOR_MAX_INFLIGHT", "8")), max_waiting=int(os.environ.get("ORNEUR_VECTOR_MAX_WAITING", "16")),
                    queue_wait_s=float(os.environ.get("ORNEUR_VECTOR_QUEUE_WAIT_S", "2")), default_deadline_s=float(os.environ.get("ORNEUR_VECTOR_DEADLINE_S", "5")))
        return t
    return _EmbeddedTransport()


def reset_for_tests() -> None:
    """Forget cached transports/host (tests that change the data directory or mode)."""
    global _embedded_host
    with _lock:
        if _embedded_host is not None:
            _embedded_host.close()
        _embedded_host = None
        _service.clear()


class Collection:
    """A chroma-collection-like handle. Holds no native object: every call is an operation on the host, so it is safe to keep, to share between threads and to outlive an owner
    restart."""

    def __init__(self, root: Path, name: str, metadata: dict | None = None, deadline_s: float | None = None):
        self.root, self.name, self.metadata, self._deadline = str(root), name, dict(metadata or {}), deadline_s

    def _call(self, method: str, kwargs: dict, *, deadline_s: float | None = None) -> dict:
        # never ``create``: a handle that outlives its collection (deleted meanwhile) must fail, not silently re-create it with new data
        return transport().call({"op": "call", "root": self.root, "collection": self.name, "method": method, "kwargs": kwargs}, deadline_s or self._deadline)

    def add(self, documents=None, ids=None, metadatas=None, embeddings=None):
        kw = {k: v for k, v in (("documents", documents), ("ids", ids), ("metadatas", metadatas), ("embeddings", embeddings)) if v is not None}
        # A batch costs time in proportion to its size (chromadb embeds every document it is given without embeddings): the deadline scales with the batch, capped, so indexing a
        # large document is not refused as "stuck" while a genuinely stuck write is still released after a bounded time.
        n = len(documents or ids or [])
        base = float(os.environ.get("ORNEUR_VECTOR_DEADLINE_S", "5"))
        self._call("add", kw, deadline_s=self._deadline or (base + min(115.0, 0.1 * n)))

    def query(self, query_texts=None, query_embeddings=None, n_results=5, where=None, include=None):
        kw = {k: v for k, v in (("query_texts", query_texts), ("query_embeddings", query_embeddings), ("where", where), ("include", include)) if v is not None}
        kw["n_results"] = n_results
        return self._call("query", kw)["result"]

    def get(self, ids=None, where=None, limit=None, include=None):
        kw = {k: v for k, v in (("ids", ids), ("where", where), ("limit", limit), ("include", include)) if v is not None}
        return self._call("get", kw)["result"]

    def peek(self, limit: int = 10):
        return self._call("peek", {"limit": limit})["result"]

    def count(self) -> int:
        return int(self._call("count", {})["result"])

    def delete(self, ids=None, where=None):
        kw = {k: v for k, v in (("ids", ids), ("where", where)) if v is not None}
        self._call("delete", kw)


class Store:
    """A chroma-client-like handle for one vector directory (``kind`` is only a label in statistics)."""

    def __init__(self, root: Path, kind: str = "vectors"):
        self.root, self.kind = Path(root), kind

    def open_collection(self, name: str, metadata: dict | None = None, binding: str | None = None, deadline_s: float | None = None) -> tuple[Collection, dict]:
        """Create-or-open ``name`` and verify its ownership ``binding`` (a hash of the full session id). Returns (handle, info) with ``info["status"]`` one of ``bound`` (new),
        ``ok``, ``adopted`` (pre-existing legacy collection, now bound), ``unbound`` (no binding requested) or ``mismatch`` (belongs to another conversation: use nothing)."""
        info = transport().call({"op": "open_collection", "root": str(self.root), "collection": name, "metadata": metadata or {"hnsw:space": "cosine"}, "binding": binding}, deadline_s)
        return Collection(self.root, name, metadata, deadline_s), info

    def binding_report(self) -> dict:
        return {k: v for k, v in transport().call({"op": "binding_report", "root": str(self.root)}).items() if k != "ok"}

    def get_or_create_collection(self, name: str, metadata: dict | None = None) -> Collection:
        return self.open_collection(name, metadata)[0]               # unbound: for tools and tests that manage their own naming

    def delete_collection(self, name: str, deadline_s: float | None = None, binding: str | None = None) -> dict:
        """Remove a collection and report whether it is verifiably gone. With ``binding``, a collection bound to a different conversation is left alone (``refused: not_owner``)."""
        return transport().call({"op": "delete_collection", "root": str(self.root), "collection": name, "binding": binding}, deadline_s)

    def list_collections(self) -> list[str]:
        return transport().call({"op": "list_collections", "root": str(self.root)})["names"]

    def collection_info(self, name: str, deadline_s: float | None = None) -> dict:
        return transport().call({"op": "collection_info", "root": str(self.root), "collection": name}, deadline_s)

    def rebuild_without(self, name: str, key: str | None = None, value=None, deadline_s: float | None = None) -> dict:
        """Copy a collection without the records whose metadata ``key`` equals ``value`` into a fresh one (fresh write-ahead log), swap it in and drop the old - the only way to
        erase individual records' text from disk. With no key it compacts (drops the log). The old collection is untouched unless the copy was verified."""
        return transport().call({"op": "rebuild_without", "root": str(self.root), "collection": name, "key": key, "value": value}, deadline_s)

    def vacuum(self, timeout_s: float = 2.0, deadline_s: float | None = None) -> str:
        return transport().call({"op": "vacuum", "root": str(self.root), "timeout_s": timeout_s}, deadline_s)["status"]


def stats() -> dict:
    t = transport()
    out = {"mode": mode()}
    if hasattr(t, "stats"):
        out.update(t.stats())
        out["owner"] = t.owner_stats()
    else:
        out["owner"] = t.host.stats()
        out["deadlines_enforced"] = False
    return out
