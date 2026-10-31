"""LANDMARK-04 P1-D -- the second factor at sign-in is single-use and brute-force bounded.

Finding (P1, reproduced in a real browser journey): ``POST /api/auth/2fa/verify-login`` accepted the same TOTP code any number of times inside its validity window and had no
per-account lockout, so a captured code (shoulder-surf, phishing relay, proxy log) replayed against a fresh pending token minted a new session, and six-digit codes could be
guessed at the IP rate limit only. The API-key step-up (L02-B3) already had both protections; the sign-in path did not.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from tests.totp_clock import FIXED_TOTP_EPOCH, freeze_totp_wall_clock

PW = "correcthorsebatterystaple"


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
    c.post("/api/auth/signup", json={"email": f"owner-{uuid.uuid4().hex[:6]}@example.com", "password": PW, "name": "owner"})  # burn the bootstrap owner
    return c


@pytest.fixture
def clock():
    with freeze_totp_wall_clock(FIXED_TOTP_EPOCH) as e:
        yield e


def _mfa_user(client):
    from orca.auth.store import get_totp_state
    from orca.auth.totp import totp_now
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    email = f"mfa-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": PW, "name": "T"})
    tok, uid = r.json()["token"], r.json()["user"]["id"]
    h = {"Authorization": f"Bearer {tok}"}
    secret = client.post("/api/auth/2fa/setup", headers=h).json()["secret"]
    assert client.post("/api/auth/2fa/enable", json={"code": totp_now(secret)}, headers=h).status_code == 200
    return email, uid, get_totp_state(uid)["secret"], tok


def _pending(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200 and r.json()["requires_2fa"] is True and "token" not in r.json()
    return r.json()["pending_token"]


def test_a_sign_in_code_cannot_be_used_twice(client, clock):
    from orca.auth.totp import totp_now

    email, uid, secret, _ = _mfa_user(client)
    code = totp_now(secret)
    first = client.post("/api/auth/2fa/verify-login", json={"pending_token": _pending(client, email), "code": code})
    assert first.status_code == 200 and first.json()["token"]
    replay = client.post("/api/auth/2fa/verify-login", json={"pending_token": _pending(client, email), "code": code})
    assert replay.status_code == 401, "the same one-time code minted a second session"
    assert "token" not in replay.text


def test_repeated_wrong_codes_lock_the_account_out_of_the_second_factor(client, clock):
    from orca.auth.totp import totp_now

    email, uid, secret, _ = _mfa_user(client)
    pending = _pending(client, email)
    from orca.serve import ratelimit

    statuses = []
    for _ in range(12):
        ratelimit._local_counters.clear()   # remove the per-IP limiter from the picture: this asserts the PER-ACCOUNT bound
        statuses.append(client.post("/api/auth/2fa/verify-login", json={"pending_token": pending, "code": "000000"}).status_code)
    assert 429 in statuses, f"unbounded guessing: {statuses}"
    # while locked even the right code is refused (and says so with Retry-After)
    ratelimit._local_counters.clear()
    locked = client.post("/api/auth/2fa/verify-login", json={"pending_token": pending, "code": totp_now(secret)})
    assert locked.status_code == 429 and "retry-after" in {k.lower() for k in locked.headers}


def test_disabling_mfa_needs_a_fresh_code_each_time(client, clock):
    from orca.auth.totp import totp_now

    email, uid, secret, tok = _mfa_user(client)
    h = {"Authorization": f"Bearer {tok}"}
    # the code used at sign-in is spent: it cannot also switch the factor off
    code = totp_now(secret)
    assert client.post("/api/auth/2fa/verify-login", json={"pending_token": _pending(client, email), "code": code}).status_code == 200
    assert client.post("/api/auth/2fa/disable", json={"code": code}, headers=h).status_code == 401
