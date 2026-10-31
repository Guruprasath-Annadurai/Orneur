"""LANDMARK-04 P1-D -- sensitive account operations require fresh authentication, like API-key creation does (L02-B3).

Findings (reproduced against main 0a4c518): ``POST /api/auth/change-password`` and ``POST /api/auth/account/delete`` checked the current password only -- no per-account failure
lockout (a stolen session token could guess the password at the IP limit) and no second factor for accounts that have 2FA (a stolen session token + a guessed password destroyed or
took over the account). Changing the password also killed the caller's own session without issuing a replacement.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from tests.totp_clock import FIXED_TOTP_EPOCH, freeze_totp_wall_clock

PW = "correcthorsebatterystaple"
NEW = "an-entirely-new-passphrase-9"


@pytest.fixture
def client(isolated_home):
    from orca import audit
    from orca.auth import apikeys
    from orca.serve import ratelimit
    from orca.serve.api import app

    apikeys._ensure_table()
    audit._ensure_table()
    ratelimit._local_counters.clear()
    c = TestClient(app)
    c.post("/api/auth/signup", json={"email": f"owner-{uuid.uuid4().hex[:6]}@example.com", "password": PW, "name": "owner"})
    return c


@pytest.fixture
def clock():
    with freeze_totp_wall_clock(FIXED_TOTP_EPOCH) as e:
        yield e


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _user(client, mfa=False):
    from orca.auth.store import get_totp_state
    from orca.auth.totp import totp_now
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    email = f"sens-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": PW, "name": "T"})
    tok, uid = r.json()["token"], r.json()["user"]["id"]
    secret = None
    if mfa:
        s = client.post("/api/auth/2fa/setup", headers=_h(tok)).json()["secret"]
        assert client.post("/api/auth/2fa/enable", json={"code": totp_now(s)}, headers=_h(tok)).status_code == 200
        secret = get_totp_state(uid)["secret"]
    return email, tok, uid, secret


def _fresh_code(secret):
    from orca.auth.totp import totp_now

    return totp_now(secret, at_time=FIXED_TOTP_EPOCH + 30)     # the next step: inside the real +-1 window


def test_change_password_wrong_password_is_bounded_per_account(client, clock):
    from orca.serve import ratelimit

    _, tok, _, _ = _user(client)
    codes = []
    for _i in range(12):
        ratelimit._local_counters.clear()
        codes.append(client.post("/api/auth/change-password", json={"current_password": "wrong-wrong-1", "new_password": NEW}, headers=_h(tok)).status_code)
    assert 429 in codes, f"unbounded password guessing through change-password: {codes}"
    ratelimit._local_counters.clear()
    assert client.post("/api/auth/change-password", json={"current_password": PW, "new_password": NEW}, headers=_h(tok)).status_code == 429


def test_change_password_on_a_2fa_account_needs_a_fresh_single_use_code(client, clock):
    email, tok, uid, secret = _user(client, mfa=True)
    body = {"current_password": PW, "new_password": NEW}
    missing = client.post("/api/auth/change-password", json=body, headers=_h(tok))
    assert missing.status_code == 401 and missing.json()["code"] == "reauth_required"
    code = _fresh_code(secret)
    ok = client.post("/api/auth/change-password", json={**body, "totp_code": code}, headers=_h(tok))
    assert ok.status_code == 200, ok.text
    # the password really changed, and the code is spent
    fresh = ok.json()["token"]
    again = client.post("/api/auth/change-password", json={"current_password": NEW, "new_password": PW, "totp_code": code}, headers=_h(fresh))
    assert again.status_code == 401


def test_change_password_returns_a_working_session_and_kills_the_old_one(client):    # real clock: token issue time must differ from the change time
    email, tok, uid, _ = _user(client)
    r = client.post("/api/auth/change-password", json={"current_password": PW, "new_password": NEW}, headers=_h(tok))
    assert r.status_code == 200 and r.json()["updated"] is True
    assert client.get("/api/auth/me", headers=_h(tok)).status_code == 401, "the pre-change session survived a password change"
    assert client.get("/api/auth/me", headers=_h(r.json()["token"])).status_code == 200, "the user was logged out of their own change"
    assert client.post("/api/auth/login", json={"email": email, "password": NEW}).status_code == 200


def test_account_delete_is_bounded_and_needs_the_second_factor(client, clock):
    from orca.serve import ratelimit

    email, tok, uid, secret = _user(client, mfa=True)
    # a stolen session token plus the right password is NOT enough on a 2FA account
    r = client.post("/api/auth/account/delete", json={"password": PW}, headers=_h(tok))
    assert r.status_code == 401 and r.json()["code"] == "reauth_required"
    assert client.get("/api/auth/me", headers=_h(tok)).status_code == 200, "the account was deleted without the second factor"
    codes = []
    for _i in range(12):
        ratelimit._local_counters.clear()
        codes.append(client.post("/api/auth/account/delete", json={"password": "wrong-wrong-1", "totp_code": "000000"}, headers=_h(tok)).status_code)
    assert 429 in codes, f"unbounded guessing through account deletion: {codes}"


def test_account_delete_still_works_with_fresh_authentication(client, clock):
    email, tok, uid, secret = _user(client, mfa=True)
    r = client.post("/api/auth/account/delete", json={"password": PW, "totp_code": _fresh_code(secret)}, headers=_h(tok))
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/me", headers=_h(tok)).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": PW}).status_code == 401
