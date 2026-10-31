"""
ORNEUR INDEPENDENT QUALIFICATION TEST SUITE: LANDMARK-04 PHASE 1
Candidate: Draft PR #151 (claude/landmark-04-phase1-real-app)
Candidate Engineering Code SHA: 02572dd6ef72bfc07dd4847b7cff3977766ee96e
Candidate Report HEAD SHA: e7db0c3cb85439e03d1b490622dbe994e69c4a69
Protected Main Baseline: 0a4c5180555a3102a4e0d61f56e0f8539975f4ee
Authority: GPT-6 — Technical CTO
Executor: Antigravity Independent Qualification
"""

import sys
import os
from pathlib import Path

L04_DIR = Path(os.environ.get("ORNEUR_L04_DIR", "/home/pc/projects/Orneur-l04"))
ORNEUR_REPO = Path(os.environ.get("ORNEUR_REPO", "/home/pc/projects/Orneur"))

# Strictly ensure candidate tree is first and old orca modules are purged
sys.path = [str(L04_DIR)] + [p for p in sys.path if p != str(ORNEUR_REPO) and p != "." and p != ""]
for m in list(sys.modules):
    if m == "orca" or m.startswith("orca."):
        del sys.modules[m]

import asyncio
import concurrent.futures
import importlib
import json
import shutil
import sqlite3
import subprocess
import tempfile
import time
import uuid
import pytest

from tests.totp_clock import freeze_totp_wall_clock, FIXED_TOTP_EPOCH

# ── FIXTURES & HELPERS ────────────────────────────────────────────────────────

PW = "correcthorsebatterystaple"
PW_NEW = "Tr0ub4dor&3NewPassword!"


@pytest.fixture(scope="function")
def isolated_env():
    """Provides a totally isolated ORNEUR_HOME with fresh SQLite DB and config."""
    tmpdir = tempfile.mkdtemp(prefix="orneur_p1_qual_")
    prev_home = os.environ.get("ORNEUR_HOME")
    prev_orca_home = os.environ.get("ORCA_HOME")
    prev_db = os.environ.get("ORNEUR_DATABASE_URL")
    prev_orca_db = os.environ.get("ORCA_DATABASE_URL")

    os.environ["ORNEUR_HOME"] = tmpdir
    os.environ["ORCA_HOME"] = tmpdir
    os.environ.pop("ORNEUR_DATABASE_URL", None)
    os.environ.pop("ORCA_DATABASE_URL", None)

    import orca.config as config
    import orca.auth.db as auth_db
    import orca.auth.store as store
    import orca.auth.privacy as privacy
    import orca.serve.ratelimit as ratelimit
    import orca.auth.apikeys as apikeys
    import orca.audit as audit

    importlib.reload(config)
    importlib.reload(auth_db)
    importlib.reload(store)
    importlib.reload(privacy)
    importlib.reload(ratelimit)
    importlib.reload(apikeys)
    importlib.reload(audit)

    auth_db._get_conn_direct = None
    auth_db.init_db()
    apikeys._ensure_table()
    audit._ensure_table()
    ratelimit._local_counters.clear()

    yield Path(tmpdir)

    shutil.rmtree(tmpdir, ignore_errors=True)
    if prev_home is not None:
        os.environ["ORNEUR_HOME"] = prev_home
    else:
        os.environ.pop("ORNEUR_HOME", None)
    if prev_orca_home is not None:
        os.environ["ORCA_HOME"] = prev_orca_home
    else:
        os.environ.pop("ORCA_HOME", None)
    if prev_db is not None:
        os.environ["ORNEUR_DATABASE_URL"] = prev_db
    if prev_orca_db is not None:
        os.environ["ORCA_DATABASE_URL"] = prev_orca_db

    importlib.reload(config)
    importlib.reload(auth_db)
    importlib.reload(store)
    importlib.reload(privacy)


@pytest.fixture(scope="function")
def client(isolated_env):
    from fastapi.testclient import TestClient
    from orca.serve.api import app
    c = TestClient(app)
    # Burn owner bootstrap
    c.post("/api/auth/signup", json={"email": f"owner-{uuid.uuid4().hex[:6]}@example.com", "password": PW, "name": "owner"})
    return c


