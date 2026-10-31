"""L02-02: a document must stay retrievable whichever embedding mode the store happens to come up in.

Baseline defect (9cb864c): ``DocStore._use_embeddings`` was decided once per instance by whether the embedding service answered at that moment. A conversation whose
chunks were embedded with the default embedder (service down at upload) and later opened with the service up (or the reverse) sent a query vector of a different
dimension to the same collection; the resulting error was swallowed and the retrieval returned NOTHING - the documents silently vanished.
"""
from __future__ import annotations

import uuid

import pytest

from orca.docs import store as store_mod
from orca.docs.chunker import chunk_text
from orca.docs.store import DocStore, register_doc


def _embed_768(texts, host=None):
    return [[(hash((t, i)) % 1000) / 1000.0 for i in range(768)] for t in texts]


def _add(st, sid, doc_id, text, name="f.txt"):
    ch = chunk_text(text, doc_id=doc_id, filename=name)
    assert st.add_chunks(ch, doc_id, name) >= 1
    register_doc(sid, doc_id, name, len(ch), len(text))


@pytest.fixture
def sid(isolated_home):
    return str(uuid.uuid4())


def test_chunks_embedded_without_the_service_remain_retrievable_when_it_comes_back(sid, monkeypatch):
    monkeypatch.setattr(store_mod, "_ollama_embed", lambda texts, host=None: None)                    # embedding service down at upload time
    a = DocStore(sid, enforce_registry=True)
    assert a._use_embeddings is False
    _add(a, sid, "d1", "Alpha quarterly report: revenue grew twelve percent.")
    monkeypatch.setattr(store_mod, "_ollama_embed", _embed_768)                                         # ... and up at the next session start
    b = DocStore(sid, enforce_registry=True)
    hits = b.retrieve("alpha quarterly report revenue")
    assert hits and hits[0]["doc_id"] == "d1", "documents embedded in one mode vanished when the store came up in the other"


def test_chunks_embedded_with_the_service_remain_retrievable_when_it_is_down(sid, monkeypatch):
    monkeypatch.setattr(store_mod, "_ollama_embed", _embed_768)
    a = DocStore(sid, enforce_registry=True)
    assert a._use_embeddings is True
    _add(a, sid, "d1", "Beta incident review: the outage lasted forty minutes.")
    monkeypatch.setattr(store_mod, "_ollama_embed", lambda texts, host=None: None)
    b = DocStore(sid, enforce_registry=True)
    hits = b.retrieve("beta incident outage forty minutes")
    assert hits and hits[0]["doc_id"] == "d1"


def test_new_chunks_added_in_the_other_mode_are_also_retrievable_together_with_old_ones(sid, monkeypatch):
    monkeypatch.setattr(store_mod, "_ollama_embed", lambda texts, host=None: None)
    a = DocStore(sid, enforce_registry=True)
    _add(a, sid, "d1", "Gamma onboarding guide for new engineers and their first week.")
    monkeypatch.setattr(store_mod, "_ollama_embed", _embed_768)
    b = DocStore(sid, enforce_registry=True)
    _add(b, sid, "d2", "Delta security policy requires hardware keys for every engineer.")
    c = DocStore(sid, enforce_registry=True)
    ids = {h["doc_id"] for h in c.retrieve("engineer onboarding guide security policy hardware keys", top_k=5)}
    assert ids == {"d1", "d2"}, ids
    assert c.count() == sum(int(d["chunk_count"]) for d in store_mod.list_docs(sid))


def test_deleting_works_across_modes(sid, monkeypatch):
    monkeypatch.setattr(store_mod, "_ollama_embed", lambda texts, host=None: None)
    a = DocStore(sid, enforce_registry=True)
    _add(a, sid, "d1", "Epsilon confidential roadmap for the next quarter.")
    monkeypatch.setattr(store_mod, "_ollama_embed", _embed_768)
    b = DocStore(sid, enforce_registry=True)
    assert b.delete_doc_detailed("d1")["ok"] is True
    assert b.retrieve("epsilon confidential roadmap") == []
