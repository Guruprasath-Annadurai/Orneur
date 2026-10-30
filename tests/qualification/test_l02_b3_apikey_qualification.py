"""ORNEUR — Independent Qualification Suite for PR #141 (L02-B3 API-Key Re-Authentication).
Authority: ORNEUR Independent Engineering, Security and Qualification Authority (Antigravity).
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

B3_WORKTREE = Path("/home/pc/projects/Orneur-b3")
L02_BASELINE = Path("/home/pc/projects/Orneur-l02")
AUDIT_REPO = Path("/home/pc/projects/Orneur")

CANDIDATE_HEAD = "66ce8aeace2077b89195735211d75ebd566716c8"
CODE_SHA = "283e3a464a3de1d0a420709a3f6602730023300d"
BASELINE_SHA = "38e0d311991875366f2bc88a39690c7b2b6ea3ee"
MAIN_SHA = "20a8546f5a1ece7e5af655c0f30ca7e305f71b1a"
PW = "Adversarial-Pass-91x!"


def _run_subp(cmd, cwd=AUDIT_REPO, env=None, check=True):
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(cmd)}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
    return p


# ── Gate 1: Provenance, Lineage, Clean Tree & Remote CI ───────────────────────────

def test_gate1_provenance_and_ci_verification():
    assert B3_WORKTREE.exists(), f"Worktree missing: {B3_WORKTREE}"
    head = subprocess.check_output(["git", "-C", str(B3_WORKTREE), "rev-parse", "HEAD"]).decode().strip()
    assert head == CANDIDATE_HEAD, f"HEAD mismatch: {head} != {CANDIDATE_HEAD}"

    status = subprocess.check_output(["git", "-C", str(B3_WORKTREE), "status", "--porcelain"]).decode().strip()
    assert status == "", f"Candidate worktree is dirty:\n{status}"

    # Merge base against PR #139 baseline
    base = subprocess.check_output(["git", "-C", str(B3_WORKTREE), "merge-base", CANDIDATE_HEAD, BASELINE_SHA]).decode().strip()
    assert base == BASELINE_SHA, f"Merge-base is not PR 139 baseline: {base}"

    # Verify Code SHA is direct parent of Evidence HEAD
    parent = subprocess.check_output(["git", "-C", str(B3_WORKTREE), "rev-parse", f"{CANDIDATE_HEAD}~1"]).decode().strip()
    assert parent == CODE_SHA, f"Code SHA mismatch: {parent} != {CODE_SHA}"

    # Remote GitHub Actions CI Verification for Evidence HEAD (Run 41018287582)
    ci_out = subprocess.check_output(["gh", "run", "view", "41018287582", "--repo", "Guruprasath-Annadurai/Orneur", "--json", "headSha,status,conclusion"]).decode().strip()
    ci_data = json.loads(ci_out)
    assert ci_data["headSha"] == CANDIDATE_HEAD and ci_data["status"] == "completed" and ci_data["conclusion"] == "success"

    # Remote GitHub Actions CI Verification for Code SHA (Run 41014535017)
    ci_code = subprocess.check_output(["gh", "run", "view", "41014535017", "--repo", "Guruprasath-Annadurai/Orneur", "--json", "headSha,status,conclusion"]).decode().strip()
    ci_code_data = json.loads(ci_code)
    assert ci_code_data["headSha"] == CODE_SHA and ci_code_data["status"] == "completed" and ci_code_data["conclusion"] == "success"

    # PR #141 state is DRAFT and OPEN
    pr_out = subprocess.check_output(["gh", "pr", "view", "141", "--repo", "Guruprasath-Annadurai/Orneur", "--json", "state,isDraft,headRefOid"]).decode().strip()
    pr_data = json.loads(pr_out)
    assert pr_data["state"] == "OPEN" and pr_data["isDraft"] is True and pr_data["headRefOid"] == CANDIDATE_HEAD


# ── Gate 2: Vulnerability Reproduction Against Baseline & Refusal on Candidate ────

def test_gate2_vulnerability_reproduction_and_candidate_refusal():
    # 1. Against baseline (Orneur-l02): POST /api/auth/apikeys with session token ONLY returns 200 OK (vulnerable!)
    code_baseline = """