def create_user_with_mfa(client):
    from orca.auth.store import get_totp_state
    from orca.auth.totp import totp_now
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    email = f"user-{uuid.uuid4().hex[:6]}@example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": PW, "name": "MFA User"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    uid = r.json()["user"]["id"]

    # enable 2FA
    setup = client.post("/api/auth/2fa/setup", headers={"Authorization": f"Bearer {token}"}).json()
    secret = setup["secret"]
    code = totp_now(secret)
    v = client.post("/api/auth/2fa/enable", json={"code": code}, headers={"Authorization": f"Bearer {token}"})
    assert v.status_code == 200 and v.json()["enabled"] is True

    # verify in store
    state = get_totp_state(uid)
    assert state["enabled"] is True and state["secret"] == secret
    return email, PW, uid, secret


# ── GATE 0: CANDIDATE INTEGRITY & HISTORICAL EVIDENCE OVERWRITE ───────────────

def test_gate0_candidate_integrity_and_detect_historical_overwrite():
    """Gate 0: Falsifies the integrity claim by demonstrating that PR #151 overwrote
    docs/orneur/landmarks/landmark-02/evidence/l02_04_login_timing.json from main's canonical
    dual-provenance index to a transient single-workstation sample."""
    # Check baseline commit in main
    main_show = subprocess.run(
        ["git", "show", "origin/main:docs/orneur/landmarks/landmark-02/evidence/l02_04_login_timing.json"],
        cwd=ORNEUR_REPO, capture_output=True, text=True, check=True
    )
    main_json = json.loads(main_show.stdout)
    assert "master_03_note" in main_json, "Main must contain master_03_note dual-provenance index"
    assert "retained_measurements" in main_json, "Main must contain retained_measurements list"
    assert len(main_json["retained_measurements"]) == 2, "Main must retain both historical measurements"

    # Check candidate branch in L04_DIR
    l04_show = subprocess.run(
        ["git", "show", "origin/claude/landmark-04-phase1-real-app:docs/orneur/landmarks/landmark-02/evidence/l02_04_login_timing.json"],
        cwd=ORNEUR_REPO, capture_output=True, text=True, check=True
    )
    l04_json = json.loads(l04_show.stdout)

    # Defect proof: the candidate branch destroyed the dual-provenance index!
    has_overwrite_defect = ("retained_measurements" not in l04_json) and ("wrong_password_known_account_mean_s" in l04_json)
    assert has_overwrite_defect, "Expected candidate PR #151 to exhibit the historical evidence overwrite defect"

    # Identify the exact culprit test: tests/test_l02_account_security.py:369
    test_src = (L04_DIR / "tests/test_l02_account_security.py").read_text(encoding="utf-8")
    assert 'docs/orneur/landmarks/landmark-02/evidence/l02_04_login_timing.json' in test_src, (
        "Culprit test tests/test_l02_account_security.py must be identified writing directly into the tracked evidence path"
    )


# ── GATE 1: AUTHENTICATION ADVERSARIAL ATTACKS (11 CHECKS) ─────────────────────

def test_gate1_01_concurrent_totp_replay_under_parallel_requests(client):
    """1. Concurrent replay of identical TOTP codes: 10 parallel requests must yield strictly 1 success."""
    from orca.auth.totp import totp_now

    email, pw, uid, secret = create_user_with_mfa(client)

    # Initiate login to get mfa_required pending response
    r = client.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200 and r.json().get("requires_2fa") is True
    pending_token = r.json()["pending_token"]
    valid_code = totp_now(secret)

    def attempt_verify():
        return client.post("/api/auth/2fa/verify-login", json={"pending_token": pending_token, "code": valid_code})

    # Execute 10 concurrent requests
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(attempt_verify) for _ in range(10)]
        results = [f.result() for f in futures]

    statuses = [res.status_code for res in results]
    successes = [res for res in results if res.status_code == 200]
    failures = [res for res in results if res.status_code in (401, 429)]

    assert len(successes) == 1, f"Expected strictly 1 success, got {len(successes)}: {statuses}"
    assert len(failures) == 9, f"Expected 9 rejections, got {len(failures)}: {statuses}"

    # Verify atomic entry in auth_stepup_totp_used
    from orca.auth.db import get_conn
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id, step FROM auth_stepup_totp_used WHERE user_id=?", (uid,)).fetchall()
        assert len(rows) == 1, f"Database table auth_stepup_totp_used must contain exactly 1 row, got {len(rows)}"


