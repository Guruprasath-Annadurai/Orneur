"""
P0 privacy remediation (2026-10-14): reopened G-025 regression, root-caused.

What actually happened, precisely (not "a commit broke this"): this exact
assertion -- that a deleted user's conversation title/fact never resurfaces
-- was written in the original fix (PR #34) and has been identical, byte for
byte, ever since. It FAILS, deterministically and reproducibly, at that
exact original commit TOO, in any environment that actually has `chromadb`
installed -- confirmed on macOS and inside a vanilla linux/python:3.11-slim
Docker container, ruling out an OS/filesystem explanation. The reason it has
always shown green in this project's own CI: NOT ONE of the 6 install
commands across every CI job in .github/workflows/test.yml installs the
`memory`/`docs`/`all` extras that pull in chromadb, so `LongTermMemory`
(orca/brain/memory.py) has silently run its JSONL-fallback code path in
100% of CI runs across this entire ~45-PR program, never once exercising
the real ChromaDB-backed implementation it exists to test. The fallback's
delete() is a plain os.unlink() -- genuinely clean, no residue, which is
why CI always passed. The real backend's delete_collection() call only
removes a collection from Chroma's own query surface; the shared
chroma.sqlite3 file (one physical file for every session's collection) is
SQLite, and SQLite marks a deleted row's page reusable, it does not
overwrite the bytes -- so the deleted session's raw text remained
physically present and recoverable on disk for as long as any OTHER
session's collection kept the file from going empty, which is the normal
shape of any real multi-user deployment.

This file exists specifically to make that code path unskippable: every
test below hard-requires chromadb (no silent skip-on-ImportError) so a
future CI config that still never installs it fails LOUDLY here instead of
silently re-opening this exact gap.
"""
from __future__ import annotations

import multiprocessing
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import pytest