import sys
sys.path.insert(0, '/home/pc/projects/Orneur-l02')
import uuid
from starlette.testclient import TestClient
from orca.serve.api import create_app
app = create_app()
client = TestClient(app)
email = f"vuln-{uuid.uuid4().hex[:8]}@example.com"
r_sign = client.post("/api/auth/signup", json={"email": email, "password": "Password123!", "name": "V"})
tok = r_sign.json()["token"]
# Call POST /api/auth/apikeys with session token and NO password
r = client.post("/api/auth/apikeys", json={"name": "test-key"}, headers={"Authorization": f"Bearer {tok}"})
print(f"BASELINE_STATUS:{r.status_code}")
"""
    p_base = _run_subp([sys.executable, "-c", code_baseline], cwd=L02_BASELINE)
    assert "BASELINE_STATUS:200" in p_base.stdout, f"Expected baseline to succeed (vulnerability): {p_base.stdout}"

    # 2. Against candidate (Orneur-b3): POST /api/auth/apikeys with session token ONLY returns 401 reauth_required
    code_candidate = """
import sys
sys.path.insert(0, '/home/pc/projects/Orneur-b3')
import uuid
from starlette.testclient import TestClient
from orca.serve.api import create_app
app = create_app()
client = TestClient(app)
email = f"cand-{uuid.uuid4().hex[:8]}@example.com"
r_sign = client.post("/api/auth/signup", json={"email": email, "password": "Password123!", "name": "C"})
tok = r_sign.json()["token"]
r = client.post("/api/auth/apikeys", json={"name": "test-key"}, headers={"Authorization": f"Bearer {tok}"})
print(f"CANDIDATE_STATUS:{r.status_code}")
print(f"CANDIDATE_CODE:{r.json().get('code')}")
"""
    p_cand = _run_subp([sys.executable, "-c", code_candidate], cwd=B3_WORKTREE)
    assert "CANDIDATE_STATUS:401" in p_cand.stdout, f"Expected candidate to refuse: {p_cand.stdout}"
    assert "CANDIDATE_CODE:reauth_required" in p_cand.stdout, f"Expected code reauth_required: {p_cand.stdout}"


# ── Gate 3: Password and MFA Boundary Adversarial Probes ─────────────────────────

def test_gate3_password_and_mfa_boundary_adversarial():
    code_boundary = """
import sys
sys.path.insert(0, '/home/pc/projects/Orneur-b3')
import time
import uuid
from starlette.testclient import TestClient
from orca.serve.api import create_app
from orca.auth.totp import totp_now

app = create_app()
client = TestClient(app)

PW = "Test-Password-91x!"
email1 = f"bnd1-{uuid.uuid4().hex[:8]}@example.com"
email2 = f"bnd2-{uuid.uuid4().hex[:8]}@example.com"

# Setup User 1 and User 2
tok1 = client.post("/api/auth/signup", json={"email": email1, "password": PW, "name": "U1"}).json()["token"]
tok2 = client.post("/api/auth/signup", json={"email": email2, "password": "User2-Pass-999!", "name": "U2"}).json()["token"]

h1 = {"Authorization": f"Bearer {tok1}"}

# Probe 1: Wrong password
r = client.post("/api/auth/apikeys", json={"name": "k", "password": "WrongPassword!"}, headers=h1)
assert r.status_code == 401 and r.json()["code"] == "reauth_failed", f"Wrong password failed: {r.text}"

# Probe 2: Missing password / blank / whitespace
for bad_pw in ["", "   ", None]:
    r = client.post("/api/auth/apikeys", json={"name": "k", "password": bad_pw}, headers=h1)
    assert r.status_code == 401 and r.json()["code"] == "reauth_required", f"Blank password failed: {r.text}"

# Probe 3: Other user's password
r = client.post("/api/auth/apikeys", json={"name": "k", "password": "User2-Pass-999!"}, headers=h1)
assert r.status_code == 401 and r.json()["code"] == "reauth_failed", f"Other password failed: {r.text}"

