"""First real chatbot journey -- browser half (evidence class: BROWSER).

Real Chromium drives the approved /conversation page against a real ``orca
serve`` + real Ollama (via the recording tap). The driver runs in a separate
tools venv so the project venv gains no dependency:

  uv venv /home/pc/projects/.journey-tools/.venv && uv pip install playwright==1.49.1
  python -m playwright install chromium
  (+ libnss3 libnspr4 libasound2 extracted under .journey-tools/libs when no sudo)

Missing capability == test FAILURE (never skip).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.journey.harness import CapabilityMissing

TOOLS = Path(os.environ.get("ORNEUR_JOURNEY_TOOLS", "/home/pc/projects/.journey-tools"))
SCRIPT = Path(__file__).with_name("browser_journey.py")
ARTIFACTS = Path(os.environ.get("ORNEUR_JOURNEY_ARTIFACTS", "/tmp/orneur-journey-artifacts"))


@pytest.fixture(scope="module")
def run(server, tap):
    py = TOOLS / ".venv" / "bin" / "python"
    if not py.exists():
        raise CapabilityMissing(f"capability missing: browser tools venv not found at {TOOLS} (needs playwright + chromium)")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    libs = TOOLS / "libs/usr/lib/x86_64-linux-gnu"
    env = dict(os.environ, LD_LIBRARY_PATH=f"{libs}:{os.environ.get('LD_LIBRARY_PATH', '')}")
    n0 = len(tap.requests)
    p = subprocess.run([str(py), str(SCRIPT), server.base, str(ARTIFACTS)], capture_output=True, text=True, env=env, timeout=900)
    if p.returncode != 0 and not p.stdout.strip():
        raise CapabilityMissing(f"capability missing: browser could not run:\n{p.stderr[-1500:]}")
    steps = {}
    for line in p.stdout.splitlines():
        try:
            d = json.loads(line)
            steps[d["step"]] = d
        except ValueError:
            pass
    return {"steps": steps, "answer_contexts": lambda prompt: tap.answer_contexts(prompt, n0), "stderr": p.stderr[-800:]}


def _ok(run, step):
    d = run["steps"].get(step)
    assert d is not None, f"step never ran: {step}\n{run['stderr']}"
    assert d["ok"], f"{step}: {d['detail']}"
    return d


@pytest.mark.parametrize("step", [
    "A1_login_form_rejects_wrong_password",
    "A2_login_succeeds_and_shell_is_usable",
    "B1_new_conversation_streams_real_answer",
    "C0_sidebar_lists_the_conversation_without_a_reload",
    "C1_reload_restores_conversation",
    "E0_same_turn_edit_is_available_after_streaming",
    "E1_inline_edit_saves_through_the_ui",
    "E2_follow_up_after_edit_sent_from_ui",
    "F1_temporary_chat_via_ui",
    "F2_closing_a_temporary_chat_in_the_ui_deletes_the_transcript",
    "G1_logout_clears_ui_and_revokes_token",
    "G2_logout_with_server_unreachable_is_reported_honestly",
    "D1_second_user_sees_none_of_the_first_users_conversations",
    "E4_two_tabs_edit_their_own_messages_by_authoritative_id",
    "C2_each_new_conversation_appears_in_the_sidebar_without_reload",
    "T1_dark_theme_renders_logged_in_shell",
])
def test_browser_step(run, step):
    _ok(run, step)


def test_E3_browser_follow_up_after_edit_sends_edited_context_to_the_model(run):
    """BROWSER + recorded Ollama request: after editing in the UI, the follow-up the UI sent
    must reach the model with the edited message and without the original."""
    _ok(run, "E2_follow_up_after_edit_sent_from_ui")
    follow = run["answer_contexts"]("Which fruit did I say is my favourite? Answer with one word.")
    assert follow, "the follow-up never reached Ollama"
    ctx = follow[-1]
    assert "favourite fruit is mango" in ctx, f"model not sent the edited message:\n{ctx[:600]}"
    assert "pineapple" not in ctx, f"model was sent the pre-edit message:\n{ctx[:600]}"


def test_no_uncaught_page_errors(run):
    d = run["steps"].get("PAGE_ERRORS")
    assert d is None, d
