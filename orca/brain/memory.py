"""
Orca Memory Engine — four-layer memory architecture.

Short-term  : in-context message history (sliding window)
Long-term   : disk-backed ChromaDB vector store
Episodic    : structured session logs with metadata
Semantic    : distilled facts/concepts across sessions
"""
from __future__ import annotations

import concurrent.futures
import json
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from orca import vectorstore as _vs
from orca.safe_cache import open_cache

from orca.config import MEMORY_DIR, CACHE_DIR, _mkdir_owner_only


@dataclass
class Message:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


@dataclass
class Episode:
    session_id: str
    messages: list[Message]
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


class ShortTermMemory:
    """Sliding-window in-context history."""

    def __init__(self, max_turns: int = 20):
        self.max_turns = max_turns
        self._messages: list[Message] = []

    def add(self, role: str, content: str, **meta) -> None:
        self._messages.append(Message(role=role, content=content, metadata=meta))
        if len(self._messages) > self.max_turns * 2:
            # Keep last max_turns exchanges
            self._messages = self._messages[-(self.max_turns * 2):]

    def to_api_messages(self) -> list[dict]:
        return [{"role": m.role, "content": m.content} for m in self._messages]

    def clear(self) -> None:
        self._messages.clear()

    def __len__(self) -> int:
        return len(self._messages)


_CHROMA_LOCK = threading.Lock()
"""Process-wide: every session's LongTermMemory shares ONE on-disk
chroma.sqlite3 file. `_vacuum_after_delete()` opens its own raw sqlite3
connection to that shared file and issues VACUUM, which needs real
exclusivity -- confirmed by reproduction that running it concurrently with
an unrelated session's store()/recall() (via chromadb's own client, a
different connection) raises chromadb.errors.NotFoundError for the
unrelated, unaffected collection. This lock serializes every chroma
operation in this class within one process.

2026-10-15 (P1 deletion-assurance design): cross-PROCESS concurrency (the
actual multi-worker case this lock cannot cover) was tested directly, not
assumed -- see docs/orneur/status/P1_DELETION_ASSURANCE_DESIGN.md for the
full adversarial evidence. Summary: ordinary concurrent writes/deletes
across genuinely separate OS processes were NOT observed to fail or
corrupt data in repeated testing (multiple concurrent writers, two
simultaneous cross-process deletes, a kill -9 mid-VACUUM followed by a
clean `PRAGMA integrity_check`) -- SQLite's own file locking and busy-wait
retry handle the common case correctly. The real, confirmed exposure is
different from what was originally assumed: a competing process holding a
write lock for longer than normal (tested up to 30s) makes the VACUUM step
block for that ENTIRE duration rather than failing fast -- an availability
risk (a hung request), not a silent-data-loss or corruption risk.
`_vacuum_after_delete()` below now bounds that wait explicitly and tracks
any deferred reclamation durably instead of silently dropping it."""

