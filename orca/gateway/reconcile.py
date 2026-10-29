"""L02-05: safe reconciliation of resources that can be left behind (orphan deployment records, orphan document chunks, atomic-write remnants).

A resource is never removed because it looks old. It is removed only when it has been observed UNREFERENCED on more than one sweep, a grace period apart, is not
protected, and (for deployment records) has first spent a quarantine period out of routing. Every transition is a durable compare-and-set in a small SQLite ledger
(``reconcile.db`` under ORNEUR_HOME), so a crash leaves a state the next sweep resumes, a second worker running the same sweep cannot double-act (kind-level lease), and every
action is an audit row. Cloud / production / candidate resources are PROTECTED and are never touched, and nothing here reads or removes user data (sessions, transcripts).

Kinds:
  deployment_record  ``registry/deployments/*.json`` whose id no live worker still announces (EXPERIMENTAL self-hosted records only: observe -> quarantine -> remove)
  doc_chunks         chunks (vector collection and keyword file) whose document is in no conversation's registry (observe twice -> remove)
  temp_file          ``*.tmp`` remnants of interrupted atomic writes in the registry / docs directories (observe twice -> remove)
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

OBSERVE_GRACE_S = float(os.environ.get("ORNEUR_RECONCILE_OBSERVE_S", "600"))
QUARANTINE_S = float(os.environ.get("ORNEUR_RECONCILE_QUARANTINE_S", str(24 * 3600)))
LIVE_TTL_S = 600.0
MAX_ACTIONS_PER_SWEEP = 25
MAX_ATTEMPTS = 5
LEASE_S = 120.0
PROTECTED_LIFECYCLES = {"CANDIDATE", "APPROVED", "PRODUCTION", "LEGACY_PRODUCTION_SERVING", "TRAINED", "EVALUATING"}


def _home() -> Path:
    from orca.config import ORCA_HOME

    return Path(ORCA_HOME)


def _db() -> sqlite3.Connection:
    p = _home() / "reconcile.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=10, isolation_level="IMMEDIATE")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS resource_ledger (kind TEXT NOT NULL, resource_id TEXT NOT NULL, state TEXT NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL,"
                 " observations INTEGER NOT NULL DEFAULT 1, last_counted REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, quarantined_at REAL, updated_at REAL NOT NULL, PRIMARY KEY (kind, resource_id))")
    conn.execute("CREATE TABLE IF NOT EXISTS reconcile_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL, resource_id TEXT NOT NULL, action TEXT NOT NULL, outcome TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS reconcile_lease (kind TEXT PRIMARY KEY, holder TEXT NOT NULL, until REAL NOT NULL)")
    return conn


def _audit(conn, kind, rid, action, outcome) -> None:
    conn.execute("INSERT INTO reconcile_audit (ts, kind, resource_id, action, outcome) VALUES (?,?,?,?,?)", (time.time(), kind, rid, action, outcome))


# ── live announcements (every worker says which deployment ids it serves) ────────────────────────────────────────────────────────

def _live_dir() -> Path:
    d = _home() / "registry" / "deployments" / ".live"
    d.mkdir(parents=True, exist_ok=True)
    return d


def announce_live(ids) -> None:
    """Called by every worker for the deployments it currently serves; a record is 'live' while ANY worker announced it within LIVE_TTL_S."""
    path = _live_dir() / f"{os.uname().nodename}-{os.getpid()}.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"at": time.time(), "ids": sorted(set(ids))}))
    os.replace(tmp, path)


def live_ids(now: float | None = None) -> set[str]:
    now = time.time() if now is None else now
    out: set[str] = set()
    for f in _live_dir().glob("*.json"):
        try:
            d = json.loads(f.read_text())
            if now - float(d["at"]) <= LIVE_TTL_S:
                out.update(d["ids"])
            elif now - float(d["at"]) > 7 * 86400:
                f.unlink(missing_ok=True)
        except Exception:
            continue
    return out


# ── ledger transitions ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _observe(conn, kind, rid, now) -> sqlite3.Row:
    """Record that the resource was seen unreferenced. ``observations`` counts DISTINCT sweeps at least OBSERVE_GRACE_S/2 apart, so two quick passes in a row (or one
    long pass) never count as the independent confirmations a removal needs."""
    spacing = OBSERVE_GRACE_S / 2
    conn.execute("INSERT INTO resource_ledger (kind, resource_id, state, first_seen, last_seen, observations, last_counted, updated_at) VALUES (?,?,?,?,?,1,?,?) "
                 "ON CONFLICT(kind, resource_id) DO UPDATE SET last_seen=?, "
                 "observations = CASE WHEN ? - last_counted >= ? THEN observations + 1 ELSE observations END, "
                 "last_counted = CASE WHEN ? - last_counted >= ? THEN ? ELSE last_counted END, updated_at=?",
                 (kind, rid, "observed", now, now, now, now, now, now, spacing, now, spacing, now, now))
    return conn.execute("SELECT * FROM resource_ledger WHERE kind=? AND resource_id=?", (kind, rid)).fetchone()


def _release(conn, kind, rid) -> None:
    cur = conn.execute("DELETE FROM resource_ledger WHERE kind=? AND resource_id=? AND state IN ('observed','quarantined','blocked')", (kind, rid))
    if cur.rowcount:
        _audit(conn, kind, rid, "released", "referenced again")


def _cas(conn, kind, rid, from_state, to_state, now) -> bool:
    return conn.execute("UPDATE resource_ledger SET state=?, updated_at=?, quarantined_at=CASE WHEN ?='quarantined' THEN ? ELSE quarantined_at END WHERE kind=? AND resource_id=? AND state=?",
                        (to_state, now, to_state, now, kind, rid, from_state)).rowcount == 1


def _fail(conn, kind, rid, err, now) -> None:
    conn.execute("UPDATE resource_ledger SET attempts=attempts+1, last_error=?, updated_at=?, state=CASE WHEN attempts+1>=? THEN 'blocked' ELSE state END WHERE kind=? AND resource_id=?",
                 (err[:120], now, MAX_ATTEMPTS, kind, rid))
    _audit(conn, kind, rid, "remove", f"failed: {err[:80]}")


def _lease(conn, kind, holder, now) -> bool:
    conn.execute("INSERT INTO reconcile_lease (kind, holder, until) VALUES (?,?,0) ON CONFLICT DO NOTHING", (kind, holder))
    return conn.execute("UPDATE reconcile_lease SET holder=?, until=? WHERE kind=? AND (until < ? OR holder=?)", (holder, now + LEASE_S, kind, now, holder)).rowcount == 1


# ── kinds ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _sweep_deployments(conn, now, budget) -> dict:
    from orca.gateway.deployment import DEPLOYMENT_DIR, scan_deployment_dir

    live = live_ids(now)
    valid, corrupt = scan_deployment_dir()
    out = {"protected": 0, "live": 0, "observed": 0, "quarantined": 0, "removed": 0, "corrupt_isolated": 0}
    qdir = DEPLOYMENT_DIR / ".quarantine"
    for d in valid:
        rid = d.deployment_id
        reclaimable = d.runtime == "ollama" and d.lifecycle == "EXPERIMENTAL" and d.lifecycle not in PROTECTED_LIFECYCLES
        if not reclaimable:
            out["protected"] += 1
            continue
        if rid in live:
            out["live"] += 1
            _release(conn, "deployment_record", rid)
            continue
        row = _observe(conn, "deployment_record", rid, now)
        if row["state"] == "observed" and row["observations"] >= 2 and now - row["first_seen"] >= OBSERVE_GRACE_S and budget["n"] > 0:
            if _cas(conn, "deployment_record", rid, "observed", "quarantined", now):
                try:                                              # out of routing, but kept: the record is renamed, not deleted
                    qdir.mkdir(exist_ok=True)
                    os.replace(DEPLOYMENT_DIR / f"{rid}.json", qdir / f"{rid}.json")
                    _audit(conn, "deployment_record", rid, "quarantine", "ok")
                    out["quarantined"] += 1
                    budget["n"] -= 1
                except Exception as e:
                    conn.execute("UPDATE resource_ledger SET state='observed' WHERE kind='deployment_record' AND resource_id=?", (rid,))
                    _fail(conn, "deployment_record", rid, repr(e), now)
        elif row["state"] == "observed":
            out["observed"] += 1
    # quarantined records: restored if announced live again, removed after the quarantine period if still unreferenced
    for row in conn.execute("SELECT * FROM resource_ledger WHERE kind='deployment_record' AND state='quarantined'").fetchall():
        rid, qfile = row["resource_id"], qdir / f"{row['resource_id']}.json"
        if rid in live:
            try:
                if qfile.exists():
                    os.replace(qfile, DEPLOYMENT_DIR / f"{rid}.json")
                _release(conn, "deployment_record", rid)
                conn.execute("DELETE FROM resource_ledger WHERE kind='deployment_record' AND resource_id=?", (rid,))
                _audit(conn, "deployment_record", rid, "restore", "announced live again")
            except Exception as e:
                _fail(conn, "deployment_record", rid, repr(e), now)
        elif now - (row["quarantined_at"] or now) >= QUARANTINE_S and budget["n"] > 0:
            try:
                qfile.unlink(missing_ok=True)
                conn.execute("UPDATE resource_ledger SET state='removed', updated_at=? WHERE kind='deployment_record' AND resource_id=? AND state='quarantined'", (now, rid))
                _audit(conn, "deployment_record", rid, "remove", "ok")
                out["removed"] += 1
                budget["n"] -= 1
            except Exception as e:
                _fail(conn, "deployment_record", rid, repr(e), now)
    # damaged files: moved aside (never deleted), once
    for p in corrupt:
        try:
            qdir.mkdir(exist_ok=True)
            os.replace(p, qdir / f"{p.name}.corrupt")
            _audit(conn, "deployment_record", p.name, "isolate_corrupt", "ok")
            out["corrupt_isolated"] += 1
        except Exception as e:
            _audit(conn, "deployment_record", p.name, "isolate_corrupt", f"failed: {e!r}"[:100])
    return out


def _registry_doc_ids_by_prefix() -> dict[str, set[str]]:
    from orca.docs.store import _load_registry

    by12: dict[str, set[str]] = {}
    for sid, docs in _load_registry().items():
        by12.setdefault(sid[:12].replace("-", ""), set()).update(d["doc_id"] for d in docs)
        by12.setdefault("kw8:" + sid[:8], set()).update(d["doc_id"] for d in docs)
    return by12


def _sweep_doc_chunks(conn, now, budget) -> dict:
    from orca.docs.store import DOCS_DIR

    out = {"collections_scanned": 0, "orphan_documents_seen": 0, "removed_documents": 0}
    known = _registry_doc_ids_by_prefix()
    # vector collections
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(DOCS_DIR / "vectors"))
        for col in client.list_collections()[:20]:
            name = col if isinstance(col, str) else col.name
            if not name.startswith("docs_"):
                continue
            out["collections_scanned"] += 1
            collection = client.get_collection(name)
            metas = (collection.get(include=["metadatas"], limit=5000).get("metadatas") or [])
            doc_ids = {m.get("doc_id") for m in metas if m and m.get("doc_id")}
            registered = known.get(name[len("docs_"):], set())
            for doc_id in sorted(doc_ids - registered):
                rid = f"vec:{name}:{doc_id}"
                out["orphan_documents_seen"] += 1
                row = _observe(conn, "doc_chunks", rid, now)
                if row["state"] == "observed" and row["observations"] >= 2 and now - row["first_seen"] >= OBSERVE_GRACE_S and budget["n"] > 0:
                    try:
                        collection.delete(where={"doc_id": doc_id})
                        conn.execute("UPDATE resource_ledger SET state='removed', updated_at=? WHERE kind='doc_chunks' AND resource_id=?", (now, rid))
                        _audit(conn, "doc_chunks", rid, "remove", "ok")
                        out["removed_documents"] += 1
                        budget["n"] -= 1
                    except Exception as e:
                        _fail(conn, "doc_chunks", rid, repr(e), now)
            for doc_id in doc_ids & registered:
                _release(conn, "doc_chunks", f"vec:{name}:{doc_id}")
    except ImportError:
        pass
    # keyword files
    for f in DOCS_DIR.glob("kw_*.jsonl"):
        registered = known.get("kw8:" + f.stem[3:], set())
        try:
            lines = f.read_text().splitlines()
        except OSError:
            continue
        ids = set()
        for line in lines:
            try:
                ids.add(json.loads(line).get("doc_id"))
            except Exception:
                continue
        for doc_id in sorted(i for i in ids - registered if i):
            rid = f"kw:{f.name}:{doc_id}"
            out["orphan_documents_seen"] += 1
            row = _observe(conn, "doc_chunks", rid, now)
            if row["state"] == "observed" and row["observations"] >= 2 and now - row["first_seen"] >= OBSERVE_GRACE_S and budget["n"] > 0:
                try:
                    from orca.docs.store import DocStore

                    # the keyword file is rewritten atomically by the store's own deletion routine
                    st = DocStore.__new__(DocStore)
                    st._fallback_file, st._collection = f, None
                    res = DocStore.delete_doc_detailed(st, doc_id)
                    if not res["ok"]:
                        raise RuntimeError("keyword rewrite failed")
                    conn.execute("UPDATE resource_ledger SET state='removed', updated_at=? WHERE kind='doc_chunks' AND resource_id=?", (now, rid))
                    _audit(conn, "doc_chunks", rid, "remove", "ok")
                    out["removed_documents"] += 1
                    budget["n"] -= 1
                except Exception as e:
                    _fail(conn, "doc_chunks", rid, repr(e), now)
        for doc_id in ids & registered:
            _release(conn, "doc_chunks", f"kw:{f.name}:{doc_id}")
    return out


def _sweep_temp_files(conn, now, budget) -> dict:
    from orca.docs.store import DOCS_DIR
    from orca.gateway.deployment import DEPLOYMENT_DIR

    out = {"seen": 0, "removed": 0}
    for d in (DOCS_DIR, DEPLOYMENT_DIR):
        for f in list(d.glob("*.tmp")) + list(d.glob(".*.tmp")):
            try:
                rid = str(f.relative_to(_home()))
            except ValueError:
                rid = str(f)
            out["seen"] += 1
            row = _observe(conn, "temp_file", rid, now)
            if row["observations"] >= 2 and now - row["first_seen"] >= OBSERVE_GRACE_S and budget["n"] > 0 and row["state"] == "observed":
                try:
                    f.unlink(missing_ok=True)
                    conn.execute("UPDATE resource_ledger SET state='removed', updated_at=? WHERE kind='temp_file' AND resource_id=?", (now, rid))
                    _audit(conn, "temp_file", rid, "remove", "ok")
                    out["removed"] += 1
                    budget["n"] -= 1
                except Exception as e:
                    _fail(conn, "temp_file", rid, repr(e), now)
    return out


_KINDS = (("deployment_record", _sweep_deployments), ("doc_chunks", _sweep_doc_chunks), ("temp_file", _sweep_temp_files))


def sweep(now: float | None = None, holder: str | None = None) -> dict:
    """One bounded, idempotent pass over every kind. Safe to run on several workers at once (kind-level lease) and safe to interrupt at any point."""
    now = time.time() if now is None else now
    holder = holder or f"{os.uname().nodename}-{os.getpid()}"
    budget = {"n": MAX_ACTIONS_PER_SWEEP}
    report: dict = {}
    conn = _db()
    try:
        for kind, fn in _KINDS:
            with conn:
                if not _lease(conn, kind, holder, now):
                    report[kind] = {"skipped": "another worker holds the lease"}
                    continue
            try:
                with conn:
                    report[kind] = fn(conn, now, budget)
            except Exception as e:                       # one kind failing never stops the others
                report[kind] = {"error": type(e).__name__}
            finally:
                with conn:                               # release at once so a peer (or the next pass) is not blocked for the whole lease
                    conn.execute("UPDATE reconcile_lease SET until=0 WHERE kind=? AND holder=?", (kind, holder))
    finally:
        conn.close()
    return report


def diagnostics() -> dict:
    """Counts by kind/state and the last audit rows - safe for an operator view (resource ids only, no content)."""
    conn = _db()
    try:
        rows = conn.execute("SELECT kind, state, COUNT(*) AS n FROM resource_ledger GROUP BY kind, state").fetchall()
        blocked = [dict(r) for r in conn.execute("SELECT kind, resource_id, attempts, last_error FROM resource_ledger WHERE state='blocked' LIMIT 20")]
        audit = [dict(r) for r in conn.execute("SELECT ts, kind, resource_id, action, outcome FROM reconcile_audit ORDER BY id DESC LIMIT 20")]
    finally:
        conn.close()
    return {"ledger": [dict(r) for r in rows], "blocked": blocked, "recent_actions": audit}
