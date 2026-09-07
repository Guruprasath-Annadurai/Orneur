"""
Phase 14C edge-qualification finding: `POST /api/docs/upload` returned a
real 500 through the live public edge --
`RuntimeError: No installed Ollama model found for tier 'core' ...` --
because `_Session.__init__` unconditionally resolved a chat model tier
and constructed a full brain/ContextManager/AgentLoop for EVERY new
session, even for routes (docs upload/list/delete, memory recall/
remember, knowledge graph, explain, session export) that never touch
`sess.agent`/`sess.brain`/`sess.ctx` at all. `model_runtime` being
unavailable is an expected, documented deployment state (see
`/readyz`'s `model_runtime: unavailable` classification) -- a doc-only
route hard-failing because of it was a real defect, not a fixture gap.

Fixed by making `_Session`'s brain/ctx/agent construction lazy (built
on first access via `_ensure_agent()`/properties, see `orca/serve/api.py`)
so doc-only session operations no longer depend on model-tier
resolution succeeding.

This test proves the fix holds by forcing model-tier resolution to
fail exactly the way it does in a deployment with no installed Ollama
models (`orca.serve.registry._list_installed_models` returns `[]`,
matching the real staging symptom), then confirming, all within ONE
session (deliberately -- `orca/docs/store.py`'s `DOCS_DIR` is a
module-level constant captured once at import time and isn't
re-isolated per test the way `ORCA_HOME` is via the `isolated_home`
fixture, so constructing more than one real chromadb-backed `_Session`
per test process is its own pre-existing fragility, unrelated to and
out of scope for this fix -- one shared session sidesteps it):

  1. Doc upload/list/delete, memory remember/recall, and the knowledge
     graph summary route all still work (200s) with no model installed.
  2. Chat on that SAME session still fails -- proving the fix removes
     a spurious dependency from routes that never needed the model,
     without masking the real dependency chat genuinely has.
"""
from __future__ import annotations

import io
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def no_model_runtime(monkeypatch):
    """Simulates the real staging symptom: Ollama reachable but with no
    installed models for any tier, so `resolve_tier_model()` raises
    RuntimeError exactly like it did in the live 500 this test guards
    against -- without needing a real Ollama-less environment."""
    import orca.serve.registry as registry

    monkeypatch.setattr(registry, "_list_installed_models", lambda host: [])
    monkeypatch.setattr(registry, "_tags_cache", None)


def test_doc_only_session_survives_missing_model_runtime_but_chat_still_fails(isolated_home, no_model_runtime):
    from orca.serve.api import app

    client = TestClient(app)
    email = f"phase14c-no-model-{uuid.uuid4().hex[:12]}@example.com"
    signup = client.post(
        "/api/auth/signup",
        json={"email": email, "password": "correcthorsebatterystaple", "name": "No Model Test"},
    )
    assert signup.status_code == 200, signup.text
    token = signup.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    session_id = str(uuid.uuid4())

    # -- doc upload/list/delete: none of these touch sess.agent/brain/ctx --
    files = {"file": ("doc.txt", io.BytesIO(b"no model runtime needed to store this."), "text/plain")}
    resp_upload = client.post(f"/api/docs/upload?session_id={session_id}", files=files, headers=headers)
    assert resp_upload.status_code == 200, resp_upload.text
    doc_id = resp_upload.json()["doc_id"]

    resp_list = client.get(f"/api/docs/list?session_id={session_id}", headers=headers)
    assert resp_list.status_code == 200, resp_list.text
    assert any(d["doc_id"] == doc_id for d in resp_list.json()["docs"])

    resp_del = client.delete(f"/api/docs/{doc_id}?session_id={session_id}", headers=headers)
    assert resp_del.status_code == 200, resp_del.text
    assert resp_del.json()["deleted"] is True

    # -- memory remember/recall and knowledge graph: also model-free --
    resp_remember = client.post("/api/remember", json={"session_id": session_id, "fact": "the sky is blue"}, headers=headers)
    assert resp_remember.status_code == 200, resp_remember.text

    resp_recall = client.post("/api/memory/recall", json={"session_id": session_id, "query": "sky"}, headers=headers)
    assert resp_recall.status_code == 200, resp_recall.text

    resp_kg = client.get(f"/api/knowledge/{session_id}", headers=headers)
    assert resp_kg.status_code == 200, resp_kg.text

    # -- chat on the SAME session must still fail: it genuinely needs the
    # model, so the fix must not have masked that real dependency --
    resp_chat = client.post(
        "/api/chat",
        json={"message": "hello", "session_id": session_id},
        headers=headers,
    )
    assert resp_chat.status_code == 500, resp_chat.text