RECLAIMED = "RECLAIMED"
"""Physical reclamation (VACUUM) completed: the deleted session's raw
bytes are no longer present anywhere in the shared on-disk file."""
DEFERRED = "DEFERRED"
"""Logical deletion succeeded (the data is gone from every normal read
path) but physical reclamation could not complete within the bounded
wait -- durably recorded in the pending-reclamation ledger for retry."""
NOT_APPLICABLE = "NOT_APPLICABLE"
"""No vacuum is needed or possible for this deletion (the JSONL fallback
path: a plain unlink() is already complete, byte-level erasure, with
nothing left to reclaim)."""
FAILED = "FAILED"
"""Logical deletion itself did not succeed. Physical reclamation was not
attempted because there is nothing confirmed-deleted to reclaim yet."""
PENDING = "PENDING"
"""Neither logical deletion nor physical reclamation could be CONFIRMED
within this request's wall-clock budget. This is a genuinely different,
rarer case than DEFERRED (see below) -- it means even `delete_collection()`
itself (chromadb's own internal call, not just this module's own VACUUM
step) did not return in time, empirically confirmed to require another
process holding a raw write lock on the shared file for longer than any
realistic chromadb operation would (tested up to 30 seconds; ordinary
concurrent reads/writes/deletes completed in well under a second in every
adversarial test performed -- see
docs/orneur/status/P1_DELETION_ASSURANCE_DESIGN.md). The underlying
`delete_collection()` call keeps running in a background worker thread
after this status is returned -- it is NOT cancelled, because a thread
blocked in a C extension/syscall cannot be safely killed from pure
Python -- and its eventual real outcome (success or failure, however long
that takes) is recorded durably via a callback, not silently discarded.

2026-10-15, two things tried and rejected before landing on the above --
recorded so neither gets re-attempted without re-discovering why:
(1) `concurrent.futures.ThreadPoolExecutor` + `Future.result(timeout=...)`
does NOT reliably bound this wait: measured ~13.9s wall-clock before
`TimeoutError` was raised despite a 5.0s budget, against a real held
SQLite lock, while a plain `time.sleep(20)` task on the identical executor
correctly timed out at exactly its requested 3.0s -- the blocked native
chromadb/sqlite3 call does not cooperate with Python's GIL/threading
timeout machinery the way pure-Python code does. This is a REAL, disclosed
limitation of the current design: PENDING's wall-clock latency is not as
tightly bounded as `_DELETE_REQUEST_BUDGET_S` implies under extreme
contention, even though it does still eventually return rather than
hanging forever.
(2) Switching to a genuinely separate OS `multiprocessing.Process`
(`Process.join(timeout=...)` + `terminate()`/`kill()` on overrun) WAS
tried, to get a real OS-enforced hard timeout instead of (1)'s cooperative
one -- justified by this module's own `kill -9` mid-VACUUM reproduction
confirming crash-safety (`PRAGMA integrity_check` returned `ok`, every
other session's data stayed intact and queryable). It was REJECTED after
its own adversarial test found a worse, correctness-breaking bug: a
chromadb client constructed in a brand-new OS process can report
`NotFoundError` for a collection a DIFFERENT process's client created and
populated moments earlier, and this did not reliably resolve even after
several seconds of bounded retry -- confirmed directly by recalling the
"deleted" session's data immediately afterward from yet another fresh
client in the ORIGINAL process and finding it still present. Treating that
`NotFoundError` as "already deleted" (the obvious-looking fix) produces a
FALSE positive: `logical_deleted=True` reported while the data is still
fully present and retrievable -- exactly the invented, unearned guarantee
this whole design effort exists to avoid, and a strictly worse failure
mode than (1)'s merely-slow-but-honest PENDING. The thread-based design
above is kept specifically because it has never been observed to lie
about an outcome, only to take longer than its nominal budget to report
one -- a disclosed availability limitation, not a disclosed-vs-actual
privacy gap. See docs/orneur/status/P1_DELETION_ASSURANCE_DESIGN.md for
the full before/after evidence on both attempts."""


@dataclass
class DeletionResult:
    """Point 7 of the P1 deletion-assurance design: a single conflated
    boolean cannot honestly represent "data is gone from every read path"
    (logical_deleted) separately from "the raw bytes are also gone from
    disk" (physical_reclamation) -- a caller or API response that collapses
    these into one value either overclaims forensic erasure it hasn't
    achieved, or (the previous behaviour) hides a real, actionable
    DEFERRED/PENDING state entirely. `bool(result)` is provided for source
    compatibility with every existing caller that only checked logical
    success (`account_delete.py`'s cascade), but any caller reporting
    status to an end user or an API response must read both fields."""
    logical_deleted: bool
    physical_reclamation: str  # one of RECLAIMED / DEFERRED / NOT_APPLICABLE / FAILED / PENDING

    def __bool__(self) -> bool:
        return self.logical_deleted


_RECLAIM_TIMEOUT_S = 2.0
"""Explicit, short bound on how long a single VACUUM attempt will wait for
exclusive access before giving up and deferring. Chosen to keep a
deletion request's worst-case latency bounded and predictable rather than
the previously-unbounded wait (empirically observed to block for the
full duration of a 30-second competing lock) -- a user-facing deletion
request must not hang indefinitely because of unrelated activity
elsewhere in the shared vector store."""

_DELETE_REQUEST_BUDGET_S = 5.0
"""Wall-clock budget for the WHOLE delete() critical section (both
delete_collection() and the vacuum together), enforced at the application
level via a dedicated worker thread + bounded Future.result() -- NOT via
any chromadb/sqlite3 parameter, because chromadb's public Settings API
was checked directly (chroma_query_request_timeout_seconds and its two
siblings are server/distributed-mode-only; nothing bounds the embedded
PersistentClient's local SQLite wait) and exposes no such control for
local persistence mode. This is the one layer this codebase can actually
enforce without patching chromadb's internals. 5 seconds is generous
relative to every realistic-contention measurement taken while building
this (sub-second even under 3 concurrent tight-loop writer processes),
while still being far short of the previously-unbounded wait.

See PENDING's docstring above for the disclosed limitation this still
has (the bound is cooperative, not OS-enforced, so a pathological case can
overrun it) and for why a genuinely OS-enforced alternative was tried and
rejected as strictly worse (a false "deleted" report, not just a slow
one)."""

