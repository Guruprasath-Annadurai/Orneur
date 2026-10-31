"""B-01 final integration -- the approved /conversation page, driven by real Chromium, against a real ``orca serve``.

Two variants of one journey (see ``browser_b01_journey.py``):

  fixture  BROWSER + FIXTURE provider. A controlled provider (16 pieces 0.3s apart) makes timing deterministic, so progressive rendering, Stop,
           the provider-side cancellation, provider outage + recovery, two-tab isolation and a server restart can all be asserted exactly.
  real     BROWSER + REAL Ollama (``ORNEUR_JOURNEY_MODEL``; ``llama3.2:1b`` when run with that literal tag), behind the recording tap.

Missing capability (browser tools, Ollama) == test FAILURE, never a skip.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.fake_ollama import FakeOllama
from tests.journey.harness import JOURNEY_MODEL, CapabilityMissing, LiveServer, User

TOOLS = Path(os.environ.get("ORNEUR_JOURNEY_TOOLS", "/home/pc/projects/.journey-tools"))
SCRIPT = Path(__file__).with_name("browser_b01_journey.py")
ARTIFACTS = Path(os.environ.get("ORNEUR_JOURNEY_ARTIFACTS", "/tmp/orneur-journey-artifacts")) / "b01"
PIECES = [f"w{i} " for i in range(16)]

FIXTURE_STEPS = [
    "J1_sign_in",
    "J2_new_conversation_long_prompt_renders_progressively_in_the_browser",
    "J3_stop_is_usable_mid_stream_and_actually_stops_the_provider",
    "J4_the_next_prompt_succeeds_immediately_after_stop",
    "J5_a_full_response_is_saved_exactly_once",
    "J6_refresh_recovers_the_committed_transcript",
    "J7_the_next_prompt_carries_only_committed_history",
    "J8_editing_an_earlier_message_changes_what_the_model_is_sent",
    "J9_two_tabs_stream_two_conversations_without_cross_talk",
    "J10_provider_outage_is_reported_without_a_phantom_turn_and_recovers",
    "J11_temporary_chat_is_not_listed_and_is_deleted_on_close",
    "J12_a_revoked_token_stops_the_page_and_never_reaches_the_model",
    "R1_after_a_server_restart_the_committed_conversation_is_still_there",
    "R2_a_new_prompt_after_the_restart_is_streamed_and_saved",
]
REAL_STEPS = [s for s in FIXTURE_STEPS if not s.startswith(("J9", "J10", "R"))]


def _run(phase: str, mode: str, base: str, email: str, fake_url: str, *extra: str) -> dict:
    py = TOOLS / ".venv" / "bin" / "python"
    if not py.exists():
        raise CapabilityMissing(f"capability missing: browser tools venv not found at {TOOLS} (needs playwright + chromium)")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    libs = TOOLS / "libs/usr/lib/x86_64-linux-gnu"
    env = dict(os.environ, LD_LIBRARY_PATH=f"{libs}:{os.environ.get('LD_LIBRARY_PATH', '')}")
    p = subprocess.run([str(py), str(SCRIPT), phase, mode, base, str(ARTIFACTS), email, fake_url, *extra], capture_output=True, text=True, env=env, timeout=900)
    steps = {}
    for line in p.stdout.splitlines():
        try:
            d = json.loads(line)
            steps[d["step"]] = d
        except ValueError:
            pass
    if p.returncode != 0 and not steps:
        raise CapabilityMissing(f"capability missing: browser could not run:\n{p.stderr[-1500:]}")
    return {"steps": steps, "stderr": p.stderr[-800:], "stdout": p.stdout}


@pytest.fixture(scope="module")
def fixture_run(tmp_path_factory):
    fake = FakeOllama(models=(JOURNEY_MODEL,), chunks=PIECES, reply="".join(PIECES), chunk_delay=0.3)
    fake.__enter__()
    home = tmp_path_factory.mktemp("b01-browser-fixture")
    extra = {"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host}
    srv = LiveServer(home, extra_env=extra)
    srv2 = None
    try:
        srv.wait_ready()
        user = User(srv.base, "b01browser")
        main = _run("main", "fixture", srv.base, user.email, fake.host)
        state = json.loads(main["steps"]["STATE"]["detail"]) if "STATE" in main["steps"] else {}
        srv.stop()                                                   # a real process restart on the same ORNEUR_HOME
        srv2 = LiveServer(home, extra_env=extra)
        srv2.wait_ready()
        after = _run("after_restart", "fixture", srv2.base, user.email, fake.host, state.get("sid") or "-", str(state.get("messages") or 0))
        yield {"steps": {**main["steps"], **after["steps"]}, "stderr": main["stderr"] + after["stderr"], "fake": fake, "home": home}
    finally:
        srv.stop()
        if srv2 is not None:
            srv2.stop()
        fake.__exit__(None, None, None)


@pytest.fixture(scope="module")
def real_run(server, tap):
    user = User(server.base, "b01realbr")
    a0 = tap.client_aborts
    out = _run("main", "real", server.base, user.email, "-")
    out["tap"] = tap
    out["aborts_during_run"] = tap.client_aborts - a0
    return out


@pytest.mark.parametrize("step", FIXTURE_STEPS)
def test_fixture_browser_journey(fixture_run, step):
    d = fixture_run["steps"].get(step)
    assert d is not None, f"step never ran: {step}\n{fixture_run['stderr']}"
    assert d["ok"], f"{step}: {d['detail']}"


def test_fixture_no_page_errors_and_no_provider_generation_left_running(fixture_run):
    assert "PAGE_ERRORS" not in fixture_run["steps"], fixture_run["steps"].get("PAGE_ERRORS")
    fake: FakeOllama = fixture_run["fake"]
    assert fake.streams_open == 0, "a provider generation is still running after the journey"


@pytest.mark.parametrize("step", REAL_STEPS)
def test_real_ollama_browser_journey(real_run, step):
    d = real_run["steps"].get(step)
    assert d is not None, f"step never ran: {step}\n{real_run['stderr']}"
    assert d["ok"], f"{step}: {d['detail']}"


def test_real_ollama_stop_in_the_browser_hung_up_on_the_model(real_run):
    assert real_run["aborts_during_run"] >= 1, "the browser's Stop never made ORNEUR close its connection to the real model"
    assert real_run["tap"].open_streams == 0
