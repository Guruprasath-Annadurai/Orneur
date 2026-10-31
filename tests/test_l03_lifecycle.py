"""L03 Phase D/E -- deletion, ownership and retrieval-authority adversarial scenarios against REAL chromadb, in both transports (``embedded`` and the supervised ``service``).

Nothing is mocked on the integration path: collections are real, tombstones are the real conversation-deletion records, the owner process is a real process. Where a fault must be
injected (a stalled embedder, an unreachable vector service) it is injected at the narrowest seam and the assertion is on the user-visible / data-visible outcome.
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pytest

from orca import vectorstore as V
from orca.brain import memory as M
from orca.docs import store as ds
from orca.serve import conversations, deletions

assert V.available(), "chromadb is required for the L03 lifecycle tests"
CANARY = "L03-LIFECYCLE-CANARY-"


@pytest.fixture(params=["embedded", "service"])
def v(request, monkeypatch):
    home = Path(tempfile.mkdtemp(prefix="l03l-", dir="/tmp"))
    for sub in ("memory", "memory/conversations", "docs"):
        (home / sub).mkdir()
    monkeypatch.setattr(M, "MEMORY_DIR", home / "memory")
    monkeypatch.setattr(ds, "DOCS_DIR", home / "docs")
    monkeypatch.setattr(ds, "_REGISTRY_FILE", home / "docs" / "registry.json")
    monkeypatch.setattr(conversations, "_dir", lambda: home / "memory" / "conversations")
    conversations._SCHEMA_READY.clear()
    monkeypatch.setattr(V, "_home", lambda: home)
    monkeypatch.setenv("ORNEUR_VECTOR_MODE", request.param)
    monkeypatch.setenv("ORNEUR_VECTOR_DEADLINE_S", "3")
    V.reset_for_tests()
    t = V.transport()
    if hasattr(t, "owner_env"):
        t.owner_env = {"ORNEUR_VECTOR_IDLE_EXIT_S": "120"}
    yield type("W", (), {"home": home, "mode": request.param, "t": t, "mem": home / "memory" / "vectors", "docs": home / "docs" / "vectors"})()
    try:
        if hasattr(t, "kill_owner"):
            t.kill_owner()
    except Exception:
        pass
    V.reset_for_tests()


def _bytes(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file())


def _collections(root: Path) -> list[str]:
    return V.Store(root).list_collections()


def _register(sid, doc_id, name="f.txt"):
    ds.register_doc(sid, {"doc_id": doc_id, "filename": name, "chunk_count": 1, "state": "ready"}) if hasattr(ds, "register_doc") else None


def _doc_session(sid, text, doc_id=None):
    """A DocStore with one registered, indexed document."""
    from orca.docs.chunker import Chunk  # noqa: F401  (import check only)

    doc_id = doc_id or uuid.uuid4().hex
    st = ds.DocStore(sid, enforce_registry=True)
    chunk = type("C", (), {"text": text, "chunk_idx": 0, "to_metadata": lambda self: {"doc_id": doc_id, "filename": "f.txt", "chunk_idx": 0}})()
    assert st.add_chunks([chunk], doc_id, "f.txt") == 1
    reg = ds._load_registry()
    reg.setdefault(sid, []).append({"doc_id": doc_id, "filename": "f.txt", "chunk_count": 1, "state": "ready", "sha256": uuid.uuid4().hex})
    ds._save_registry(reg)
    return st, doc_id


# ── D1 / D4 / D6: deletion while in use; crash after revocation; leftovers after restart ───────────────────────────────────────

def test_a_deleted_conversation_is_not_retrievable_through_a_cached_handle_and_a_stale_write_cannot_recreate_the_collection(v):
    sid = str(uuid.uuid4())
    ltm = M.LongTermMemory(sid)
    ltm.store(CANARY + "memory fact", strict=True)
    assert ltm.recall("memory fact", strict=True)
    st, _ = _doc_session(sid, CANARY + "document text about turbines")
    assert st.retrieve("turbines")
    deletions.begin(sid, "u1")
    res = deletions.run(sid, "u1")
    assert res["state"] == "complete" and res["deleted"] is True
    # the instances were built BEFORE the deletion and are still referenced by an in-flight request
    assert ltm.recall("memory fact") == [] and st.retrieve("turbines") == []
    ltm.store("late write from a request that started before the deletion")          # must neither raise into the caller nor re-create anything
    assert not any(n.startswith("orca_") for n in _collections(v.mem)), _collections(v.mem)
    assert CANARY.encode() not in _bytes(v.mem) + _bytes(v.docs)


def test_a_crash_after_access_revocation_but_before_cleanup_leaves_data_unreachable_and_the_sweep_finishes_it(v):
    sid = str(uuid.uuid4())
    M.LongTermMemory(sid).store(CANARY + "to be swept", strict=True)
    assert f"orca_{sid[:8]}" in _collections(v.mem)
    deletions.begin(sid, "u1")                              # tombstone written (access revoked) ... and the worker dies before the cascade
    assert f"orca_{sid[:8]}" in _collections(v.mem), "precondition: the collection is still on disk"
    assert M.LongTermMemory(sid).recall("swept") == [], "revoked access must hold even while the bytes are still there"
    with pytest.raises(V.VectorOwnershipError):
        M.LongTermMemory(sid).recall("swept", strict=True)
    assert deletions.resume_pending() >= 1                  # the periodic / startup sweep
    assert f"orca_{sid[:8]}" not in _collections(v.mem) and deletions.get(sid)["state"] == "complete"


def test_old_vector_files_present_after_a_restart_are_unreachable_and_then_removed(v):
    """A restore / old snapshot puts a deleted conversation's collection back next to its tombstone."""
    sid = str(uuid.uuid4())
    M.LongTermMemory(sid).store(CANARY + "resurrected", strict=True)
    snap = {}
    deletions.begin(sid, "u1")
    V.reset_for_tests()                                      # "restart"
    assert M.LongTermMemory(sid).recall("resurrected") == []
    deletions.run(sid, "u1")
    assert f"orca_{sid[:8]}" not in _collections(v.mem)


