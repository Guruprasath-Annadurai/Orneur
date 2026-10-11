"""Workstream B -- sign-out that really signs out (stateless 30-day bearer tokens had no logout and no per-token revocation)."""
from __future__ import annotations

import time
import uuid

import pytest

from tests.test_g006_tenant_isolation import PASSWORD, _hdr, client  # noqa: F401  (fixture re-export)


def _login(client, email):
    from orca.serve import ratelimit
    ratelimit._local_counters.clear()
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture
def account(client):
    from orca.auth.store import create_user
    email = f"b-{uuid.uuid4().hex[:8]}@example.com"
    create_user(email, PASSWORD, "B")
    return email


def _me(client, token):
    return client.get("/api/auth/me", headers=_hdr(token)).status_code


def test_logout_revokes_exactly_that_token(client, account):
    t1, t2 = _login(client, account), _login(client, account)
    assert _me(client, t1) == 200 and _me(client, t2) == 200
    r = client.post("/api/auth/logout", headers=_hdr(t1))
    assert r.status_code == 200 and r.json()["revoked"] == "this_session"
    assert _me(client, t1) == 401 and _me(client, t2) == 200


def test_logout_twice_is_idempotent_and_never_500(client, account):
    t = _login(client, account)
    assert client.post("/api/auth/logout", headers=_hdr(t)).status_code == 200
    assert client.post("/api/auth/logout", headers=_hdr(t)).status_code == 401      # already dead: simply unauthenticated


def test_logout_all_signs_out_every_session_including_this_one(client, account):
    t1, t2 = _login(client, account), _login(client, account)
    time.sleep(0.02)
    r = client.post("/api/auth/logout-all", headers=_hdr(t1))
    assert r.status_code == 200 and r.json()["revoked"] == "all_sessions"
    assert _me(client, t1) == 401 and _me(client, t2) == 401
    assert _me(client, _login(client, account)) == 200                          # a fresh login afterwards works


def test_logout_requires_authentication(client):
    assert client.post("/api/auth/logout").status_code == 401
    assert client.post("/api/auth/logout-all").status_code == 401


def test_a_legacy_token_without_a_jti_logs_out_everything_because_it_cannot_be_singled_out(client, account):
    from orca.auth.crypto import create_token
    from orca.auth.store import get_user_by_email
    u = get_user_by_email(account)
    legacy = create_token({"sub": u.id, "type": "session", "email": u.email, "tier": u.tier, "role": u.role})   # no jti, like pre-upgrade tokens
    other = _login(client, account)
    time.sleep(0.02)
    r = client.post("/api/auth/logout", headers=_hdr(legacy))
    assert r.status_code == 200 and r.json()["revoked"] == "all_sessions"
    assert _me(client, legacy) == 401 and _me(client, other) == 401


def test_a_user_cannot_revoke_someone_elses_token_by_guessing_ids(client, account):
    other_email = f"o-{uuid.uuid4().hex[:8]}@example.com"
    from orca.auth.store import create_user
    create_user(other_email, PASSWORD, "O")
    mine, theirs = _login(client, account), _login(client, other_email)
    client.post("/api/auth/logout", headers=_hdr(mine))
    assert _me(client, theirs) == 200


def test_revocations_are_purged_after_the_token_would_have_expired(client, account):
    from orca.auth.db import get_conn
    from orca.auth.store import is_token_revoked, purge_expired_revocations, revoke_token
    revoke_token("jti-old", "u", time.time() - 10)
    revoke_token("jti-new", "u", time.time() + 3600)
    assert purge_expired_revocations() == 1
    assert is_token_revoked("jti-new") and not is_token_revoked("jti-old")


def test_session_tokens_carry_a_unique_jti(client, account):
    from orca.auth.crypto import verify_token
    a, b = verify_token(_login(client, account)), verify_token(_login(client, account))
    assert a["jti"] and b["jti"] and a["jti"] != b["jti"]


def test_a_revoked_token_cannot_be_used_as_an_optional_identity_either(client, account):
    """Routes with optional auth must treat a revoked token as ANONYMOUS, not as the user."""
    t = _login(client, account)
    sid = client.post("/api/remember", json={"session_id": str(uuid.uuid4()), "fact": "x"}, headers=_hdr(t)).json()["session_id"]
    client.post("/api/auth/logout", headers=_hdr(t))
    r = client.get(f"/api/session/{sid}/export", headers=_hdr(t))
    assert r.status_code == 404                                                  # anonymous callers cannot read an owned session