_delete_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="ltm-delete")
"""A single dedicated worker thread, not one per call -- this naturally
serializes chroma delete/vacuum operations the same way `_CHROMA_LOCK`
already does for store()/recall(), and gives delete() a real, bounded
Future.result(timeout=...) to wait on without needing to kill or cancel
the underlying blocked call if the budget is exceeded (not possible for a
thread blocked in a C extension/syscall; instead its eventual real
outcome is recorded via a done_callback, never silently dropped)."""


def _pending_reclamation_path() -> Path:
    return MEMORY_DIR / "vectors" / "pending_reclamation.json"


def _load_pending_reclamations() -> list[dict]:
    p = _pending_reclamation_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_pending_reclamations(entries: list[dict]) -> None:
    p = _pending_reclamation_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries))
    tmp.replace(p)  # atomic on POSIX: a crash never leaves a half-written ledger


def _record_pending_reclamation(session_id: str, error: str) -> None:
    entries = _load_pending_reclamations()
    now = time.time()
    for e in entries:
        if e.get("session_id") == session_id:
            e["attempts"] = e.get("attempts", 0) + 1
            e["last_attempt_at"] = now
            e["last_error"] = error
            break
    else:
        entries.append({
            "session_id": session_id, "logically_deleted_at": now,
            "attempts": 1, "last_attempt_at": now, "last_error": error,
        })
    _save_pending_reclamations(entries)


def _clear_pending_reclamation(session_id: str) -> None:
    entries = [e for e in _load_pending_reclamations() if e.get("session_id") != session_id]
    _save_pending_reclamations(entries)


def retry_pending_reclamations(*, timeout_s: float = _RECLAIM_TIMEOUT_S) -> dict:
    """Maintenance entry point: attempt the one outstanding operation that
    can satisfy every still-pending reclamation at once (VACUUM of the one
    shared file), and clear every pending entry on success. Safe to call
    from a scheduled job, an admin endpoint, or opportunistically before/
    after an unrelated deletion (`delete()` already does the latter).
    Never raises -- reports status instead, consistent with the rest of
    this module's best-effort-but-never-silent design."""
    entries = _load_pending_reclamations()
    if not entries:
        return {"pending_before": 0, "status": NOT_APPLICABLE}
    status = _vacuum_shared_file(timeout_s=timeout_s)
    if status == RECLAIMED:
        _save_pending_reclamations([])
    return {"pending_before": len(entries), "status": status}


def _vacuum_shared_file(*, timeout_s: float = _RECLAIM_TIMEOUT_S) -> str:
    """The actual VACUUM of the shared vector file, bounded. Runs inside the vector service (service mode) or in-process (embedded). Returns RECLAIMED / DEFERRED /
    NOT_APPLICABLE; an unreachable or timed-out service is DEFERRED (nothing was confirmed), never RECLAIMED."""
    try:
        return _vs.Store(MEMORY_DIR / "vectors").vacuum(timeout_s=timeout_s, deadline_s=timeout_s + 3.0)
    except _vs.VectorError:
        return DEFERRED


def _pending_logical_deletion_path() -> Path:
    return MEMORY_DIR / "vectors" / "pending_logical_deletion.json"


def _load_pending_logical_deletions() -> list[dict]:
    p = _pending_logical_deletion_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_pending_logical_deletions(entries: list[dict]) -> None:
    p = _pending_logical_deletion_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries))
    tmp.replace(p)


def _record_pending_logical_deletion(session_id: str, reason: str) -> None:
    entries = _load_pending_logical_deletions()
    now = time.time()
    for e in entries:
        if e.get("session_id") == session_id:
            e["attempts"] = e.get("attempts", 0) + 1
            e["last_attempt_at"] = now
            e["last_status"] = "still pending"
            break
    else:
        entries.append({
            "session_id": session_id, "first_requested_at": now,
            "attempts": 1, "last_attempt_at": now, "last_status": reason,
        })
    _save_pending_logical_deletions(entries)


def _resolve_pending_logical_deletion(session_id: str, outcome: "DeletionResult | BaseException") -> None:
    """Called at the end of every delete_session() attempt (fresh or a
    retry via check_pending_logical_deletions()) with whatever real
    outcome that attempt reached. A no-op if this session_id has no
    pending-logical-deletion entry (the normal, common case -- most
    deletes never hit the bounded timeout at all).

    2026-10-15: previously a done_callback fired by a background worker
    THREAD once its (uncancellable) blocked call eventually finished on
    its own. Now that an overrun attempt is enforced by killing a worker
    PROCESS (see _DELETE_REQUEST_BUDGET_S's docstring), there is no
    eventual background finish to wait for -- a killed attempt's outcome
    is genuinely unknown, not just delayed. This function is now called
    directly, synchronously, with whatever delete_session() itself just
    confirmed.

    A confirmed logical success REMOVES the entry (its job -- tracking
    something that still needs attention -- is done; keeping it around
    forever would grow the ledger unboundedly in a busy deployment). A
    failure, exception, or renewed PENDING stays in the ledger, updated
    with the real status, so it keeps surfacing to
    check_pending_logical_deletions() until someone resolves the
    underlying cause -- "track cleanup failures durably" means durably,
    not silently dropped after one try."""
    entries = _load_pending_logical_deletions()
    kept = []
    for e in entries:
        if e.get("session_id") != session_id:
            kept.append(e)
            continue
        if isinstance(outcome, BaseException):
            e["resolved_at"] = time.time()
            e["last_status"] = f"background attempt raised: {outcome!r}"
            kept.append(e)
        elif outcome.logical_deleted:
            pass  # resolved successfully -- drop it
        else:
            e["resolved_at"] = time.time()
            e["last_status"] = f"background attempt completed but logical deletion still failed: physical_reclamation={outcome.physical_reclamation}"
            kept.append(e)
    _save_pending_logical_deletions(kept)