# ── D2 / D7 / D10: documents ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_document_deleted_while_its_embedding_was_stalled_never_enters_a_prompt_even_if_the_late_write_lands(v):
    sid = str(uuid.uuid4())
    st, doc_id = _doc_session(sid, CANARY + "payroll figures for the Q3 reorganisation")
    assert st.retrieve("payroll")
    ds.mark_doc_deleting(sid, doc_id)                        # the user deletes; indexing of a later chunk is still stalled somewhere
    late = type("C", (), {"text": CANARY + "payroll late chunk", "chunk_idx": 1, "to_metadata": lambda self: {"doc_id": doc_id, "filename": "f.txt", "chunk_idx": 1}})()
    st.add_chunks([late], doc_id, "f.txt")                   # the stalled worker finally writes
    assert st.retrieve("payroll") == [], "a deleting document must not be retrievable"
    out = st.delete_doc_detailed(doc_id)
    assert out["ok"] is True and out["bytes"] == "RECLAIMED"
    ds.unregister_doc(sid, doc_id)
    assert st.retrieve("payroll") == []
    assert CANARY.encode() not in _bytes(v.docs), "the deleted chunks' text is still inside the shared document-vector database"


def test_a_document_deleted_after_a_snapshot_stays_out_of_retrieval_when_the_snapshot_files_come_back(v):
    import shutil

    sid = str(uuid.uuid4())
    st, doc_id = _doc_session(sid, CANARY + "confidential merger terms")
    V.reset_for_tests() if v.mode == "embedded" else None
    if v.mode == "service":
        v.t.stop_owner()
    snap = Path(tempfile.mkdtemp(prefix="snap-", dir="/tmp")) / "vectors"
    shutil.copytree(v.docs, snap)                            # an OLDER snapshot that still holds the chunk
    st2 = ds.DocStore(sid, enforce_registry=True)
    assert st2.delete_doc_detailed(doc_id)["ok"] is True
    ds.unregister_doc(sid, doc_id)
    if v.mode == "service":
        v.t.stop_owner()
    else:
        V.reset_for_tests()
    shutil.rmtree(v.docs)
    shutil.copytree(snap, v.docs)                            # restore the old files over the live vectors
    st3 = ds.DocStore(sid, enforce_registry=True)
    assert st3.retrieve("merger") == [], "registry authority must beat whatever the restored vector files contain"


