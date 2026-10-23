"""P0: a presented credential that fails authentication is HTTP 401.

A missing Authorization header stays a guest. An expired, revoked, forged,
reset, or 2FA-pending token must not become an anonymous upload or an
empty conversation list.
"""
from __future__ import annotations

import time
import uuid

from orca.auth.crypto import create_token
from orca.auth.store import revoke_token
from orca.auth.tokens import make_2fa_pending_token, make_reset_token
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


def _user(client):
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    token, user_id = _signup(client)
    return token, user_id


def test_missing_authorization_header_is_a_guest(client):
    listed = client.get("/api/sessions")
    assert listed.status_code == 200
    assert listed.json()["sessions"] == []


def test_valid_login_is_authenticated(client):
    token, user_id = _user(client)
    me = client.get("/api/auth/me", headers=_hdr(token))
    assert me.status_code == 200
    assert me.json()["user"]["id"] == user_id


def test_expired_token_is_401_on_sessions_and_does_not_list_as_guest(client):
    _token, user_id = _user(client)
    expired = create_token({"sub": user_id, "type": "session", "jti": uuid.uuid4().hex}, expires_in=-10)
    listed = client.get("/api/sessions", headers=_hdr(expired))
    assert listed.status_code == 401
    assert listed.json()["detail"] == "Invalid or expired token"


def test_revoked_token_is_401(client):
    _token, user_id = _user(client)
    jti = uuid.uuid4().hex
    token = create_token({"sub": user_id, "type": "session", "jti": jti}, expires_in=3600)
    revoke_token(jti, user_id, time.time() + 3600)
    assert client.get("/api/auth/me", headers=_hdr(token)).status_code == 401
    assert client.get("/api/sessions", headers=_hdr(token)).status_code == 401


def test_forged_signature_is_401(client):
    token, _user_id = _user(client)
    forged = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert client.get("/api/sessions", headers=_hdr(forged)).status_code == 401


def test_reset_and_2fa_pending_tokens_are_not_sessions(client):
    _token, user_id = _user(client)
    from orca.auth.store import get_user_by_id

    email = get_user_by_id(user_id).email
    for token in (make_reset_token(user_id, email), make_2fa_pending_token(user_id, email)):
        assert client.get("/api/sessions", headers=_hdr(token)).status_code == 401
        assert client.get("/api/auth/me", headers=_hdr(token)).status_code == 401


def test_malformed_authorization_schemes_are_401(client):
    for header in (
        "Basic abc",
        "Bearer",
        "Bearer a b",
        "Bearer  token",
        "Token xyz",
        "",
    ):
        response = client.get("/api/sessions", headers={"Authorization": header})
        assert response.status_code == 401, header


def test_expired_token_does_not_upload_a_document(client, monkeypatch):
    import orca.docs.store as store
    import orca.serve.api as api

    _token, user_id = _user(client)
    expired = create_token({"sub": user_id, "type": "session", "jti": uuid.uuid4().hex}, expires_in=-10)
    called = []
    monkeypatch.setattr(api, "admit_uploaded_document", lambda *a, **k: called.append("admit"))

    def refuse(self, *a, **k):
        called.append("chunks")
        raise AssertionError("document store must not be written")

    monkeypatch.setattr(store.DocStore, "add_chunks", refuse)
    response = client.post(
        "/api/docs/upload",
        files={"file": ("secret.txt", b"EXPIRED-UPLOAD-MUST-NOT-LAND", "text/plain")},
        headers=_hdr(expired),
    )
    assert response.status_code == 401
    assert called == []


def test_expired_token_does_not_load_a_conversation(client):
    token, user_id = _user(client)
    created = client.post(
        "/api/docs/upload",
        files={"file": ("notes.txt", b"hello notes", "text/plain")},
        headers=_hdr(token),
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]
    expired = create_token({"sub": user_id, "type": "session", "jti": uuid.uuid4().hex}, expires_in=-10)
    loaded = client.post("/api/session/load", json={"session_id": session_id}, headers=_hdr(expired))
    assert loaded.status_code == 401


def test_cross_user_session_access_stays_404(client):
    token_a, _user_a = _user(client)
    token_b, _user_b = _user(client)
    created = client.post(
        "/api/docs/upload",
        files={"file": ("notes.txt", b"hello notes", "text/plain")},
        headers=_hdr(token_a),
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]
    stolen = client.get("/api/docs/list", params={"session_id": session_id}, headers=_hdr(token_b))
    assert stolen.status_code == 404
    listed = client.post("/api/session/load", json={"session_id": session_id}, headers=_hdr(token_b))
    assert listed.status_code == 404