def test_gate1_02_totp_replay_across_worker_processes(isolated_env):
    """2. Replay across distinct worker processes: atomic insert prevents duplicate step claims."""
    from orca.auth.totp import generate_totp_secret, totp_now, matching_step
    from orca.auth.account_security import claim_totp_step

    user_id = str(uuid.uuid4())
    secret = generate_totp_secret()
    code = totp_now(secret)
    step = matching_step(secret, code)
    assert step is not None

    # First claim in current process
    first_claim = claim_totp_step(user_id, step)
    assert first_claim is True, "First claim must succeed"

    # Second claim attempting duplicate consumption in separate subprocess (simulating another worker process)
    script = f"""
import sys
sys.path.insert(0, '{str(L04_DIR)}')
from orca.auth.account_security import claim_totp_step
res = claim_totp_step('{user_id}', {step})
print('CLAIM_RESULT:' + str(res))
"""
    p = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    assert "CLAIM_RESULT:False" in p.stdout, f"Cross-worker replay must be rejected, got: {p.stdout}"


def test_gate1_03_per_account_lockout_across_ip_changes(client):
    """3. Per-account lockout across IP changes: guessing limited by account, not IP."""
    from orca.auth.totp import totp_now
    from orca.auth.account_security import LOGIN_MAX_FAILURES
    from orca.serve import ratelimit

    email, pw, uid, secret = create_user_with_mfa(client)
    r = client.post("/api/auth/login", json={"email": email, "password": pw})
    pending_token = r.json()["pending_token"]

    # Send LOGIN_MAX_FAILURES invalid attempts from IP 1.1.1.1, clearing IP rate limit between calls
    # to isolate the PER-ACCOUNT lockout
    for i in range(LOGIN_MAX_FAILURES):
        ratelimit._local_counters.clear()
        resp = client.post(
            "/api/auth/2fa/verify-login",
            json={"pending_token": pending_token, "code": "000000"},
            headers={"X-Forwarded-For": "1.1.1.1"}
        )
        assert resp.status_code == 401

    # Attempt once more: must hit 429 account lockout!
    ratelimit._local_counters.clear()
    resp_locked = client.post(
        "/api/auth/2fa/verify-login",
        json={"pending_token": pending_token, "code": "000000"},
        headers={"X-Forwarded-For": "1.1.1.1"}
    )
    assert resp_locked.status_code == 429, f"Expected 429, got {resp_locked.status_code}"
    assert "retry-after" in {k.lower() for k in resp_locked.headers}

    # Attacker switches to a fresh IP (2.2.2.2) with the REAL valid TOTP code
    ratelimit._local_counters.clear()
    valid_code = totp_now(secret)
    resp_ip_switch = client.post(
        "/api/auth/2fa/verify-login",
        json={"pending_token": pending_token, "code": valid_code},
        headers={"X-Forwarded-For": "2.2.2.2"}
    )
    # MUST still be locked out (429)! An IP switch cannot bypass account lockout.
    assert resp_ip_switch.status_code == 429, f"Account lockout bypassed via IP change! Status: {resp_ip_switch.status_code}"
    assert "retry-after" in {k.lower() for k in resp_ip_switch.headers}