def test_an_orphaned_chunk_and_a_chunk_of_an_unregistered_document_are_never_cited(v):
    sid = str(uuid.uuid4())
    st, doc_id = _doc_session(sid, CANARY + "legitimate chunk about solar panels")
    stray = type("C", (), {"text": CANARY + "stray chunk about solar panels", "chunk_idx": 0, "to_metadata": lambda self: {"doc_id": "not-registered", "filename": "x.txt", "chunk_idx": 0}})()
    st.add_chunks([stray], "not-registered", "x.txt")
    got = st.retrieve("solar panels", top_k=5)
    assert got and {h["doc_id"] for h in got} == {doc_id}


# ── D9: another customer's records under a colliding name ────────────────────────────────────────────────────────────────────

def test_two_conversations_sharing_a_collection_name_never_read_or_destroy_each_other(v):
    a, b = "deadbeef-1111-victim-aaaa", "deadbeef-2222-attacker-bbbb"          # same first 8 characters => same legacy collection name
    victim = M.LongTermMemory(a)
    victim.store(CANARY + "VICTIM PRIVATE forecast", strict=True)
    attacker = M.LongTermMemory(b)
    assert attacker.recall("forecast") == []                                     # refused, not served
    with pytest.raises(V.VectorOwnershipError):
        attacker.recall("forecast", strict=True)
    assert attacker.store("attacker write") == ""                                # and not written into the victim's collection
    M.LongTermMemory.delete_session(b)                                           # a deletion by the colliding conversation ...
    assert [h["text"] for h in M.LongTermMemory(a).recall("forecast")] and "VICTIM PRIVATE" in M.LongTermMemory(a).recall("forecast")[0]["text"], "... must not destroy the victim's data"
    assert M.vector_memory_counters().get("ownership_refusals", 0) >= 1


def test_a_colliding_conversation_gets_no_documents_from_the_shared_keyword_file(v):
    a, b = "cafebabe-1111-victim-aaaa", "cafebabe-2222-attacker-bbbb"
    st_a, doc_id = _doc_session(a, CANARY + "victim contract clause on liability")
    (v.home / "docs").mkdir(exist_ok=True)
    kw = ds.DOCS_DIR / f"kw_{a[:8]}.jsonl"
    kw.write_text(json.dumps({"doc_id": doc_id, "filename": "f.txt", "chunk_idx": 0, "text": CANARY + "victim contract clause on liability"}) + "\n")      # the prefix-named fallback file
    st_b = ds.DocStore(b, enforce_registry=True)
    assert st_b.degraded in (None, "ownership")
    assert st_b.retrieve("contract liability") == [], "registry authority: the colliding conversation has no such document"


# ── physical-erasure honesty ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_reclaimed_means_the_bytes_are_gone_and_deferred_means_they_may_not_be(v):
    sid, other = str(uuid.uuid4()), str(uuid.uuid4())
    M.LongTermMemory(other).store(CANARY + "KEEP", strict=True)
    M.LongTermMemory(sid).store(CANARY + "ERASE-ME", strict=True)
    r = M.LongTermMemory.delete_session(sid)
    assert r.logical_deleted is True and r.physical_reclamation == M.RECLAIMED
    assert b"ERASE-ME" not in _bytes(v.mem) and b"KEEP" in _bytes(v.mem)
    # now make the VACUUM impossible: the state must say DEFERRED, be recorded durably, be visible to operators, and the data may still be on disk
    sid2 = str(uuid.uuid4())
    M.LongTermMemory(sid2).store(CANARY + "STILL-ON-DISK", strict=True)
    import orca.brain.memory as mm

    real = mm._vacuum_shared_file
    mm._vacuum_shared_file = lambda **k: mm.DEFERRED
    try:
        r2 = M.LongTermMemory.delete_session(sid2)
    finally:
        mm._vacuum_shared_file = real
    assert r2.logical_deleted is True and r2.physical_reclamation == M.DEFERRED
    from orca.serve import ops

    assert ops.backlog_report()["vector_reclamation_pending"] >= 1
    assert M.retry_pending_reclamations()["status"] == M.RECLAIMED and ops.backlog_report()["vector_reclamation_pending"] == 0


