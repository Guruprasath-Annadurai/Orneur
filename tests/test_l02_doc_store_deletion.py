"""L02-01 — document deletion must remove a document from EVERY retrieval path, and must not claim success it did not achieve.

Baseline defect (9cb864c, PR #112's finding still present): ``DocStore.delete_doc`` returned True as soon as the vector collection accepted the delete,
leaving the keyword-fallback copy of the text retrievable; and when the collection delete RAISED it swallowed the error, rewrote only the fallback and
still returned True while the chunks stayed in the collection.
"""
from __future__ import annotations

import json
import uuid

import pytest


class _Chunk:
    def __init__(self, text, idx):
        self.text, self.chunk_idx = text, idx
        self.doc_id = "x"
        self.filename = "f.txt"
        self.char_start, self.char_end = 0, len(text)

    def to_metadata(self):
        return {"doc_id": self.doc_id, "filename": self.filename, "chunk_idx": self.chunk_idx, "char_start": 0, "char_end": self.char_end}


@pytest.fixture
def store(isolated_home):
    from orca.docs.store import DocStore

    sid = str(uuid.uuid4())
    return DocStore(sid), sid


def _seed_both(st, doc_id, filename, text):
    """Put the same document in the vector collection AND the keyword fallback (what a collection write failure followed by a later success leaves behind)."""
    c = _Chunk(text, 0)
    c.doc_id, c.filename = doc_id, filename
    assert st.add_chunks([c], doc_id, filename) == 1
    with open(st._fallback_file, "a") as f:
        f.write(json.dumps({"doc_id": doc_id, "filename": filename, "chunk_idx": 0, "text": text}) + "\n")


def test_delete_removes_the_keyword_fallback_copy_too(store):
    st, sid = store
    _seed_both(st, "d1", "secret.txt", "PAYROLL-CANARY-4711 quarterly figures")
    _seed_both(st, "d2", "keep.txt", "UNRELATED-KEEP-9982 meeting notes")
    r = st.delete_doc_detailed("d1")
    assert r["ok"] is True
    assert st.delete_doc("d1") is True                        # idempotent
    assert "PAYROLL-CANARY-4711" not in st._fallback_file.read_text()
    assert "UNRELATED-KEEP-9982" in st._fallback_file.read_text()       # an unrelated document survives the rewrite
    assert not any("PAYROLL-CANARY-4711" in h["text"] for h in st.retrieve("PAYROLL-CANARY-4711 quarterly"))
    assert any("UNRELATED-KEEP-9982" in h["text"] for h in st.retrieve("UNRELATED-KEEP-9982 meeting"))


def test_collection_failure_is_reported_not_swallowed(store, monkeypatch):
    st, sid = store
    _seed_both(st, "d1", "secret.txt", "PAYROLL-CANARY-4711 quarterly figures")

    def boom(**kw):
        raise RuntimeError("chroma unavailable at /secret/path")

    monkeypatch.setattr(st._collection, "delete", boom)
    r = st.delete_doc_detailed("d1")
    assert r["ok"] is False and r["collection"] == "failed"
    assert st.delete_doc("d1") is False                        # must NOT claim success while chunks remain in the collection
    assert "secret/path" not in json.dumps(r)
    # the fallback copy is still removed (best effort per store) so a later collection outage cannot resurrect it
    assert "PAYROLL-CANARY-4711" not in st._fallback_file.read_text()


def test_fallback_rewrite_is_atomic_and_preserves_unparseable_lines(store):
    st, sid = store
    st._fallback_file.write_text(
        json.dumps({"doc_id": "d1", "filename": "a", "chunk_idx": 0, "text": "gone"}) + "\n"
        + "not json at all\n"
        + json.dumps({"doc_id": "d2", "filename": "b", "chunk_idx": 0, "text": "stay"}) + "\n"
    )
    assert st.delete_doc_detailed("d1")["ok"] is True
    body = st._fallback_file.read_text()
    assert "gone" not in body and "stay" in body and "not json at all" in body
    assert not list(st._fallback_file.parent.glob(st._fallback_file.name + ".*tmp*")), "no temp file left behind"


def test_api_doc_delete_keeps_the_document_listed_when_a_store_failed(isolated_home, monkeypatch):
    from fastapi.testclient import TestClient
    from orca.serve import ratelimit
    from orca.serve.api import app
    from orca.docs.store import DocStore, list_docs, register_doc

    ratelimit._local_counters.clear()
    client = TestClient(app)
    r = client.post("/api/auth/signup", json={"email": f"l02-{uuid.uuid4().hex[:10]}@example.com", "password": "correcthorsebatterystaple", "name": "T"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    sid = str(uuid.uuid4())
    assert client.get("/api/docs/list", params={"session_id": sid}, headers=h).status_code == 200
    st = DocStore(sid)
    _seed_both(st, "d1", "secret.txt", "PAYROLL-CANARY-4711 quarterly figures")
    register_doc(sid, "d1", "secret.txt", 1, 40)
    down = {"v": True}
    real = DocStore.delete_doc_detailed

    def flaky(self, doc_id):
        if down["v"]:
            return {"ok": False, "collection": "failed", "fallback": "ok"}
        return real(self, doc_id)

    monkeypatch.setattr(DocStore, "delete_doc_detailed", flaky)
    r = client.delete("/api/docs/d1", params={"session_id": sid}, headers=h)
    assert r.status_code == 202 and r.json()["deleted"] is False and r.json()["retryable"] is True
    assert [d["doc_id"] for d in list_docs(sid)] == ["d1"], "still registered so the owner can retry"
    down["v"] = False
    r = client.delete("/api/docs/d1", params={"session_id": sid}, headers=h)
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert list_docs(sid) == []
