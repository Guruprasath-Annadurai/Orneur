"""LANDMARK-04 Phase 1 (P1-E, P1-A, P1-C mobile) -- conversation management, tenant isolation, mobile and accessibility basics in real Chromium
against a real ``orca serve`` (fixture provider: it controls timing, it is not intelligence). Missing capability == FAILURE, never a skip."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from tests.fake_ollama import FakeOllama
from tests.journey.harness import JOURNEY_MODEL, CapabilityMissing, LiveServer, User

TOOLS = Path(os.environ.get("ORNEUR_JOURNEY_TOOLS", "/home/pc/projects/.journey-tools"))
SCRIPT = Path(__file__).with_name("browser_p1_manage.py")
ARTIFACTS = Path(os.environ.get("ORNEUR_JOURNEY_ARTIFACTS", "/tmp/orneur-journey-artifacts")) / "p1"
PIECES = [f"w{i} " for i in range(16)]
STEPS = ["M1_a_new_conversation_is_created_answered_and_listed", "M2_rename_from_the_menu_persists_across_reload",
         "M3_search_finds_own_conversation_by_content_and_never_anothers", "M4_another_user_cannot_read_modify_stream_into_or_delete_the_conversation",
         "M5_reopen_after_close_and_login_restores_the_exact_transcript", "M6_delete_needs_confirmation_then_removes_it_everywhere",
         "N1_mobile_navigation_send_stream_stop_and_reopen", "N2_mobile_touch_targets_and_layout", "H1_controls_have_accessible_names_and_visible_focus",
         "H2_reduced_motion_is_honoured", "Z_no_uncaught_page_errors"]


def test_conversation_management_isolation_and_mobile_in_a_real_browser(tmp_path):
    py = TOOLS / ".venv" / "bin" / "python"
    if not py.exists():
        raise CapabilityMissing(f"capability missing: browser tools venv not found at {TOOLS}")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    fake = FakeOllama(models=(JOURNEY_MODEL,), chunks=PIECES, reply="".join(PIECES), chunk_delay=0.3)
    fake.__enter__()
    srv = LiveServer(tmp_path, extra_env={"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host})
    try:
        srv.wait_ready()
        alice, bob = User(srv.base, "p1alice"), User(srv.base, "p1bob")
        libs = TOOLS / "libs/usr/lib/x86_64-linux-gnu"
        env = dict(os.environ, LD_LIBRARY_PATH=f"{libs}:{os.environ.get('LD_LIBRARY_PATH', '')}")
        p = subprocess.run([str(py), str(SCRIPT), srv.base, str(ARTIFACTS), alice.email, bob.email, fake.host], capture_output=True, text=True, env=env, timeout=600)
        steps = {}
        for line in p.stdout.splitlines():
            try:
                d = json.loads(line)
                steps[d["step"]] = d
            except ValueError:
                pass
        assert steps, f"browser produced no steps:\n{p.stderr[-1500:]}"
        failed = {k: v["detail"] for k, v in steps.items() if not v["ok"] and k != "N1_detail"}
        missing = [s for s in STEPS if s not in steps]
        assert not failed and not missing, json.dumps({"failed": failed, "missing": missing, "stderr": p.stderr[-500:]}, indent=1)
    finally:
        srv.stop()
        fake.__exit__(None, None, None)
