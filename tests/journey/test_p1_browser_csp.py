"""LANDMARK-04 Phase 1 -- the approved page works under its real CSP, and the policy actually limits exfiltration and framing (real Chromium, real ``orca serve``).
Missing capability == FAILURE, never a skip."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from tests.fake_ollama import FakeOllama
from tests.journey.harness import JOURNEY_MODEL, CapabilityMissing, LiveServer, User

TOOLS = Path(os.environ.get("ORNEUR_JOURNEY_TOOLS", "/home/pc/projects/.journey-tools"))
SCRIPT = Path(__file__).with_name("browser_p1_csp.py")
ARTIFACTS = Path(os.environ.get("ORNEUR_JOURNEY_ARTIFACTS", "/tmp/orneur-journey-artifacts")) / "p1"
STEPS = ["C1_policy_is_delivered_with_the_page", "C2_sign_in_and_streamed_answer_work_under_the_policy", "C3_a_script_cannot_reach_another_origin",
         "C4_beacon_to_another_origin_is_refused", "C5_the_application_cannot_be_framed_by_another_site", "C6_no_policy_violations_by_the_page_itself"]


def test_the_page_works_under_its_csp_and_the_csp_blocks_exfiltration_and_framing(tmp_path):
    py = TOOLS / ".venv" / "bin" / "python"
    if not py.exists():
        raise CapabilityMissing(f"capability missing: browser tools venv not found at {TOOLS}")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    fake = FakeOllama(models=(JOURNEY_MODEL,), reply="A calm answer under policy.")
    fake.__enter__()
    srv = LiveServer(tmp_path, extra_env={"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host})
    try:
        srv.wait_ready()
        user = User(srv.base, "p1csp")
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
