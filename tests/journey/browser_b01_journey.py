"""Playwright driver: the B-01 acceptance journey on the approved /conversation page (evidence class: BROWSER; provider = FIXTURE or REAL Ollama).

``python browser_b01_journey.py <phase> <mode> <base_url> <out_dir> <email> <fake_url|-> [<session_id> <expected_messages>]``

  phase  main           sign in -> new conversation -> long prompt -> progressive rendering -> Stop -> no phantom turn -> next prompt ->
                        full answer -> refresh -> history in the next prompt -> edit -> two tabs -> provider outage + recovery
                        -> temporary chat -> token revocation          (outage steps run only in `fixture` mode)
         after_restart  (after the wrapper restarted the server process) sign in -> the committed conversation is still there -> a new prompt is answered
  mode   fixture        controlled multi-piece provider (FakeOllama, controlled over its /__config, /__stats, /__requests endpoints)
         real           the workstation's real Ollama model; provider-side assertions are made by the pytest wrapper through the recording tap

Emits one JSON object per line: {"step", "ok", "detail"}. A step that cannot run reports ok=false. Nothing here skips.
"""
import json
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

PHASE, MODE, BASE, OUT, EMAIL, FAKE = sys.argv[1:7]
RESUME_SID = sys.argv[7] if len(sys.argv) > 7 else None
RESUME_N = int(sys.argv[8]) if len(sys.argv) > 8 else 0
PW = "Journey-Pass-91x"
FIXTURE = MODE == "fixture"
PIECES = [f"w{i} " for i in range(16)]
FULL = "".join(PIECES)
LONG_PROMPT = "Write a long detailed essay about lighthouses, at least 300 words, in several paragraphs." if not FIXTURE else "tell me the long story"
results = []
page = None


def report(step, ok, detail=""):
    results.append((step, ok))
    print(json.dumps({"step": step, "ok": bool(ok), "detail": str(detail)[:900]}), flush=True)


def step(name):
    def deco(fn):
        def run(*a, **k):
            try:
                fn(*a, **k)
            except Exception as exc:
                report(name, False, f"{type(exc).__name__}: {str(exc)[:700]}")
                try:
                    page.screenshot(path=f"{OUT}/{name}_FAIL.png")
                except Exception:
                    pass
        return run
    return deco


def ctl(path, payload=None):
    """Control/inspect the fixture provider (no-op in real mode)."""
    if not FIXTURE:
        return None
    req = urllib.request.Request(FAKE + path, data=json.dumps(payload).encode() if payload is not None else None,
                                 method="POST" if payload is not None else "GET", headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=10))


def stats():
    return ctl("/__stats")