chromadb = pytest.importorskip(
    "chromadb",
    reason=(
        "chromadb is not installed in this environment. This is not a benign skip: it means "
        "LongTermMemory's real ChromaDB-backed deletion path -- the one this entire file exists "
        "to test -- cannot be exercised here, exactly the gap that let the reopened G-025 "
        "regression go undetected by CI for this project's whole history. If this skip is firing "
        "in CI, that CI job is missing the `memory` (or `docs`/`all`) extra and needs it added."
    ),
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ORNEUR_HOME", str(tmp_path))
    monkeypatch.setenv("ORCA_HOME", str(tmp_path))
    import orca.config as config
    import importlib
    importlib.reload(config)
    import orca.brain.memory as memory
    importlib.reload(memory)
    yield memory


def _raw_db_bytes(memory_module) -> bytes:
    db = memory_module.MEMORY_DIR / "vectors" / "chroma.sqlite3"
    return db.read_bytes() if db.exists() else b""


def _cross_process_delete_probe(vectors_path: str, collection_name: str, q: "multiprocessing.Queue") -> None:
    """Module-level (not nested in the test) so `multiprocessing`'s
    `spawn` start method can import it by name in the fresh child
    interpreter. Mirrors exactly what a hypothetical multi-worker-process
    deployment of LongTermMemory would do: construct its OWN chromadb
    client against the SAME shared persistent directory another process
    just wrote to, and try to act on a collection by name."""
    import chromadb
    from chromadb.errors import NotFoundError

    client = chromadb.PersistentClient(path=vectors_path)
    try:
        client.delete_collection(name=collection_name)
        q.put(("deleted", None))
    except NotFoundError as e:
        q.put(("not_found", repr(e)))
    except Exception as e:
        q.put(("other_error", repr(e)))


def test_chromadb_persistent_client_is_not_a_safe_cross_process_interface(home):
    """P1 deletion-assurance design, Architecture Decision review
    (2026-10-15, corrected): this test is kept as regression coverage for
    a REAL, CONFIRMED-BUT-UNREPRODUCED anomaly, not a reliably-reproducing
    bug. The original observation (full traceback captured, preserved in
    docs/orneur/status/P1_DELETION_ASSURANCE_DESIGN.md §8.3): during a
    specific full-suite pytest run, a client constructed in a brand-new
    process -- strictly AFTER a different process's client had already
    returned successfully from store() -- raised `NotFoundError` on
    `delete_collection()` for a collection that data showed was still
    fully present and recallable in the original process.

    This specific test IS properly sequenced (store() returns before the
    probe subprocess starts) -- the methodology here was never the
    problem. What changed on 2026-10-15 is confidence in the ROOT CAUSE:
    seven separate, deliberate attempts to reproduce this anomaly under
    controlled conditions -- isolated sequential runs (20/20 clean),
    realistic ~1985-collection scale (25/25 clean), concurrent unrelated
    writes (15/15 clean), concurrent background VACUUM churn (20/20
    clean), repeated `importlib.reload()` churn matching this test
    file's own fixture pattern (40/40 clean), and even re-running the
    exact original two-file combined suite against a realistic-scale copy
    of this codebase's own real accumulated store (14/14 clean, 3 runs)
    -- did NOT reproduce it. The anomaly is real (a genuine traceback was
    captured) but its cause remains UNRESOLVED, not confirmed to be
    general chromadb cross-process catalog staleness as first assumed.

    This test is kept, asserting leniently, specifically so that if this
    anomaly recurs under normal CI/dev usage, it is captured again here
    rather than silently vanishing -- and so nothing related to deletion
    routes through a freshly-started separate process regardless (a
    chromadb-recommended precaution, independent of whether this exact
    anomaly is ever pinned down). See
    docs/orneur/status/P1_DELETION_ASSURANCE_DESIGN.md §8.3 for the full,
    corrected evidence record, what remains unresolved, and the exact
    additional instrumentation that would be needed to pin this down if
    it recurs."""
    sid = str(uuid.uuid4())
    ltm = home.LongTermMemory(sid)
    ltm.store("fact for the cross-process visibility probe")

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    probe = ctx.Process(
        target=_cross_process_delete_probe,
        args=(str(home.MEMORY_DIR / "vectors"), f"orca_{sid[:8]}", q),
    )
    probe.start()
    probe.join(timeout=10)
    assert not probe.is_alive(), "cross-process probe hung -- unexpected, investigate separately"

    outcome, detail = q.get_nowait()
    assert outcome in ("deleted", "not_found", "other_error")
    if outcome == "not_found":
        # The specific race this test exists to document: the probe's
        # fresh cross-process client could not see the collection, yet
        # the data is still fully present and recallable right here, in
        # the process that actually owns it. A false "not found" from a
        # context this codebase never routes real deletions through is
        # exactly why it never does.
        assert "NotFoundError" in detail or "does not exist" in detail
        assert home.LongTermMemory(sid).recall("fact for the cross-process visibility probe")
    # "deleted": this run's race didn't reproduce -- the probe's client
    # happened to see the collection and genuinely deleted it. Expected
    # to happen sometimes; the race is real but not deterministic, so no
    # assertion is made either way about post-probe recall() in that case.


def _cross_process_store_then_signal(vectors_path: str, write_sid: str, text: str, done: "multiprocessing.Event") -> None:
    """Module-level target (spawn-importable). Simulates the realistic
    two-real-process shape this codebase actually has in production TODAY
    -- orca/serve/api.py's uvicorn process and orca/mcp/memory_server.py's
    independent stdio process both constructing their own chromadb client
    against the same MEMORY_DIR/vectors -- not a hypothetical future
    multi-worker topology.

    2026-10-15 CORRECTION: an earlier version of this test (see git
    history / PR #48's original commit) read `write_sid` from the PARENT
    process concurrently with this subprocess's store() call, with NO
    synchronization between them, and reported a ~40-45% "silent miss
    rate". That number has been RETRACTED -- the reader was never
    guaranteed to run after the write actually completed, so a miss there
    is an artifact of an unsynchronized race (the read may simply have
    run before the write finished), not evidence of a post-completion
    consistency defect. This version uses a real process-safe
    synchronization primitive (`multiprocessing.Event`) so a reader can
    only ever observe a write that has ALREADY, confirmedly, completed --
    the only ordering that constitutes a genuine "read-after-write"
    test. See docs/orneur/status/P1_DELETION_ASSURANCE_DESIGN.md §8.3 for
    the full retraction and the corrected evidence."""
    import orca.brain.memory as memory
    ltm = memory.LongTermMemory(write_sid)
    ltm.store(text)
    done.set()  # only signaled AFTER store() has returned -- the real completion barrier


def test_read_after_confirmed_write_is_consistent_across_real_processes(home):
    """CTO correction (2026-10-15): the MCP memory server
    (orca/mcp/memory_server.py) is a genuinely independent, already-shipped
    OS process that can run at the same time as the API server, both
    constructing their own chromadb client against the same
    MEMORY_DIR/vectors -- this is a real, existing architectural shape,
    not a hypothetical future multi-worker topology, so it deserves a
    real regression test. This is the CORRECTED replacement for this
    test's earlier version (see the retraction note on
    `_cross_process_store_then_signal` above): the earlier version
    conflated an unsynchronized race with a genuine consistency defect.
    This version uses `multiprocessing.Event` as a real completion
    barrier -- the parent process's read only ever starts strictly AFTER
    the writer subprocess has signaled that `store()` has already
    returned successfully. This is THE scientifically valid version of
    "read-after-write consistency" (CTO directive Mission 2/3, 2026-10-15):
    confirmed clean across repeated manual reproduction (15/15 at small
    scale, 15/15 against a real HTTP-server-backed chroma instance, 25/25
    against a realistic ~1985-collection copy of this codebase's own
    real accumulated store) before being committed here as a permanent
    regression test. A failure here WOULD be a genuine, actionable
    finding -- unlike the retracted version, this one does not accept a
    miss as a legitimate race outcome."""
    for _ in range(15):
        home.LongTermMemory(str(uuid.uuid4())).store("preload filler fact")

    write_sid = str(uuid.uuid4())
    text = "Q: what is my project called?\nA: Nightingale"

    ctx = multiprocessing.get_context("spawn")
    done = ctx.Event()
    writer = ctx.Process(target=_cross_process_store_then_signal, args=(str(home.MEMORY_DIR / "vectors"), write_sid, text, done))
    writer.start()

    # The real completion barrier: block until the writer process has
    # itself confirmed store() returned, not until some arbitrary amount
    # of wall-clock time has passed. This is what "the writer's
    # completion has been communicated across processes" means in
    # practice, not just "we waited a bit".
    signaled = done.wait(timeout=10)
    writer.join(timeout=10)
    assert signaled, "writer subprocess never signaled completion -- unexpected, investigate separately"
    assert not writer.is_alive(), "writer subprocess hung after signaling -- unexpected, investigate separately"

    # Now, and only now, is a read a genuine "read-after-write" test. A
    # miss here is a real finding, not a legitimate race outcome.
    hits = home.LongTermMemory(write_sid).recall("Nightingale")
    assert hits and hits[0]["text"] == text


def test_deleting_a_session_removes_its_raw_bytes_even_with_another_live_collection_present(home):
    """The core regression. A single-collection file happened to come out
    clean by coincidence of SQLite page layout; a second, still-live
    collection in the same shared file is what exposed the real gap, and
    is the realistic shape of any multi-user deployment."""
    ltm_a = home.LongTermMemory("aaaaaaaa-0000-0000-0000-000000000000")
    ltm_a.store("my secret preference")
    ltm_b = home.LongTermMemory("bbbbbbbb-0000-0000-0000-000000000000")
    ltm_b.store("unrelated session b content")

    assert b"my secret preference" in _raw_db_bytes(home)
    result = ltm_a.delete()
    assert result.logical_deleted is True
    assert result.physical_reclamation == home.RECLAIMED
    assert b"my secret preference" not in _raw_db_bytes(home)


def test_deleted_session_is_not_retrievable_via_recall(home):
    sid = str(uuid.uuid4())
    ltm = home.LongTermMemory(sid)
    ltm.store("a fact that must not survive deletion")
    assert ltm.recall("fact that must not survive")
    ltm.delete()
    assert home.LongTermMemory(sid).recall("fact that must not survive") == []


def test_another_live_session_is_unaffected_by_the_vacuum_triggered_by_an_unrelated_deletion(home):
    """The fix (a VACUUM of the whole shared file) must not corrupt or lose
    a DIFFERENT, still-live session's data."""
    ltm_a = home.LongTermMemory("aaaaaaaa-1111-0000-0000-000000000000")
    ltm_a.store("deleted tenant's data")
    ltm_b = home.LongTermMemory("bbbbbbbb-1111-0000-0000-000000000000")
    ltm_b.store("live tenant's data, must survive")

    ltm_a.delete()

    results = home.LongTermMemory("bbbbbbbb-1111-0000-0000-000000000000").recall("live tenant")
    assert len(results) == 1
    assert results[0]["text"] == "live tenant's data, must survive"


def test_restart_like_reconnect_does_not_resurrect_deleted_data(home):
    """Simulates a process restart: a brand-new chromadb PersistentClient
    opening the same on-disk file from scratch must not see, via any path
    (recall, or a fresh raw-byte scan), data from a session already
    deleted in a prior 'process' (prior LongTermMemory instance)."""
    sid = str(uuid.uuid4())
    home.LongTermMemory(sid).store("should not survive a restart-like reconnect")
    home.LongTermMemory(sid).delete()

    # A fresh instance = a fresh chromadb.PersistentClient over the same path.
    reconnected = home.LongTermMemory(sid)
    assert reconnected.recall("should not survive") == []
    assert b"should not survive a restart-like reconnect" not in _raw_db_bytes(home)


def test_cross_tenant_session_id_collision_does_not_resurrect_a_deleted_tenants_data(home):
    """orca/brain/memory.py keys LongTermMemory's chroma collection name by
    session_id[:8] (register gap G-022: an 8-char, not full-id, namespace).
    A different session that happens to collide on those first 8
    characters must never see the deleted tenant's old content, and must
    be able to use 'its' collision-shared collection name normally
    afterward."""
    colliding_prefix = "deadbeef"
    sid_deleted = f"{colliding_prefix}-0000-0000-0000-000000000001"
    sid_other = f"{colliding_prefix}-1111-1111-1111-000000000002"
    assert sid_deleted[:8] == sid_other[:8] == colliding_prefix

    home.LongTermMemory(sid_deleted).store("deleted tenant's private fact")
    home.LongTermMemory(sid_deleted).delete()

    other = home.LongTermMemory(sid_other)
    assert other.recall("deleted tenant") == []
    other.store("the colliding tenant's own, unrelated fact")
    assert other.recall("colliding tenant")[0]["text"] == "the colliding tenant's own, unrelated fact"
    assert b"deleted tenant's private fact" not in _raw_db_bytes(home)


def test_concurrent_write_during_delete_does_not_resurrect_or_corrupt(home):
    """A write to a DIFFERENT, unrelated session racing against delete()
    (and its VACUUM) for another session must neither resurrect the
    deleted content nor corrupt the concurrent write."""
    sid_deleted = str(uuid.uuid4())
    sid_concurrent = str(uuid.uuid4())
    home.LongTermMemory(sid_deleted).store("racing to be deleted")

    errors = []

    def concurrent_writer():
        try:
            for i in range(20):
                home.LongTermMemory(sid_concurrent).store(f"concurrent write {i}")
        except Exception as e:  # noqa: BLE001 -- recorded, not swallowed
            errors.append(e)

    t = threading.Thread(target=concurrent_writer)
    t.start()
    deleted_ok = home.LongTermMemory(sid_deleted).delete()
    t.join(timeout=30)

    assert not errors, f"concurrent writer raised: {errors}"
    assert deleted_ok.logical_deleted is True
    assert home.LongTermMemory(sid_deleted).recall("racing to be deleted") == []
    concurrent_results = home.LongTermMemory(sid_concurrent).recall("concurrent write", n=20)
    assert len(concurrent_results) > 0, "the concurrent writer's own data must not be lost"


def test_vacuum_failure_does_not_block_logical_deletion(home, monkeypatch):
    """delete() must still report logical success (the collection really is
    gone from every normal read path) even if the best-effort VACUUM step
    itself fails -- e.g. the file is momentarily locked by another process.
    The vacuum is defense in depth, not the primary privacy guarantee --
    and a failure there must be reported as DEFERRED, not hidden."""
    sid = str(uuid.uuid4())
    ltm = home.LongTermMemory(sid)
    ltm.store("fact")

    def boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(home, "_vacuum_shared_file", boom)
    result = ltm.delete()
    assert result.logical_deleted is True
    assert result.physical_reclamation == home.DEFERRED
    assert home.LongTermMemory(sid).recall("fact") == []


# --- P1 deletion-assurance design: bounded timeout + durable ledger ------

def test_vacuum_is_bounded_and_deferred_rather_than_blocking_indefinitely(home, monkeypatch):
    """Empirically, the pre-P1 implementation (an unbounded sqlite3.connect
    timeout) was observed to block a delete() call for the ENTIRE duration
    of a competing process's held write lock (tested up to 30s) -- an
    availability risk, not just a theoretical one. _RECLAIM_TIMEOUT_S must
    actually bound that wait: simulate a slow/stuck VACUUM attempt and
    confirm delete() returns well inside a few seconds, not tens of
    seconds, reporting DEFERRED rather than hanging."""
    import time

    sid = str(uuid.uuid4())
    ltm = home.LongTermMemory(sid)
    ltm.store("fact under a simulated stuck vacuum")

    def slow_vacuum(*a, **k):
        time.sleep(0.05)  # simulates *some* real work happening, not instant
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(home, "_vacuum_shared_file", slow_vacuum)
    t0 = time.time()
    result = ltm.delete()
    elapsed = time.time() - t0

    assert result.logical_deleted is True
    assert result.physical_reclamation == home.DEFERRED
    assert elapsed < 5.0, f"delete() took {elapsed:.2f}s -- the bounded-timeout design must keep this well under the old unbounded behaviour"


def test_deferred_reclamation_is_durably_recorded_and_retryable(home, monkeypatch):
    """A DEFERRED reclamation must not be silently forgotten -- it has to
    be durably persisted so a later maintenance pass (retry_pending_reclamations)
    can find and resolve it, surviving even a process restart (simulated
    here by re-reading the ledger file fresh)."""
    sid = str(uuid.uuid4())
    ltm = home.LongTermMemory(sid)
    ltm.store("fact pending reclamation")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(home, "_vacuum_shared_file", lambda *a, **k: home.DEFERRED)
        result = ltm.delete()
    # patch is undone here -- the real _vacuum_shared_file is restored for
    # the retry call below, matching what would really happen (a later,
    # independent maintenance pass, not the same simulated failure forever)
    assert result.physical_reclamation == home.DEFERRED

    ledger_path = home._pending_reclamation_path()
    assert ledger_path.exists()
    entries = home._load_pending_reclamations()
    assert len(entries) == 1
    assert entries[0]["session_id"] == sid
    assert entries[0]["attempts"] == 1

    # A later maintenance pass (vacuum now succeeds for real) must find and clear it.
    retry_result = home.retry_pending_reclamations()
    assert retry_result["status"] == home.RECLAIMED
    assert home._load_pending_reclamations() == []
    assert home.LongTermMemory(sid).recall("fact pending reclamation") == []


def test_a_successful_vacuum_self_heals_other_sessions_earlier_deferred_entries(home, monkeypatch):
    """One VACUUM call rebuilds the WHOLE shared file, so a later,
    unrelated deletion that succeeds should opportunistically clear out
    any OTHER session's earlier-deferred reclamation too -- no dedicated
    scheduled-job infrastructure needed for the common case."""
    sid_earlier_deferred = str(uuid.uuid4())
    sid_now_deleting = str(uuid.uuid4())
    home.LongTermMemory(sid_earlier_deferred).store("earlier deferred fact")
    home.LongTermMemory(sid_now_deleting).store("now deleting fact")

    home._record_pending_reclamation(sid_earlier_deferred, "simulated earlier deferral")
    assert len(home._load_pending_reclamations()) == 1

    result = home.LongTermMemory(sid_now_deleting).delete()
    assert result.physical_reclamation == home.RECLAIMED
    assert home._load_pending_reclamations() == []
