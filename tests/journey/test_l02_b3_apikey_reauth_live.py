"""L02-B3 -- API-key step-up against REAL ``orca serve`` workers sharing one auth database (evidence class: LIVE_API, fixture provider, no mail).

A session token alone must not mint a key; password (+ TOTP when enabled) must; a TOTP code must not work twice, including on the OTHER worker; an API key
must not mint a key; repeated failures lock creation on both workers.
Run:  pytest tests/journey/test_l02_b3_apikey_reauth_live.py -p no:cacheprovider -v
"""
from __future__ import annotations

import json
import os
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
    home = tmp_path_factory.mktemp("l02-b3")
    env = {"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host, "ORNEUR_DELETION_SWEEP_S": "3600"}
    a, b = LiveServer(home, extra_env=env), LiveServer(home, extra_env=env)
    try:
        a.wait_ready()
        b.wait_ready()
        yield a, b
    finally:
        a.stop(); b.stop(); fake.__exit__(None, None, None)


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _signup(base):
    email = f"b3-{uuid.uuid4().hex[:8]}@example.com"
    r = httpx.post(f"{base}/api/auth/signup", json={"email": email, "password": PW, "name": "T"}, timeout=30)
    assert r.status_code == 200, r.text
    return email, r.json()["token"]


def test_live_stepup_on_two_real_workers(pair):
    from orca.auth.totp import totp_now

    a, b = pair
    _signup(a.base)  # the first account on a fresh install is the owner; use ordinary members below
    email, tok = _signup(a.base)
    out = {}

    r = httpx.post(f"{a.base}/api/auth/apikeys", json={"name": "x"}, headers=_h(tok), timeout=30)
    out["session_only"] = [r.status_code, r.json().get("code")]
    assert r.status_code in (401, 403) and r.json()["code"] == "reauth_required"

    r = httpx.post(f"{a.base}/api/auth/apikeys", json={"name": "x", "password": PW}, headers=_h(tok), timeout=30)
    assert r.status_code == 200
    raw = r.json()["key"]
    out["password_creates"] = r.status_code

    r = httpx.post(f"{b.base}/api/auth/apikeys", json={"name": "y", "password": PW}, headers=_h(raw), timeout=30)
    out["api_key_only"] = [r.status_code, r.json().get("code")]
    assert r.status_code == 403 and r.json()["code"] == "reauth_requires_session"

    # enable 2FA, then password alone is refused and a code works once, on either worker
    secret = httpx.post(f"{a.base}/api/auth/2fa/setup", headers=_h(tok), timeout=30).json()["secret"]
    assert httpx.post(f"{a.base}/api/auth/2fa/enable", json={"code": totp_now(secret)}, headers=_h(tok), timeout=30).status_code == 200
    r = httpx.post(f"{b.base}/api/auth/apikeys", json={"name": "z", "password": PW}, headers=_h(tok), timeout=30)
    out["mfa_password_only"] = [r.status_code, r.json().get("code")]
    assert r.status_code == 401
    code = totp_now(secret, time.time() + 31)
    ok = httpx.post(f"{a.base}/api/auth/apikeys", json={"name": "z", "password": PW, "totp_code": code}, headers=_h(tok), timeout=30)
    replay = httpx.post(f"{b.base}/api/auth/apikeys", json={"name": "z2", "password": PW, "totp_code": code}, headers=_h(tok), timeout=30)
    out["mfa_code_first_worker_a"], out["mfa_code_replay_worker_b"] = ok.status_code, [replay.status_code, replay.json().get("code")]
    assert ok.status_code == 200 and replay.status_code == 401

    # lockout is shared: failures on A lock creation on B
    for _ in range(8):
        httpx.post(f"{a.base}/api/auth/apikeys", json={"name": "k", "password": "wrong-wrong-wrong"}, headers=_h(tok), timeout=30)
    locked = httpx.post(f"{b.base}/api/auth/apikeys", json={"name": "k", "password": PW, "totp_code": totp_now(secret, time.time() - 31)}, headers=_h(tok), timeout=30)
    out["lockout_seen_on_other_worker"] = [locked.status_code, locked.json().get("code")]
    assert locked.status_code == 429 and locked.json()["code"] == "too_many_attempts"
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "b3_apikey_reauth_live_two_workers.json").write_text(json.dumps(out, indent=1))
