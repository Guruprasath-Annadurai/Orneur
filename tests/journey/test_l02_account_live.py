"""L02-04 -- account security across REAL workers: two ``orca serve`` processes share one ORNEUR_HOME (one auth database) and one local mail sink.

Verification state, single-use links and login-failure counters must be the same on both workers (evidence class: LIVE_API; mail = local sink, delivered to nobody).
Run:  pytest tests/journey/test_l02_account_live.py -p no:cacheprovider -v
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

import httpx
import pytest

from tests.fake_ollama import FakeOllama
from tests.journey.harness import JOURNEY_MODEL, LiveServer

EVIDENCE = Path(os.environ.get("ORNEUR_L02_EVIDENCE_DIR", "/tmp/orneur-l02-evidence"))
PW = "Journey-Pass-91x"


@pytest.fixture(scope="module")
def pair(tmp_path_factory):
    fake = FakeOllama(models=(JOURNEY_MODEL,), reply="OK")
    fake.__enter__()
    home = tmp_path_factory.mktemp("l02-acct")
    sink = home / "sink"
    env = {"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host, "ORNEUR_MAIL_SINK_DIR": str(sink), "ORNEUR_REQUIRE_EMAIL_VERIFICATION": "1", "ORNEUR_DELETION_SWEEP_S": "3600"}
    a, b = LiveServer(home, extra_env={**env, "APP_URL": "http://placeholder"}), LiveServer(home, extra_env=env)
    try:
        a.wait_ready(); b.wait_ready()
        yield {"a": a, "b": b, "sink": sink}
    finally:
        a.stop(); b.stop(); fake.__exit__(None, None, None)


def _mails(sink, to):
    out = []
    for f in sorted(sink.glob("*.json")) if sink.exists() else []:
        m = json.loads(f.read_text())
        if m["to"] == to:
            out.append(m)
    return out


def _token(mail, kind="verify"):
    return re.search(r"token=([A-Za-z0-9_\-\.]+)" if kind == "verify" else r"reset_token=([A-Za-z0-9_\-\.]+)", mail["plain"]).group(1)


def test_verification_is_consistent_and_single_use_across_workers(pair):
    a, b, sink = pair["a"], pair["b"], pair["sink"]
    email = f"acct-{uuid.uuid4().hex[:8]}@example.com"
    r = httpx.post(f"{a.base}/api/auth/signup", json={"email": email, "password": PW, "name": "T"}, timeout=30)
    assert r.status_code == 202 and "token" not in r.json()
    tok = _token(_mails(sink, email)[-1])
    # not verified anywhere yet
    for base in (a.base, b.base):
        assert httpx.post(f"{base}/api/auth/login", json={"email": email, "password": PW}, timeout=30).status_code == 403
    # opening the link on worker B does not spend it; confirming on B verifies the account for BOTH workers
    assert httpx.get(f"{b.base}/api/auth/verify", params={"token": tok}, timeout=30).status_code == 200
    ok = httpx.post(f"{b.base}/api/auth/verify", data={"token": tok}, timeout=30)
    assert ok.status_code == 200 and "EMAIL VERIFIED" in ok.text
    login_a = httpx.post(f"{a.base}/api/auth/login", json={"email": email, "password": PW}, timeout=30)
    assert login_a.status_code == 200
    # replay on the OTHER worker is refused
    replay = httpx.post(f"{a.base}/api/auth/verify", data={"token": tok}, timeout=30)
    assert replay.status_code == 400
    # a session issued by A is honoured by B, and logout-all on B ends A's session
    token_a = login_a.json()["token"]
    assert httpx.get(f"{b.base}/api/auth/me", headers={"Authorization": f"Bearer {token_a}"}, timeout=30).json()["user"]["email_verified"] is True
    assert httpx.post(f"{b.base}/api/auth/logout-all", headers={"Authorization": f"Bearer {token_a}"}, timeout=30).status_code == 200
    assert httpx.get(f"{a.base}/api/auth/me", headers={"Authorization": f"Bearer {token_a}"}, timeout=30).status_code == 401
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "l02_account_live_cross_worker.json").write_text(json.dumps({
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "workers": 2, "mail": "local sink (delivered to nobody)",
        "signup_response": r.status_code, "login_before_verify_on_both": 403, "link_open_on_B_spends_it": False, "confirm_on_B_verifies_for_A": True, "replay_on_A_refused": True,
        "session_from_A_valid_on_B": True, "logout_all_on_B_ends_A_session": True}, indent=2))


def test_login_failures_are_counted_across_workers(pair):
    a, b, sink = pair["a"], pair["b"], pair["sink"]
    from orca.auth.account_security import LOGIN_MAX_FAILURES

    email = f"lock-{uuid.uuid4().hex[:8]}@example.com"
    httpx.post(f"{a.base}/api/auth/signup", json={"email": email, "password": PW, "name": "T"}, timeout=30)
    tok = _token(_mails(sink, email)[-1])
    httpx.post(f"{a.base}/api/auth/verify", data={"token": tok}, timeout=30)
    codes = []
    for i in range(LOGIN_MAX_FAILURES):                                      # failures alternate between the two workers (and are not blocked by the per-IP limit: it is 10/5min)
        base = a.base if i % 2 == 0 else b.base
        codes.append(httpx.post(f"{base}/api/auth/login", json={"email": email, "password": "wrong-wrong"}, timeout=30).status_code)
        if codes[-1] == 429 and i < LOGIN_MAX_FAILURES - 1:
            break
    locked = httpx.post(f"{b.base}/api/auth/login", json={"email": email, "password": PW}, timeout=30)
    assert locked.status_code in (429,), (codes, locked.status_code)
    assert locked.json().get("code") in ("too_many_attempts", "rate_limited")
