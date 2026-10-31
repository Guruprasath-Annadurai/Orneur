"""LANDMARK-04 Phase 1 -- adversarial browser rendering (evidence class: BROWSER + FIXTURE provider, real ``orca serve``, real Chromium).

The fixture provider returns attack payloads as the "model answer". The approved page must render them inert while streaming and when the stored
conversation is reopened. Missing capability == test FAILURE, never a skip.
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
SCRIPT = Path(__file__).with_name("browser_p1_xss.py")
ARTIFACTS = Path(os.environ.get("ORNEUR_JOURNEY_ARTIFACTS", "/tmp/orneur-journey-artifacts")) / "p1"

HOSTILE_REPLY = "\n".join([
    "# Heading <img src=x onerror=\"window.__pwned='h1'\">",
    "<script>window.__pwned='script'</script>",
    "<img src=x onerror=\"window.__pwned='img'\">",
    "<svg onload=\"window.__pwned='svg'\"></svg>",
    "<iframe src=\"javascript:window.parent.__pwned='iframe'\"></iframe>",
    "[click](javascript:window.__pwned='js1')",
    "[tab](java\tscript:window.__pwned='js2')",
    "[data](data:text/html,<script>window.__pwned='d'</script>)",
    "[v](vbscript:msgbox(1))",
    "[quote](https://example.com/\" onmouseover=\"window.__pwned='attr'\" x=\")",
    "[good](https://example.com/ok)",
    "**<b onmouseover=window.__pwned=1>bold</b>** `<img src=x onerror=window.__pwned=2>`",
    "```html\n<script>window.__pwned='fence'</script>\n```",
    "[D1] <button onclick=\"window.__pwned='cite'\">x</button>",
])


def test_hostile_content_never_executes_in_a_real_browser(tmp_path):
    py = TOOLS / ".venv" / "bin" / "python"
    if not py.exists():
        raise CapabilityMissing(f"capability missing: browser tools venv not found at {TOOLS}")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    fake = FakeOllama(models=(JOURNEY_MODEL,), reply=HOSTILE_REPLY)
    fake.__enter__()
    srv = LiveServer(tmp_path, extra_env={"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host})
    try:
        srv.wait_ready()
        user = User(srv.base, "p1xss")
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
        assert not failed, json.dumps(failed, indent=1)
        assert {"X1_live_render_is_inert", "X4_reopened_history_is_inert"} <= set(steps)
    finally:
        srv.stop()
        fake.__exit__(None, None, None)
