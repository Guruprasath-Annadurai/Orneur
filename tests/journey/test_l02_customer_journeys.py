"""L02-07 -- real customer journeys on the approved /conversation page (real Chromium) against a real ``orca serve``.

Six runs: three personas x two provider classes, recorded and labelled separately:
  *_fixture   BROWSER + FIXTURE provider (FakeOllama): deterministic content and timing; asserts UI behaviour, never model quality.
  *_real      BROWSER + REAL Ollama behind the recording tap (``ORNEUR_JOURNEY_MODEL``; ``llama3.2:1b`` run with that literal tag; third-party weights, NOT an ORNEUR model).
              Assertions are about what the page shows, what ORNEUR sent to the model and what it stored - never about what the model says.

Missing capability (browser tools, Ollama, Redis/docker where used) == FAILURE, never a skip. Results go to ``$ORNEUR_L02_EVIDENCE_DIR/l02_journey_<persona>_<mode>.json``.

Run:  ORNEUR_JOURNEY_MODEL=llama3.2:1b pytest tests/journey/test_l02_customer_journeys.py -p no:cacheprovider -v
"""
from __future__ import annotations

import json
import os
import platform
import re
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest

from tests.fake_ollama import FakeOllama
from tests.journey.harness import JOURNEY_MODEL, OLLAMA_HOST, CapabilityMissing, LiveServer, OllamaTap, User

TOOLS = Path(os.environ.get("ORNEUR_JOURNEY_TOOLS", "/home/pc/projects/.journey-tools"))
SCRIPT = Path(__file__).with_name("browser_l02_journeys.py")
EVIDENCE = Path(os.environ.get("ORNEUR_L02_EVIDENCE_DIR", "/tmp/orneur-l02-evidence"))
ARTIFACTS = Path(os.environ.get("ORNEUR_JOURNEY_ARTIFACTS", "/tmp/orneur-journey-artifacts")) / "l02"
PW = "Journey-Pass-91x"

STUDY_NOTES = (b"Study notes: photosynthesis.\nPhotosynthesis converts light energy into chemical energy stored as glucose. It happens in the chloroplasts.\n"
               b"The light-dependent reactions occur in the thylakoid membranes and produce ATP and NADPH.\n"
               b"The Calvin cycle occurs in the stroma and uses ATP and NADPH to fix carbon dioxide into glucose.\n")
FINANCE = (b"Bakery financial summary (confidential).\nQ3 revenue was 128,400 dollars and Q3 net income was 17,976 dollars, a net margin of 14 percent.\n"
           b"Owner contact: jane.baker@example.com, phone 415-555-0137. Owner SSN 123-45-6789.\n")
CODE_REPLY = ("Here is the function:\n```python\ndef is_palindrome(s):\n    \"\"\"Return True if s reads the same forwards and backwards.\"\"\"\n"
              "    cleaned = ''.join(c.lower() for c in s if c.isalnum())\n    return cleaned == cleaned[::-1]\n\nprint(is_palindrome('A man, a plan, a canal: Panama'))\nprint(is_palindrome('hello'))\n```\n"
              "It ignores case and punctuation. These two calls are examples only; nothing was executed.")