# Probe 4: 2FA account checks
sec = client.post("/api/auth/2fa/setup", headers=h1).json()["secret"]
client.post("/api/auth/2fa/enable", json={"code": totp_now(sec)}, headers=h1)

# 2FA enabled, password only -> refusal
r = client.post("/api/auth/apikeys", json={"name": "k", "password": PW}, headers=h1)
assert r.status_code == 401 and r.json()["code"] == "reauth_failed", f"MFA missing code failed: {r.text}"

# 2FA enabled, wrong code -> refusal
r = client.post("/api/auth/apikeys", json={"name": "k", "password": PW, "totp_code": "000000"}, headers=h1)
assert r.status_code == 401 and r.json()["code"] == "reauth_failed", f"MFA wrong code failed: {r.text}"

# 2FA enabled, valid code -> success
code_valid = totp_now(sec, time.time() + 31)
r_ok = client.post("/api/auth/apikeys", json={"name": "k-ok", "password": PW, "totp_code": code_valid}, headers=h1)
assert r_ok.status_code == 200, f"MFA valid code failed: {r_ok.text}"
key_raw = r_ok.json()["key"]

# 2FA replayed code -> refusal
r_replay = client.post("/api/auth/apikeys", json={"name": "k-replay", "password": PW, "totp_code": code_valid}, headers=h1)
assert r_replay.status_code == 401 and r_replay.json()["code"] == "reauth_failed", f"MFA replay failed: {r_replay.text}"

# Probe 5: API-key-as-bearer cannot mint an API key
r_keybearer = client.post("/api/auth/apikeys", json={"name": "k-sub", "password": PW}, headers={"Authorization": f"Bearer {key_raw}"})
assert r_keybearer.status_code == 403 and r_keybearer.json()["code"] == "reauth_requires_session", f"API key bearer failed: {r_keybearer.text}"

# Probe 6: Revoked session cannot create a key
client.post("/api/auth/logout", headers=h1)
r_revoked = client.post("/api/auth/apikeys", json={"name": "k", "password": PW}, headers=h1)
assert r_revoked.status_code == 401, f"Revoked session failed: {r_revoked.text}"

print("GATE3_PROBES_PASSED")
"""
    p = _run_subp([sys.executable, "-c", code_boundary], cwd=B3_WORKTREE)
    assert "GATE3_PROBES_PASSED" in p.stdout


# ── Gate 4: Genuine Simultaneous Attempts Sharing PostgreSQL ───────────────────

def test_gate4_simultaneous_postgres_totp_atomicity(tmp_path):
    pytest.importorskip("pgserver")
    import pgserver

    pg_dir = tmp_path / "pgdata"
    pg_dir.mkdir(parents=True, exist_ok=True)
    srv = pgserver.get_server(str(pg_dir), cleanup_mode="stop")
    base_uri = srv.get_uri()
    db_name = "t_simul_" + uuid.uuid4().hex[:8]
    srv.psql(f"CREATE DATABASE {db_name};")
    pg_url = base_uri.replace("/postgres?", f"/{db_name}?")

    code_pg_simultaneous = f"""
import os
import sys
sys.path.insert(0, '/home/pc/projects/Orneur-b3')
import concurrent.futures
import time
import uuid
from orca.auth import db, account_security as acct

db.init_db()

uid = "user-simul-" + uuid.uuid4().hex[:8]
step = 44556677

# Execute two simultaneous claims on PostgreSQL using a ThreadPoolExecutor
def attempt_claim(worker_id):
    return worker_id, acct.claim_totp_step(uid, step)

with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
    f1 = ex.submit(attempt_claim, "worker_1")
    f2 = ex.submit(attempt_claim, "worker_2")
    results = [f1.result(), f2.result()]

claims = [res[1] for res in results]
true_count = claims.count(True)
false_count = claims.count(False)

print(f"PG_RESULTS:{{results}}")
print(f"PG_TRUE_COUNT:{{true_count}}")
print(f"PG_FALSE_COUNT:{{false_count}}")

