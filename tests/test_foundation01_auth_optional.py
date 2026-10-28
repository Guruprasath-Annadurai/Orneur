"""FOUNDATION LANDMARK-01 — invalid credentials must not become anonymous."""
from __future__ import annotations

import time
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from orca.auth.crypto import create_token
from orca.auth.db import init_db
from orca.auth.middleware import get_current_user_optional
from orca.auth.store import create_user, revoke_token


class _Creds:
    def __init__(self, credentials: str):
        self.credentials = credentials


@pytest.fixture()
def two_users(isolated_home):
    init_db()
    a = create_user(f"a-{uuid.uuid4().hex[:8]}@example.com", "password-a-12", "A")
    b = create_user(f"b-{uuid.uuid4().hex[:8]}@example.com", "password-b-12", "B")
    return a, b


@pytest.mark.asyncio
async def test_missing_credentials_are_anonymous(two_users):
    assert await get_current_user_optional(None) is None


@pytest.mark.asyncio
async def test_invalid_jwt_is_rejected_not_anonymous(two_users):
    with pytest.raises(HTTPException) as ei:
        await get_current_user_optional(_Creds("not-a-real-jwt"))
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_revoked_jwt_is_rejected(two_users):
    user_a, _ = two_users
    token = create_token({"sub": user_a.id, "type": "session", "jti": "jti-revoked-1"})
    revoke_token("jti-revoked-1", user_a.id, time.time() + 3600)
    with pytest.raises(HTTPException) as ei:
        await get_current_user_optional(_Creds(token))
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_password_reset_token_cannot_authenticate_session(two_users):
    user_a, _ = two_users
    reset = create_token({"sub": user_a.id, "type": "password_reset", "jti": "reset-1"})
    with pytest.raises(HTTPException) as ei:
        await get_current_user_optional(_Creds(reset))
    assert ei.value.status_code == 401


def test_cross_user_session_isolation_on_messages(two_users, isolated_home):
    from orca.auth.store import claim_session
    from orca.serve import conversations
    from orca.serve.api import app

    user_a, user_b = two_users
    sid = "sessA" + uuid.uuid4().hex[:12]
    claim_session(sid, user_a.id)
    fence = uuid.uuid4().hex
    auth = conversations.acquire_authority(sid, user_a.id, fence, ttl_s=30.0)
    assert auth is not None
    committed = conversations.commit_turn(
        sid,
        "secret-fact-alpha",
        "assistant-reply",
        user_id=user_a.id,
        turn_id="turn-a-1",
        fence_token=fence,
        epoch=auth.epoch,
        meta={"message_id": "msg-a-1", "user_message_id": "umsg-a-1"},
    )
    assert committed.ok
    conversations.release_authority(sid, fence, auth.epoch)

    token_b = create_token({"sub": user_b.id, "type": "session", "jti": "b-session"})
    client = TestClient(app)
    r = client.get(
        f"/api/session/{sid}/messages",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r.status_code in (401, 403, 404)
    assert "secret-fact-alpha" not in r.text


def test_invalid_bearer_on_chat_returns_401(two_users, isolated_home):
    from orca.serve.api import app

    client = TestClient(app)
    r = client.post(
        "/api/chat",
        json={"message": "hello", "model_variant": "nano"},
        headers={"Authorization": "Bearer totally-invalid"},
    )
    assert r.status_code == 401
