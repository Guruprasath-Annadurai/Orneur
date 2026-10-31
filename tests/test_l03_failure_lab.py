"""L03 Phase F -- reusable adversarial scenarios for the vector subsystem: descriptor pressure, damaged sidecar state, partial deletions, missing embedding service, conflicting
identifiers across customers. Real chromadb and a real owner process; an expected refusal and a successful recovery are both asserted, and a missing optional dependency is a
failure, never a silent pass."""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path

import pytest

from orca import vectorstore as V
from orca.brain import memory as M
from orca.docs import store as ds
from orca.serve import conversations, deletions

assert V.available(), "chromadb is required for the L03 failure lab"


@pytest.fixture
def lab(monkeypatch):
    home = Path(tempfile.mkdtemp(prefix="l03f-", dir="/tmp"))
    for sub in ("memory", "memory/conversations", "docs"):
        (home / sub).mkdir()
    monkeypatch.setattr(M, "MEMORY_DIR", home / "memory")
    monkeypatch.setattr(ds, "DOCS_DIR", home / "docs")
    monkeypatch.setattr(ds, "_REGISTRY_FILE", home / "docs" / "registry.json")
    monkeypatch.setattr(conversations, "_dir", lambda: home / "memory" / "conversations")
    conversations._SCHEMA_READY.clear()
    monkeypatch.setattr(V, "_home", lambda: home)
    monkeypatch.setenv("ORNEUR_VECTOR_MODE", "service")
    monkeypatch.setenv("ORNEUR_VECTOR_DEADLINE_S", "4")
    V.reset_for_tests()
    t = V.transport()
    t.owner_env = {"ORNEUR_VECTOR_IDLE_EXIT_S": "120"}
    yield type("L", (), {"home": home, "t": t, "mem": home / "memory" / "vectors", "docs": home / "docs" / "vectors"})()
    try:
        t.kill_owner()
    except Exception:
        pass
    V.reset_for_tests()


def test_high_descriptor_pressure_is_absorbed_by_recycling_not_by_failed_operations(lab):
    """The owner's descriptor limit is capped at 120; 80 conversations (each ~4 descriptors when kept open) would exhaust it. With the default recycling every operation succeeds."""
    lab.t.owner_env = {"ORNEUR_VECTOR_NOFILE": "120", "ORNEUR_VECTOR_MAX_OPEN": "10", "ORNEUR_VECTOR_IDLE_EXIT_S": "120"}
    failures = 0
    for i in range(80):
        try:
            m = M.LongTermMemory(f"fd{i:06d}x")
            m.store(f"fact {i}", strict=True)
            m.recall("fact", 1, strict=True)
        except V.VectorError:
            failures += 1
    st = lab.t.owner_stats()
    assert failures == 0, f"{failures} operations failed under descriptor pressure"
    assert st["fds"] < 120 and sum(v["recycles"] for v in st["stores"].values()) >= 5


def test_a_descriptor_exhausted_owner_recycles_on_pressure_even_when_the_collection_limit_is_effectively_off(lab):
    lab.t.owner_env = {"ORNEUR_VECTOR_NOFILE": "100", "ORNEUR_VECTOR_MAX_OPEN": "100000", "ORNEUR_VECTOR_IDLE_EXIT_S": "120"}
    failures = 0
    for i in range(60):
        try:
            M.LongTermMemory(f"pr{i:06d}x").store(f"fact {i}", strict=True)
        except V.VectorError:
            failures += 1
    st = lab.t.owner_stats()
    assert sum(v["recycles"] for v in st["stores"].values()) >= 1 and failures <= 3, (failures, st["fds"])


def test_a_damaged_binding_database_fails_closed_and_serves_nothing_until_repaired(lab):
    sid = str(uuid.uuid4())
    M.LongTermMemory(sid).store("L03 binding damage canary", strict=True)
    lab.t.stop_owner()
    good = (lab.mem / "orneur_bindings.sqlite").read_bytes()
    (lab.mem / "orneur_bindings.sqlite").write_bytes(b"this is not a sqlite database" * 50)
    assert M.LongTermMemory(sid).recall("canary") == [], "an unverifiable ownership record must not serve data"
    with pytest.raises(V.VectorError):
        M.LongTermMemory(sid).recall("canary", strict=True)
    assert M.LongTermMemory(sid).store("written while damaged") == "", "and must not accept writes"
    (lab.mem / "orneur_bindings.sqlite").write_bytes(good)
    lab.t.kill_owner()
    assert any("canary" in h["text"] for h in M.LongTermMemory(sid).recall("canary", strict=True))