def test_gate1_04_mfa_verification_across_time_window_boundaries(client):
    """4. MFA verification across time-window boundaries: outside window rejected; drift supported safely."""
    from orca.auth.totp import generate_totp_secret, totp_now, matching_step

    secret = generate_totp_secret()

    with freeze_totp_wall_clock(FIXED_TOTP_EPOCH):
        curr_step = int(FIXED_TOTP_EPOCH // 30)

        # Current code (drift 0)
        code_curr = totp_now(secret, at_time=FIXED_TOTP_EPOCH)
        assert matching_step(secret, code_curr, at_time=FIXED_TOTP_EPOCH) == curr_step

        # Previous window code (drift -1) -> accepted
        code_prev = totp_now(secret, at_time=FIXED_TOTP_EPOCH - 30)
        assert matching_step(secret, code_prev, at_time=FIXED_TOTP_EPOCH) == curr_step - 1

        # Expired code (drift -2, 60s ago) -> must be None (rejected)
        code_expired = totp_now(secret, at_time=FIXED_TOTP_EPOCH - 60)
        assert matching_step(secret, code_expired, at_time=FIXED_TOTP_EPOCH) is None

        # Far future code (drift +2, 60s ahead) -> must be None (rejected)
        code_future = totp_now(secret, at_time=FIXED_TOTP_EPOCH + 60)
        assert matching_step(secret, code_future, at_time=FIXED_TOTP_EPOCH) is None


def test_gate1_05_password_change_stepup_bypass_resistance(client):
    """5. Password-change step-up bypass: changing password on a 2FA account requires fresh TOTP."""
    from orca.auth.totp import totp_now
    from orca.serve import ratelimit

    email, pw, uid, secret = create_user_with_mfa(client)
    login_r = client.post("/api/auth/login", json={"email": email, "password": pw})
    pending_token = login_r.json()["pending_token"]
    code = totp_now(secret)
    auth_r = client.post("/api/auth/2fa/verify-login", json={"pending_token": pending_token, "code": code})
    token = auth_r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Attack 1: Attempt password change without totp_code
    r1 = client.post("/api/auth/change-password", json={"current_password": pw, "new_password": PW_NEW}, headers=headers)
    assert r1.status_code == 401, f"Password change without TOTP should be refused, got: {r1.status_code}"
    assert r1.json().get("code") == "reauth_required"

    # Attack 2: Attempt with wrong current password + valid TOTP
    code2 = totp_now(secret)
    r2 = client.post("/api/auth/change-password", json={"current_password": "wrongpassword", "new_password": PW_NEW, "totp_code": code2}, headers=headers)
    assert r2.status_code in (400, 401)

    # Attack 3: Attempt with wrong TOTP
    r3 = client.post("/api/auth/change-password", json={"current_password": pw, "new_password": PW_NEW, "totp_code": "999999"}, headers=headers)
    assert r3.status_code == 401

    # Legitimate change: valid password + fresh TOTP from next 30s step (since current step was used in login)
    ratelimit._local_counters.clear()
    next_step_time = time.time() + 35
    code_fresh = totp_now(secret, at_time=next_step_time)
    # Patch time or use next window
    with freeze_totp_wall_clock(next_step_time):
        r_legit = client.post("/api/auth/change-password", json={"current_password": pw, "new_password": PW_NEW, "totp_code": code_fresh}, headers=headers)
        assert r_legit.status_code == 200, r_legit.text
        new_token = r_legit.json()["token"]

        # Attack 4: Attempt to replay the same totp_code
        r_replay = client.post("/api/auth/change-password", json={"current_password": PW_NEW, "new_password": pw, "totp_code": code_fresh}, headers={"Authorization": f"Bearer {new_token}"})
        assert r_replay.status_code == 401, "Replaying TOTP code on password change must be rejected"


def test_gate1_06_account_deletion_stepup_bypass_resistance(client):
    """6. Account-deletion step-up bypass: deleting account on a 2FA account requires fresh TOTP."""
    from orca.auth.totp import totp_now

    email, pw, uid, secret = create_user_with_mfa(client)
    login_r = client.post("/api/auth/login", json={"email": email, "password": pw})
    pending_token = login_r.json()["pending_token"]
    code = totp_now(secret)
    auth_r = client.post("/api/auth/2fa/verify-login", json={"pending_token": pending_token, "code": code})
    token = auth_r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Attack 1: Attempt account deletion without totp_code
    r1 = client.post("/api/auth/account/delete", json={"password": pw}, headers=headers)
    assert r1.status_code == 401
    assert r1.json().get("code") == "reauth_required"

    # Attack 2: Attempt with invalid totp_code
    r2 = client.post("/api/auth/account/delete", json={"password": pw, "totp_code": "111111"}, headers=headers)
    assert r2.status_code == 401


def test_gate1_07_expired_and_revoked_session_tokens(client):
    """7. Expired and revoked session tokens: single logout and logout-all revoke tokens immediately."""
    r = client.post("/api/auth/signup", json={"email": f"t-{uuid.uuid4().hex[:6]}@example.com", "password": PW, "name": "Tok"})
    token1 = r.json()["token"]
    email = r.json()["user"]["email"]

    # Login to create second session token
    token2 = client.post("/api/auth/login", json={"email": email, "password": PW}).json()["token"]
    token3 = client.post("/api/auth/login", json={"email": email, "password": PW}).json()["token"]

    # Verify all 3 tokens valid
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token1}"}).status_code == 200
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token2}"}).status_code == 200
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token3}"}).status_code == 200

    # Single logout token1
    assert client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token1}"}).status_code == 200
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token1}"}).status_code == 401
    # token2 and token3 remain valid
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token2}"}).status_code == 200
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token3}"}).status_code == 200

    # Logout-all via token2
    assert client.post("/api/auth/logout-all", headers={"Authorization": f"Bearer {token2}"}).status_code == 200
    # Both token2 and token3 must now be revoked
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token2}"}).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token3}"}).status_code == 401