# Verify database-level row count in auth_stepup_totp_used (column is 'step', not 'time_step')
with db.get_conn() as conn:
    row = conn.execute("SELECT count(*) as cnt FROM auth_stepup_totp_used WHERE user_id = %s AND step = %s;", (uid, step)).fetchone()
    db_count = row["cnt"]
    print(f"PG_DB_ROW_COUNT:{{db_count}}")
"""
    try:
        p = _run_subp([sys.executable, "-c", code_pg_simultaneous], cwd=B3_WORKTREE, env={"ORNEUR_DATABASE_URL": pg_url})
        assert "PG_TRUE_COUNT:1" in p.stdout, f"Expected exactly 1 claim to succeed: {p.stdout}"
        assert "PG_FALSE_COUNT:1" in p.stdout, f"Expected exactly 1 claim to fail: {p.stdout}"
        assert "PG_DB_ROW_COUNT:1" in p.stdout, f"Expected exactly 1 DB row inserted: {p.stdout}"
    finally:
        srv.cleanup()


# ── Gate 5: Rate Limiting and Forged X-Forwarded-For Analysis ─────────────────────

def test_gate5_rate_limits_and_xff_forgery_analysis():
    code_ratelimit = """
import sys
sys.path.insert(0, '/home/pc/projects/Orneur-b3')
import os
import uuid
from starlette.testclient import TestClient
from orca.serve.api import create_app
from orca.serve import ratelimit
from orca.auth import account_security as acct

app = create_app()
client = TestClient(app)

PW = "Ratelimit-Pass-123!"
email = f"rate-{uuid.uuid4().hex[:8]}@example.com"
r_sign = client.post("/api/auth/signup", json={"email": email, "password": PW, "name": "R"}).json()
tok = r_sign["token"]
user_id = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()["user"]["id"]
h = {"Authorization": f"Bearer {tok}"}

# 1. Per-account lockout: 8 failed attempts in 15 mins -> 429 too_many_attempts
for i in range(8):
    ratelimit._local_counters.clear()
    r = client.post("/api/auth/apikeys", json={"name": f"k{i}", "password": "wrong"}, headers=h)
    assert r.status_code == 401

# 9th attempt with CORRECT password must now be rejected with 429 too_many_attempts
ratelimit._local_counters.clear()
r_locked = client.post("/api/auth/apikeys", json={"name": "k-locked", "password": PW}, headers=h)
assert r_locked.status_code == 429 and r_locked.json()["code"] == "too_many_attempts", f"Account lock failed: {r_locked.text}"
print("ACCOUNT_LOCKOUT_VERIFIED")

# 2. Per-IP limiter: AUTH_LOGIN rule (10 attempts / 5 mins)
ratelimit._local_counters.clear()
acct.clear_stepup_failures(user_id) # clear account failures so only IP rate limiter triggers

# Perform 10 failed requests while clearing account failures before each, so account lockout doesn't intercept
for j in range(10):
    acct.clear_stepup_failures(user_id)
    client.post("/api/auth/apikeys", json={"name": f"k{j}", "password": "wrong"}, headers=h)

# 11th attempt on the same IP must hit the 429 IP rate limit
acct.clear_stepup_failures(user_id)
r_ip_limited = client.post("/api/auth/apikeys", json={"name": "k-ip", "password": "wrong"}, headers=h)
assert r_ip_limited.status_code == 429 and r_ip_limited.json().get("code") == "rate_limited", f"Per-IP limit failed: {r_ip_limited.text}"
print("PER_IP_LIMIT_VERIFIED")

# 3. Inherited Vulnerability Investigation: Forged X-Forwarded-For under default settings
# By default, ORNEUR_TRUSTED_PROXY_CIDRS is unset, so ratelimit.get_client_ip trusts the first entry of X-Forwarded-For
r_forged = client.post("/api/auth/apikeys", json={"name": "k-forged", "password": "wrong"}, headers={**h, "X-Forwarded-For": "203.0.113.195"})
assert r_forged.status_code == 401, f"Expected forged XFF to bypass IP limit under default unset CIDRs: {r_forged.status_code}"
print("INHERITED_XFF_DEFAULT_BYPASS_VERIFIED")