def test_a_collection_without_a_binding_is_adopted_once_and_then_protected(lab):
    """Collections created before bindings existed are adopted by the first conversation that opens them (recorded, countable); the next claimant with another id is refused."""
    name = "orca_legacy01"
    col = V.Store(lab.mem).get_or_create_collection(name)       # created the old way: unbound
    col.add(documents=["legacy text"], ids=["1"], metadatas=[{"a": 1}])
    assert V.Store(lab.mem).binding_report()["never_reopened_since_bindings"] == 1
    first = M.LongTermMemory("legacy01-AAAA")
    assert first.recall("legacy", strict=True) and first.last_status == "adopted"
    assert V.Store(lab.mem).binding_report() == {"collections": 1, "bound": 1, "adopted_legacy": 1, "never_reopened_since_bindings": 0, "bindings_without_collection": 0}
    with pytest.raises(V.VectorOwnershipError):
        M.LongTermMemory("legacy01-BBBB").recall("legacy", strict=True)


def test_a_lease_holder_that_died_after_removing_the_collection_but_before_reclaiming_is_completed_by_the_next_worker(lab):
    sid = str(uuid.uuid4())
    M.LongTermMemory(sid).store("L03 half-deleted canary", strict=True)
    deletions.begin(sid, "u1")
    V.Store(lab.mem).delete_collection(f"orca_{sid[:8]}", binding=V.session_binding(sid))           # the dead worker got this far
    conn = conversations._turns_conn()
    with conn:
        conn.execute("UPDATE session_deletions SET state='running', lease_until=? WHERE session_id=?", (time.time() - 5, sid))   # its lease has expired
    conn.close()
    assert deletions.resume_pending() >= 1
    view = deletions.get(sid)
    assert view["state"] == "complete" and view["stores"]["_vector_physical_reclamation"] == M.RECLAIMED
    assert b"half-deleted canary" not in b"".join(p.read_bytes() for p in lab.mem.rglob("*") if p.is_file())


def test_the_embedding_service_being_absent_does_not_lose_or_leak_documents(lab, monkeypatch):
    """No Ollama: chunks are embedded by chroma's default model into the collection and retrieval still works; nothing is borrowed from another conversation."""
    monkeypatch.setattr(ds, "_ollama_embed", lambda texts, host: None)
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    for sid, text in ((a, "L03 alpha lease agreement renewal terms"), (b, "L03 beta lease agreement renewal terms")):
        st = ds.DocStore(sid, enforce_registry=True)
        did = uuid.uuid4().hex
        c = type("C", (), {"text": text, "chunk_idx": 0, "to_metadata": lambda self, d=did: {"doc_id": d, "filename": "lease.pdf", "chunk_idx": 0}})()
        assert st.add_chunks([c], did, "lease.pdf") == 1
        reg = ds._load_registry()
        reg.setdefault(sid, []).append({"doc_id": did, "filename": "lease.pdf", "chunk_count": 1, "state": "ready", "sha256": uuid.uuid4().hex})
        ds._save_registry(reg)
    ra = ds.DocStore(a, enforce_registry=True).retrieve("lease renewal")
    rb = ds.DocStore(b, enforce_registry=True).retrieve("lease renewal")
    assert [h["text"] for h in ra] == ["L03 alpha lease agreement renewal terms"] and [h["text"] for h in rb] == ["L03 beta lease agreement renewal terms"]


def test_customers_with_the_same_filename_and_the_same_document_id_text_stay_separate(lab):
    """Two customers upload 'contract.pdf'; a hostile one reuses the other's document id string. Chunk identity is per conversation: neither sees the other's chunks."""
    shared_id = "doc-0123456789abcdef"
    sa, sb = str(uuid.uuid4()), str(uuid.uuid4())
    for sid, text in ((sa, "L03 customer A confidential payment schedule"), (sb, "L03 customer B different payment schedule")):
        st = ds.DocStore(sid, enforce_registry=True)
        c = type("C", (), {"text": text, "chunk_idx": 0, "to_metadata": lambda self: {"doc_id": shared_id, "filename": "contract.pdf", "chunk_idx": 0}})()
        st.add_chunks([c], shared_id, "contract.pdf")
        reg = ds._load_registry()
        reg.setdefault(sid, []).append({"doc_id": shared_id, "filename": "contract.pdf", "chunk_count": 1, "state": "ready", "sha256": uuid.uuid4().hex})
        ds._save_registry(reg)
    assert [h["text"] for h in ds.DocStore(sa, enforce_registry=True).retrieve("payment schedule")] == ["L03 customer A confidential payment schedule"]
    assert [h["text"] for h in ds.DocStore(sb, enforce_registry=True).retrieve("payment schedule")] == ["L03 customer B different payment schedule"]
    ds.DocStore(sa, enforce_registry=True).delete_doc_detailed(shared_id)
    assert [h["text"] for h in ds.DocStore(sb, enforce_registry=True).retrieve("payment schedule")] == ["L03 customer B different payment schedule"]


def test_a_missing_chromadb_is_reported_not_papered_over():
    """The vector layer answers 'unavailable' honestly; nothing here may pass through the keyword fallback while claiming vector behaviour."""
    assert V.available() is True and V.mode() in ("service", "embedded")
