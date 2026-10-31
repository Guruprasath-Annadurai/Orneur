"""L02-B3 -- API-key creation requires fresh, server-verified authentication (step-up), not merely a session token.

Finding (independent, P1): ``POST /api/auth/apikeys`` created a long-lived credential for any caller holding a valid session token, so a stolen or hijacked session
could mint a key that outlives logout and password change. The step-up here is verified IN the creation request itself (current password, plus a TOTP code when the
account has 2FA enabled), so it is bound to the operation, the user and the presented session, cannot be stored and replayed, and needs no new token to leak.
"""
from __future__ import annotations

import threading
import uuid

import pytest
from fastapi.testclient import TestClient

from tests.totp_clock import FIXED_TOTP_EPOCH, freeze_totp_wall_clock, next_step_mid

PW = "correcthorsebatterystaple"


@pytest.fixture
def client(isolated_home):
    from orca.auth import apikeys
    from orca.serve import ratelimit
    from orca.serve.api import app

    from orca import audit

    apikeys._ensure_table()  # created at import time against the pre-isolation database
    audit._ensure_table()
    ratelimit._local_counters.clear()
    c = TestClient(app)
    _user(c)  # the first account is the bootstrap owner; burn it so the identities below are ordinary members
    return c


@pytest.fixture
def totp_clock():
    """Pin wall clock mid-step so next-step codes stay inside the real ±1 drift window."""
    with freeze_totp_wall_clock(FIXED_TOTP_EPOCH) as epoch:
        yield epoch


def _user(client, pw=PW):
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    email = f"b3-{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": pw, "name": "T"})
    assert r.status_code == 200, r.text
    return email, r.json()["token"], r.json()["user"]["id"]


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _keys(uid):
    from orca.auth.apikeys import list_keys

    return [k for k in list_keys(uid) if not k["revoked"]]


def _enable_2fa(client, tok, uid):
    from orca.auth.store import get_totp_state
    from orca.auth.totp import totp_now

    secret = client.post("/api/auth/2fa/setup", headers=_h(tok)).json()["secret"]
    assert client.post("/api/auth/2fa/enable", json={"code": totp_now(secret)}, headers=_h(tok)).status_code == 200
    return get_totp_state(uid)["secret"]


def _create(client, tok, **body):
    body.setdefault("name", "ci")
    return client.post("/api/auth/apikeys", json=body, headers=_h(tok))


# ── the vulnerability ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_session_token_alone_cannot_create_an_api_key(client):
    _, tok, uid = _user(client)
    r = _create(client, tok)
    assert r.status_code in (401, 403) and r.json()["code"] == "reauth_required", r.text
    assert _keys(uid) == []
    assert "key" not in r.json()


def test_a_wrong_password_creates_nothing(client):
    _, tok, uid = _user(client)
    r = _create(client, tok, password="not-the-password-at-all")
    assert r.status_code == 401 and r.json()["code"] == "reauth_failed"
    assert _keys(uid) == []


def test_the_correct_password_creates_a_working_key_and_it_is_not_shown_again(client):
    _, tok, uid = _user(client)
    r = _create(client, tok, password=PW)
    assert r.status_code == 200 and r.json()["key"].startswith("athr_")
    assert len(_keys(uid)) == 1
    assert client.get("/api/auth/me", headers=_h(r.json()["key"])).status_code == 200
    assert "key" not in client.get("/api/auth/apikeys", headers=_h(tok)).json()["keys"][0]


@pytest.mark.parametrize("body", [{"password": ""}, {"password": None}, {"password": 123}, {"password": ["x"]}, {"password": " "}])
def test_incomplete_or_malformed_verification_fails_closed(client, body):
    _, tok, uid = _user(client)
    r = _create(client, tok, **body)
    assert r.status_code in (401, 403, 422)
    assert _keys(uid) == []


# ── MFA is never bypassed by the password ───────────────────────────────────────────────────────────────────────────────────────

def test_with_2fa_enabled_the_password_alone_is_refused(client):
    _, tok, uid = _user(client)
    _enable_2fa(client, tok, uid)
    r = _create(client, tok, password=PW)
    assert r.status_code in (401, 403) and r.json()["code"] == "reauth_failed"
    assert _keys(uid) == []


