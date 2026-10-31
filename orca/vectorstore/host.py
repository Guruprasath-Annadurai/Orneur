"""``ChromaHost``: the ONLY place in the product that talks to chromadb.

It runs either inside the vector-service process (``server.py``, production) or in-process (embedded mode: CLI tools, tests, platforms without AF_UNIX). Both modes execute the
same operations with the same JSON-safe inputs and outputs, so behaviour is tested once and is the same either way.

Resource lifecycle (L03 Phase C): chromadb keeps ~4 file descriptors and a few MB per collection touched since a client was created and gives none back until the client is
closed (measured, docs/orneur/landmarks/landmark-03/evidence). The host therefore counts the distinct collections touched by the current client "generation" and, when the
count passes ``max_open`` and no operation is in flight, closes the client (releasing every descriptor) and opens a new one. Data is untouched; the next operation simply reopens
what it needs. Deletes, vacuum and recycling take the exclusive side of a readers-writer gate; add/query/get/count/peek take the shared side.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

RECLAIMED, DEFERRED, NOT_APPLICABLE = "RECLAIMED", "DEFERRED", "NOT_APPLICABLE"
METHODS = {"add", "upsert", "query", "get", "peek", "count", "delete"}


def _jsonable(x):
    if hasattr(x, "tolist"):
        return x.tolist()
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    return x


def proc_fds() -> int:
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        return -1


def proc_rss_mb() -> int:
    try:
        return int(open("/proc/self/statm").read().split()[1]) * (os.sysconf("SC_PAGE_SIZE") // 1024) // 1024
    except (OSError, ValueError):
        return -1


class _Gate:
    """Readers-writer gate: any number of shared holders, or one exclusive holder."""

    def __init__(self):
        self._c = threading.Condition()
        self._shared = 0
        self._excl = False
        self._waiting_excl = 0

    def shared(self):
        g = self

        class _S:
            def __enter__(s):
                with g._c:
                    while g._excl or g._waiting_excl:
                        g._c.wait()
                    g._shared += 1

            def __exit__(s, *a):
                with g._c:
                    g._shared -= 1
                    g._c.notify_all()
        return _S()

    def exclusive(self):
        g = self

        class _X:
            def __enter__(s):
                with g._c:
                    g._waiting_excl += 1
                    while g._excl or g._shared:
                        g._c.wait()
                    g._waiting_excl -= 1
                    g._excl = True

            def __exit__(s, *a):
                with g._c:
                    g._excl = False
                    g._c.notify_all()
        return _X()

    @property
    def inflight(self) -> int:
        return self._shared


class _Store:
    def __init__(self, root: Path):
        self.root = root
        self.client = None
        self.touched: set[str] = set()
        self.generation = 0
        self.gate = _Gate()
        self.recycles = 0
        self.open_lock = threading.Lock()


class ChromaHost:
    def __init__(self, *, max_open: int = 32):
        self.max_open = max(2, int(max_open))
        self._stores: dict[str, _Store] = {}
        self._lock = threading.Lock()
        self.counters = {"ops": 0, "errors": 0, "recycles": 0, "vacuums": 0, "deleted_collections": 0}

    # ── internals ────────────────────────────────────────────────────────────────────────────────────────────────────
    def _store(self, root: str) -> _Store:
        key = str(Path(root))
        with self._lock:
            st = self._stores.get(key)
            if st is None:
                st = self._stores[key] = _Store(Path(key))
            return st

    def _client(self, st: _Store):
        if st.client is None:
            with st.open_lock:
                if st.client is None:
                    import chromadb

                    st.root.mkdir(parents=True, exist_ok=True)
                    st.client = chromadb.PersistentClient(path=str(st.root))
                    st.generation += 1
                    st.touched = set()
        return st.client

    def _maybe_recycle(self, st: _Store) -> None:
        if len(st.touched) <= self.max_open or st.gate.inflight:
            return
        with st.gate.exclusive():
            if len(st.touched) <= self.max_open or st.client is None:
                return
            try:
                st.client.close()
            finally:
                st.client = None
                st.touched = set()
                st.recycles += 1
                self.counters["recycles"] += 1

    # ── operations ───────────────────────────────────────────────────────────────────────────────────────────────────
    def execute(self, req: dict) -> dict:
        op = req.get("op")
        self.counters["ops"] += 1
        try:
            if op == "ping":
                return {"pong": True}
            if op == "stats":
                return self.stats()
            if op == "call":
                return self._call(req)
            if op == "delete_collection":
                return self._delete_collection(req)
            if op == "open_collection":
                return self._open_collection(req)
            if op == "binding_report":
                return self._binding_report(req)
            if op == "list_collections":
                return self._list(req)
            if op == "collection_info":
                return self._info(req)
            if op == "vacuum":
                return self._vacuum(req)
            raise ValueError("unknown op")
        except BaseException:
            self.counters["errors"] += 1
            raise

    def _call(self, req: dict) -> dict:
        method = req["method"]
        if method not in METHODS:
            raise ValueError("method not allowed")
        st = self._store(req["root"])
        kwargs = req.get("kwargs") or {}
        exclusive = method == "delete"
        ctx = st.gate.exclusive() if exclusive else st.gate.shared()
        with ctx:
            client = self._client(st)
            name = req["collection"]
            if req.get("create"):
                col = client.get_or_create_collection(name=name, metadata=req.get("metadata") or {"hnsw:space": "cosine"})
            else:
                col = client.get_collection(name=name)
            st.touched.add(name)
            out = getattr(col, method)(**kwargs)
            meta = dict(col.metadata or {}) if req.get("return_metadata") else None
        self._maybe_recycle(st)
        res = {"result": _jsonable(out)}
        if meta is not None:
            res["metadata"] = _jsonable(meta)
        return res

    # ── ownership binding ────────────────────────────────────────────────────────────────────────────────────────────
    # A collection is NAMED from a truncated session id (legacy naming, kept so existing data stays reachable), which cannot by itself say whose it is. Each collection is therefore
    # bound, in a sidecar database in the same directory, to a hash of the FULL session id that opened it first. Opening it with a different binding is refused ("mismatch") and the
    # collection is neither read nor written. A collection that already existed before bindings did is ADOPTED by its first opener (recorded as such, for operators).
    def _bindings_db(self, st: _Store) -> sqlite3.Connection:
        st.root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(st.root / "orneur_bindings.sqlite"), timeout=5.0)
        conn.execute("CREATE TABLE IF NOT EXISTS bindings (collection TEXT PRIMARY KEY, binding TEXT NOT NULL, adopted INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL)")
        return conn

    def _open_collection(self, req: dict) -> dict:
        st = self._store(req["root"])
        name, binding = req["collection"], req.get("binding")
        with st.gate.shared():
            client = self._client(st)
            existed = name in {c.name for c in client.list_collections()}
            if binding:
                conn = self._bindings_db(st)
                try:
                    row = conn.execute("SELECT binding FROM bindings WHERE collection=?", (name,)).fetchone()
                    if row is not None and row[0] != binding:
                        return {"status": "mismatch"}                       # not opened, not created: nothing of the other conversation is touched
                    if row is None:
                        with conn:
                            conn.execute("INSERT OR IGNORE INTO bindings (collection, binding, adopted, created_at) VALUES (?,?,?,?)", (name, binding, 1 if existed else 0, time.time()))
                        row = conn.execute("SELECT binding, adopted FROM bindings WHERE collection=?", (name,)).fetchone()
                        if row[0] != binding:
                            return {"status": "mismatch"}                   # lost a race to another conversation with the same collection name
                        status = "adopted" if existed else "bound"
                    else:
                        status = "ok"
                finally:
                    conn.close()
            else:
                status = "unbound"
            col = client.get_or_create_collection(name=name, metadata=req.get("metadata") or {"hnsw:space": "cosine"})
            st.touched.add(name)
            return {"status": status, "metadata": _jsonable(dict(col.metadata or {})), "count": col.count()}

    def _binding_report(self, req: dict) -> dict:
        st = self._store(req["root"])
        with st.gate.shared():
            names = {c.name for c in self._client(st).list_collections()}
            conn = self._bindings_db(st)
            try:
                rows = conn.execute("SELECT collection, adopted FROM bindings").fetchall()
            finally:
                conn.close()
        bound = {r[0] for r in rows}
        return {"collections": len(names), "bound": len(bound & names), "adopted_legacy": sum(1 for r in rows if r[1] and r[0] in names), "never_reopened_since_bindings": len(names - bound),
                "bindings_without_collection": len(bound - names)}

    def _delete_collection(self, req: dict) -> dict:
        st = self._store(req["root"])
        with st.gate.exclusive():
            client = self._client(st)
            existed = True
            try:
                client.delete_collection(name=req["collection"])
            except Exception as exc:
                if "not exist" in str(exc).lower() or "NotFound" in type(exc).__name__ or "does not exist" in str(exc).lower():
                    existed = False
                else:
                    raise
            st.touched.discard(req["collection"])
            self.counters["deleted_collections"] += 1
        # the deletion is only reported once the collection is verifiably gone
        with st.gate.shared():
            still = req["collection"] in {c.name for c in self._client(st).list_collections()}
        if not still:
            conn = self._bindings_db(st)
            try:
                with conn:
                    conn.execute("DELETE FROM bindings WHERE collection=?", (req["collection"],))
            finally:
                conn.close()
        return {"existed": existed, "removed": not still}

    def _list(self, req: dict) -> dict:
        st = self._store(req["root"])
        with st.gate.shared():
            return {"names": sorted(c.name for c in self._client(st).list_collections())}

    def _info(self, req: dict) -> dict:
        st = self._store(req["root"])
        with st.gate.shared():
            try:
                col = self._client(st).get_collection(name=req["collection"])
            except Exception:
                return {"exists": False}
            return {"exists": True, "metadata": _jsonable(dict(col.metadata or {})), "count": col.count()}

    def _vacuum(self, req: dict) -> dict:
        """VACUUM rewrites the shared file, so deleted pages are not left holding deleted text. Needs exclusivity (measured: running it beside live chroma operations
        raises NotFoundError for unrelated collections); bounded by ``timeout_s`` on the SQLite side."""
        st = self._store(req["root"])
        db = st.root / "chroma.sqlite3"
        if not db.exists():
            return {"status": NOT_APPLICABLE}
        with st.gate.exclusive():
            try:
                if st.client is not None:                       # release our own handles first so VACUUM is not blocked by this process
                    st.client.close()
                    st.client, st.touched = None, set()
                conn = sqlite3.connect(str(db), timeout=float(req.get("timeout_s", 2.0)))
                try:
                    conn.execute("VACUUM")
                finally:
                    conn.close()
                self.counters["vacuums"] += 1
                return {"status": RECLAIMED}
            except Exception:
                return {"status": DEFERRED}

    def stats(self) -> dict:
        per = {}
        with self._lock:
            for key, st in self._stores.items():
                per[Path(key).parent.name + "/" + Path(key).name] = {"open_collections": len(st.touched), "client_generation": st.generation, "recycles": st.recycles,
                                                                      "client_open": st.client is not None, "inflight": st.gate.inflight}
        return {"stores": per, "counters": dict(self.counters), "fds": proc_fds(), "rss_mb": proc_rss_mb(), "max_open": self.max_open, "pid": os.getpid(), "time": time.time()}

    def close(self) -> None:
        with self._lock:
            for st in self._stores.values():
                try:
                    if st.client is not None:
                        st.client.close()
                except Exception:
                    pass
                st.client = None
