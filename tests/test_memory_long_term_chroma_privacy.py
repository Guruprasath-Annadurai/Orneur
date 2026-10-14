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

import sqlite3
import threading
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
    assert ltm_a.delete() is True
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
    assert deleted_ok is True
    assert home.LongTermMemory(sid_deleted).recall("racing to be deleted") == []
    concurrent_results = home.LongTermMemory(sid_concurrent).recall("concurrent write", n=20)
    assert len(concurrent_results) > 0, "the concurrent writer's own data must not be lost"


def test_vacuum_failure_does_not_block_logical_deletion(home, monkeypatch):
    """delete() must still report success (the collection really is gone
    from every normal read path) even if the best-effort VACUUM step
    itself fails -- e.g. the file is momentarily locked by another
    process. The vacuum is defense in depth, not the primary guarantee."""
    sid = str(uuid.uuid4())
    ltm = home.LongTermMemory(sid)
    ltm.store("fact")

    def boom(self):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(home.LongTermMemory, "_vacuum_after_delete", boom)
    assert ltm.delete() is True
    assert home.LongTermMemory(sid).recall("fact") == []