def check_pending_logical_deletions() -> dict:
    """Maintenance entry point, parallel to retry_pending_reclamations()
    but for the rarer PENDING case: re-attempts delete() for every session
    still recorded as pending. Safe and idempotent -- delete_collection()
    on an already-deleted (or never-existing) collection name either
    no-ops or raises, both handled the same as any other delete() call;
    if the original background attempt already finished on its own, this
    simply confirms and clears the ledger entry via the normal path."""
    entries = _load_pending_logical_deletions()
    results = {}
    for e in entries:
        sid = e["session_id"]
        results[sid] = LongTermMemory(sid).delete().physical_reclamation
    # A confirmed success removes its own entry (see
    # _resolve_pending_logical_deletion); re-load to report the current,
    # post-attempt ledger size rather than the pre-attempt one.
    return {"checked": len(entries), "results": results, "still_pending": len(_load_pending_logical_deletions())}


session_binding = _vs.session_binding


class LongTermMemory:
    """Vector store for semantic retrieval across a conversation's turns (service-contained chromadb, see orca/vectorstore). Falls back to simple JSON search if chromadb is
    not installed.

    L03: the constructor does no I/O (a request thread can never block while building a session). The collection is opened on first use, its ownership binding is verified
    (a collection bound to a different conversation is not read or written), and a conversation with a deletion tombstone is refused. Failures of the vector service degrade a
    derived-state write or read (counted, never silent); callers that must not lose data (``strict=True``) get the error instead."""

    def __init__(self, session_id: str):
        self._session_id = session_id
        self._fallback_file = MEMORY_DIR / "vectors" / f"{session_id[:8]}.jsonl"
        self._available = _vs.available()
        self._col = None
        self._open_lock = threading.Lock()
        self.last_status = "unopened"
        if not self._available:
            self._fallback_file.parent.mkdir(parents=True, exist_ok=True)

    @property
    def _collection(self):
        return self._ensure()

    @_collection.setter
    def _collection(self, value):                              # tests substitute a fake collection
        self._col = value

    @property
    def _name(self) -> str:
        return f"orca_{self._session_id[:8]}"

    def _ensure(self):
        """The collection handle, opened (and ownership-checked) on first use. Raises VectorOwnershipError / VectorUnavailable / VectorBusy / VectorTimeout."""
        if self._col is not None:
            return self._col
        with self._open_lock:
            if self._col is not None:
                return self._col
            from orca.serve import deletions

            if deletions.is_tombstoned(self._session_id):           # fails closed: an unreadable tombstone store means "unavailable"
                self.last_status = "tombstoned"
                raise _vs.VectorOwnershipError("conversation is deleted")
            Path(str(MEMORY_DIR / "vectors")).mkdir(parents=True, exist_ok=True)
            col, info = _vs.Store(MEMORY_DIR / "vectors").open_collection(self._name, {"hnsw:space": "cosine"}, binding=session_binding(self._session_id))
            self.last_status = info.get("status", "ok")
            if self.last_status == "mismatch":
                _count("ownership_refusals")
                raise _vs.VectorOwnershipError("collection belongs to another conversation")
            self._col = col
            return col

    def store(self, text: str, metadata: dict | None = None, *, strict: bool = False) -> str:
        if self._available:
            doc_id = str(uuid.uuid4())
            # A real production bug, found via load testing: newer chromadb versions reject an EMPTY metadata dict outright ("Expected metadata to be a non-empty dict") --
            # every commit_to_long_term() call with no explicit metadata (the normal case) crashed the whole request. Always include at least a timestamp.
            stored_metadata = dict(metadata) if metadata else {}
            stored_metadata.setdefault("stored_at", time.time())
            try:
                self._ensure().add(documents=[text], ids=[doc_id], metadatas=[stored_metadata])
            except _vs.VectorError as exc:
                if strict:
                    raise
                _count("dropped_writes", type(exc).__name__)       # derived state: the turn is already durable, so it is not failed; the loss is counted and visible
                return ""
            return doc_id
        # Fallback: append to JSONL
        with open(self._fallback_file, "a") as f:
            f.write(json.dumps({"text": text, "metadata": metadata or {}}) + "\n")
        return ""

    def recall(self, query: str, n: int = 5, *, strict: bool = False) -> list[dict]:
        if self._available:
            try:
                results = self._ensure().query(query_texts=[query], n_results=n)
            except _vs.VectorError as exc:
                if strict:
                    raise
                _count("empty_recalls", type(exc).__name__)
                return []
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            return [{"text": d, "metadata": m} for d, m in zip(docs, metas)]
        # Fallback: keyword search over JSONL
        if not self._fallback_file.exists():
            return []
        hits = []
        query_words = set(query.lower().split())
        with open(self._fallback_file) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    text = entry.get("text", "")
                    score = sum(1 for w in query_words if w in text.lower())
                    if score > 0:
                        hits.append((score, entry))
                except json.JSONDecodeError:
                    continue
        hits.sort(key=lambda x: x[0], reverse=True)
        return [h[1] for h in hits[:n]]

    def delete(self) -> "DeletionResult":
        """Phase 5.1 (docs/orneur/phase-5/LEGACY_MEMORY_AUTHORITY_AUDIT.md):
        a real, confirmed gap -- this class had NO deletion method at
        all, and orca/serve/account_delete.py never touched it, meaning
        every raw Q:/A: turn ever written via commit_to_long_term()
        (which runs unconditionally on every chat/stream/ultra turn)
        persisted in this session's ChromaDB collection FOREVER, even
        after a full account deletion.

        2026-10-14 (P0 privacy remediation, reopened G-025): `delete_collection()`
        alone is NOT sufficient. It removes the collection from Chroma's own
        query surface, but the shared `chroma.sqlite3` file is a single SQLite
        database used by every session's collection -- SQLite marks a deleted
        row's page as free for reuse, it does not overwrite the bytes, so the
        deleted collection's raw text remains physically present and
        recoverable from the file on disk for as long as any OTHER
        collection's data keeps the file from being fully emptied.

        2026-10-15 (P1 deletion-assurance design -- see
        docs/orneur/status/P1_DELETION_ASSURANCE_DESIGN.md for the full
        evaluated alternatives and adversarial evidence): logical deletion
        (this always runs, fast, and is the real privacy guarantee -- once
        it returns True, no normal read path anywhere, in any process, can
        retrieve this session's data) is now reported SEPARATELY from
        physical reclamation (VACUUM, best-effort hardening against raw
        disk-byte recovery, bounded to `_RECLAIM_TIMEOUT_S` seconds rather
        than the previously-unbounded wait). A deferred reclamation is
        durably recorded, never silently dropped, and this method also
        opportunistically retries any PRE-EXISTING pending reclamation
        left over from an earlier, deferred deletion -- cheap self-healing
        that needs no new scheduled-job infrastructure.

        2026-10-15, continued -- CRITICAL CORRECTION found by testing this
        fix against a real held lock, not just unit tests with mocks: the
        FIRST attempt at this bounding only wrapped the operations on an
        ALREADY-CONSTRUCTED `self._client`/`self._collection`. That missed
        the actual unbounded wait entirely, because `LongTermMemory.__init__`
        itself (`chromadb.PersistentClient(...)` +
        `get_or_create_collection(...)`) ALSO touches the same locked file,
        and runs synchronously on the CALLING thread, before `delete()` is
        even invoked -- so a caller doing `LongTermMemory(session_id).delete()`
        could still block unboundedly inside the constructor, before any
        watchdog ever started. Confirmed by direct reproduction (a real
        15-second held lock still produced a ~14-second `delete()` call
        after the first version of this fix). Fixed by moving ALL chroma
        client/collection setup for a deletion into the SAME bounded
        background thread via the `delete_session()` classmethod below,
        which this instance method now delegates to -- nothing related to
        deletion constructs a chromadb client on the calling thread
        anymore. Re-verified against the same real 15-second held-lock
        reproduction: see docs/orneur/status/P1_DELETION_ASSURANCE_DESIGN.md
        for the exact before/after timings."""
        return LongTermMemory.delete_session(self._session_id, fallback_file=self._fallback_file)

    @classmethod
    def delete_session(cls, session_id: str, *, fallback_file: Path | None = None) -> "DeletionResult":
        """The deletion entry point. Nothing here constructs a chromadb client on the calling thread.

        L03: in service mode the delete and the VACUUM are operations on the vector-service process with a deadline enforced on the socket, so the caller is released at
        ``_DELETE_REQUEST_BUDGET_S`` however the native call behaves. In embedded mode (no deadline possible) the previous bounded-worker-thread design is kept.
        States (never conflated): ``logical_deleted`` only when the service CONFIRMED the collection is gone (or never existed); ``physical_reclamation`` is RECLAIMED only when
        the VACUUM completed, DEFERRED when it could not (recorded durably and retried), PENDING when even the deletion could not be confirmed in time (recorded durably),
        FAILED when the deletion itself failed."""
        fallback_file = fallback_file or (MEMORY_DIR / "vectors" / f"{session_id[:8]}.jsonl")
        if not _vs.available():
            if fallback_file.exists():
                fallback_file.unlink()
                return DeletionResult(logical_deleted=True, physical_reclamation=NOT_APPLICABLE)
            return DeletionResult(logical_deleted=False, physical_reclamation=NOT_APPLICABLE)

        if _vs.mode() == "service":
            try:
                result = _delete_sync(session_id, deadline_s=_DELETE_REQUEST_BUDGET_S)
            except (_vs.VectorTimeout, _vs.VectorUnavailable, _vs.VectorBusy):
                _record_pending_logical_deletion(session_id, "the vector service did not confirm the deletion within the request budget")
                return DeletionResult(logical_deleted=False, physical_reclamation=PENDING)
            _resolve_pending_logical_deletion(session_id, result)
            return result

        future = _delete_executor.submit(_delete_sync, session_id)
        try:
            return future.result(timeout=_DELETE_REQUEST_BUDGET_S)
        except concurrent.futures.TimeoutError:
            _record_pending_logical_deletion(session_id, "client construction/delete_collection()/vacuum did not complete within the request budget")

            def _on_done(f: "concurrent.futures.Future[DeletionResult]") -> None:
                try:
                    _resolve_pending_logical_deletion(session_id, f.result())
                except BaseException as e:  # noqa: BLE001 -- recorded, never swallowed
                    _resolve_pending_logical_deletion(session_id, e)

            future.add_done_callback(_on_done)
            return DeletionResult(logical_deleted=False, physical_reclamation=PENDING)


