"""L02-06: operational facts the server reports about itself (readiness inputs, drain state, storage headroom, backlogs). No user content is ever included."""
from __future__ import annotations

import os
import shutil
import time

_state = {"draining": False, "drain_started": None, "started_at": time.time()}
_disk_cache: dict = {"at": 0.0, "value": None}


_inflight: dict[tuple, bool] = {}       # (user_id, request_key) of turns this process is running right now


def inflight_add(user_id: str, key: str) -> None:
    _inflight[(user_id, key)] = True


def inflight_remove(user_id: str, key: str) -> None:
    _inflight.pop((user_id, key), None)


def close_inflight_as_shutdown() -> int:
    """Called when the process is stopping: every turn still running here will never commit, so its durable record says so NOW (``not_committed`` / ``server_shutdown``)
    instead of leaving clients to wait for the turn authority to expire. Compare-and-set: a turn that already committed is untouched."""
    n = 0
    try:
        from orca.serve import turn_requests as tr

        for (uid, key) in list(_inflight):
            if tr.finish(uid, key, "not_committed", "server_shutdown"):
                n += 1
    except Exception:
        pass
    _inflight.clear()
    return n


def begin_drain() -> None:
    if not _state["draining"]:
        _state["draining"] = True
        _state["drain_started"] = time.time()


def draining() -> bool:
    return bool(_state["draining"])


def reset_for_tests() -> None:
    _state.update(draining=False, drain_started=None)
    _disk_cache.update(at=0.0, value=None)


def _mb(name: str, default: int) -> int:
    from orca.config import orneur_env

    try:
        return int(orneur_env(name, str(default)))
    except ValueError:
        return default


def disk_report(path: str | None = None, *, max_age_s: float = 5.0) -> dict:
    """Free space on the volume that holds the transcript, document and memory stores. ``critical`` means writes are about to fail: new turns are refused (503
    ``history_unavailable``) BEFORE any model call or quota is spent, instead of generating an answer that cannot be saved."""
    now = time.monotonic()
    if _disk_cache["value"] is not None and now - _disk_cache["at"] < max_age_s:
        return _disk_cache["value"]
    from orca.config import ORCA_HOME

    target = path or str(ORCA_HOME)
    try:
        u = shutil.disk_usage(target)
        free_mb, total_mb = u.free // (1024 * 1024), u.total // (1024 * 1024)
        warn, crit = _mb("DISK_WARN_MB", 1024), _mb("DISK_CRITICAL_MB", 128)
        state = "critical" if free_mb < crit else "low" if free_mb < warn else "ok"
        value = {"state": state, "free_mb": free_mb, "total_mb": total_mb, "warn_below_mb": warn, "critical_below_mb": crit}
    except OSError:
        value = {"state": "unknown"}
    _disk_cache.update(at=now, value=value)
    return value


def disk_critical() -> bool:
    return disk_report()["state"] == "critical"


def fd_report() -> dict:
    """Open file descriptors against the process limit. Each conversation that has written to the vector store keeps its index files open (4 descriptors measured per
    conversation), so the count grows with active conversations; at ~90% of the limit new work would start failing with EMFILE, so readiness goes false before that."""
    import resource

    try:
        open_fds = len(os.listdir("/proc/self/fd"))
        soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        frac = open_fds / soft if soft and soft > 0 else 0.0
        return {"state": "critical" if frac >= 0.9 else "low" if frac >= 0.7 else "ok", "open": open_fds, "limit": soft}
    except Exception:
        return {"state": "unknown"}


def raise_fd_limit(target: int = 65536) -> dict:
    """Raise the soft descriptor limit to min(hard limit, target). Called once at server start."""
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    want = target if hard == resource.RLIM_INFINITY else min(hard, target)
    if soft != resource.RLIM_INFINITY and soft < want:
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (want, hard))
        except (ValueError, OSError):
            pass
    return {"before": soft, "after": resource.getrlimit(resource.RLIMIT_NOFILE)[0]}


def transcript_store_report() -> dict:
    """Can the authoritative transcript database be opened and read right now? (REQUIRED: without it nothing can be committed.)"""
    t0 = time.perf_counter()
    try:
        from orca.serve import conversations

        conn = conversations._turns_conn(timeout=2.0)
        try:
            conn.execute("SELECT 1 FROM conversation_turns LIMIT 1").fetchall()
        finally:
            conn.close()
        return {"status": "ok", "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as e:
        return {"status": "unavailable", "reason": type(e).__name__}


def redis_report() -> dict:
    """Redis is ADVISORY (coordination / cache). Reported, never a reason for not-ready: with Redis down the SQLite authority still protects the transcript."""
    from orca.serve import session_store

    if not session_store.enabled():
        return {"status": "not_configured"}
    # A readiness probe must answer fast even when Redis is frozen (measured: an unbounded ping held /readyz for 5 s), so the check is bounded to 1 s.
    import concurrent.futures

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        ok = ex.submit(session_store.ping).result(timeout=1.0)
        return {"status": "ok" if ok else "unavailable", "role": "advisory"}
    except concurrent.futures.TimeoutError:
        return {"status": "unavailable", "role": "advisory", "detail": "no answer within 1s"}
    except Exception:
        return {"status": "unavailable", "role": "advisory"}
    finally:
        ex.shutdown(wait=False)


def backlog_report() -> dict:
    out: dict = {}
    try:
        from orca.serve import deletions

        out["conversation_deletions_incomplete"] = deletions.count_incomplete()
    except Exception:
        out["conversation_deletions_incomplete"] = "unknown"
    try:
        from orca.docs.store import pending_document_deletions

        out["document_deletions_pending"] = len(pending_document_deletions())
    except Exception:
        out["document_deletions_pending"] = "unknown"
    try:
        from orca.gateway import reconcile

        out["reconciler_blocked"] = len(reconcile.diagnostics()["blocked"])
    except Exception:
        out["reconciler_blocked"] = "unknown"
    return out


def stream_report() -> dict:
    try:
        from orca.serve import streaming

        return streaming.pool_stats()
    except Exception:
        return {}