def wait_for(pred, timeout=10.0, step_s=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(step_s)
    return pred()


INIT = """
window.__sseLog = [];
window.__domLog = [];
const __o = window.fetch.bind(window);
window.fetch = async (...a) => {
  const r = await __o(...a);
  try {
    const u = typeof a[0] === 'string' ? a[0] : (a[0] && a[0].url) || '';
    if (u.includes('/api/stream') && r.body) {
      const rd = r.clone().body.getReader(); const dec = new TextDecoder(); let buf = '';
      (async () => { for (;;) { const {done, value} = await rd.read(); if (done) break; buf += dec.decode(value, {stream: true});
        let i; while ((i = buf.indexOf('\\n\\n')) >= 0) { const blk = buf.slice(0, i); buf = buf.slice(i + 2);
          if (blk.startsWith('data: ')) { try { window.__sseLog.push({t: performance.now(), ev: JSON.parse(blk.slice(6))}); } catch (e) {} } } } })().catch(() => {});
    }
  } catch (e) {}
  return r;
};
document.addEventListener('DOMContentLoaded', () => {
  const root = document.getElementById('reading-container');
  if (!root) return;
  new MutationObserver(() => {
    const a = [...root.querySelectorAll('.answer .msg-body')].pop();
    const n = a ? a.textContent.length : 0;
    const last = window.__domLog[window.__domLog.length - 1];
    if (!last || last.n !== n) window.__domLog.push({t: performance.now(), n});
  }).observe(root, {subtree: true, childList: true, characterData: true});
});
"""


def token_of(p):
    return p.evaluate("() => localStorage.getItem('orneur_token')")


def api(p, method, path, body=None):
    tok = token_of(p)
    return p.evaluate(
        """async ([m,u,t,b]) => { const r = await fetch(u,{method:m,headers:{'Authorization':'Bearer '+t,'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});
        let j=null; try { j = await r.json(); } catch(e) {} return {status:r.status, json:j}; }""", [method, path, tok, body])


def active_sid(p):
    return p.evaluate("() => sessionId")


def committed(p, sid):
    r = api(p, "GET", f"/api/session/{sid}/messages")
    return [(m["role"], m["content"]) for m in (r["json"] or {}).get("messages", [])] if r["status"] == 200 else []


def usage(p):
    return api(p, "GET", "/api/usage")["json"]["today"]["messages"]


def choose_model(p):
    if "Choose model" not in p.inner_text("#model-label"):
        return
    p.click("#model-btn")
    p.wait_for_selector("#model-panel.open", timeout=10000)
    p.locator("#model-panel .modelopt:not(.unavailable)").first.click()
    p.wait_for_function("() => !document.getElementById('model-label').textContent.includes('Choose model')", timeout=5000)


def type_and_send(p, text):
    time.sleep(0.6)
    choose_model(p)
    p.fill("#msg-input", text)
    choose_model(p)
    p.click("#send-btn")


def n_done(p):
    return p.evaluate("window.__sseLog.filter(e => e.ev.type === 'done').length")


def wait_done(p, before, timeout=120000):
    p.wait_for_function("n => window.__sseLog.filter(e => e.ev.type === 'done').length > n", arg=before, timeout=timeout)


def n_answers(p):
    return p.locator(".answer .msg-body").count()


def wait_new_text(p, before, min_chars=8, timeout=60000):
    p.wait_for_function("([n, k]) => { const a=[...document.querySelectorAll('.answer .msg-body')]; return a.length > n && a[a.length-1].textContent.length >= k; }",
                        arg=[before, min_chars], timeout=timeout)


def sign_in(p):
    p.goto(f"{BASE}/conversation")
    p.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
    p.fill("#si-email", EMAIL)
    p.fill("#si-password", PW)
    p.click("#si-btn")
    p.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)


def new_conversation(p):
    p.evaluate("() => { if (typeof newConversation === 'function') newConversation(); }")
    p.wait_for_selector("#empty-view", state="visible", timeout=10000)


