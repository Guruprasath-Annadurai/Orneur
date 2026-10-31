"""L03 x L02-B6 cross-workstream comparison (run in an isolated local merge of PR #143 and the L03 branch; neither PR is modified). Records what the two designs do to each other.
Scenarios use the real encrypted backup/restore, the real deletion ledger, a real vector-service owner and real chromadb."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import pytest

from orca import vectorstore as V
from orca.brain import memory as M
from orca.serve import backup, conversations, deletions
from tests.test_l02_b6_backup import key, world  # noqa: F401

OUT = Path(os.environ.get("L03_X_OUT", "/tmp/l03_b6_integration.json"))
RES: dict = {}


@pytest.fixture
def vworld(world, monkeypatch):
    home = world.home
    monkeypatch.setattr(M, "MEMORY_DIR", home / "memory")
    monkeypatch.setattr(V, "_home", lambda: home)
    monkeypatch.setenv("ORNEUR_VECTOR_MODE", "service")
    monkeypatch.setenv("ORNEUR_VECTOR_DEADLINE_S", "5")
    V.reset_for_tests()
    t = V.transport()
    t.owner_env = {"ORNEUR_VECTOR_IDLE_EXIT_S": "300"}
    yield world
    try:
        t.kill_owner()
    except Exception:
        pass
    V.reset_for_tests()
    OUT.write_text(json.dumps(RES, indent=1))


def _vec_counts(root: Path) -> dict:
    c = sqlite3.connect(str(root / "chroma.sqlite3"))
    try:
        return {"embeddings_rows": c.execute("select count(*) from embeddings").fetchone()[0], "collections": c.execute("select count(*) from collections").fetchone()[0]}
    finally:
        c.close()


def test_X1_a_backup_taken_while_the_owner_is_writing_is_flagged_or_restorable(vworld, key, tmp_path):
    w = vworld
    sids = [str(uuid.uuid4()) for _ in range(4)]
    for s in sids:
        M.LongTermMemory(s).store("seed " + s[:6], strict=True)
    stop = threading.Event()
    wrote = [0]

    def writer():
        i = 0
        while not stop.is_set():
            try:
                M.LongTermMemory(sids[i % 4]).store(f"bulk {i} " * 30)
                wrote[0] += 1
            except Exception:
                pass
            i += 1

    th = threading.Thread(target=writer, daemon=True)
    th.start()
    time.sleep(1.0)
    out = tmp_path / "bk.orbk"
    made = backup.create(w.home, out, key=key)
    stop.set()
    th.join(10)
    RES["X1_backup"] = {"files": made["files"], "consistent_flag": made["consistent"], "unstable_files": made["unstable_files"], "writes_during": wrote[0]}
    fresh = tmp_path / "restored"
    r = backup.restore(out, fresh, key=key, unsafe_without_deletion_history=True, allow_inconsistent=True)
    root = fresh / "memory" / "vectors"
    info = {"restored_files": r["restored_files"], "sqlite_counts": _vec_counts(root)}
    # open the restored vector store with a fresh engine and check every collection answers
    code_ok = True
    try:
        V.reset_for_tests()
        V._home = lambda: fresh
        t2 = V.transport()
        t2.owner_env = {"ORNEUR_VECTOR_IDLE_EXIT_S": "60"}
        st = V.Store(root)
        names = st.list_collections()
        counts = {}
        for n in names:
            col = V.Collection(root, n)
            counts[n] = col.count()
            col.query(query_texts=["seed"], n_results=1)
        info["collections_answering"] = len(names)
        info["counts"] = counts
        t2.kill_owner()
    except Exception as exc:
        code_ok = False
        info["restored_store_error"] = type(exc).__name__
    RES["X1_restore"] = info
    assert code_ok, info


def test_X2_restoring_over_a_live_directory_while_the_owner_is_running(vworld, key, tmp_path):
    w = vworld
    sid_keep, sid_gone = str(uuid.uuid4()), str(uuid.uuid4())
    M.LongTermMemory(sid_keep).store("keep this", strict=True)
    M.LongTermMemory(sid_gone).store("L03X-ERASE-ME-AFTER-BACKUP", strict=True)
    out = tmp_path / "bk.orbk"
    backup.create(w.home, out, key=key)
    deletions.begin(sid_gone, "u1")
    deletions.run(sid_gone, "u1")
    owner_before = V.transport().owner_pid()
    # B6's restore refuses while a SERVER holds the directory; the vector owner is not a server and holds no such lock
    err = None
    try:
        r = backup.restore(out, w.home, key=key, overwrite=True)
    except Exception as exc:
        err = type(exc).__name__
        r = None
    after = {"restore_error": err, "owner_pid_before": owner_before, "owner_alive_after_restore": V.transport().owner_pid() == owner_before}
    # what does the still-running owner see now?
    try:
        n = V.Collection(w.home / "memory" / "vectors", f"orca_{sid_keep[:8]}").count()
        after["owner_view_keep"] = n
    except Exception as exc:
        after["owner_view_keep"] = type(exc).__name__
    try:
        after["owner_view_deleted_collection_count"] = V.Collection(w.home / "memory" / "vectors", f"orca_{sid_gone[:8]}").count()
    except Exception as exc:
        after["owner_view_deleted_collection_count"] = type(exc).__name__
    RES["X2_running_owner"] = after


def test_X3_with_the_owner_stopped_first_a_restored_deleted_conversation_stays_unreachable_and_is_then_physically_removed(vworld, key, tmp_path):
    w = vworld
    sid_keep, sid_gone = str(uuid.uuid4()), str(uuid.uuid4())
    M.LongTermMemory(sid_keep).store("keep this", strict=True)
    M.LongTermMemory(sid_gone).store("L03X-ERASE-ME-AFTER-BACKUP", strict=True)
    out = tmp_path / "bk.orbk"
    backup.create(w.home, out, key=key)
    deletions.begin(sid_gone, "u1")
    deletions.run(sid_gone, "u1")
    V.transport().stop_owner()                                   # the integration requirement: the vector owner must not be running during a restore
    r = backup.restore(out, w.home, key=key, overwrite=True)
    V.reset_for_tests()
    reach = M.LongTermMemory(sid_gone).recall("ERASE")
    names_before = V.Store(w.home / "memory" / "vectors").list_collections()
    swept = deletions.resume_pending()
    names_after = V.Store(w.home / "memory" / "vectors").list_collections()
    raw = b"".join(p.read_bytes() for p in (w.home / "memory" / "vectors").rglob("*") if p.is_file())
    RES["X3_restore_after_stop"] = {"history_sources": r["deletion_history_sources"], "tombstone_applied": r["deletions_applied"], "recall_of_deleted_after_restore": reach,
                                    "collection_present_right_after_restore": f"orca_{sid_gone[:8]}" in names_before, "swept": swept,
                                    "collection_present_after_sweep": f"orca_{sid_gone[:8]}" in names_after, "deleted_text_on_disk_after_sweep": b"ERASE-ME-AFTER-BACKUP" in raw,
                                    "kept_conversation_recall_hits": len(M.LongTermMemory(sid_keep).recall("keep"))}
    assert reach == [] and f"orca_{sid_gone[:8]}" not in names_after and b"ERASE-ME-AFTER-BACKUP" not in raw


def test_X4_the_binding_sidecar_and_pending_ledger_travel_with_the_backup(vworld, key, tmp_path):
    w = vworld
    sid = str(uuid.uuid4())
    M.LongTermMemory(sid).store("bound", strict=True)
    out = tmp_path / "bk.orbk"
    backup.create(w.home, out, key=key)
    stage = tmp_path / "stage"
    manifest = backup._extract(out, key, stage)
    names = sorted(k for k in manifest["files"] if "vectors" in k and "/" not in k.split("vectors/", 1)[1])
    RES["X4_archive_vector_top_level_files"] = names
    assert "memory/vectors/orneur_bindings.sqlite" in manifest["files"] and "memory/vectors/chroma.sqlite3" in manifest["files"]


def test_X5_proposed_integration_the_owner_holds_the_serving_lock_so_a_restore_refuses_until_it_is_stopped(vworld, key, tmp_path):
    w = vworld
    M.LongTermMemory(str(uuid.uuid4())).store("x", strict=True)
    out = tmp_path / "bk.orbk"
    backup.create(w.home, out, key=key)
    refused = None
    try:
        backup.restore(out, w.home, key=key, overwrite=True)
    except backup.RestoreFailed as exc:
        refused = str(exc)
    V.transport().stop_owner()
    ok = backup.restore(out, w.home, key=key, overwrite=True)
    RES["X5_with_owner_holding_serving_lock"] = {"restore_while_owner_running": refused, "restore_after_owner_stopped": bool(ok["verified"])}
    assert refused and "server is running" in refused and ok["verified"]