# 4. Correctly configured proxy: When ORNEUR_TRUSTED_PROXY_CIDRS is set, untrusted direct peers cannot forge XFF
os.environ["ORNEUR_TRUSTED_PROXY_CIDRS"] = "192.168.1.1/32"
from orca.serve.ratelimit import get_client_ip
from starlette.requests import Request
scope = {"type": "http", "client": ("127.0.0.1", 1234), "headers": [(b"x-forwarded-for", b"203.0.113.195")]}
req = Request(scope)
ip_resolved = get_client_ip(req)
assert ip_resolved == "127.0.0.1", f"Expected direct peer 127.0.0.1 when proxy is untrusted, got: {ip_resolved}"
print("CONFIGURED_PROXY_SECURE_VERIFIED")
"""
    p = _run_subp([sys.executable, "-c", code_ratelimit], cwd=B3_WORKTREE)
    assert "ACCOUNT_LOCKOUT_VERIFIED" in p.stdout
    assert "PER_IP_LIMIT_VERIFIED" in p.stdout
    assert "INHERITED_XFF_DEFAULT_BYPASS_VERIFIED" in p.stdout
    assert "CONFIGURED_PROXY_SECURE_VERIFIED" in p.stdout


# ── Gate 6: Full Password-Reset Workflow Revokes API Keys ─────────────────────────

def test_gate6_password_reset_workflow_revokes_api_keys(tmp_path):
    sink_dir = tmp_path / "mail_sink"
    sink_dir.mkdir(parents=True, exist_ok=True)
    code_reset = f"""
import os
import sys
sys.path.insert(0, '/home/pc/projects/Orneur-b3')
import json
import re
import uuid
from starlette.testclient import TestClient

os.environ["ORNEUR_MAIL_SINK_DIR"] = "{sink_dir}"
os.environ["ORNEUR_REQUIRE_EMAIL_VERIFICATION"] = "1"

from orca.serve.api import create_app
app = create_app()
client = TestClient(app)

PW_OLD = "Old-Password-123!"
PW_NEW = "Brand-New-Passphrase-456!"
email = f"reset-{{uuid.uuid4().hex[:8]}}@example.com"

# 1. Signup user (returns 202 verification_required when verification is enforced)
r_signup = client.post("/api/auth/signup", json={{"email": email, "password": PW_OLD, "name": "ResetTest"}})
assert r_signup.status_code in (200, 202), r_signup.text

# 2. Retrieve verification link from mail sink and verify account
sink_path = "{sink_dir}"
mails = [json.loads(open(os.path.join(sink_path, f)).read()) for f in sorted(os.listdir(sink_path))]
verify_mails = [m for m in mails if m.get("to") == email and "verify" in m.get("subject", "").lower()]
assert len(verify_mails) >= 1, "Verification email missing"
verify_tok = re.search(r"token=([A-Za-z0-9._-]+)", verify_mails[-1]["plain"]).group(1)
r_v = client.post("/api/auth/verify", json={{"token": verify_tok}})
assert r_v.status_code in (200, 302), r_v.text

# Sign in to get valid session
r_log = client.post("/api/auth/login", json={{"email": email, "password": PW_OLD}})
assert r_log.status_code == 200, f"Login failed: {{r_log.text}}"
tok = r_log.json()["token"]
h = {{"Authorization": "Bearer " + tok}}

# 3. Mint API key with valid password
r_key = client.post("/api/auth/apikeys", json={{"name": "pre-reset-key", "password": PW_OLD}}, headers=h)
assert r_key.status_code == 200, f"Key creation failed: {{r_key.text}}"
raw_key = r_key.json()["key"]

# 4. Test API key works
h_key = {{"Authorization": "Bearer " + raw_key}}
r_me = client.get("/api/auth/me", headers=h_key)
assert r_me.status_code == 200, f"API key lookup failed: {{r_me.text}}"

