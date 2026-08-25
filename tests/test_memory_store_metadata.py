"""
Tests for orca/brain/memory.py's LongTermMemory.store() metadata handling.

Covers a real production bug found via live load testing: newer chromadb
versions reject an empty metadata dict outright ("Expected metadata to be
a non-empty dict, got 0 metadata attributes in add"). Every real chat
request calls commit_to_long_term() with no explicit metadata (the normal
path via orca/serve/api.py), which crashed the entire request with a 500 —
this would have been a total production outage for every single chat
message, not an edge case.
"""
from __future__ import annotations

import pytest

from orca.brain.memory import LongTermMemory


class _FakeCollection:
    def __init__(self):
        self.add_calls = []

    def add(self, documents, ids, metadatas):
        # Mirror chromadb's real validation: reject empty metadata dicts.
        for m in metadatas:
            if not m:
                raise ValueError(
                    "Expected metadata to be a non-empty dict, got 0 metadata attributes in add."
                )
        self.add_calls.append({"documents": documents, "ids": ids, "metadatas": metadatas})


@pytest.fixture
def memory_with_fake_collection(monkeypatch):
    mem = LongTermMemory.__new__(LongTermMemory)
    mem._session_id = "test-session"
    mem._available = True
    mem._collection = _FakeCollection()
    return mem


def test_store_with_no_metadata_does_not_raise(memory_with_fake_collection):
    # This is the exact real-world call shape: commit_to_long_term(text)
    # with no metadata argument at all.
    doc_id = memory_with_fake_collection.store("Q: hello\nA: hi there")
    assert doc_id
    assert len(memory_with_fake_collection._collection.add_calls) == 1


def test_store_with_no_metadata_includes_a_timestamp(memory_with_fake_collection):
    memory_with_fake_collection.store("some text")
    stored_meta = memory_with_fake_collection._collection.add_calls[0]["metadatas"][0]
    assert stored_meta
    assert "stored_at" in stored_meta


def test_store_with_explicit_empty_dict_still_gets_a_timestamp(memory_with_fake_collection):
    memory_with_fake_collection.store("some text", metadata={})
    stored_meta = memory_with_fake_collection._collection.add_calls[0]["metadatas"][0]
    assert stored_meta
    assert "stored_at" in stored_meta


def test_store_with_real_metadata_preserves_it_and_does_not_overwrite_existing_key(memory_with_fake_collection):
    memory_with_fake_collection.store("some text", metadata={"source": "chat", "stored_at": 12345})
    stored_meta = memory_with_fake_collection._collection.add_calls[0]["metadatas"][0]
    assert stored_meta["source"] == "chat"
    assert stored_meta["stored_at"] == 12345  # caller's own timestamp wins, not overwritten


def test_store_does_not_mutate_caller_supplied_dict(memory_with_fake_collection):
    caller_dict = {"source": "chat"}
    memory_with_fake_collection.store("some text", metadata=caller_dict)
    assert caller_dict == {"source": "chat"}  # unchanged — store() must copy, not mutate in place
