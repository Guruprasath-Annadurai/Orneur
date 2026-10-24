"""P0: model context comes from the authorized index, not the legacy store.

These tests reproduce the divergence (legacy text present, authorized text
absent or abstained) and assert the legacy text never reaches planning,
inference, tool arguments, citations, or the answer.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading

import pytest

from orca.docs.chunker import Chunk
from orca.serve.authorized_product_index import (
    ProductRetrievalDenied,
    admit_uploaded_document,
    bind,
    delete_uploaded_document,
    drop_process_state_for_tests,
    reset_for_tests,
    retrieve_authorized,
    revoke,
)
from orca.truth.access import AccessDenied, SessionAuthority
from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401

POISON = "UNAUTH-POISON-9f3a"
AUTHORIZED = "The archive key is cobalt and the retention period is ninety days."


@pytest.fixture(autouse=True)
def _reset_bindings():
    reset_for_tests()
    yield
    reset_for_tests()


def _auth(client):
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    token, user_id = _signup(client)
    return token, user_id, _hdr(token)


def _upload(client, headers, filename, text, session_id=None):
    data = {"session_id": session_id} if session_id else None
    response = client.post(
        "/api/docs/upload",
        files={"file": (filename, text.encode(), "text/plain")},
        data=data,
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _poison(session_id: str, text: str = POISON) -> None:
    from orca.serve import api

    store = api._sessions[session_id].doc_store
    chunk = Chunk(text=text, doc_id="poison-doc", filename="poison.txt", chunk_idx=0, char_start=0, char_end=len(text))
    store.add_chunks([chunk], doc_id="poison-doc", filename="poison.txt")


def _requests_have(fake, needle: str) -> bool:
    return any(needle in json.dumps(payload) for payload in fake.requests)


def _capture_kernel_store(monkeypatch):
    from orca.cognitive.kernel import CognitiveKernel

    seen = []
    original = CognitiveKernel.execute

    async def wrapped(self, request, entitlement=None, doc_store=None, **kwargs):
        seen.append(doc_store)
        return await original(self, request, entitlement=entitlement, doc_store=doc_store, **kwargs)

    monkeypatch.setattr(CognitiveKernel, "execute", wrapped)
    return seen


def test_replay_rejection_drops_the_passage_before_the_prompt(client, monkeypatch):
    from orca.docs.authorized_index import AuthorizedIndex

    monkeypatch.setattr(AuthorizedIndex, "replay", lambda self, session, digest, text: False)
    with FakeOllama() as fake:
        point_orneur_at(fake, monkeypatch)
        _token, _user, headers = _auth(client)
        uploaded = _upload(client, headers, "policy.txt", AUTHORIZED)
        fake.requests.clear()
        chat = client.post(
            "/api/chat",
            json={"message": "What is the archive key?", "session_id": uploaded["session_id"]},
            headers=headers,
        )
    assert chat.status_code == 200, chat.text
    body = chat.json()
    assert body["authorized_retrieval"]["hit_count"] >= 1
    assert body["authorized_retrieval"]["prompt_passage_count"] == 0
    assert body["sources"] == []
    assert not _requests_have(fake, "cobalt")


def test_legacy_only_text_does_not_reach_the_model_or_the_kernel(client, monkeypatch):
    seen = _capture_kernel_store(monkeypatch)
    with FakeOllama() as fake:
        point_orneur_at(fake, monkeypatch)
        token, _user, headers = _auth(client)
        uploaded = _upload(client, headers, "policy.txt", AUTHORIZED)
        session_id = uploaded["session_id"]
        _poison(session_id)
        fake.requests.clear()
        chat = client.post(
            "/api/chat",
            json={"message": "What is the archive key?", "session_id": session_id},
            headers=headers,
        )
    assert chat.status_code == 200, chat.text
    body = chat.json()
    assert body["authorized_retrieval"]["prompt_passage_count"] >= 1
    assert body["authorized_retrieval"]["tool_grant"] is False
    assert body["authorized_retrieval"]["production_neural"] is False
    assert _requests_have(fake, "cobalt")
    assert not _requests_have(fake, POISON)
    assert seen and all(store is None for store in seen)
    assert all(source.get("excerpt") and POISON not in source["excerpt"] for source in body["sources"])
    assert "cobalt" in body["sources"][0]["excerpt"]
    assert body["sources"][0]["content_sha256"]
    assert body["source_summary"]["retrieval"]["tool_grant"] is False


def test_zero_authorized_hits_do_not_fall_through_to_legacy_text(client, monkeypatch):
    with FakeOllama() as fake:
        point_orneur_at(fake, monkeypatch)
        _token, _user, headers = _auth(client)
        uploaded = _upload(client, headers, "policy.txt", AUTHORIZED)
        _poison(uploaded["session_id"])
        fake.requests.clear()
        chat = client.post(
            "/api/chat",
            json={"message": "zzzzqqqq unrelated token", "session_id": uploaded["session_id"]},
            headers=headers,
        )
    assert chat.status_code == 200, chat.text
    body = chat.json()
    assert body["authorized_retrieval"]["hit_count"] == 0
    assert body["authorized_retrieval"]["prompt_passage_count"] == 0
    assert body["authorized_retrieval"]["abstained"] is False
    assert body["sources"] == []
    assert body["source_summary"]["grounding"] == "none"
    assert not _requests_have(fake, POISON)
    assert not _requests_have(fake, "cobalt")


def test_contradiction_is_not_injected_as_settled_context(client, monkeypatch):
    with FakeOllama() as fake:
        point_orneur_at(fake, monkeypatch)
        _token, _user, headers = _auth(client)
        uploaded = _upload(client, headers, "lamp.txt", "lamp=on\nlamp=off")
        _poison(uploaded["session_id"])
        fake.requests.clear()
        chat = client.post(
            "/api/chat",
            json={"message": "What is the lamp state?", "session_id": uploaded["session_id"]},
            headers=headers,
        )
    assert chat.status_code == 200, chat.text
    body = chat.json()
    assert body["authorized_retrieval"]["abstained"] is True
    assert body["authorized_retrieval"]["prompt_passage_count"] == 0
    assert body["sources"] == []
    assert body["source_summary"]["grounding"] == "none"
    assert not _requests_have(fake, "lamp=on")
    assert not _requests_have(fake, POISON)


def test_stream_does_not_send_legacy_text(client, monkeypatch):
    with FakeOllama(chunks=("ok",)) as fake:
        point_orneur_at(fake, monkeypatch)
        _token, _user, headers = _auth(client)
        uploaded = _upload(client, headers, "policy.txt", AUTHORIZED)
        _poison(uploaded["session_id"])
        fake.requests.clear()
        with client.stream(
            "POST",
            "/api/stream",
            json={"message": "What is the archive key?", "session_id": uploaded["session_id"]},
            headers=headers,
        ) as response:
            raw = "".join(response.iter_text())
    assert response.status_code == 200
    assert "cobalt" in json.dumps(fake.requests)
    assert POISON not in json.dumps(fake.requests)
    assert POISON not in raw


def test_guest_documents_still_use_the_legacy_pipeline(client, monkeypatch):
    seen = _capture_kernel_store(monkeypatch)
    with FakeOllama() as fake:
        point_orneur_at(fake, monkeypatch)
        from orca.serve import ratelimit

        ratelimit._local_counters.clear()
        uploaded = client.post(
            "/api/docs/upload",
            files={"file": ("notes.txt", b"The guest token is amber.", "text/plain")},
        )
        assert uploaded.status_code == 200, uploaded.text
        session_id = uploaded.json()["session_id"]
        chat = client.post(
            "/api/chat",
            json={"message": "What is the guest token?", "session_id": session_id, "model_variant": "nano"},
        )
    assert chat.status_code == 200, chat.text
    assert "authorized_retrieval" not in chat.json()
    assert _requests_have(fake, "amber")
    assert seen and seen[0] is not None


def test_conversations_of_one_user_do_not_share_documents(client, monkeypatch):
    with FakeOllama() as fake:
        point_orneur_at(fake, monkeypatch)
        _token, _user, headers = _auth(client)
        first = _upload(client, headers, "a.txt", "project alpha uses cobalt")
        second = _upload(client, headers, "b.txt", "project beta uses saffron")
        fake.requests.clear()
        chat = client.post(
            "/api/chat",
            json={"message": "Which project is described in the upload?", "session_id": first["session_id"]},
            headers=headers,
        )
    assert chat.status_code == 200, chat.text
    assert _requests_have(fake, "cobalt")
    assert not _requests_have(fake, "saffron")
    assert second["session_id"] != first["session_id"]


def test_restart_reopens_the_same_conversation_and_not_its_sibling(client, monkeypatch):
    with FakeOllama() as fake:
        point_orneur_at(fake, monkeypatch)
        _token, user_id, headers = _auth(client)
        first = _upload(client, headers, "a.txt", "project alpha uses cobalt")
        second = _upload(client, headers, "b.txt", "project beta uses saffron")
        _poison(first["session_id"])
        from orca.serve import api

        api._sessions.clear()
        drop_process_state_for_tests()
        fake.requests.clear()
        chat = client.post(
            "/api/chat",
            json={"message": "Which project is described in the upload?", "session_id": first["session_id"]},
            headers=headers,
        )
        assert chat.status_code == 200, chat.text
        assert _requests_have(fake, "cobalt")
        assert not _requests_have(fake, "saffron")
        assert not _requests_have(fake, POISON)
        revoke(user_id, first["session_id"])
        drop_process_state_for_tests()
        api._sessions.clear()
        denied = client.post(
            "/api/chat",
            json={"message": "Which project is described in the upload?", "session_id": first["session_id"]},
            headers=headers,
        )
    assert denied.status_code == 403
    assert denied.json()["code"] == "retrieval_unauthorized"


# These tests redirect ORCA_HOME with monkeypatch. They must not also use
# isolated_home: that fixture's temporary directory is deleted on teardown,
# and monkeypatch then writes that deleted path back onto orca.config.ORCA_HOME.
# The next first import of orca.train.cloud then fails with FileNotFoundError.
def test_stale_trusted_session_cannot_search_after_revoke(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.config.ORCA_HOME", tmp_path / "home")
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    admit_uploaded_document("user-a", "sess-a", filename="notes.txt", text=AUTHORIZED, doc_id="doc-a")
    binding = bind("user-a", "sess-a")
    stale = binding.trusted
    revoke("user-a", "sess-a")
    with pytest.raises(AccessDenied):
        binding.index.search(stale, "cobalt")
    with pytest.raises(ProductRetrievalDenied):
        retrieve_authorized("user-a", "sess-a", "cobalt")


def test_adopt_refuses_revoked_and_foreign_sessions():
    authority = SessionAuthority()
    issued = authority.issue("user:one", "one")
    authority.revoke(issued)
    with pytest.raises(AccessDenied):
        authority.adopt(issued.session_id, "user:one", "one")
    other = authority.issue("user:one", "one")
    with pytest.raises(AccessDenied):
        authority.adopt(other.session_id, "user:two", "two")
    with pytest.raises(AccessDenied):
        authority.adopt("../etc", "user:one", "one")
    again = authority.adopt(other.session_id, "user:one", "one")
    assert again.session_id == other.session_id
    assert authority.is_current(again)


def test_concurrent_admits_stay_inside_their_conversations(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.config.ORCA_HOME", tmp_path / "home")
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    errors = []

    def admit(name, text):
        try:
            admit_uploaded_document("user-a", name, filename=f"{name}.txt", text=text, doc_id=name)
        except Exception as exc:  # noqa: BLE001 — the assertion is the collected failure
            errors.append(exc)

    threads = [
        threading.Thread(target=admit, args=("sess-one", "alpha uses cobalt")),
        threading.Thread(target=admit, args=("sess-two", "beta uses saffron")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    one = retrieve_authorized("user-a", "sess-one", "cobalt")
    two = retrieve_authorized("user-a", "sess-two", "saffron")
    assert "cobalt" in one.hits[0].text and all("saffron" not in hit.text for hit in one.hits)
    assert "saffron" in two.hits[0].text and all("cobalt" not in hit.text for hit in two.hits)


def test_a_second_process_reads_only_the_bound_directory(tmp_path, monkeypatch):
    home = tmp_path / "proc-home"
    home.mkdir()
    monkeypatch.setattr("orca.config.ORCA_HOME", home)
    monkeypatch.setenv("ORCA_HOME", str(home))
    admit_uploaded_document("user-a", "sess-one", filename="a.txt", text="alpha uses cobalt", doc_id="doc-one")
    admit_uploaded_document("user-a", "sess-two", filename="b.txt", text="beta uses saffron", doc_id="doc-two")
    script = textwrap.dedent(
        """
        import os
        from orca.serve.authorized_product_index import retrieve_authorized
        one = retrieve_authorized("user-a", "sess-one", "cobalt")
        two = retrieve_authorized("user-a", "sess-two", "saffron")
        one_text = " ".join(hit.text for hit in one.hits)
        two_text = " ".join(hit.text for hit in two.hits)
        assert "cobalt" in one_text and "saffron" not in one_text
        assert "saffron" in two_text and "cobalt" not in two_text
        print("ok")
        """
    )
    env = os.environ.copy()
    env["ORCA_HOME"] = str(home)
    completed = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    assert "ok" in completed.stdout


def test_docstore_failure_after_admission_does_not_publish_the_document(client, monkeypatch):
    import orca.docs.store as store

    real = store.DocStore.add_chunks
    calls = {"n": 0}

    def wrapped(self, chunks, doc_id, filename):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("docstore commit failed")
        return real(self, chunks, doc_id=doc_id, filename=filename)

    monkeypatch.setattr(store.DocStore, "add_chunks", wrapped)
    with FakeOllama() as fake:
        point_orneur_at(fake, monkeypatch)
        _token, _user, headers = _auth(client)
        first = _upload(client, headers, "a.txt", "project alpha uses cobalt")
        failed = client.post(
            "/api/docs/upload",
            files={"file": ("b.txt", b"beta code is ZQX-SAFFRON-441", "text/plain")},
            params={"session_id": first["session_id"]},
            headers=headers,
        )
        assert failed.status_code == 500
        assert "ZQX-SAFFRON-441" not in failed.text
        fake.requests.clear()
        chat = client.post(
            "/api/chat",
            json={"message": "What is the beta code?", "session_id": first["session_id"]},
            headers=headers,
        )
    assert chat.status_code == 200, chat.text
    assert not _requests_have(fake, "ZQX-SAFFRON-441")


def test_index_delete_failure_leaves_the_legacy_copy_untouched(client, monkeypatch):
    import orca.serve.api as api

    def refuse(*_args, **_kwargs):
        raise ProductRetrievalDenied("index delete failed", code="denied")

    with FakeOllama() as fake:
        point_orneur_at(fake, monkeypatch)
        _token, _user, headers = _auth(client)
        uploaded = _upload(client, headers, "policy.txt", AUTHORIZED)
        session_id = uploaded["session_id"]
        doc_id = uploaded["doc_id"]
        before = api._sessions[session_id].doc_store.count()
        monkeypatch.setattr(api, "delete_uploaded_document", refuse)
        denied = client.delete(f"/api/docs/{doc_id}", params={"session_id": session_id}, headers=headers)
        assert denied.status_code == 403
        assert api._sessions[session_id].doc_store.count() == before
        fake.requests.clear()
        chat = client.post(
            "/api/chat",
            json={"message": "What is the archive key?", "session_id": session_id},
            headers=headers,
        )
    assert chat.status_code == 200, chat.text
    assert _requests_have(fake, "cobalt")


def test_legacy_delete_failure_after_index_delete_is_not_prompt_visible(client, monkeypatch):
    import orca.docs.store as store

    def boom(self, doc_id):
        raise RuntimeError("docstore delete failed")

    monkeypatch.setattr(store.DocStore, "delete_doc", boom)
    with FakeOllama() as fake:
        point_orneur_at(fake, monkeypatch)
        _token, _user, headers = _auth(client)
        uploaded = _upload(client, headers, "policy.txt", AUTHORIZED)
        session_id = uploaded["session_id"]
        removed = client.delete(
            f"/api/docs/{uploaded['doc_id']}",
            params={"session_id": session_id},
            headers=headers,
        )
        assert removed.status_code == 500
        fake.requests.clear()
        chat = client.post(
            "/api/chat",
            json={"message": "What is the archive key?", "session_id": session_id},
            headers=headers,
        )
    assert chat.status_code == 200, chat.text
    assert not _requests_have(fake, "cobalt")
    assert chat.json()["sources"] == []


def test_same_user_directory_is_not_scanned_for_another_conversation(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.config.ORCA_HOME", tmp_path / "home")
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    admit_uploaded_document("user-a", "sess-one", filename="a.txt", text="alpha uses cobalt", doc_id="doc-one")
    admit_uploaded_document("user-a", "sess-two", filename="b.txt", text="beta uses saffron", doc_id="doc-two")
    drop_process_state_for_tests()
    answer = retrieve_authorized("user-a", "sess-one", "cobalt")
    assert all("saffron" not in hit.text for hit in answer.hits)
    with pytest.raises(ProductRetrievalDenied, match="no authorized index"):
        retrieve_authorized("user-a", "sess-missing", "cobalt")


def test_delete_after_restart_removes_the_authorized_passage(tmp_path, monkeypatch):
    monkeypatch.setattr("orca.config.ORCA_HOME", tmp_path / "home")
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    admit_uploaded_document("user-a", "sess-a", filename="notes.txt", text=AUTHORIZED, doc_id="doc-a")
    drop_process_state_for_tests()
    removed = delete_uploaded_document("user-a", "sess-a", filename="notes.txt", doc_id="doc-a")
    assert removed >= 1
    answer = retrieve_authorized("user-a", "sess-a", "cobalt")
    assert answer.hits == ()