def _delete_sync(session_id: str, deadline_s: float | None = None) -> "DeletionResult":
    """Delete the conversation's collection and reclaim its bytes. In embedded mode this runs on ``_delete_executor``'s worker thread; in service mode on the caller, bounded by
    ``deadline_s`` on the socket. Raises Vector* errors only when NOTHING could be confirmed (the caller records PENDING)."""
    store = _vs.Store(MEMORY_DIR / "vectors")
    name = f"orca_{session_id[:8]}"
    try:
        res = store.delete_collection(name, deadline_s=deadline_s, binding=_vs.session_binding(session_id))
    except _vs.VectorNotFound:
        res = {"existed": False, "removed": True}
    except (_vs.VectorTimeout, _vs.VectorUnavailable, _vs.VectorBusy):
        if deadline_s is not None:
            raise
        return DeletionResult(logical_deleted=False, physical_reclamation=FAILED)
    except Exception:
        return DeletionResult(logical_deleted=False, physical_reclamation=FAILED)
    if res.get("refused") == "not_owner":
        _count("ownership_refusals")
        return DeletionResult(logical_deleted=True, physical_reclamation=NOT_APPLICABLE)    # the collection holds another conversation's data; nothing of THIS one is in it, and it is left intact
    if not res.get("removed"):
        return DeletionResult(logical_deleted=False, physical_reclamation=FAILED)      # asked to delete and it is still listed: not deleted
    try:
        status = _vacuum_shared_file()
        deferred_reason = "VACUUM did not complete within the bounded timeout"
    except Exception as e:      # defence in depth: the logical deletion above already succeeded regardless -- never let a surprise here crash the caller's delete() request
        status, deferred_reason = DEFERRED, f"unexpected: {type(e).__name__}"
    if status == DEFERRED:
        _record_pending_reclamation(session_id, deferred_reason)
    elif status == RECLAIMED:
        _save_pending_reclamations([])            # one VACUUM rewrites the whole shared file, so it satisfies every earlier-deferred reclamation too
    return DeletionResult(logical_deleted=True, physical_reclamation=status)