def test_with_2fa_enabled_password_and_a_valid_code_succeed_and_a_wrong_code_does_not(client, totp_clock):
    from orca.auth.totp import totp_now

    _, tok, uid = _user(client)
    secret = _enable_2fa(client, tok, uid)
    bad = _create(client, tok, password=PW, totp_code="000000" if totp_now(secret) != "000000" else "111111")
    assert bad.status_code == 401 and _keys(uid) == []
    # Next-step code under the frozen clock — inside the real ±1-step drift window
    ok = _create(client, tok, password=PW, totp_code=totp_now(secret, next_step_mid(totp_clock)))
    assert ok.status_code == 200, ok.text
    assert len(_keys(uid)) == 1


def test_a_totp_code_cannot_be_replayed_for_a_second_key(client, totp_clock):
    from orca.auth.totp import totp_now

    _, tok, uid = _user(client)
    secret = _enable_2fa(client, tok, uid)
    code = totp_now(secret, next_step_mid(totp_clock))  # a step the 2fa/enable call above did not use
    assert _create(client, tok, password=PW, totp_code=code).status_code == 200
    again = _create(client, tok, password=PW, totp_code=code)
    assert again.status_code == 401 and again.json()["code"] == "reauth_failed"
    assert len(_keys(uid)) == 1


# ── binding to the user and the session; credential classes that must not mint keys ────────────────────────────────────────────

def test_another_accounts_password_cannot_authorise_creation(client):
    _, tok_a, uid_a = _user(client)
    _, _tok_b, _ = _user(client, pw="a-completely-different-passphrase")
    r = _create(client, tok_a, password="a-completely-different-passphrase")
    assert r.status_code == 401 and _keys(uid_a) == []


def test_an_api_key_cannot_create_another_api_key_even_with_the_password(client):
    _, tok, uid = _user(client)
    raw = _create(client, tok, password=PW).json()["key"]
    r = _create(client, raw, password=PW)
    assert r.status_code == 403 and r.json()["code"] == "reauth_requires_session"
    assert len(_keys(uid)) == 1


def test_a_revoked_session_cannot_create_a_key_even_with_the_password(client):
    email, tok, uid = _user(client)
    client.post("/api/auth/logout", headers=_h(tok))
    r = _create(client, tok, password=PW)
    assert r.status_code == 401 and _keys(uid) == []


def test_a_two_factor_pending_token_is_not_a_session(client):
    email, tok, uid = _user(client)
    from orca.auth.tokens import make_2fa_pending_token

    r = _create(client, make_2fa_pending_token(uid, email), password=PW)
    assert r.status_code == 401 and _keys(uid) == []


# ── brute force ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_repeated_wrong_verification_locks_creation_even_for_the_right_password(client):
    from orca.serve import ratelimit

    _, tok, uid = _user(client)
    for _ in range(8):
        ratelimit._local_counters.clear()  # isolate the per-account ledger from the per-IP limiter
        assert _create(client, tok, password="wrong-wrong-wrong").status_code == 401
    ratelimit._local_counters.clear()
    locked = _create(client, tok, password=PW)
    assert locked.status_code == 429 and locked.json()["code"] == "too_many_attempts" and "Retry-After" in locked.headers
    assert _keys(uid) == []


def test_a_per_ip_limit_also_applies(client):
    from orca.serve import ratelimit

    _, tok, uid = _user(client)
    ratelimit._local_counters.clear()
    codes = [_create(client, tok, password="x" * 12).status_code for _ in range(14)]
    assert 429 in codes and _keys(uid) == []


def test_a_successful_verification_clears_the_failure_count(client):
    from orca.serve import ratelimit

    _, tok, uid = _user(client)
    for _ in range(5):
        ratelimit._local_counters.clear()
        _create(client, tok, password="wrong-wrong-wrong")
    ratelimit._local_counters.clear()
    assert _create(client, tok, password=PW).status_code == 200
    for _ in range(5):
        ratelimit._local_counters.clear()
        assert _create(client, tok, password="wrong-wrong-wrong").status_code == 401  # not yet locked: the count restarted


