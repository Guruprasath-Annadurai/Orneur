"""LANDMARK-04 Phase 1 (P1-D) -- account settings dialog in real Chromium against a real ``orca serve`` (fixture provider; mail not involved). Missing capability == FAILURE."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from tests.fake_ollama import FakeOllama
from tests.journey.harness import JOURNEY_MODEL, CapabilityMissing, LiveServer, User

TOOLS = Path(os.environ.get("ORNEUR_JOURNEY_TOOLS", "/home/pc/projects/.journey-tools"))
SCRIPT = Path(__file__).with_name("browser_p1_account.py")
ARTIFACTS = Path(os.environ.get("ORNEUR_JOURNEY_ARTIFACTS", "/tmp/orneur-journey-artifacts")) / "p1"
STEPS = ["U1_account_row_opens_a_real_dialog_and_escape_returns_focus", "U2_change_password_continues_this_session_and_ends_the_old_one",
         "U3_two_step_verification_can_be_turned_on_in_the_page", "U4_deleting_a_2fa_account_needs_the_code_and_the_confirmation",
         "U5_two_step_verification_can_be_turned_off_and_sign_in_no_longer_asks", "U6_delete_account_signs_out_and_the_account_is_gone", "U7_no_uncaught_page_errors"]


def test_account_settings_dialog_in_a_real_browser(tmp_path):
    py = TOOLS / ".venv" / "bin" / "python"
    if not py.exists():
        raise CapabilityMissing(f"capability missing: browser tools venv not found at {TOOLS}")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    fake = FakeOllama(models=(JOURNEY_MODEL,), reply="OK")
    fake.__enter__()
    srv = LiveServer(tmp_path, extra_env={"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host})
    try:
        srv.wait_ready()
        User(srv.base, "burn")                      # the first account is the bootstrap owner; make the tested one an ordinary member
        user = User(srv.base, "p1acct")
        libs = TOOLS / "libs/usr/lib/x86_64-linux-gnu"
        env = dict(os.environ, LD_LIBRARY_PATH=f"{libs}:{os.environ.get('LD_LIBRARY_PATH', '')}")
        p = subprocess.run([str(py), str(SCRIPT), srv.base, str(ARTIFACTS), user.email], capture_output=True, text=True, env=env, timeout=300)
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
