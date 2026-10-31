"""L02-04 -- account verification, recovery and session security, against a LOCAL mail sink (no message is ever delivered to anyone).

Real FastAPI app, real auth database. ``ORNEUR_MAIL_SINK_DIR`` makes the app write each outgoing message to a directory; tests read the link from there exactly as a person would
read it from an inbox. Nothing here claims email delivery works in production: ``/api/auth/email-status`` reports ``real_delivery: false`` for the sink.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PW = "correcthorsebatterystaple"


@pytest.fixture
def app(isolated_home, tmp_path, monkeypatch):
    from orca.serve import ratelimit
    from orca.serve.api import app as fastapi_app

    monkeypatch.setenv("ORNEUR_MAIL_SINK_DIR", str(tmp_path / "sink"))
    monkeypatch.setenv("ORNEUR_REQUIRE_EMAIL_VERIFICATION", "1")
    ratelimit._local_counters.clear()
    return TestClient(fastapi_app), tmp_path / "sink"


def _mails(sink: Path, to: str | None = None):
    out = []
    for f in sorted(sink.glob("*.json")) if sink.exists() else []:
        m = json.loads(f.read_text())
        if to is None or m["to"] == to:
            out.append(m)
    return out


def _link_token(mail: dict, kind: str) -> str:
    pat = r"token=([A-Za-z0-9_\-\.]+)" if kind == "verify" else r"reset_token=([A-Za-z0-9_\-\.]+)"
    return re.search(pat, mail["plain"]).group(1)


def _email():
    return f"l02-{uuid.uuid4().hex[:10]}@example.com"


def _signup(client, email=None):
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    email = email or _email()
    r = client.post("/api/auth/signup", json={"email": email, "password": PW, "name": "T"})
    return email, r


def _verify(client, token):
    return client.post("/api/auth/verify", data={"token": token})


def _verified_user(client, sink):
    email, _ = _signup(client)
    _verify(client, _link_token(_mails(sink, email)[-1], "verify"))
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    r = client.post("/api/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    return email, r.json()["token"], r.json()["user"]["id"]


def _h(t):
    return {"Authorization": f"Bearer {t}"}


# ── disclosure and configuration ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_email_status_discloses_what_delivery_really_is(isolated_home, tmp_path, monkeypatch):
    from orca.serve.api import app as fastapi_app

    c = TestClient(fastapi_app)
    monkeypatch.delenv("ORNEUR_MAIL_SINK_DIR", raising=False)
    monkeypatch.delenv("ORNEUR_REQUIRE_EMAIL_VERIFICATION", raising=False)
    assert c.get("/api/auth/email-status").json() == {"configured": False, "delivery": "none", "real_delivery": False, "verification_required": False}
    monkeypatch.setenv("ORNEUR_MAIL_SINK_DIR", str(tmp_path / "s"))
    monkeypatch.setenv("ORNEUR_REQUIRE_EMAIL_VERIFICATION", "1")
    st = c.get("/api/auth/email-status").json()
    assert st == {"configured": True, "delivery": "local_sink", "real_delivery": False, "verification_required": True}


def test_verification_without_any_delivery_is_not_enforced_and_is_reported_as_a_configuration_finding(monkeypatch):
    from orca.serve import config_validation as cv

    monkeypatch.delenv("ORNEUR_MAIL_SINK_DIR", raising=False)
    monkeypatch.setenv("ORNEUR_REQUIRE_EMAIL_VERIFICATION", "1")
    from orca.auth import account_security as acct

    assert acct.verification_required() is False, "nobody could ever verify: enforcing it would lock every user out"
    codes = {f.code for f in cv.collect_findings()}
    assert "EMAIL_VERIFICATION_NO_DELIVERY" in codes
    monkeypatch.setenv("ORNEUR_MAIL_SINK_DIR", "/tmp/x")
    monkeypatch.setenv("ORNEUR_PUBLIC_EDGE", "1")
    f = {f.code: f for f in cv.collect_findings()}
    assert f["EMAIL_LOCAL_SINK_ON_PUBLIC_EDGE"].severity == "ERROR"


# ── enumeration-resistant signup, verification gate ──────────────────────────────────────────────────────────────────────────────

def test_new_and_existing_addresses_get_the_same_signup_response_and_no_session(app):
    client, sink = app
    email, r1 = _signup(client)
    _, r2 = _signup(client, email)
    assert r1.status_code == r2.status_code == 202 and r1.json() == r2.json()
    assert "token" not in r1.json() and "user" not in r1.json()
    kinds = [m["subject"] for m in _mails(sink, email)]
    assert any("Verify" in s for s in kinds) and any("Someone tried to create" in s for s in kinds)
    # an unrelated person is told nothing either
    assert _mails(sink, "someone-else@example.com") == []


def test_an_unverified_account_cannot_sign_in_or_spend_model_capacity_until_verified(app):
    client, sink = app
    email, _ = _signup(client)
    r = client.post("/api/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "email_verification_required"
    assert client.post("/api/auth/login", json={"email": email, "password": "wrong-password"}).status_code == 401, "a wrong password still looks like any other wrong password"
    link = _link_token(_mails(sink, email)[-1], "verify")
    assert _verify(client, link).status_code == 200
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    ok = client.post("/api/auth/login", json={"email": email, "password": PW})
    assert ok.status_code == 200 and ok.json()["user"]["email"] == email
    assert client.get("/api/auth/me", headers=_h(ok.json()["token"])).json()["user"]["email_verified"] is True


def test_the_verification_gate_also_stops_an_unverified_session_from_using_the_model(app, monkeypatch):
    """A session issued BEFORE the operator turned the gate on (or to an account verified-then-flagged) is refused at the model, not just at login."""
    client, sink = app
    monkeypatch.delenv("ORNEUR_REQUIRE_EMAIL_VERIFICATION", raising=False)
    email, r = _signup(client)
    token = r.json()["token"]                                              # legacy mode: signed in immediately
    monkeypatch.setenv("ORNEUR_REQUIRE_EMAIL_VERIFICATION", "1")
    resp = client.post("/api/chat", json={"message": "hello", "model_variant": "nano"}, headers=_h(token))
    assert resp.status_code in (402, 403) and "Verify your email" in resp.text


# ── single-use, expiring, bound verification links ───────────────────────────────────────────────────────────────────────────────

def test_opening_the_link_does_not_spend_it_and_confirming_does_exactly_once(app):
    client, sink = app
    email, _ = _signup(client)
    tok = _link_token(_mails(sink, email)[-1], "verify")
    page = client.get(f"/api/auth/verify?token={tok}")                      # what a mail scanner or link preview does
    assert page.status_code == 200 and "CONFIRM" in page.text and "VERIFIED" not in page.text
    assert client.get(f"/api/auth/verify?token={tok}").status_code == 200   # still unspent after a second fetch
    from orca.auth.store import get_user_by_email

    assert get_user_by_email(email).verified is False
    assert _verify(client, tok).status_code == 200 and get_user_by_email(email).verified is True
    replay = _verify(client, tok)
    assert replay.status_code == 400 and "already used" in replay.text
    assert client.get(f"/api/auth/verify?token={tok}").status_code == 400


def test_an_expired_verification_link_is_refused(app):
    client, sink = app
    email, _ = _signup(client)
    tok = _link_token(_mails(sink, email)[-1], "verify")
    from orca.auth.db import get_conn

    with get_conn() as conn:
        conn.execute("UPDATE auth_one_time_tokens SET expires_at=?", (time.time() - 5,))
    assert _verify(client, tok).status_code == 400


def test_a_newer_link_supersedes_the_older_one_and_resend_is_throttled_per_account(app):
    client, sink = app
    from orca.auth import account_security as acct

    email, _ = _signup(client)
    first = _link_token(_mails(sink, email)[-1], "verify")
    r = client.post("/api/auth/verification/resend", json={"email": email})
    assert r.status_code == 200 and len(_mails(sink, email)) == 1, "a second link inside the minimum interval must not be sent"
    from orca.auth.db import get_conn

    with get_conn() as conn:
        conn.execute("UPDATE auth_email_sends SET sent_at = sent_at - ?", (acct.SEND_MIN_INTERVAL_S + 1,))
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    client.post("/api/auth/verification/resend", json={"email": email})
    mails = _mails(sink, email)
    assert len(mails) == 2
    second = _link_token(mails[-1], "verify")
    assert _verify(client, first).status_code == 400, "the older link was superseded"
    assert _verify(client, second).status_code == 200


def test_resend_for_unknown_and_for_verified_addresses_answers_identically_and_sends_nothing(app):
    client, sink = app
    email, tok, _ = _verified_user(client, sink)
    n = len(_mails(sink))
    a = client.post("/api/auth/verification/resend", json={"email": "nobody-here@example.com"})
    b = client.post("/api/auth/verification/resend", json={"email": email})
    assert a.status_code == b.status_code == 200 and a.json() == b.json() and len(_mails(sink)) == n


def test_daily_send_cap_per_account(app):
    from orca.auth import account_security as acct
    from orca.auth.db import get_conn

    client, sink = app
    uid = str(uuid.uuid4())
    sent = 0
    for _ in range(acct.SEND_MAX_PER_DAY + 3):
        with get_conn() as conn:
            conn.execute("UPDATE auth_email_sends SET sent_at = sent_at - ?", (acct.SEND_MIN_INTERVAL_S + 1,))
        ok, _ = acct.may_send(uid, "verify")
        sent += ok
    assert sent == acct.SEND_MAX_PER_DAY


# ── recovery ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_forgot_password_is_indistinguishable_for_known_and_unknown_addresses_and_throttled_silently(app):
    client, sink = app
    email, tok, uid = _verified_user(client, sink)
    base = len(_mails(sink))
    a = client.post("/api/auth/forgot-password", json={"email": email})
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    b = client.post("/api/auth/forgot-password", json={"email": "ghost@example.com"})
    assert a.status_code == b.status_code == 200 and a.json() == b.json() == {"sent": True}
    assert len(_mails(sink)) == base + 1
    ratelimit._local_counters.clear()
    c = client.post("/api/auth/forgot-password", json={"email": email})                  # second request inside the interval
    assert c.status_code == 200 and c.json() == {"sent": True} and len(_mails(sink)) == base + 1, "throttled silently: still 200, no second message"


def test_reset_is_single_use_expiring_and_ends_every_old_session_and_api_key(app):
    client, sink = app
    email, old_session, uid = _verified_user(client, sink)
    other_device = client.post("/api/auth/login", json={"email": email, "password": PW}).json()["token"]
    from orca.auth import apikeys

    apikeys._ensure_table()                                   # created at import time against the pre-isolation database
    key = client.post("/api/auth/apikeys", json={"name": "ci", "password": PW}, headers=_h(old_session)).json()  # L02-B3: creation needs fresh verification
    key_value = key.get("key") or key.get("api_key") or key.get("raw_key")
    assert key_value, key
    client.post("/api/auth/forgot-password", json={"email": email})
    tok = _link_token([m for m in _mails(sink, email) if "reset" in m["subject"].lower() or "Reset" in m["subject"]][-1], "reset")
    r = client.post("/api/auth/reset-password", json={"token": tok, "password": "a-brand-new-passphrase"})
    assert r.status_code == 200 and "token" in r.json()
    assert client.get("/api/auth/me", headers=_h(old_session)).status_code == 401
    assert client.get("/api/auth/me", headers=_h(other_device)).status_code == 401, "a session on another device survived the recovery"
    if key_value:
        assert client.get("/api/auth/me", headers=_h(key_value)).status_code == 401, "an API key minted before the recovery still works"
    replay = client.post("/api/auth/reset-password", json={"token": tok, "password": "attacker-chosen-password"})
    assert replay.status_code == 400
    assert client.post("/api/auth/login", json={"email": email, "password": "a-brand-new-passphrase"}).status_code == 200


def test_expired_and_superseded_and_foreign_reset_links_are_refused(app):
    from orca.auth import account_security as acct
    from orca.auth.db import get_conn

    client, sink = app
    email, _, uid = _verified_user(client, sink)
    from orca.auth.tokens import make_reset_token

    first = make_reset_token(uid, email, acct.issue(uid, "reset", email, acct.RESET_TTL_S))
    second = make_reset_token(uid, email, acct.issue(uid, "reset", email, acct.RESET_TTL_S))       # issuing again supersedes
    assert client.post("/api/auth/reset-password", json={"token": first, "password": "irrelevant-password"}).status_code == 400
    with get_conn() as conn:
        conn.execute("UPDATE auth_one_time_tokens SET expires_at=?", (time.time() - 1,))
    assert client.post("/api/auth/reset-password", json={"token": second, "password": "irrelevant-password"}).status_code == 400
    third = make_reset_token(uid, email, "not-a-real-jti")
    assert client.post("/api/auth/reset-password", json={"token": third, "password": "irrelevant-password"}).status_code == 400
    legacy = make_reset_token(uid, email)                                                          # stateless, jti-less: refused
    assert client.post("/api/auth/reset-password", json={"token": legacy, "password": "irrelevant-password"}).status_code == 400


def test_a_verification_link_cannot_be_used_as_a_reset_link_or_session(app):
    client, sink = app
    email, _ = _signup(client)
    ver = _link_token(_mails(sink, email)[-1], "verify")
    assert client.post("/api/auth/reset-password", json={"token": ver, "password": "irrelevant-password"}).status_code == 400
    assert client.get("/api/auth/me", headers=_h(ver)).status_code == 401


def test_recovery_does_not_bypass_two_factor(app):
    client, sink = app
    email, tok, uid = _verified_user(client, sink)
    from orca.auth.store import enable_totp, set_pending_totp_secret

    set_pending_totp_secret(uid, "JBSWY3DPEHPK3PXP")
    enable_totp(uid)
    client.post("/api/auth/forgot-password", json={"email": email})
    rt = _link_token([m for m in _mails(sink, email) if "eset" in m["subject"]][-1], "reset")
    r = client.post("/api/auth/reset-password", json={"token": rt, "password": "a-brand-new-passphrase"})
    assert r.status_code == 200 and r.json().get("requires_2fa") is True and "token" not in r.json(), "password reset handed out a session without the second factor"


# ── lockout, timing, sessions ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_repeated_failures_lock_the_account_whatever_the_source_and_the_lock_is_identical_for_unknown_addresses(app):
    from orca.auth import account_security as acct
    from orca.serve import ratelimit

    client, sink = app
    email, tok, uid = _verified_user(client, sink)
    for target in (email, "ghost-account@example.com"):
        for _ in range(acct.LOGIN_MAX_FAILURES):
            ratelimit._local_counters.clear()
            assert client.post("/api/auth/login", json={"email": target, "password": "wrong-wrong"}).status_code == 401
        ratelimit._local_counters.clear()
        locked = client.post("/api/auth/login", json={"email": target, "password": PW})
        assert locked.status_code == 429 and locked.json()["code"] == "too_many_attempts" and locked.headers.get("retry-after"), target
    from orca.auth.db import get_conn

    with get_conn() as conn:
        conn.execute("DELETE FROM auth_login_failures")
    ratelimit._local_counters.clear()
    assert client.post("/api/auth/login", json={"email": email, "password": PW}).status_code == 200


def test_a_successful_login_clears_earlier_failures(app):
    from orca.auth import account_security as acct
    from orca.serve import ratelimit

    client, sink = app
    email, tok, uid = _verified_user(client, sink)
    for _ in range(acct.LOGIN_MAX_FAILURES - 2):
        ratelimit._local_counters.clear()
        client.post("/api/auth/login", json={"email": email, "password": "wrong-wrong"})
    ratelimit._local_counters.clear()
    assert client.post("/api/auth/login", json={"email": email, "password": PW}).status_code == 200
    for _ in range(acct.LOGIN_MAX_FAILURES - 1):
        ratelimit._local_counters.clear()
        client.post("/api/auth/login", json={"email": email, "password": "wrong-wrong"})
    ratelimit._local_counters.clear()
    assert client.post("/api/auth/login", json={"email": email, "password": PW}).status_code == 200


def test_an_unknown_address_costs_about_as_much_as_a_wrong_password(app):
    """Timing side channel: a missing account used to return without hashing. Measured ratio is recorded; the assertion is generous (this is a wall-clock test)."""
    from orca.serve import ratelimit

    client, sink = app
    email, tok, uid = _verified_user(client, sink)

    def mean(target):
        ts = []
        for _ in range(5):
            ratelimit._local_counters.clear()
            t0 = time.perf_counter()
            client.post("/api/auth/login", json={"email": target, "password": "wrong-wrong-pw"})
            ts.append(time.perf_counter() - t0)
            from orca.auth.db import get_conn

            with get_conn() as conn:
                conn.execute("DELETE FROM auth_login_failures")
        return sum(ts) / len(ts)

    known, unknown = mean(email), mean(f"nobody-{uuid.uuid4().hex[:6]}@example.com")
    out = Path(__file__).resolve().parent.parent / "docs/orneur/landmarks/landmark-02/evidence/l02_04_login_timing.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"wrong_password_known_account_mean_s": round(known, 4), "unknown_account_mean_s": round(unknown, 4), "ratio": round(unknown / known, 3), "samples_each": 5,
                               "note": "single workstation, wall clock; recorded, not a security proof"}, indent=2))
    assert unknown > 0.5 * known, f"unknown address answers {known/unknown:.1f}x faster than a wrong password"


def test_logout_all_ends_other_devices_but_single_logout_does_not(app):
    client, sink = app
    email, a, uid = _verified_user(client, sink)
    b = client.post("/api/auth/login", json={"email": email, "password": PW}).json()["token"]
    c = client.post("/api/auth/login", json={"email": email, "password": PW}).json()["token"]
    assert client.post("/api/auth/logout", headers=_h(a)).status_code == 200
    assert client.get("/api/auth/me", headers=_h(a)).status_code == 401
    assert client.get("/api/auth/me", headers=_h(b)).status_code == 200 and client.get("/api/auth/me", headers=_h(c)).status_code == 200
    assert client.post("/api/auth/logout-all", headers=_h(b)).status_code == 200
    assert client.get("/api/auth/me", headers=_h(b)).status_code == 401 and client.get("/api/auth/me", headers=_h(c)).status_code == 401


def test_sensitive_actions_demand_the_password(app):
    client, sink = app
    email, a, uid = _verified_user(client, sink)
    assert client.post("/api/auth/change-password", json={"current_password": "wrong-wrong", "new_password": "another-passphrase"}, headers=_h(a)).status_code == 400
    assert client.post("/api/auth/account/delete", json={"password": "wrong-wrong"}, headers=_h(a)).status_code == 401
    assert client.get("/api/auth/me", headers=_h(a)).status_code == 200


def test_signup_failures_do_not_leak_internals(isolated_home, monkeypatch):
    from orca.serve import ratelimit
    from orca.serve.api import app as fastapi_app

    monkeypatch.delenv("ORNEUR_REQUIRE_EMAIL_VERIFICATION", raising=False)
    client = TestClient(fastapi_app)
    ratelimit._local_counters.clear()
    import orca.auth.routes as routes

    def boom(*a, **k):
        raise RuntimeError("sqlite3.OperationalError: disk full at /var/lib/orneur/secret.db")

    monkeypatch.setattr(routes, "create_user", boom)
    r = client.post("/api/auth/signup", json={"email": _email(), "password": PW, "name": "T"})
    assert r.status_code == 500 and "sqlite" not in r.text and "secret.db" not in r.text and "disk full" not in r.text


def test_an_unverified_session_cannot_upload_documents_when_verification_is_required(app, monkeypatch):
    client, sink = app
    monkeypatch.delenv("ORNEUR_REQUIRE_EMAIL_VERIFICATION", raising=False)
    email, r = _signup(client)
    token = r.json()["token"]
    monkeypatch.setenv("ORNEUR_REQUIRE_EMAIL_VERIFICATION", "1")
    up = client.post("/api/docs/upload", files={"file": ("a.txt", b"hello world document", "text/plain")}, headers=_h(token))
    assert up.status_code == 403 and up.json()["code"] == "email_verification_required"