# 5. Initiate forgot-password workflow
r_forgot = client.post("/api/auth/forgot-password", json={{"email": email}})
assert r_forgot.status_code == 200

# Retrieve reset token from mail sink
mails_after = [json.loads(open(os.path.join(sink_path, f)).read()) for f in sorted(os.listdir(sink_path))]
reset_mails = [m for m in mails_after if m.get("to") == email and "reset" in m.get("subject", "").lower()]
assert len(reset_mails) >= 1, "Password reset email missing in mail sink"
reset_token = re.search(r"reset_token=([A-Za-z0-9._-]+)", reset_mails[-1]["plain"]).group(1)

# 6. Complete password reset via POST /api/auth/reset-password
r_reset = client.post("/api/auth/reset-password", json={{"token": reset_token, "password": PW_NEW}})
assert r_reset.status_code == 200, f"Reset password failed: {{r_reset.text}}"

# 7. Prove that the old API key is NOW REVOKED and returns 401
r_me_after = client.get("/api/auth/me", headers=h_key)
assert r_me_after.status_code == 401, f"Expected 401 on revoked API key after reset, got {{r_me_after.status_code}}"

# 8. Old session is also revoked
assert client.get("/api/auth/me", headers=h).status_code == 401

# 9. User can sign in with new password
r_login = client.post("/api/auth/login", json={{"email": email, "password": PW_NEW}})
assert r_login.status_code == 200, f"Login with new password failed: {{r_login.text}}"
new_tok = r_login.json()["token"]

# 10. Minting a new key with new password succeeds
r_new_key = client.post("/api/auth/apikeys", json={{"name": "post-reset-key", "password": PW_NEW}}, headers={{"Authorization": "Bearer " + new_tok}})
assert r_new_key.status_code == 200, f"New key creation failed: {{r_new_key.text}}"

print("FULL_PASSWORD_RESET_INTEGRATION_PASSED")
"""
    p = _run_subp([sys.executable, "-c", code_reset], cwd=B3_WORKTREE)
    assert "FULL_PASSWORD_RESET_INTEGRATION_PASSED" in p.stdout


# ── Gate 7: Real Chromium Browser Journey for API Keys Panel ─────────────────────

def test_gate7_browser_ui_panel_and_credential_clearing(tmp_path):
    browser_py = Path("/home/pc/projects/.journey-tools/.venv/bin/python")
    if not browser_py.exists():
        pytest.skip("Journey tools playwright environment missing")

    test_driver = Path("/home/pc/projects/Orneur/tests/qualification/browser_b3_apikey_test.py")
    assert test_driver.exists(), f"Driver script missing: {test_driver}"

    home_dir = tmp_path / "browser_srv"
    home_dir.mkdir(parents=True, exist_ok=True)

    code_launcher = f"""
import os
import subprocess
import sys
import uuid
from pathlib import Path
import httpx

sys.path.insert(0, '/home/pc/projects/Orneur-b3')
from tests.fake_ollama import FakeOllama
from tests.journey.harness import JOURNEY_MODEL, LiveServer

fake = FakeOllama(models=(JOURNEY_MODEL,), reply="OK")
fake.__enter__()
home = Path("{home_dir}")
env = {{
    "ORNEUR_OLLAMA_HOST": fake.host,
    "OLLAMA_HOST": fake.host,
    "ORNEUR_DELETION_SWEEP_S": "3600",
    "PYTHONPATH": "/home/pc/projects/Orneur-b3",
}}
srv = LiveServer(home, extra_env=env)
try:
    srv.wait_ready()
    PW = "{PW}"
    email = f"browser-{{uuid.uuid4().hex[:8]}}@example.com"
    r_signup = httpx.post(f"{{srv.base}}/api/auth/signup", json={{"email": email, "password": PW, "name": "BrowserUser"}}, timeout=30)
    assert r_signup.status_code == 200

    libs = Path("/home/pc/projects/.journey-tools/libs/usr/lib/x86_64-linux-gnu")
    run_env = dict(os.environ, LD_LIBRARY_PATH=f"{{libs}}:{{os.environ.get('LD_LIBRARY_PATH', '')}}")

    driver_path = "{test_driver}"
    browser_bin = "{browser_py}"
    p = subprocess.run([browser_bin, driver_path, srv.base, PW, email], capture_output=True, text=True, env=run_env, timeout=120)
    print(p.stdout)
    if p.returncode != 0:
        print(p.stderr, file=sys.stderr)
        sys.exit(p.returncode)
