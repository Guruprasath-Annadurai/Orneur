"""Journey B2/J -- browser behaviour against a CONTROLLED multi-chunk provider (evidence class: BROWSER + FIXTURE provider).

A short real-model answer can legitimately arrive as one chunk, so incremental rendering, Stop, refresh/network loss mid-stream, revocation while a page is
open and cross-tab sign-out are proven with a provider that emits 6 chunks 0.5s apart. Missing capability == test FAILURE (never skip).
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

import httpx
import pytest

from tests.fake_ollama import FakeOllama
from tests.journey.harness import JOURNEY_MODEL, CapabilityMissing, LiveServer, User

TOOLS = Path(os.environ.get("ORNEUR_JOURNEY_TOOLS", "/home/pc/projects/.journey-tools"))
SCRIPT = Path(__file__).with_name("browser_stream_journey.py")
ARTIFACTS = Path(os.environ.get("ORNEUR_JOURNEY_ARTIFACTS", "/tmp/orneur-journey-artifacts"))
PIECES = [f"piece{i} " for i in range(6)]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    py = TOOLS / ".venv" / "bin" / "python"
    if not py.exists():
        raise CapabilityMissing(f"capability missing: browser tools venv not found at {TOOLS} (needs playwright + chromium)")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    fake = FakeOllama(models=(JOURNEY_MODEL,), chunks=PIECES, reply="".join(PIECES), chunk_delay=0.5)
    fake.__enter__()
    home = tmp_path_factory.mktemp("browser-fixture-home")
    srv = LiveServer(home, extra_env={"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host})
    try:
        srv.wait_ready()
        user = User(srv.base, "stream")
        sid = str(uuid.uuid4())
        up = httpx.post(f"{srv.base}/api/docs/upload", params={"session_id": sid}, headers=user.headers,
                        files={"file": ("n.txt", b"Orneur is a fictional architecture used in tests.", "text/plain")}, timeout=120)
        assert up.status_code == 200, up.text
        status, events = user.stream("seed turn", session_id=sid)
        assert status == 200 and events[-1]["type"] == "done" and events[-1]["persisted"] == "saved", events[-2:]
        libs = TOOLS / "libs/usr/lib/x86_64-linux-gnu"
        env = dict(os.environ, LD_LIBRARY_PATH=f"{libs}:{os.environ.get('LD_LIBRARY_PATH', '')}")
        n0 = len(fake.requests)
        p = subprocess.run([str(py), str(SCRIPT), srv.base, str(ARTIFACTS), user.email, sid], capture_output=True, text=True, env=env, timeout=600)
        if p.returncode != 0 and not p.stdout.strip():
            raise CapabilityMissing(f"capability missing: browser could not run:\n{p.stderr[-1500:]}")
        steps = {}
        for line in p.stdout.splitlines():
            try:
                d = json.loads(line)
                steps[d["step"]] = d
            except ValueError:
                pass
        yield {"steps": steps, "stderr": p.stderr[-800:], "fake": fake, "n0": n0, "base": srv.base}
    finally:
        srv.stop()
        fake.__exit__(None, None, None)


@pytest.mark.parametrize("step", [
    "S0_sign_in_and_open_conversation",
    "S1_provider_chunks_render_incrementally_in_the_browser",
    "S2_stop_ends_the_stream_and_leaves_no_phantom_turn_or_stuck_conversation",
    "S3_refreshing_the_page_mid_stream_shows_only_committed_turns",
    "S4_network_loss_mid_stream_is_reported_and_recoverable",
    "S5_token_revoked_elsewhere_stops_the_page_without_reaching_the_model",
    "S6_signing_out_in_one_tab_signs_out_the_other",
])
def test_browser_fixture_step(run, step):
    d = run["steps"].get(step)
    assert d is not None, f"step never ran: {step}\n{run['stderr']}"
    assert d["ok"], f"{step}: {d['detail']}"


def test_revoked_page_never_reached_the_provider(run):
    sent = [r for r in run["fake"].requests[run["n0"]:] if (r.get("messages") or [{}])[-1].get("content", "") == "this must never reach the provider"]
    assert sent == [], "a message typed after revocation reached the model"


def test_the_provider_saw_the_client_hang_up_when_the_user_pressed_stop(run):
    assert run["fake"].stream_aborted.is_set(), "the upstream generation was not cancelled when the browser disconnected"


def test_no_uncaught_page_errors_or_console_errors(run):
    assert run["steps"].get("PAGE_ERRORS") is None, run["steps"].get("PAGE_ERRORS")
    assert run["steps"].get("CONSOLE_ERRORS") is None, run["steps"].get("CONSOLE_ERRORS")