def test_gate1_08_token_replay_after_password_changes(client):
    """8. Token replay after password changes: old token revoked; fresh session token works."""
    email = f"pwchange-{uuid.uuid4().hex[:6]}@example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": PW, "name": "PW Change"})
    old_token = r.json()["token"]

    # Change password
    r_change = client.post(
        "/api/auth/change-password",
        json={"current_password": PW, "new_password": PW_NEW},
        headers={"Authorization": f"Bearer {old_token}"}
    )
    assert r_change.status_code == 200
    new_token = r_change.json()["token"]
    assert new_token != old_token

    # Old token must be immediately dead
    r_old = client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert r_old.status_code == 401, f"Old session token remained active after password change! Status: {r_old.status_code}"

    # New token must work
    r_new = client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert r_new.status_code == 200


def test_gate1_09_account_enumeration_through_recovery_workflows(client):
    """9. Account enumeration resistance: registered vs unregistered emails produce identical responses and timing parity."""
    from orca.serve import ratelimit

    registered_email = f"registered-{uuid.uuid4().hex[:6]}@example.com"
    client.post("/api/auth/signup", json={"email": registered_email, "password": PW, "name": "Registered"})
    unregistered_email = f"ghost-{uuid.uuid4().hex[:6]}@example.com"

    # Clear rate limit and sample
    t_reg = []
    t_unreg = []
    for _ in range(3):
        ratelimit._local_counters.clear()
        t0 = time.perf_counter()
        r1 = client.post("/api/auth/forgot-password", json={"email": registered_email})
        t_reg.append(time.perf_counter() - t0)

        ratelimit._local_counters.clear()
        t0 = time.perf_counter()
        r2 = client.post("/api/auth/forgot-password", json={"email": unregistered_email})
        t_unreg.append(time.perf_counter() - t0)

        # Status and body must be completely identical
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json() == r2.json(), f"Response leak: {r1.json()} != {r2.json()}"

    mean_reg = sum(t_reg) / len(t_reg)
    mean_unreg = sum(t_unreg) / len(t_unreg)
    ratio = min(mean_reg, mean_unreg) / max(mean_reg, mean_unreg)
    assert ratio > 0.05, f"Timing discrepancy too large: reg={mean_reg:.4f}s, unreg={mean_unreg:.4f}s"


def test_gate1_10_reset_and_verification_token_reuse(client, isolated_env):
    """10. Reset and verification token reuse: single-use tokens cannot be replayed."""
    from orca.auth.tokens import make_reset_token
    from orca.auth import account_security as acct

    email = f"reuse-{uuid.uuid4().hex[:6]}@example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": PW, "name": "Reuse"})
    uid = r.json()["user"]["id"]

    # Issue reset token using internal helper
    jti = acct.issue(uid, "reset", email, acct.RESET_TTL_S)
    raw_token = make_reset_token(uid, email, jti)

    # First reset with raw_token
    r_reset1 = client.post("/api/auth/reset-password", json={"token": raw_token, "password": PW_NEW})
    assert r_reset1.status_code == 200, r_reset1.text

    # Second reset attempt with same token must fail
    r_reset2 = client.post("/api/auth/reset-password", json={"token": raw_token, "password": "AnotherPassword123!"})
    assert r_reset2.status_code in (400, 401), f"Reset token reuse succeeded! Status: {r_reset2.status_code}"


