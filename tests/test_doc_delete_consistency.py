"""Legacy fallback deletion on the combined backend.

The authorized index is a separate store. These tests do not treat a
bool from DocStore as an atomic cross-store commit.
"""
from __future__ import annotations

import json
import threading

from orca.docs.store import DocStore
from orca.serve.authorized_product_index import delete_uploaded_document
from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_b_conversations import fake  # noqa: F401
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401
from tests.test_p0_authorized_context import _upload


class _Collection:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deleted: list = []

    def delete(self, where):
        if self.fail:
            raise RuntimeError("collection unavailable")
        self.deleted.append(where)

    def query(self, **_kwargs):
        raise RuntimeError("collection query unavailable")

    def count(self):
        raise RuntimeError("collection count unavailable")


def _line(doc_id: str, text: str) -> str:
    return json.dumps({"doc_id": doc_id, "filename": f"{doc_id}.txt", "chunk_idx": 0, "text": text}) + "\n"


def _store(tmp_path, *, fail: bool = False, lines: str | None = None) -> DocStore:
    store = DocStore.__new__(DocStore)
    store.session_id = "session-1"
    store._collection = _Collection(fail=fail)
    store._fallback_file = tmp_path / "kw.jsonl"
    store._use_embeddings = False
    store._chroma = None
    store._col_name = "docs_test"
    store._fallback_file.write_text(lines if lines is not None else _line("d1", "secret attachment body"))
    return store


def test_authorized_index_delete_is_still_a_separate_function():
    assert callable(delete_uploaded_document)


def test_successful_delete_removes_the_collection_and_the_fallback(tmp_path):
    store = _store(tmp_path)
    assert store.retrieve("secret")[0]["text"] == "secret attachment body"
    assert store.delete_doc("d1") is True
    assert store.last_delete_state["atomic"] is False
    assert store.last_delete_state["collection"] == "removed"
    assert store.last_delete_state["fallback"] == "removed"
    assert store.retrieve("secret") == []
    assert "secret attachment body" not in store._fallback_file.read_text()
    assert store._collection.deleted == [{"doc_id": "d1"}]


def test_collection_failure_keeps_the_fallback(tmp_path):
    store = _store(tmp_path, fail=True)
    assert store.delete_doc("d1") is False
    assert store.last_delete_state["collection"] == "failed"
    assert store.last_delete_state["fallback"] == "unchanged"
    assert store.last_delete_state["fallback_contains"] is True
    assert "secret attachment body" in store._fallback_file.read_text()


def test_fallback_failure_reports_a_removed_collection(tmp_path):
    store = _store(tmp_path)

    def boom(_doc_id):
        raise OSError("fallback rewrite failed")

    store._purge_fallback = boom
    assert store.delete_doc("d1") is False
    assert store.last_delete_state["collection"] == "removed"
    assert store.last_delete_state["fallback"] == "failed"
    assert store.last_delete_state["complete"] is False


def test_interrupted_replace_leaves_the_original_fallback(tmp_path):
    store = _store(tmp_path)

    def stop(_tmp, _path):
        raise RuntimeError("process interrupted before replace")

    store._before_fallback_replace = stop
    assert store.delete_doc("d1") is False
    assert "secret attachment body" in store._fallback_file.read_text()
    assert store.last_delete_state["fallback"] == "failed"


def test_retry_after_a_partial_failure_is_idempotent(tmp_path):
    store = _store(tmp_path, fail=True)
    assert store.delete_doc("d1") is False
    store._collection.fail = False
    assert store.delete_doc("d1") is True
    assert store.delete_doc("d1") is True
    assert store.retrieve("secret") == []


def test_concurrent_deletes_of_different_documents_keep_both_results(tmp_path):
    store = _store(tmp_path, lines=_line("d1", "alpha secret") + _line("d2", "beta secret"))
    barrier = threading.Barrier(2)

    def worker(doc_id: str):
        barrier.wait(timeout=5)
        assert store.delete_doc(doc_id) is True

    threads = [threading.Thread(target=worker, args=(doc_id,)) for doc_id in ("d1", "d2")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    text = store._fallback_file.read_text()
    assert "alpha secret" not in text
    assert "beta secret" not in text


def test_retrieval_sees_the_document_until_the_fallback_replace(tmp_path):
    store = _store(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def pause(_tmp, _path):
        started.set()
        assert release.wait(timeout=5)

    store._before_fallback_replace = pause
    holder = threading.Thread(target=store.delete_doc, args=("d1",))
    holder.start()
    assert started.wait(timeout=5)
    assert store.retrieve("secret")[0]["text"] == "secret attachment body"
    release.set()
    holder.join(timeout=5)
    assert store.retrieve("secret") == []


def test_authorized_delete_removes_the_legacy_fallback_and_does_not_readmit(client, fake, monkeypatch):
    import orca.serve.api as api

    readmitted = []
    original = api.admit_uploaded_document

    def guarded(*args, **kwargs):
        if readmitted:
            raise AssertionError("revoked document access was restored")
        readmitted.append("admit")
        return original(*args, **kwargs)

    monkeypatch.setattr(api, "admit_uploaded_document", guarded)
    with FakeOllama() as server:
        point_orneur_at(server, monkeypatch)
        token, _user = _signup(client)
        headers = _hdr(token)
        uploaded = _upload(client, headers, "notes.txt", "archive key cobalt")
        session_id = uploaded["session_id"]
        doc_id = uploaded["doc_id"]
        store = api._sessions[session_id].doc_store
        with open(store._fallback_file, "a") as handle:
            handle.write(_line(doc_id, "secret attachment body"))
        removed = client.delete(f"/api/docs/{doc_id}", params={"session_id": session_id}, headers=headers)
    assert removed.status_code == 200, removed.text
    body = removed.json()
    assert body["deleted"] is True
    assert body["atomic"] is False
    assert body["index_removed"] >= 1
    assert readmitted == ["admit"]
    assert "secret attachment body" not in store._fallback_file.read_text()
    listed = client.get("/api/docs/list", params={"session_id": session_id}, headers=headers)
    assert listed.status_code == 200
    assert all(row.get("doc_id") != doc_id for row in listed.json()["docs"])


def test_collection_failure_after_index_delete_reports_the_partial_state(client, fake, monkeypatch):
    import orca.serve.api as api

    def fail_collection(self, doc_id):
        self.last_delete_state = {
            "complete": False,
            "atomic": False,
            "collection": "failed",
            "fallback": "unchanged",
            "fallback_contains": True,
        }
        return False

    monkeypatch.setattr(DocStore, "delete_doc", fail_collection)
    with FakeOllama() as server:
        point_orneur_at(server, monkeypatch)
        token, _user = _signup(client)
        headers = _hdr(token)
        uploaded = _upload(client, headers, "notes.txt", "archive key cobalt")
        removed = client.delete(
            f"/api/docs/{uploaded['doc_id']}",
            params={"session_id": uploaded["session_id"]},
            headers=headers,
        )
    assert removed.status_code == 500
    body = removed.json()
    assert body["code"] == "document_store_disagreement"
    assert body["atomic"] is False
    assert body["collection"] == "failed"
    assert body["fallback"] == "unchanged"
    listed = client.get("/api/docs/list", params={"session_id": uploaded["session_id"]}, headers=headers)
    assert any(row.get("doc_id") == uploaded["doc_id"] for row in listed.json()["docs"])