def env_block(mode, tag):
    mem = next((int(l.split()[1]) // 1024 for l in open("/proc/meminfo") if l.startswith("MemTotal")), None)
    return {"mode": mode, "provider": "FakeOllama fixture" if mode == "fixture" else f"real Ollama {tag} (third-party weights)", "model_tag": tag if mode == "real" else None,
            "browser": "Chromium via Playwright 1.49.1", "cpu_count": os.cpu_count(), "mem_total_mb": mem, "kernel": platform.release(), "python": platform.python_version()}


def run_driver(journey, mode, base, email, fake_url, doc_path="", link_file="", timeout=1500, cut_url=""):
    py = TOOLS / ".venv" / "bin" / "python"
    if not py.exists():
        raise CapabilityMissing(f"capability missing: browser tools venv not found at {TOOLS}")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    libs = TOOLS / "libs/usr/lib/x86_64-linux-gnu"
    env = dict(os.environ, LD_LIBRARY_PATH=f"{libs}:{os.environ.get('LD_LIBRARY_PATH', '')}", L02_CUT_URL=cut_url)
    cmd = [str(py), str(SCRIPT), journey, mode, base, str(ARTIFACTS), email, PW, fake_url, doc_path, link_file]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    return proc


def collect(proc, timeout=1500):
    out, err = proc.communicate(timeout=timeout)
    steps = {}
    for line in out.splitlines():
        try:
            d = json.loads(line)
            steps[d["step"]] = d
        except ValueError:
            pass
    if proc.returncode not in (0, 1) and not steps:
        raise CapabilityMissing(f"capability missing: browser could not run:\n{err[-1500:]}")
    return steps, err[-800:]


def write_evidence(persona, mode, steps, extra):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    tag = JOURNEY_MODEL
    rec = {"recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "persona": persona, "environment": env_block(mode, tag), "command": f"pytest tests/journey/test_l02_customer_journeys.py -k {persona}_{mode}",
           "steps": {k: {"ok": v["ok"], "detail": v["detail"]} for k, v in steps.items()}, "passed": sum(v["ok"] for k, v in steps.items() if k != "PAGE_ERRORS"),
           "failed": [k for k, v in steps.items() if not v["ok"]], **extra}
    (EVIDENCE / f"l02_journey_{persona}_{mode}.json").write_text(json.dumps(rec, indent=2))


def assert_all(steps, expected):
    missing = [s for s in expected if s not in steps]
    bad = {k: v["detail"] for k, v in steps.items() if not v["ok"]}
    assert not missing, f"steps never reported: {missing}"
    assert not bad, f"failed steps: {json.dumps(bad, indent=2)}"



class CutProxy:
    """A plain TCP forwarder between the browser and the server whose connections can be severed on demand: a REAL dropped connection (the sockets are closed mid-stream), which is
    what a lost network looks like to the page. (Playwright's ``set_offline`` does not cut an already-open stream.) ``/cut`` on the control port severs every live connection."""

    def __init__(self, host, port):
        import http.server
        import socket

        self.target = (host, port)
        self.conns = []
        self.lock = threading.Lock()
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(64)
        self.port = self.srv.getsockname()[1]
        self.cuts = 0
        threading.Thread(target=self._accept, daemon=True).start()
        proxy = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                proxy.cut()
                self.send_response(200); self.end_headers(); self.wfile.write(b"cut")

            def log_message(self, *a):
                pass

        self.ctl = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.ctl_port = self.ctl.server_address[1]
        threading.Thread(target=self.ctl.serve_forever, daemon=True).start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"

    @property
    def cut_url(self):
        return f"http://127.0.0.1:{self.ctl_port}/cut"

    def _accept(self):
        import socket

        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            try:
                u = socket.create_connection(self.target, timeout=10)
            except OSError:
                c.close()
                continue
            with self.lock:
                self.conns += [c, u]
            for a, b in ((c, u), (u, c)):
                threading.Thread(target=self._pump, args=(a, b), daemon=True).start()

    def _pump(self, a, b):
        try:
            while True:
                data = a.recv(65536)
                if not data:
                    break
                b.sendall(data)
        except OSError:
            pass
        finally:
            for x in (a, b):
                try:
                    x.shutdown(2)
                except OSError:
                    pass
                try:
                    x.close()
                except OSError:
                    pass

    def cut(self):
        with self.lock:
            conns, self.conns = self.conns, []
            self.cuts += 1
        for x in conns:
            try:
                x.shutdown(2)
            except OSError:
                pass
            try:
                x.close()
            except OSError:
                pass

    def close(self):
        self.srv.close()
        self.ctl.shutdown()
        self.cut()


@pytest.fixture
def doc(tmp_path):
    def make(name, data):
        p = tmp_path / name
        p.write_bytes(data)
        return str(p)
    return make


@pytest.fixture(params=["fixture", "real"])
def provider(request):
    mode = request.param
    if mode == "fixture":
        text = "This is a fixture answer in several short pieces so the page can paint it progressively as it arrives, which lets the test observe real progressive rendering."
        f = FakeOllama(models=(JOURNEY_MODEL,), reply=text, chunk_delay=0.12)
        f._chunks = tuple(w + " " for w in text.split())
        f.__enter__()
        yield {"mode": "fixture", "host": f.host, "fake": f, "tap": None}
        f.__exit__(None, None, None)
    else:
        from tests.journey.harness import require_ollama

        require_ollama()
        tap = OllamaTap()
        yield {"mode": "real", "host": tap.url, "fake": None, "tap": tap}
        tap.close()


def _contexts(provider, since=0):
    """All provider-side request bodies since index ``since`` (fixture: chat payloads; real: tap-recorded chat/generate bodies)."""
    if provider["mode"] == "fixture":
        return provider["fake"].requests[since:]
    return [r["body"] for r in provider["tap"].requests[since:]]


def _n_requests(provider):
    return len(provider["fake"].requests) if provider["mode"] == "fixture" else len(provider["tap"].requests)


# ══════════════════════════════════════════ A. STUDENT ══════════════════════════════════════════
STUDENT_STEPS = ["S1_create_account_in_the_page_and_verify_the_address_by_the_emailed_link", "S2_sign_in_and_see_which_model_will_answer",
                 "S3_a_learning_question_streams_progressively_and_names_the_model_that_answered", "S4_a_follow_up_uses_the_earlier_context",
                 "S5_upload_a_study_document_and_ask_a_grounded_question_with_visible_sources",
                 "S6_a_question_the_document_cannot_answer_gets_a_truthful_uncertainty_path_and_no_invented_source",
                 "S7_stop_generation_mid_answer_and_the_page_says_what_really_happened", "S8_after_an_interruption_the_conversation_is_recovered_from_the_server",
                 "S9_delete_the_conversation_and_everything_stored_with_it", "S10_log_out_and_the_old_token_stops_working"]


def test_student_journey(provider, doc, tmp_path_factory):
    home = tmp_path_factory.mktemp("student-home")
    sink = home / "mail-sink"
    env = {"ORNEUR_OLLAMA_HOST": provider["host"], "OLLAMA_HOST": provider["host"], "ORNEUR_MAIL_SINK_DIR": str(sink), "ORNEUR_REQUIRE_EMAIL_VERIFICATION": "1",
           "ORNEUR_DELETION_SWEEP_S": "3600"}
    srv = LiveServer(home, extra_env=env)
    try:
        srv.wait_ready()
        env_app = {"APP_URL": srv.base}
        os.environ.update(env_app)
        email = f"student-{os.getpid()}-{int(time.time())}@example.com"
        link_file = str(home / "verify-link.txt")
        # the link is read from the LOCAL SINK exactly as a person would read it from an inbox; nothing is delivered to anyone
        proc = run_driver("student", provider["mode"], srv.base, email, provider["host"] if provider["mode"] == "fixture" else "-", doc("study-notes.txt", STUDY_NOTES), link_file)

        def pump():
            end = time.time() + 120
            while time.time() < end and not os.path.exists(link_file):
                for f in sorted(sink.glob("*.json")) if sink.exists() else []:
                    m = json.loads(f.read_text())
                    if m["to"] == email and "Verify" in m["subject"]:
                        tok = re.search(r"token=([A-Za-z0-9_\-\.]+)", m["plain"]).group(1)
                        Path(link_file).write_text(f"{srv.base}/api/auth/verify?token={tok}")
                        return
                time.sleep(0.3)
        t = threading.Thread(target=pump)
        t.start()
        n0 = 0 if provider["mode"] == "real" else len(provider["fake"].requests)
        steps, err = collect(proc)
        t.join()
        extra = {"server_log_tail": None}
        # provider-side facts
        ctx = _contexts(provider)
        blob = json.dumps(ctx)
        checks = {}
        checks["S4_followup_context_contains_the_earlier_question"] = "photosynthesis" in blob.lower()
        checks["S5_document_text_reached_the_model"] = "stroma" in blob.lower()
        checks["S6_model_was_told_the_documents_do_not_contain_the_answer"] = "NO passage in the uploaded documents matched" in blob
        if provider["mode"] == "real":
            checks["provider_streams_open_after_stop"] = provider["tap"].open_streams
        # deletion truth in the stores
        c = sqlite3.connect(str(next(home.rglob("turns.db"))))
        try:
            st = c.execute("SELECT state FROM session_deletions").fetchall()
            turns = c.execute("SELECT COUNT(*) FROM conversation_turns").fetchone()[0]
        finally:
            c.close()
        checks["deletion_state"] = [r[0] for r in st]
        checks["turns_left_in_store"] = turns
        reg = home / "docs" / "registry.json"
        checks["documents_left_in_registry"] = sum(len(v) for v in json.loads(reg.read_text()).values()) if reg.exists() else 0
        extra["provider_side_checks"] = checks
        write_evidence("student", provider["mode"], steps, extra)
        assert_all(steps, STUDENT_STEPS + ["PAGE_ERRORS"])
        assert checks["S4_followup_context_contains_the_earlier_question"] and checks["S5_document_text_reached_the_model"] and checks["S6_model_was_told_the_documents_do_not_contain_the_answer"], checks
        assert checks["deletion_state"] == ["complete"] and turns == 0 and checks["documents_left_in_registry"] == 0, checks
        if provider["mode"] == "real":
            assert provider["tap"].open_streams == 0
    finally:
        srv.stop()


# ══════════════════════════════════════════ B. DEVELOPER ══════════════════════════════════════════
DEV_STEPS = ["D1_sign_in", "D2_a_coding_answer_renders_as_readable_multiline_code", "D3_streaming_never_leaves_broken_markup_and_final_text_equals_saved_text",
             "D4_a_follow_up_about_the_previous_code_carries_it_as_context", "D5_a_long_answer_completes_scrolls_and_is_saved_once",
             "D6_stop_then_retry_is_safe_one_completed_turn_and_no_phantom", "D8_the_assistant_does_not_present_suggested_code_as_executed"]


def test_developer_journey(provider, tmp_path_factory):
    home = tmp_path_factory.mktemp("dev-home")
    if provider["mode"] == "fixture":
        f = provider["fake"]
        f.reply = CODE_REPLY
        f.chunk_delay = 0.04
        f._chunks = tuple(CODE_REPLY[i:i + 7] for i in range(0, len(CODE_REPLY), 7))
    srv = LiveServer(home, extra_env={"ORNEUR_OLLAMA_HOST": provider["host"], "OLLAMA_HOST": provider["host"], "ORNEUR_DELETION_SWEEP_S": "3600"})
    try:
        srv.wait_ready()
        user = User(srv.base, "devjourney")
        proc = run_driver("developer", provider["mode"], srv.base, user.email, provider["host"] if provider["mode"] == "fixture" else "-")
        steps, err = collect(proc)
        ctx = _contexts(provider)
        blob = json.dumps(ctx)
        offered = set()
        for body in ctx:                                           # the tool planner lists the tools it may use: "Available tools: web_search, ..."
            for m in re.findall(r"Available tools: ([a-z_, ]+)", json.dumps(body)):
                offered.update(t.strip() for t in m.split(","))
        checks = {"D4_previous_code_was_in_the_follow_up_context": "palindrome" in blob.lower(),
                  "tools_offered_to_the_planner": sorted(offered),
                  "no_code_execution_or_file_or_shell_tool_offered": not (offered & {"run_code", "shell", "read_file", "write_file", "security_scan"})}
        write_evidence("developer", provider["mode"], steps, {"provider_side_checks": checks})
        expected = DEV_STEPS + (["D7_provider_failure_is_explained_without_internals_and_is_not_charged"] if provider["mode"] == "fixture" else []) + ["PAGE_ERRORS"]
        assert_all(steps, expected)
        assert checks["D4_previous_code_was_in_the_follow_up_context"] and checks["no_code_execution_or_file_or_shell_tool_offered"], checks
    finally:
        srv.stop()


# ══════════════════════════════════════════ C. BUSINESS OWNER ══════════════════════════════════════════
BIZ_STEPS = ["B1_sign_in", "B2_multi_turn_business_analysis", "B3_upload_a_confidential_document_and_ask_about_it_evidence_is_separated_from_suggestions",
             "B4_nothing_is_claimed_as_done_the_page_shows_no_completed_action", "B5_losing_the_network_mid_answer_the_page_reports_what_the_server_says",
             "B6_the_conversation_is_restored_after_a_reload", "B7_remove_the_uploaded_document_then_delete_the_conversation", "B8_log_out_everywhere_ends_the_other_devices_sessions"]


def test_business_owner_journey(provider, doc, tmp_path_factory):
    home = tmp_path_factory.mktemp("biz-home")
    srv = LiveServer(home, extra_env={"ORNEUR_OLLAMA_HOST": provider["host"], "OLLAMA_HOST": provider["host"], "ORNEUR_DELETION_SWEEP_S": "3600"})
    try:
        srv.wait_ready()
        user = User(srv.base, "bizjourney")
        stranger = User(srv.base, "stranger")
        port = int(srv.base.rsplit(":", 1)[1])
        proxy = CutProxy("127.0.0.1", port)
        try:
            proc = run_driver("business", provider["mode"], proxy.base, user.email, provider["host"] if provider["mode"] == "fixture" else "-", doc("financial-summary.txt", FINANCE), cut_url=proxy.cut_url)
            steps, err = collect(proc)
        finally:
            proxy.close()
        ctx = _contexts(provider)
        blob = json.dumps(ctx)
        checks = {"confidential_numbers_reached_the_model_for_the_grounded_question": "17,976" in blob or "17976" in blob or "14 percent" in blob,
                  "ssn_never_sent_to_the_model": "123-45-6789" not in blob, "email_never_sent_to_the_model": "jane.baker@example.com" not in blob,
                  "no_external_action_tool_used": "send_email" not in blob and "place_order" not in blob}
        # another account cannot reach any of this user's conversations
        sessions = [r for r in httpx.get(f"{srv.base}/api/sessions", headers=user.headers, timeout=20).json().get("sessions", [])]
        checks["stranger_cannot_read_owner_conversations"] = True
        c = sqlite3.connect(str(next(home.rglob("turns.db"))))
        try:
            sids = [r[0] for r in c.execute("SELECT DISTINCT session_id FROM conversation_turns").fetchall()] + [r[0] for r in c.execute("SELECT session_id FROM session_deletions").fetchall()]
        finally:
            c.close()
        for sid in sids:
            assert httpx.get(f"{srv.base}/api/session/{sid}/messages", headers=stranger.headers, timeout=20).status_code == 404
        checks["connections_severed_by_the_test_proxy"] = proxy.cuts
        write_evidence("business", provider["mode"], steps, {"provider_side_checks": checks})
        assert_all(steps, BIZ_STEPS + ["PAGE_ERRORS"])
        assert all(checks.values()), checks
    finally:
        srv.stop()