finally:
    srv.stop()
    fake.__exit__(None, None, None)
"""
    p = _run_subp([sys.executable, "-c", code_launcher], cwd=B3_WORKTREE)
    assert "[Browser Test] SUCCESS" in p.stdout


# ── Gate 8: Audit Logs & Security Test Skip Count Integrity ──────────────────────

def test_gate8_audit_logs_and_skip_count_verification():
    code_audit = """
import sys
sys.path.insert(0, '/home/pc/projects/Orneur-b3')
import uuid
from starlette.testclient import TestClient
from orca.serve.api import create_app
from orca import audit

app = create_app()
client = TestClient(app)

PW = "Audit-Pass-777!"
email = f"audit-{uuid.uuid4().hex[:8]}@example.com"
tok = client.post("/api/auth/signup", json={"email": email, "password": PW, "name": "Auditor"}).json()["token"]
h = {"Authorization": f"Bearer {tok}"}

# Trigger failed reauth
client.post("/api/auth/apikeys", json={"name": "fail-key", "password": "wrong"}, headers=h)

# Trigger successful reauth
r_ok = client.post("/api/auth/apikeys", json={"name": "ok-key", "password": PW}, headers=h)
raw_key = r_ok.json()["key"]

# Inspect audit log
events = audit.recent(limit=50)
reauth_fail = [e for e in events if e.get("event") == "api_key_reauth_failed"]
key_created = [e for e in events if e.get("event") == "api_key_created"]

assert len(reauth_fail) >= 1, "Missing api_key_reauth_failed audit event"
assert len(key_created) >= 1, "Missing api_key_created audit event"

# Ensure no passwords, TOTP codes or raw keys are anywhere in audit events
audit_dump = repr(events)
assert PW not in audit_dump, "Raw password leaked into audit log!"
assert raw_key not in audit_dump, "Raw API key leaked into audit log!"
print("AUDIT_HYGIENE_VERIFIED")
"""
    p = _run_subp([sys.executable, "-c", code_audit], cwd=B3_WORKTREE)
    assert "AUDIT_HYGIENE_VERIFIED" in p.stdout

    # Verify that test_07d in test_g006_tenant_isolation.py does NOT skip
    p_g006 = _run_subp([
        sys.executable, "-m", "pytest", "tests/test_g006_tenant_isolation.py",
        "-k", "test_07d", "-v"
    ], cwd=B3_WORKTREE, env={"PYTHONPATH": str(B3_WORKTREE)})
    assert "PASSED" in p_g006.stdout and "SKIPPED" not in p_g006.stdout, f"test_07d must not be skipped:\n{p_g006.stdout}"


# ── Gate 9: Immutability of Governance & Pretraining Authority ───────────────────

def test_gate9_governance_and_parent_immutability():
    protected_files = [
        "docs/orneur/acceptance/acceptance_ledger.json",
        "docs/orneur/authorization/TRAINING_AUTHORITY_REGISTRY.json",
        "docs/orneur/authorization/TRAINING_AUTHORIZATION.json",
        "orca/training/authorization.py",
        "orca/training/training_freeze.py",
    ]
    diff = subprocess.check_output(
        ["git", "-C", str(B3_WORKTREE), "diff", f"{MAIN_SHA}..{CANDIDATE_HEAD}", "--"] + protected_files
    ).decode().strip()
    assert diff == "", f"Protected governance files modified in candidate PR 141:\n{diff}"

    # Verify ledger remains 0/95
    ledger_path = B3_WORKTREE / "docs/orneur/acceptance/acceptance_ledger.json"
    ledger_data = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger_data == [], f"Formal acceptance ledger is non-empty: {ledger_data}"