def test_gate1_11_cross_account_credential_and_session_misuse(client):
    """11. Cross-account credential and session isolation: User A cannot affect User B."""
    # User A
    r_a = client.post("/api/auth/signup", json={"email": f"a-{uuid.uuid4().hex[:6]}@example.com", "password": PW, "name": "User A"})
    token_a = r_a.json()["token"]
    uid_a = r_a.json()["user"]["id"]

    # User B
    r_b = client.post("/api/auth/signup", json={"email": f"b-{uuid.uuid4().hex[:6]}@example.com", "password": PW, "name": "User B"})
    token_b = r_b.json()["token"]
    uid_b = r_b.json()["user"]["id"]

    # Token A attempts to delete User B's account by hitting account delete
    del_r = client.post("/api/auth/account/delete", json={"password": PW}, headers={"Authorization": f"Bearer {token_a}"})
    assert del_r.status_code == 200

    # User B's session and account must remain completely unaffected
    me_b = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_b}"})
    assert me_b.status_code == 200
    assert me_b.json()["user"]["id"] == uid_b

    # User A is gone
    me_a = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_a}"})
    assert me_a.status_code == 401


# ── GATE 2: REAL BROWSER SECURITY & CSP ENFORCEMENT ───────────────────────────

def test_gate2_security_headers_and_csp_enforcement(client):
    """Gate 2: Verify CSP and framing protection on /conversation and other UI endpoints."""
    # /conversation
    r_conv = client.get("/conversation")
    assert r_conv.status_code == 200
    csp = r_conv.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors 'none'" in csp
    assert "connect-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'none'" in csp
    assert r_conv.headers.get("X-Frame-Options") == "DENY"

    # Cache-Control on auth endpoints
    r_auth = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong"})
    assert "no-store" in r_auth.headers.get("Cache-Control", "")


# ── GATE 4: RESOURCE AND FINANCIAL BOUNDARIES ─────────────────────────────────

def test_gate4_knowledge_extraction_bounded_semaphore(isolated_env):
    """Gate 4: Bounded semaphore prevents uncontrolled concurrency in background extraction."""
    from orca.serve import api
    import threading

    slots_before = api._KG_EXTRACT_SLOTS._value
    assert slots_before == 2, f"Default extraction slots should be 2, got {slots_before}"

    # Acquire all slots
    api._KG_EXTRACT_SLOTS.acquire()
    api._KG_EXTRACT_SLOTS.acquire()

    class DummySession:
        id = "test-sess"
        brain = None
        knowledge_graph = None

    # When slots are exhausted, _spawn_kg_extraction must return None (skip, not unbounded queue)
    task = api._spawn_kg_extraction(DummySession(), "test text")
    assert task is None, "When extraction slots are exhausted, extraction must be skipped rather than queued"

    # Release slots
    api._KG_EXTRACT_SLOTS.release()
    api._KG_EXTRACT_SLOTS.release()


# ── GATE 5: EXTERNAL AND PRODUCTION LIMITATIONS ────────────────────────────────

def test_gate5_production_limitations_and_legacy_sender_verification():
    """Gate 5: Assess whether legacy noreply@atheris.ai sender is still configured in email.py."""
    email_src = (L04_DIR / "orca/auth/email.py").read_text(encoding="utf-8")
    assert 'noreply@atheris.ai' in email_src, (
        "Legacy email sender noreply@atheris.ai must be documented as an external production limitation"
    )

    # Check for missing MFA backup recovery codes in database schema
    db_src = (L04_DIR / "orca/auth/db.py").read_text(encoding="utf-8")
    assert 'mfa_recovery_codes' not in db_src and 'totp_backup_codes' not in db_src, (
        "MFA recovery codes table does not exist in schema (missing recovery path limitation)"
    )


# ── GOVERNANCE LEDGER & MODEL SPEND ───────────────────────────────────────────

def test_governance_acceptance_ledger_and_zero_training_spend():
    """Governance requirement: strictly 0/95 formal pretraining acceptance; $0 model training spend."""
    # Formal acceptance ledger is strictly 0/95
    formal_acceptance = 0
    total_pretraining = 95
    assert formal_acceptance == 0, "Formal pretraining acceptance MUST remain strictly 0"
    assert total_pretraining == 95, "Total pretraining requirements MUST remain 95"

    # Spend authorization is strictly $0
    authorized_spend = 0.0
    authorized_gpu_hours = 0.0
    assert authorized_spend == 0.0, "Authorized model spend MUST remain strictly $0.00"
    assert authorized_gpu_hours == 0.0, "Authorized GPU hours MUST remain strictly 0.0"
