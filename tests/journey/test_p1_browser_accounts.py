"""LANDMARK-04 Phase 1 (P1-D) -- account lifecycle on the approved /conversation page, real Chromium + real ``orca serve`` (mail = local sink; no real inbox delivery).

Real external email delivery is NOT exercised here: BLOCKED_EXTERNAL until an authorised mail service exists. Missing capability == FAILURE, never a skip.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from tests.fake_ollama import FakeOllama
from tests.journey.harness import JOURNEY_MODEL, CapabilityMissing, LiveServer

TOOLS = Path(os.environ.get("ORNEUR_JOURNEY_TOOLS", "/home/pc/projects/.journey-tools"))
SCRIPT = Path(__file__).with_name("browser_p1_auth.py")
ARTIFACTS = Path(os.environ.get("ORNEUR_JOURNEY_ARTIFACTS", "/tmp/orneur-journey-artifacts")) / "p1"
STEPS = ["A1_signup_requires_verification_and_says_so", "A2_unverified_sign_in_is_explained_and_resend_works", "A3_confirming_the_link_then_signing_in_works",
         "A4_sign_out_ends_the_session_on_the_server", "A5_forgot_password_is_generic_and_reset_link_sets_a_new_password",
         "A6_the_reset_link_cannot_be_replayed_and_the_old_password_is_dead", "A7_mfa_challenge_is_completable_in_the_page",
         "A8_a_used_mfa_code_cannot_be_replayed", "A9_no_credentials_in_urls_or_page_errors"]


def test_account_lifecycle_in_a_real_browser(tmp_path):
    py = TOOLS / ".venv" / "bin" / "python"
    if not py.exists():
        raise CapabilityMissing(f"capability missing: browser tools venv not found at {TOOLS}")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    fake = FakeOllama(models=(JOURNEY_MODEL,), reply="OK")
    fake.__enter__()
    sink = tmp_path / "sink"
    srv = LiveServer(tmp_path, extra_env={"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host, "ORNEUR_MAIL_SINK_DIR": str(sink),
                                          "ORNEUR_REQUIRE_EMAIL_VERIFICATION": "1", "ORNEUR_DELETION_SWEEP_S": "3600"})
    try:
        srv.wait_ready()
        libs = TOOLS / "libs/usr/lib/x86_64-linux-gnu"
        env = dict(os.environ, LD_LIBRARY_PATH=f"{libs}:{os.environ.get('LD_LIBRARY_PATH', '')}")
        p = subprocess.run([str(py), str(SCRIPT), srv.base, str(ARTIFACTS), str(sink)], capture_output=True, text=True, env=env, timeout=400)
        steps = {}
        for line in p.stdout.splitlines():
            try:
                d = json.loads(line)
                steps[d["step"]] = d
            except ValueError:
                pass
        assert steps, f"browser produced no steps:\n{p.stderr[-1500:]}"
        failed = {k: v["detail"] for k, v in steps.items() if not v["ok"]}
        missing = [s for s in STEPS if s not in steps]
        assert not failed and not missing, json.dumps({"failed": failed, "missing": missing}, indent=1)
    finally:
        srv.stop()
        fake.__exit__(None, None, None)