def test_repeated_cleanup_failure_is_never_reported_as_deleted_and_stays_visible_until_it_heals(v, monkeypatch):
    sid = str(uuid.uuid4())
    M.LongTermMemory(sid).store(CANARY + "stubborn", strict=True)
    real = V.Store.delete_collection
    state = {"down": True}

    def flaky(self, name, deadline_s=None, binding=None):
        if state["down"]:
            raise V.VectorUnavailable("injected outage")
        return real(self, name, deadline_s, binding)

    monkeypatch.setattr(V.Store, "delete_collection", flaky)
    deletions.begin(sid, "u1")
    for _ in range(3):
        view = deletions.run(sid, "u1")
        assert view["deleted"] is False and view["state"] == "partial" and view["retryable"] is True and view["access_revoked"] is True
    from orca.serve import ops

    assert ops.backlog_report()["conversation_deletions_incomplete"], "the operator can see it"
    assert M.LongTermMemory(sid).recall("stubborn") == [], "revoked while cleanup keeps failing"
    state["down"] = False
    assert deletions.resume_pending() >= 1 and deletions.get(sid)["state"] == "complete"
    assert f"orca_{sid[:8]}" not in _collections(v.mem)


def test_deletion_state_separates_collection_removed_from_bytes_reclaimed(v):
    sid = str(uuid.uuid4())
    M.LongTermMemory(sid).store(CANARY + "x", strict=True)
    deletions.begin(sid, "u1")
    view = deletions.run(sid, "u1")
    assert view["stores"]["_vector_collection"] == "removed" and view["stores"]["_vector_physical_reclamation"] in (M.RECLAIMED, M.DEFERRED)


# ── two workers deleting the same conversation ───────────────────────────────────────────────────────────────────────────────

def test_two_workers_deleting_the_same_conversation_converge_on_one_complete_deletion(v):
    sid = str(uuid.uuid4())
    M.LongTermMemory(sid).store(CANARY + "twice", strict=True)
    deletions.begin(sid, "u1")
    out = []
    ths = [threading.Thread(target=lambda: out.append(deletions.run(sid, "u1"))) for _ in range(4)]
    [t.start() for t in ths]
    [t.join(60) for t in ths]
    assert deletions.get(sid)["state"] == "complete" and f"orca_{sid[:8]}" not in _collections(v.mem)
    assert all(o["access_revoked"] for o in out)


def test_a_rebuild_interrupted_between_dropping_the_old_collection_and_renaming_the_copy_loses_nothing(v):
    """The one window in the per-document erasure: the old collection is gone and the verified copy still carries the temporary name. The next open completes the rename."""
    sid = str(uuid.uuid4())
    st, doc_a = _doc_session(sid, CANARY + "kept document about turbines")
    doc_b = uuid.uuid4().hex
    c = type("C", (), {"text": CANARY + "document to erase about payroll", "chunk_idx": 0, "to_metadata": lambda self: {"doc_id": doc_b, "filename": "g.txt", "chunk_idx": 0}})()
    st.add_chunks([c], doc_b, "g.txt")
    from orca.vectorstore import host as vhost

    name = f"docs_{sid[:12].replace('-', '')}"
    if v.mode == "service":
        v.t.stop_owner()
    V.reset_for_tests()
    h = vhost.ChromaHost()
    real_exec = h._rebuild_without

    class Boom(Exception):
        pass

    client = h._client(h._store(str(v.docs)))
    real_delete = client.delete_collection

    def crash_after_drop(name_arg=None, **kw):
        real_delete(name=kw.get("name", name_arg))
        if kw.get("name", name_arg) == name:
            raise Boom("killed between drop and rename")

    client.delete_collection = crash_after_drop
    with pytest.raises(Boom):
        h.execute({"op": "rebuild_without", "root": str(v.docs), "collection": name, "key": "doc_id", "value": doc_b})
    client.delete_collection = real_delete
    names = {c.name for c in client.list_collections()}
    assert name not in names and name + "__rebuild" in names, "precondition: the window was reproduced"
    h.close()
    V.reset_for_tests()
    again = ds.DocStore(sid, enforce_registry=True)                      # opening the conversation again completes the rename
    assert [hit["doc_id"] for hit in again.retrieve("turbines")] == [doc_a]
    assert name in _collections(v.docs) and name + "__rebuild" not in _collections(v.docs)
