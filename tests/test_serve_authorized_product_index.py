"""G9: authenticated product requests go through AuthorizedIndex.

These tests do not train a model, do not call a live neural encoder, and
do not edit Claude UI. FakeOllama is a routing double, not a model claim.
"""
from __future__ import annotations

import json

import pytest

from orca.serve.authorized_product_index import (
    ProductRetrievalDenied,
    admit_uploaded_document,
    bind,
    reset_for_tests,
    retrieve_authorized,
    revoke,
)
from orca.truth.access import AccessDenied
from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401

DOC = b"The archive key is cobalt and the retention period is ninety days."


@pytest.fixture(autouse=True)
def _reset_bindings():
    reset_for_tests()
    yield
    reset_for_tests()


def test_cross_user_index_search_is_denied(isolated_home, tmp_path, monkeypatch):
    monkeypatch.setattr("orca.config.ORCA_HOME", tmp_path / "home")
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    admit_uploaded_document("user-a", "sess-a", filename="notes.txt", text=DOC.decode(), doc_id="doc-a")
    other = bind("user-b", "sess-b")
    owner = bind("user-a", "sess-a")
    with pytest.raises(AccessDenied):
        owner.index.search(other.trusted, "cobalt")
    answer = retrieve_authorized("user-a", "sess-a", "archive key")
    assert answer.hits and "cobalt" in answer.hits[0].text
    assert answer.production_neural is False
    assert answer.tool_grant is False


def test_revoked_product_session_cannot_retrieve(isolated_home, tmp_path, monkeypatch):
    monkeypatch.setattr("orca.config.ORCA_HOME", tmp_path / "home")
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    admit_uploaded_document("user-a", "sess-a", filename="notes.txt", text=DOC.decode(), doc_id="doc-a")
    revoke("user-a", "sess-a")
    with pytest.raises(ProductRetrievalDenied):
        retrieve_authorized("user-a", "sess-a", "cobalt")


def test_unbound_authenticated_session_fails_closed(isolated_home):
    with pytest.raises(ProductRetrievalDenied, match="no authorized index"):
        retrieve_authorized("user-z", "sess-missing", "anything")


def test_chat_exercises_authorized_retrieval_and_revocation_fails_closed(client, monkeypatch):
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    with FakeOllama() as fake:
        point_orneur_at(fake, monkeypatch)
        token_a, user_a = _signup(client)
        h_a = _hdr(token_a)
        up = client.post("/api/docs/upload", files={"file": ("policy.txt", DOC, "text/plain")}, headers=h_a)
        assert up.status_code == 200, up.text
        sid = up.json()["session_id"]
        chat = client.post(
            "/api/chat",
            json={"message": "What is the archive key?", "session_id": sid},
            headers=h_a,
        )
        assert chat.status_code == 200, chat.text
        body = chat.json()
        assert body["authorized_retrieval"]["hit_count"] >= 1
        assert body["authorized_retrieval"]["production_neural"] is False
        assert body["authorized_retrieval"]["tool_grant"] is False
        assert any("cobalt" in json.dumps(q) for q in fake.requests)

        token_b, _user_b = _signup(client)
        other = client.post(
            "/api/chat",
            json={"message": "What is the archive key?", "session_id": sid},
            headers=_hdr(token_b),
        )
        assert other.status_code == 404

        revoke(user_a, sid)
        denied = client.post(
            "/api/chat",
            json={"message": "What is the archive key?", "session_id": sid},
            headers=h_a,
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == "retrieval_unauthorized"
