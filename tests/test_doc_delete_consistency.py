"""A deleted attachment must leave both the vector store and the keyword fallback."""
from __future__ import annotations

import json

from orca.docs.store import DocStore


class _Collection:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deleted = []

    def delete(self, where):
        if self.fail:
            raise RuntimeError("collection unavailable")
        self.deleted.append(where)

    def query(self, **_kwargs):
        raise RuntimeError("collection query unavailable")

    def count(self):
        raise RuntimeError("collection count unavailable")


def _store(tmp_path, *, fail: bool = False) -> DocStore:
    store = DocStore.__new__(DocStore)
    store.session_id = "session-1"
    store._collection = _Collection(fail=fail)
    store._fallback_file = tmp_path / "kw.jsonl"
    store._use_embeddings = False
    store._chroma = None
    store._col_name = "docs_test"
    store._fallback_file.write_text(
        json.dumps({
            "doc_id": "d1",
            "filename": "secret.txt",
            "chunk_idx": 0,
            "text": "secret attachment body",
        }) + "\n"
    )
    return store


def test_delete_purges_fallback_text_when_the_collection_delete_returns(tmp_path):
    store = _store(tmp_path)
    assert store.retrieve("secret")[0]["text"] == "secret attachment body"
    assert store.delete_doc("d1") is True
    assert store.retrieve("secret") == []
    assert "secret attachment body" not in store._fallback_file.read_text()


def test_collection_failure_keeps_the_fallback_and_reports_failure(tmp_path):
    store = _store(tmp_path, fail=True)
    assert store.delete_doc("d1") is False
    assert "secret attachment body" in store._fallback_file.read_text()
    assert store.retrieve("secret")[0]["text"] == "secret attachment body"
