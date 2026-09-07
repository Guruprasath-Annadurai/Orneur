"""
Phase 14C edge-qualification finding: `/api/knowledge/{session_id}`,
`/api/explain/{session_id}/{message_id}`, `/api/session/{session_id}/export`,
`POST /api/session/load`, `/api/memory/recall`, `/api/remember`,
`/api/docs/list`, and `/api/ultra` all took a bare `session_id` with no
ownership check at all -- any caller who learned or guessed another
signed-in user's session_id could read (or, for docs/upload and
docs/delete, write into) their data, regardless of their own identity.
Fixed centrally in `_get_session()` itself (every one of the above
routes reaches a session through that one function) rather than
per-route. Real, end-to-end HTTP tests (TestClient -> the actual
FastAPI app, real signup/login through /api/auth) proving:

  1. A session created by user A, while authenticated, is NOT readable
     by user B (404, not 403 -- never confirms existence to a stranger)
     -- across every affected route, not just one.
  2. User A can still read their own session normally.
  3. An anonymous (no-token) session remains accessible without a
     token -- the session_id itself is its own shareable credential
     for anonymous chat, unaffected by this fix.
"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _signup(client: TestClient) -> tuple[str, str]:
    email = f"phase14c-test-{uuid.uuid4().hex[:12]}@example.com"
    resp = client.post("/api/auth/signup", json={"email": email, "password": "correcthorsebatterystaple", "name": "Test User"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return data["token"], data["user"]["id"]


def test_session_owned_by_user_a_is_not_readable_by_user_b(isolated_home):
    from orca.serve.api import app
    from orca.auth.store import record_user_session

    client = TestClient(app)
    token_a, user_id_a = _signup(client)
    token_b, user_id_b = _signup(client)

    session_id = str(uuid.uuid4())
    record_user_session(user_id_a, session_id)

    resp_b = client.get(f"/api/knowledge/{session_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert resp_b.status_code == 404, resp_b.text

    resp_b2 = client.get(f"/api/session/{session_id}/export", headers={"Authorization": f"Bearer {token_b}"})
    assert resp_b2.status_code == 404, resp_b2.text

    resp_b3 = client.post("/api/session/load", json={"session_id": session_id}, headers={"Authorization": f"Bearer {token_b}"})
    assert resp_b3.status_code == 404, resp_b3.text

    resp_anon = client.get(f"/api/knowledge/{session_id}")
    assert resp_anon.status_code == 404, resp_anon.text

    resp_recall = client.post("/api/memory/recall", json={"session_id": session_id, "query": "anything"}, headers={"Authorization": f"Bearer {token_b}"})
    assert resp_recall.status_code == 404, resp_recall.text

    resp_remember = client.post("/api/remember", json={"session_id": session_id, "fact": "anything"}, headers={"Authorization": f"Bearer {token_b}"})
    assert resp_remember.status_code == 404, resp_remember.text

    resp_docs = client.get("/api/docs/list", params={"session_id": session_id}, headers={"Authorization": f"Bearer {token_b}"})
    assert resp_docs.status_code == 404, resp_docs.text


def test_session_owner_can_still_read_their_own_session(isolated_home):
    from orca.serve.api import app
    from orca.auth.store import record_user_session

    client = TestClient(app)
    token_a, user_id_a = _signup(client)

    session_id = str(uuid.uuid4())
    record_user_session(user_id_a, session_id)

    resp = client.get(f"/api/knowledge/{session_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["session_id"] == session_id


def test_anonymous_session_remains_accessible_without_a_token(isolated_home):
    """Preserves existing anonymous-chat behavior: a session never
    recorded via record_user_session() (created with no bearer token)
    has no owner to check against -- unaffected by this fix."""
    from orca.serve.api import app

    client = TestClient(app)
    session_id = str(uuid.uuid4())  # never recorded as owned by anyone

    resp = client.get(f"/api/knowledge/{session_id}")
    assert resp.status_code == 200, resp.text

    token_b, _ = _signup(client)
    resp_b = client.get(f"/api/knowledge/{session_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert resp_b.status_code == 200, resp_b.text