_COUNTERS: dict[str, int] = {}
_COUNTER_LOCK = threading.Lock()


def _count(name: str, kind: str = "") -> None:
    key = f"{name}:{kind}" if kind else name
    with _COUNTER_LOCK:
        _COUNTERS[key] = _COUNTERS.get(key, 0) + 1


def vector_memory_counters() -> dict[str, int]:
    """Counts of degraded derived-state operations (dropped writes, empty recalls, ownership refusals) since process start. No content."""
    with _COUNTER_LOCK:
        return dict(_COUNTERS)


class EpisodicMemory:
    """Structured session logs stored as JSON files."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.path = MEMORY_DIR / "episodes" / f"{session_id}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, episode: Episode) -> None:
        with open(self.path, "w") as f:
            json.dump(
                {
                    "session_id": episode.session_id,
                    "messages": [asdict(m) for m in episode.messages],
                    "summary": episode.summary,
                    "tags": episode.tags,
                    "created_at": episode.created_at,
                },
                f,
                indent=2,
            )

    def load(self) -> Episode | None:
        if not self.path.exists():
            return None
        with open(self.path) as f:
            data = json.load(f)
        msgs = [Message(**m) for m in data["messages"]]
        return Episode(
            session_id=data["session_id"],
            messages=msgs,
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            created_at=data.get("created_at", 0),
        )

    @classmethod
    def list_sessions(cls) -> list[str]:
        ep_dir = MEMORY_DIR / "episodes"
        if not ep_dir.exists():
            return []
        return [p.stem for p in sorted(ep_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)]


class SemanticMemory:
    """Distilled facts/concepts persisted across all sessions via disk cache."""

    _shared: dict = {}
    _shared_lock = __import__("threading").Lock()

    def __init__(self):
        # "semantic" is created by diskcache itself if missing; validate it
        # (and refuse a symlink/foreign-owned pre-existing entry) first.
        semantic_dir = _mkdir_owner_only(CACHE_DIR / "semantic")
        # L02-06: ONE cache object per directory per process. Every conversation used to open its own diskcache (a SQLite database plus its WAL = 2 file descriptors and
        # a connection per thread), none of them ever closed: measured on a live server, 72 sessions held 58+ open copies and descriptors grew 34 -> 356 until the
        # process would have hit its descriptor limit. diskcache.Cache is thread-safe, so sharing it is correct.
        key = str(semantic_dir)
        with SemanticMemory._shared_lock:
            cache = SemanticMemory._shared.get(key)
            if cache is None:
                cache = SemanticMemory._shared[key] = open_cache(semantic_dir)  # SafeDisk: never unpickles (orca/safe_cache.py)
        self._cache = cache

    def store_fact(self, key: str, value: Any) -> None:
        self._cache[f"fact:{key}"] = value

    def recall_fact(self, key: str) -> Any | None:
        return self._cache.get(f"fact:{key}")

    def store_concept(self, concept: str, description: str) -> None:
        existing = self._cache.get("concepts", {})
        existing[concept] = description
        self._cache["concepts"] = existing

    def all_concepts(self) -> dict[str, str]:
        return self._cache.get("concepts", {})

    def delete_session_facts(self, session_id: str) -> bool:
        """Phase 5 (docs/orneur/phase-5/CURRENT_MEMORY_ARCHITECTURE.md's
        Finding: this store was entirely missing from
        orca/serve/account_delete.py's deletion cascade before this fix).

        Removes this session's own `fact:session_{id[:8]}` key, AND strips
        this session's block out of the shared `all_sessions_summary`
        string -- distill_and_save() merges every session's distilled
        summary into ONE global string tagged with "[Session {id[:8]}]"
        markers, so a plain per-session key deletion alone would leave
        this session's content sitting inside that merged blob forever.
        Returns whether anything was actually found and removed.
        """
        removed = False
        session_key = f"fact:session_{session_id[:8]}"
        if session_key in self._cache:
            del self._cache[session_key]
            removed = True

        merged = self._cache.get("fact:all_sessions_summary", "")
        marker = f"[Session {session_id[:8]}]"
        if marker in merged:
            import re
            # Split on each "[Session <id>]" header, keeping the header
            # attached to its own block, regardless of whether it's the
            # first block in the string or not.
            parts = re.split(r"(?=\[Session )", merged)
            kept = [p for p in parts if p.strip() and not p.startswith(marker)]
            self._cache["fact:all_sessions_summary"] = "\n\n".join(p.strip() for p in kept).strip()
            removed = True
        return removed


class MemoryEngine:
    """Unified interface over all four memory layers."""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.short = ShortTermMemory()
        self.long = LongTermMemory(self.session_id)
        self.episodic = EpisodicMemory(self.session_id)
        self.semantic = SemanticMemory()

    def add_turn(self, role: str, content: str) -> None:
        self.short.add(role, content)

    def recall_context(self, query: str, n: int = 3) -> str:
        hits = self.long.recall(query, n=n)
        if not hits:
            return ""
        lines = [f"[Memory] {h['text']}" for h in hits]
        return "\n".join(lines)

    def commit_to_long_term(self, text: str, meta: dict | None = None) -> None:
        self.long.store(text, meta)

    def save_session(self, summary: str = "", tags: list[str] | None = None) -> None:
        ep = Episode(
            session_id=self.session_id,
            messages=self.short._messages,
            summary=summary,
            tags=tags or [],
        )
        self.episodic.save(ep)

    def load_session(self, session_id: str) -> bool:
        ep_mem = EpisodicMemory(session_id)
        ep = ep_mem.load()
        if not ep:
            return False
        self.session_id = session_id
        for m in ep.messages:
            self.short._messages.append(m)
        return True

    def messages(self) -> list[dict]:
        return self.short.to_api_messages()

    def distill_and_save(self, brain) -> str:
        """Summarize session into semantic facts. Call at session end.

        Phase 5.1 (docs/orneur/phase-5/LEGACY_MEMORY_AUTHORITY_AUDIT.md):
        this used to ALSO merge every session's distilled summary into one
        shared, unscoped `all_sessions_summary` string -- readable by ANY
        session via load_prior_context(), including through the
        `memory_recall` agent tool on the multi-tenant web serving path
        (orca/tools/__init__.py::_recall_memory_engine). That was a real,
        confirmed cross-session (and, in a multi-user deployment,
        cross-user) read path with zero scope check. Retired outright
        (spec §9/§16 option "retire the path") -- no code still needs it,
        and it never went through MemoryArbiter/evidence-lineage/firewall
        governance in the first place.

        The distilled summary is now ALSO routed through Memory
        Continuum's real candidate/promotion pipeline, scoped to this
        session and carrying NO evidence_refs (a raw self-summary of the
        conversation is not verified against anything) -- MemoryArbiter
        promotes it at UNVERIFIED, never KNOWN/SUPPORTED, per spec §9's
        "no silently labeling generated summaries as SUPPORTED or KNOWN".
        The legacy per-session `fact:session_{id[:8]}` key is still
        written too (an explicit, documented dual-write -- see
        docs/orneur/phase-5/MEMORY_MIGRATION.md) since
        orca/variants/core.py's own `/recall` command still reads it
        directly; it is itself session-scoped and was never part of the
        cross-session leak.
        """
        msgs = self.short.to_api_messages()
        if len(msgs) < 2:
            return ""
        history = "\n".join(f"[{m['role'].upper()}]: {m['content'][:300]}" for m in msgs[-20:])
        try:
            summary = brain.complete(
                [{"role": "user", "content": (
                    "Extract the key facts, decisions, goals, and context from this conversation "
                    "that should be remembered for future sessions. Be concise and specific. "
                    "Focus on: user goals, business context, technical decisions, personal preferences.\n\n"
                    f"{history}"
                )}],
                system="You are a memory distiller. Output only a bulleted list of key facts. No preamble.",
                temperature=0.1,
                max_tokens=400,
            )
        except Exception:
            return ""
        self.semantic.store_fact(f"session_{self.session_id[:8]}", summary)
        self.save_session(summary=summary)

        try:
            from orca.memory.arbiter import MemoryArbiter
            from orca.memory.contracts import MemoryCandidate, MemoryScope, MemoryType
            from orca.memory import store as memory_store

            arbiter = MemoryArbiter()
            candidate = MemoryCandidate(
                extracted_claim=summary[:2000], scope=MemoryScope.SESSION, scope_id=self.session_id,
            )
            existing = memory_store.list_records(MemoryType.SEMANTIC, MemoryScope.SESSION, self.session_id)
            decision, _reasons = arbiter.decide_promotion(candidate, existing)
            if decision.value == "PROMOTED":
                arbiter.promote(candidate)
        except Exception:
            pass  # Memory Continuum promotion is additive -- never blocks the legacy summary from being returned/saved

        return summary

    def load_prior_context(self) -> str:
        """Return this session's own distilled facts -- NEVER another
        session's (see distill_and_save()'s docstring: the old
        cross-session `all_sessions_summary` fallback was a real,
        confirmed unscoped read leak, retired in Phase 5.1)."""
        return self.semantic.recall_fact(f"session_{self.session_id[:8]}") or ""


def vector_maintenance() -> dict:
    """Periodic maintenance (the deletion sweep): retry byte reclamation that was deferred and deletions that could not be confirmed. Bounded, idempotent, never raises."""
    out = {}
    try:
        out["memory_reclamation"] = retry_pending_reclamations()
        out["logical_deletions"] = check_pending_logical_deletions() if _load_pending_logical_deletions() else {"checked": 0}
    except Exception as exc:
        out["memory_error"] = type(exc).__name__
    try:
        from orca.docs.store import retry_pending_doc_reclamation

        out["docs_reclamation"] = retry_pending_doc_reclamation()
    except Exception as exc:
        out["docs_error"] = type(exc).__name__
    return out
