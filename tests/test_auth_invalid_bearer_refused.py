"""LANDMARK-01 Wave 1: a presented-but-invalid bearer credential is NEVER anonymous.

``get_current_user_optional`` used to swallow every authentication failure and return ``None`` (anonymous), so a logged-out, expired, revoked or
wrong-type token silently kept working on every anonymous-permitted route, including the ones that spend model inference. The acceptance criterion is
not just the status code: a rejected probe must cause ZERO model dispatches.
"""
from __future__ import annotations

import json

import pytest

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401  (fixture re-export)

# Routes that accept a credential optionally; each one spends inference or reads/writes user data.
GUARDED = [
    ("post", "/api/chat", {"message": "hello", "session_id": "probe-sess-0001"}),
    ("post", "/api/stream", {"message": "hello", "session_id": "probe-sess-0002"}),
    ("get", "/api/sessions", None),
    ("get", "/api/session/probe-sess-0003/messages", None),
    ("post", "/api/inference/complete", {"message": "hello", "session_id": "probe-sess-0004", "model_variant": "nano"}),
]


@pytest.fixture
def fake(client, monkeypatch):  # noqa: F811
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    f = FakeOllama(models=("orca-nano", "orca-core", "orca-ultra"))
    f.__enter__()
    point_orneur_at(f, monkeypatch)
    yield f
    f.__exit__(None, None, None)


def _call(client, method, path, body, headers):
    if method == "get":
        return client.get(path, headers=headers)
    # Drain the stream so a (wrongly) accepted request would actually reach the model.
    with client.stream("POST", path, json=body, headers=headers) as r:
        r.read()
        return r


def _assert_refused(client, fake, token_headers, label):
    before = len(fake.requests)
    for method, path, body in GUARDED:
        resp = _call(client, method, path, body, token_headers)
        assert resp.status_code == 401, f"{label}: {method.upper()} {path} -> {resp.status_code}, expected 401"
    assert len(fake.requests) == before, f"{label}: a rejected credential caused {len(fake.requests) - before} model dispatch(es)"


def test_absent_credentials_remain_anonymous_where_permitted(client, fake):
    resp = client.get("/api/sessions")
    assert resp.status_code != 401


def test_garbage_bearer_is_401_with_zero_dispatches(client, fake):
    _assert_refused(client, fake, {"Authorization": "Bearer not-a-real-token"}, "garbage")


def test_expired_jwt_is_401_with_zero_dispatches(client, fake):
    from orca.auth.crypto import create_token

    _, uid = _signup(client)
    expired = create_token({"sub": uid, "type": "session", "jti": "expired-jti"}, expires_in=-30)
    _assert_refused(client, fake, _hdr(expired), "expired")


def test_revoked_jwt_after_logout_is_401_with_zero_dispatches(client, fake):
    token, _ = _signup(client)
    assert client.get("/api/auth/me", headers=_hdr(token)).status_code == 200
    assert client.post("/api/auth/logout", headers=_hdr(token)).status_code == 200
    _assert_refused(client, fake, _hdr(token), "revoked-by-logout")


def test_logout_all_revokes_every_device_session(client, fake):
    from orca.auth.routes import _make_response
    from orca.auth.store import create_user

    user = create_user("lall-device@example.com", "Correct-Horse-9!", "Synthetic")
    device_a = _make_response(user)["token"]
    device_b = _make_response(user)["token"]
    assert client.get("/api/auth/me", headers=_hdr(device_b)).status_code == 200
    assert client.post("/api/auth/logout-all", headers=_hdr(device_a)).status_code == 200
    _assert_refused(client, fake, _hdr(device_a), "device-a-after-logout-all")
    _assert_refused(client, fake, _hdr(device_b), "device-b-after-logout-all")


@pytest.mark.parametrize("kind", ["reset", "email_verification", "2fa_pending", "bogus"])
def test_non_session_tokens_never_become_session_credentials(client, fake, kind):
    from orca.auth.crypto import create_token

    _, uid = _signup(client)
    other = create_token({"sub": uid, "type": kind, "jti": f"{kind}-jti"})
    _assert_refused(client, fake, _hdr(other), f"type={kind}")


def test_unknown_api_key_is_401_with_zero_dispatches(client, fake):
    _assert_refused(client, fake, {"Authorization": "Bearer athr_" + "0" * 40}, "unknown-api-key")


def test_token_issued_before_a_password_change_is_401(client, fake):
    from orca.auth.store import invalidate_all_sessions

    token, uid = _signup(client)
    invalidate_all_sessions(uid)
    _assert_refused(client, fake, _hdr(token), "pre-invalidation")


def test_valid_token_still_works(client, fake):
    token, _ = _signup(client)
    resp = client.get("/api/sessions", headers=_hdr(token))
    assert resp.status_code == 200
    assert isinstance(json.loads(resp.text), dict)