def reopen_conversation(p, sid):
    p.wait_for_selector("#recents-list .rec-row", timeout=20000)
    p.locator(f'#recents-list .rec[data-sid="{sid}"]').first.click()
    p.wait_for_selector(".msg-user .sample-q", timeout=15000)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    ctx.add_init_script(INIT)
    page = ctx.new_page()
    page_errors = []
    page.on("pageerror", lambda e: page_errors.append(str(e)))
    S = {}

    if PHASE == "after_restart":
        @step("R1_after_a_server_restart_the_committed_conversation_is_still_there")
        def r1():
            sign_in(page)
            reopen_conversation(page, RESUME_SID)
            sid = active_sid(page)
            assert sid == RESUME_SID, (sid, RESUME_SID)
            rows = committed(page, sid)
            assert len(rows) == RESUME_N, f"expected {RESUME_N} committed messages after the restart, got {len(rows)}"
            shown = page.locator(".msg-user .sample-q").count()
            assert shown == RESUME_N // 2, f"the page shows {shown} user messages"
            report("R1_after_a_server_restart_the_committed_conversation_is_still_there", True, f"{len(rows)} messages restored")
        r1()

        @step("R2_a_new_prompt_after_the_restart_is_streamed_and_saved")
        def r2():
            d0 = n_done(page)
            a0 = n_answers(page)
            type_and_send(page, "short question after restart" if FIXTURE else "Reply with the single word: ready.")
            wait_done(page, d0)
            ev = [e["ev"] for e in page.evaluate("window.__sseLog")]
            assert ev[-1]["type"] == "done" and ev[-1]["persisted"] == "saved" and ev[-1]["delivery"] == "upstream", ev[-1]
            assert len(committed(page, RESUME_SID)) == RESUME_N + 2
            report("R2_a_new_prompt_after_the_restart_is_streamed_and_saved", True, "")
        r2()
        browser.close()
        sys.exit(0)

    @step("J1_sign_in")
    def j1():
        sign_in(page)
        report("J1_sign_in", True, "")
    j1()

    @step("J2_new_conversation_long_prompt_renders_progressively_in_the_browser")
    def j2():
        new_conversation(page)
        page.evaluate("window.__sseLog = []; window.__domLog = []")
        type_and_send(page, LONG_PROMPT)
        d0 = 0
        wait_done(page, d0, timeout=180000)
        log = page.evaluate("window.__sseLog")
        kinds = [e["ev"]["type"] for e in log]
        stream_ev = next(e["ev"] for e in log if e["ev"]["type"] == "stream")
        assert stream_ev == {"type": "stream", "delivery": "upstream", "cancellable": True}, stream_ev
        chunks = [e for e in log if e["ev"]["type"] == "chunk"]
        assert len(chunks) >= 6, kinds[:12]
        assert chunks[-1]["t"] - chunks[0]["t"] >= (1500 if FIXTURE else 800), "chunks arrived together on the wire"
        dom = [d for d in page.evaluate("window.__domLog") if d["n"] > 0]
        distinct = sorted({d["n"] for d in dom})
        assert len(distinct) >= 3, f"DOM grew in too few distinct states: {dom[:8]}"
        assert dom[-1]["t"] - dom[0]["t"] >= (1500 if FIXTURE else 800), f"answer painted all at once: {dom[:6]}"
        shown = page.locator(".answer .msg-body").last.inner_text().strip()
        if FIXTURE:
            assert shown == FULL.strip(), shown
        assert shown and kinds[-1] == "done" and log[-1]["ev"]["persisted"] == "saved"
        S["sid"] = active_sid(page)
        S["n1"] = len(committed(page, S["sid"]))
        assert S["n1"] == 2
        S["main_sid"] = S["sid"]
        report("J2_new_conversation_long_prompt_renders_progressively_in_the_browser", True,
               f"chunks={len(chunks)} distinct_dom_states={len(distinct)} wire_ms={int(chunks[-1]['t']-chunks[0]['t'])} dom_ms={int(dom[-1]['t']-dom[0]['t'])}")
    j2()

    @step("J3_stop_is_usable_mid_stream_and_actually_stops_the_provider")
    def j3():
        sid = S["sid"]
        before_msgs, a0 = len(committed(page, sid)), n_answers(page)
        s0 = stats() if FIXTURE else None
        used0 = usage(page)
        page.evaluate("window.__sseLog = []")
        d0 = n_done(page)
        type_and_send(page, LONG_PROMPT + " (second)")
        wait_new_text(page, a0, 12)
        stop = page.locator("#send-btn[aria-label='Stop generating response']")
        assert stop.count() == 1, "Stop control is not offered while the answer is streaming"
        if FIXTURE:
            assert stats()["streams_open"] == 1
        stop.click()
        page.wait_for_selector(".interrupted-badge", timeout=15000)
        note = page.inner_text("#reading-container")
        assert "model connection was closed" in note, "the Stop message does not say what really happened: " + note[-300:]
        assert not any(e["ev"]["type"] == "done" for e in page.evaluate("window.__sseLog")), "a stopped generation must never show a completion"
        shown_at_stop = page.locator(".answer .msg-body").last.inner_text()
        if FIXTURE:
            assert wait_for(lambda: stats()["stream_aborts"] == s0["stream_aborts"] + 1 and stats()["streams_open"] == 0, 8), "provider generation was not cancelled: " + json.dumps(stats())
            sent = stats()["chunks_sent"]
            time.sleep(1.2)
            assert stats()["chunks_sent"] == sent, "the provider kept generating after Stop"
            assert FULL.strip() not in shown_at_stop
        time.sleep(0.8)
        assert len(committed(page, sid)) == before_msgs, "Stop left a phantom turn in the transcript"
        assert usage(page) - used0 == 1, "billing: the first model output arrived, so exactly one unit is spent (established policy)"
        assert page.evaluate("window.__sseLog.length") > 0
        report("J3_stop_is_usable_mid_stream_and_actually_stops_the_provider", True, f"shown_at_stop_chars={len(shown_at_stop)} {json.dumps(stats()) if FIXTURE else ''}")
    j3()

    @step("J4_the_next_prompt_succeeds_immediately_after_stop")
    def j4():
        sid = S["sid"]
        d0 = n_done(page)
        type_and_send(page, "short follow up one" if FIXTURE else "Reply with the single word: ready.")
        wait_done(page, d0)
        rows = committed(page, sid)
        assert len(rows) == S["n1"] + 2, rows
        assert rows[-2][0] == "user" and rows[-2][1].startswith("short follow up" if FIXTURE else "Reply with")
        report("J4_the_next_prompt_succeeds_immediately_after_stop", True, "conversation was not left busy")
    j4()

    @step("J5_a_full_response_is_saved_exactly_once")
    def j5():
        sid = S["sid"]
        d0 = n_done(page)
        a0 = n_answers(page)
        type_and_send(page, LONG_PROMPT + " (third)")
        wait_done(page, d0, timeout=180000)
        rows = committed(page, sid)
        assert len(rows) == S["n1"] + 4, rows
        saved = rows[-1][1]
        shown = page.locator(".answer .msg-body").last.inner_text().strip()
        assert saved.strip() == shown, "what the page shows differs from what was saved"
        if FIXTURE:
            assert saved == FULL
        assert n_answers(page) == a0 + 1, "the final answer was rendered twice"
        S["n3"] = len(rows)
        report("J5_a_full_response_is_saved_exactly_once", True, f"{len(saved)} chars")
    j5()

    @step("J6_refresh_recovers_the_committed_transcript")
    def j6():
        page.reload()
        page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        page.wait_for_selector(".msg-user .sample-q", timeout=20000)
        sid = active_sid(page)
        assert sid == S["sid"]
        assert page.locator(".msg-user .sample-q").count() == S["n3"] // 2
        assert page.locator(".answer .msg-body").count() == S["n3"] // 2
        report("J6_refresh_recovers_the_committed_transcript", True, f"{S['n3']} messages")
    j6()

    @step("J7_the_next_prompt_carries_only_committed_history")
    def j7():
        sid = S["sid"]
        d0 = n_done(page)
        type_and_send(page, "history probe question" if FIXTURE else "Reply with the single word: ok.")
        wait_done(page, d0)
        if FIXTURE:
            time.sleep(1.0)
            reqs = [r for r in ctl("/__requests")["requests"] if (r.get("messages") or [{}])[-1].get("content") == "history probe question"]
            assert len(reqs) == 1, len(reqs)
            ctx_text = json.dumps(reqs[0]["messages"])
            assert "short follow up one" in ctx_text and LONG_PROMPT in ctx_text
            assert "(second)" not in ctx_text, "the stopped generation's prompt leaked into later context"
        S["n4"] = len(committed(page, sid))
        report("J7_the_next_prompt_carries_only_committed_history", True, "")
    j7()

    @step("J8_editing_an_earlier_message_changes_what_the_model_is_sent")
    def j8():
        sid = S["sid"]
        page.reload()
        page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        page.wait_for_selector(".msg-user .edit-msg-btn", timeout=20000)
        msg = page.locator(".msg-user").nth(1)              # "short follow up one" (the stopped prompt was never committed, so it is not in the list)
        assert "short follow up one" in msg.inner_text() or not FIXTURE
        msg.locator(".edit-msg-btn").click()
        msg.locator(".edit-msg-textarea").fill("short follow up EDITED")
        page.wait_for_function("() => { const b=document.querySelectorAll('.msg-user')[1].querySelector('[data-action=save]'); return b && !b.disabled; }", timeout=20000)
        msg.locator("[data-action=save]").click()
        page.wait_for_selector(".msg-user .edited-badge", timeout=20000)
        d0 = n_done(page)
        type_and_send(page, "post edit probe" if FIXTURE else "Reply with the single word: yes.")
        wait_done(page, d0)
        if FIXTURE:
            time.sleep(1.0)
            reqs = [r for r in ctl("/__requests")["requests"] if (r.get("messages") or [{}])[-1].get("content") == "post edit probe"]
            assert len(reqs) == 1
            ctx_text = json.dumps(reqs[0]["messages"])
            assert "short follow up EDITED" in ctx_text and "short follow up one" not in ctx_text, ctx_text[:400]
        S["n_main"] = len(committed(page, sid))
        report("J8_editing_an_earlier_message_changes_what_the_model_is_sent", True, "")
    j8()

    if FIXTURE:
        @step("J9_two_tabs_stream_two_conversations_without_cross_talk")
        def j9():
            ctl("/__config", {"chunk_delay": 0.25})
            a = page
            b = ctx.new_page()
            b.goto(f"{BASE}/conversation")
            b.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
            new_conversation(a)
            new_conversation(b)
            a.evaluate("window.__sseLog = []")
            b.evaluate("window.__sseLog = []")
            type_and_send(a, "tab A question")
            type_and_send(b, "tab B question")
            wait_done(a, 0)
            wait_done(b, 0)
            sid_a, sid_b = active_sid(a), active_sid(b)
            assert sid_a != sid_b
            for p, sid, mine, other in ((a, sid_a, "tab A question", "tab B question"), (b, sid_b, "tab B question", "tab A question")):
                rows = committed(p, sid)
                assert [r[0] for r in rows] == ["user", "assistant"] and rows[0][1] == mine and rows[1][1] == FULL, rows
                assert other not in p.inner_text("#reading-container")
                assert p.locator(".answer .msg-body").last.inner_text().strip() == FULL.strip()
            b.close()
            report("J9_two_tabs_stream_two_conversations_without_cross_talk", True, "")
        j9()

        @step("J10_provider_outage_is_reported_without_a_phantom_turn_and_recovers")
        def j10():
            new_conversation(page)
            sid_holder = {}
            used0 = usage(page)
            ctl("/__config", {"fail_status": 503})
            page.evaluate("window.__sseLog = []")
            type_and_send(page, "question during the outage")
            page.wait_for_selector(".unavailable-note", timeout=30000)
            sid = active_sid(page)
            log = [e["ev"]["type"] for e in page.evaluate("window.__sseLog")]
            assert "done" not in log and "chunk" not in log, log
            assert committed(page, sid) == []
            assert usage(page) == used0, "an outage must not spend quota"
            assert not page.locator("#send-btn.stop-mode").count(), "the page is stuck in a streaming state"
            ctl("/__config", {"fail_status": None, "chunk_delay": 0.0})
            d0 = n_done(page)
            page.evaluate("window.__sseLog = []")
            type_and_send(page, "question after recovery")
            wait_done(page, 0)
            rows = committed(page, active_sid(page))
            assert [r[0] for r in rows] == ["user", "assistant"] and rows[0][1] == "question after recovery", rows
            assert usage(page) == used0 + 1
            report("J10_provider_outage_is_reported_without_a_phantom_turn_and_recovers", True, "")
        j10()

    @step("J11_temporary_chat_is_not_listed_and_is_deleted_on_close")
    def j11():
        new_conversation(page)
        page.click("#temp-mode-btn")
        page.wait_for_selector("#temp-mode-start", state="visible", timeout=10000)
        page.click("#temp-mode-start")
        page.wait_for_function("() => document.getElementById('temp-mode-active') && !document.getElementById('temp-mode-active').hidden || document.getElementById('relay-badge')", timeout=15000)
        d0 = n_done(page)
        page.evaluate("window.__sseLog = []")
        type_and_send(page, "temp secret quokka-5521" if FIXTURE else "Temp secret: quokka-5521. Reply with the single word: ok.")
        wait_done(page, 0)
        assert "quokka" not in page.inner_text("#recents-list").lower(), "temporary chat appears in history"
        sid = active_sid(page)
        page.click("#temp-mode-btn")
        page.wait_for_selector("#temp-mode-close-chat", state="visible", timeout=10000)
        page.click("#temp-mode-close-chat")
        time.sleep(2)
        got = api(page, "GET", f"/api/session/{sid}/messages")
        assert "quokka" not in json.dumps(got["json"]).lower(), got
        report("J11_temporary_chat_is_not_listed_and_is_deleted_on_close", True, f"transcript GET -> {got['status']}")
    j11()

    @step("J12_a_revoked_token_stops_the_page_and_never_reaches_the_model")
    def j12():
        n_req = stats()["requests"] if FIXTURE else None
        tok = token_of(page)
        req = urllib.request.Request(f"{BASE}/api/auth/logout", method="POST", headers={"Authorization": "Bearer " + tok})
        urllib.request.urlopen(req, timeout=15).read()
        new_conversation(page)
        type_and_send(page, "this must never reach the provider")
        page.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
        assert not token_of(page)
        if FIXTURE:
            time.sleep(1.0)
            assert stats()["requests"] == n_req, "a revoked credential reached the model"
        report("J12_a_revoked_token_stops_the_page_and_never_reaches_the_model", True, "")
    j12()

    if page_errors:
        report("PAGE_ERRORS", False, page_errors[:3])
    S_out = {"sid": S.get("main_sid"), "messages": S.get("n_main")}
    print(json.dumps({"step": "STATE", "ok": True, "detail": json.dumps(S_out)}), flush=True)
    browser.close()