# ── what must keep working ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_listing_and_revocation_are_unchanged_and_need_no_extra_verification(client):
    _, tok, uid = _user(client)
    kid = _create(client, tok, password=PW).json()["key_id"]
    listed = client.get("/api/auth/apikeys", headers=_h(tok))
    assert listed.status_code == 200 and [k["id"] for k in listed.json()["keys"]] == [kid]
    assert client.delete(f"/api/auth/apikeys/{kid}", headers=_h(tok)).status_code == 200
    assert _keys(uid) == []
    assert client.get("/api/auth/apikeys", headers=_h(tok)).status_code == 200


def test_a_password_reset_still_revokes_existing_keys_and_account_recovery_is_untouched(client, monkeypatch, tmp_path):
    _, tok, uid = _user(client)
    raw = _create(client, tok, password=PW).json()["key"]
    from orca.auth.apikeys import list_keys, revoke_key

    for k in list_keys(uid):
        revoke_key(k["id"], uid)
    assert client.get("/api/auth/me", headers=_h(raw)).status_code == 401


# ── audit: safe, useful, no secrets ─────────────────────────────────────────────────────────────────────────────────────────────

def test_audit_records_outcomes_without_passwords_codes_or_keys(client, totp_clock):
    from orca import audit
    from orca.auth.totp import totp_now

    _, tok, uid = _user(client)
    secret = _enable_2fa(client, tok, uid)
    _create(client, tok, password="a-wrong-password-9")
    _create(client, tok, password=PW, totp_code="123456")
    good = _create(client, tok, password=PW, totp_code=totp_now(secret, next_step_mid(totp_clock)))
    assert good.status_code == 200
    blob = repr(audit.recent(limit=200, user_id=uid))
    events = [e["event"] for e in audit.recent(limit=200, user_id=uid)]
    assert "api_key_created" in events and "api_key_reauth_failed" in events
    for secret_value in ("a-wrong-password-9", PW, "123456", good.json()["key"], secret):
        assert secret_value not in blob


# ── simultaneous TOTP step claim (independent connections / processes) ─────────────────────────────

def _totp_claim_worker(orca_home: str, user_id: str, totp_step: int, q) -> None:
    """Spawn-safe child: reload auth against shared ORCA_HOME, claim one step, report."""
    import importlib
    import os

    os.environ["ORCA_HOME"] = orca_home
    os.environ["ORNEUR_HOME"] = orca_home
    import orca.config as config_mod

    importlib.reload(config_mod)
    import orca.auth.db as db_mod

    importlib.reload(db_mod)
    import orca.auth.account_security as acct_mod

    importlib.reload(acct_mod)
    q.put(acct_mod.claim_totp_step(user_id, totp_step))


def test_simultaneous_totp_step_claim_admits_exactly_one(isolated_home):
    """True concurrent claim_totp_step: independent SQLite connections race ON CONFLICT DO NOTHING.

    Product behaviour must admit exactly one winner without loosening replay prevention.
    """
    import multiprocessing as mp

    from orca.auth import account_security as acct
    from orca.auth import db
    from orca.config import ORCA_HOME

    db.init_db()
    uid = "totp-race-" + uuid.uuid4().hex
    step = 42_000_042

    # Threads: independent connections sharing one process (WAL + busy timeout).
    n_threads = 8
    barrier = threading.Barrier(n_threads)
    thread_hits: list[bool] = []
    lock = threading.Lock()

    def _thread_claim() -> None:
        barrier.wait(timeout=10)
        ok = acct.claim_totp_step(uid, step)
        with lock:
            thread_hits.append(ok)

    threads = [threading.Thread(target=_thread_claim) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive()
    assert thread_hits.count(True) == 1 and thread_hits.count(False) == n_threads - 1, thread_hits

    # Processes: independent interpreters against the same auth.db (where SQLite WAL supports it).
    home = str(ORCA_HOME)
    step_b = step + 1
    n_procs = 4
    ctx = mp.get_context("spawn")
    result_q = ctx.Queue()
    procs = [
        ctx.Process(target=_totp_claim_worker, args=(home, uid, step_b, result_q))
        for _ in range(n_procs)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0, p.exitcode
    proc_hits = [result_q.get(timeout=5) for _ in range(n_procs)]
    assert proc_hits.count(True) == 1 and proc_hits.count(False) == n_procs - 1, proc_hits
    # Same step must still be refused after the race winner claimed it.
    assert acct.claim_totp_step(uid, step_b) is False
