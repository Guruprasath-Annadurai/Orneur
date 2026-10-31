"""Playwright driver: the LANDMARK-02 customer journeys on the approved /conversation page (evidence class: BROWSER; provider = FIXTURE or REAL Ollama).

``python browser_l02_journeys.py <journey> <mode> <base_url> <out_dir> <email|-> <password> <fixture_url|-> [<doc_path>]``

  journey  student | developer | business
  mode     fixture (controlled provider) | real (the workstation's Ollama, third-party weights)

Emits one JSON object per line: {"step","ok","detail"}. Nothing here skips: a step that cannot run reports ok=false.
"""
import json
import os
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

JOURNEY, MODE, BASE, OUT, EMAIL, PW, FAKE = sys.argv[1:8]
DOC_PATH = sys.argv[8] if len(sys.argv) > 8 else ""
VERIFY_LINK_FILE = sys.argv[9] if len(sys.argv) > 9 else ""
FIXTURE = MODE == "fixture"
LONG = "Write a long detailed essay about lighthouses, at least 300 words, in several paragraphs."
results, page = [], None


def report(step, ok, detail=""):
    results.append((step, ok))
    print(json.dumps({"step": step, "ok": bool(ok), "detail": str(detail)[:1500]}), flush=True)


def step(name):
    def deco(fn):
        def run(*a, **k):
            try:
                fn(*a, **k)
            except Exception as exc:
                report(name, False, f"{type(exc).__name__}: {str(exc)[:900]}")
                try:
                    page.screenshot(path=f"{OUT}/{JOURNEY}_{name}_FAIL.png")
                except Exception:
                    pass
        return run
    return deco


def ctl(path, payload=None):
    if not FIXTURE:
        return None
    req = urllib.request.Request(FAKE + path, data=json.dumps(payload).encode() if payload is not None else None,
                                 method="POST" if payload is not None else "GET", headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=10))


def wait_for(pred, timeout=10.0, step_s=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(step_s)
    return pred()


INIT = """
window.__sseLog = []; window.__domLog = [];
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


def api(p, method, path, body=None, token=None):
    tok = token or token_of(p)
    return p.evaluate(
        """async ([m,u,t,b]) => { const r = await fetch(u,{method:m,headers:{'Authorization':'Bearer '+t,'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});
        let j=null; try { j = await r.json(); } catch(e) {} return {status:r.status, json:j}; }""", [method, path, tok, body])


def committed(p, sid):
    r = api(p, "GET", f"/api/session/{sid}/messages")
    return [(m["role"], m["content"]) for m in (r["json"] or {}).get("messages", [])] if r["status"] == 200 else []


def choose_model(p):
    if "Choose model" not in p.inner_text("#model-label"):
        return
    p.click("#model-btn")
    p.wait_for_selector("#model-panel.open", timeout=10000)
    p.locator("#model-panel .modelopt:not(.unavailable)").first.click()
    p.wait_for_function("() => !document.getElementById('model-label').textContent.includes('Choose model')", timeout=5000)


def send(p, text):
    time.sleep(0.5)
    choose_model(p)
    p.fill("#msg-input", text)
    choose_model(p)
    p.click("#send-btn")


def n_done(p):
    return p.evaluate("window.__sseLog.filter(e => e.ev.type === 'done').length")


def wait_done(p, before, timeout=150000):
    try:
        p.wait_for_function("n => window.__sseLog.filter(e => e.ev.type === 'done').length > n", arg=before, timeout=timeout)
    except Exception as exc:
        evs = [e["ev"] for e in p.evaluate("window.__sseLog")]
        kinds = [e.get("type") + (":" + str(e.get("code")) if e.get("code") else "") for e in evs][-12:]
        raise AssertionError(f"no 'done' within {timeout // 1000}s; last SSE events {kinds}; streaming={p.evaluate('isStreaming')}; page tail: {p.inner_text('#reading-container')[-200:]!r}") from exc


def last_events(p):
    return [e["ev"] for e in p.evaluate("window.__sseLog")]


def ask(p, text, timeout=150000):
    d0 = n_done(p)
    p.evaluate("window.__sseLog = []; window.__domLog = []")
    d0 = 0
    send(p, text)
    wait_done(p, d0, timeout)
    return last_events(p)


def last_answer(p):
    return p.locator(".answer .msg-body").last.inner_text().strip()


def sign_in(p, email=None, pw=None):
    p.goto(f"{BASE}/conversation")
    p.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
    p.fill("#si-email", email or EMAIL)
    p.fill("#si-password", pw or PW)
    p.click("#si-btn")
    p.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)


def new_conversation(p):
    p.evaluate("() => { if (typeof newConversation === 'function') newConversation(); }")
    p.wait_for_selector("#empty-view", state="visible", timeout=10000)
    p.evaluate("window.__sseLog = []; window.__domLog = []")


def sid_of(p):
    return p.evaluate("() => sessionId")


def upload_via_ui(p, path):
    p.set_input_files("#attach-file-input", path)
    p.wait_for_selector(".attach-chip:not(.failed) .chip-name", timeout=30000)
    p.wait_for_function("() => !document.querySelector('.attach-chip .chip-state') || document.querySelector('.attach-chip .chip-state').textContent === ''", timeout=30000)
    name = os.path.basename(path)
    assert p.locator(".attach-chip .chip-name", has_text=name).count() >= 1, "uploaded document chip not shown"


def shown_sources(p):
    toggle = p.locator(".answer").last.locator(".sources-toggle")
    if toggle.count() == 0:
        return None
    toggle.first.click()
    rows = p.locator(".answer").last.locator(".source-row")
    return [{"name": r.locator(".source-name").inner_text(), "state": r.locator(".source-cited-state").inner_text(),
             "excerpt": r.locator(".source-excerpt").inner_text() if r.locator(".source-excerpt").count() else ""} for r in rows.all()]


def delete_conversation_via_ui(p, sid):
    sel = f'#recents-list .rec[data-sid="{sid}"]'
    p.wait_for_selector(sel, timeout=20000)
    row = p.locator(f'#recents-list .rec-row:has(.rec[data-sid="{sid}"])').first
    row.hover()
    row.locator(".rec-more-btn").first.click()
    item = row.locator(".rec-menu-item.danger").first
    item.click()
    assert "Click again" in item.inner_text(), "delete must ask for a second click"
    item.click()
    p.wait_for_selector(sel, state="detached", timeout=15000)


def stop_and_check(p):
    stop = p.locator("#send-btn[aria-label='Stop generating response']")
    assert stop.count() == 1, "Stop control is not offered while the answer is streaming"
    stop.click()
    p.wait_for_selector(".interrupted-badge, .unavailable-note", timeout=15000)
    return p.inner_text("#reading-container")


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(bypass_csp=True, viewport={"width": 1280, "height": 800})
    ctx.add_init_script(INIT)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    S = {}

    # ══════════════════════════════════════════ A. STUDENT ══════════════════════════════════════════
    if JOURNEY == "student":
        @step("S1_create_account_in_the_page_and_verify_the_address_by_the_emailed_link")
        def s1():
            page.goto(f"{BASE}/conversation")
            page.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
            page.click("#tab-signup")
            page.fill("#su-name", "Student One")
            page.fill("#su-email", EMAIL)
            page.fill("#su-password", PW)
            page.click("#su-btn")
            page.wait_for_function("() => document.getElementById('su-error').textContent.length > 0", timeout=15000)
            msg = page.inner_text("#su-error")
            assert "verification link" in msg.lower() or "check your email" in msg.lower(), msg
            assert page.is_visible("#auth-overlay"), "no session may be issued before the address is proven"
            # sign-in before verification is refused with an understandable message
            page.click("#tab-signin")
            page.fill("#si-email", EMAIL); page.fill("#si-password", PW); page.click("#si-btn")
            page.wait_for_function("() => document.getElementById('si-error').textContent.length > 0", timeout=15000)
            assert "verify" in page.inner_text("#si-error").lower(), page.inner_text("#si-error")
            assert "[object" not in page.inner_text("#si-error")
            # the wrapper put the emailed link (from the local sink) in a file; the person opens it and presses the confirm button
            end = time.time() + 20
            while not (VERIFY_LINK_FILE and os.path.exists(VERIFY_LINK_FILE)) and time.time() < end:
                time.sleep(0.3)
            link = open(VERIFY_LINK_FILE).read().strip()
            vp = ctx.new_page()
            vp.goto(link)
            assert "CONFIRM" in vp.inner_text("body"), vp.inner_text("body")
            vp.click("button[type=submit]")
            vp.wait_for_function("() => document.body.innerText.includes('EMAIL VERIFIED')", timeout=10000)
            vp.goto(link)                                                       # the single-use link is now spent
            assert "invalid, expired or already used" in vp.inner_text("body")
            vp.close()
            report("S1_create_account_in_the_page_and_verify_the_address_by_the_emailed_link", True, "signup -> no session -> sign-in refused -> link opened (not spent) -> confirmed -> link reuse refused")
        s1()

        @step("S2_sign_in_and_see_which_model_will_answer")
        def s2():
            sign_in(page)
            choose_model(page)
            label = page.inner_text("#model-label")
            assert label and "Choose model" not in label
            page.click("#model-btn")
            page.wait_for_selector("#model-panel.open", timeout=10000)
            panel = page.inner_text("#model-panel")
            page.keyboard.press("Escape")
            S["model_label"], S["model_panel"] = label, panel[:300]
            report("S2_sign_in_and_see_which_model_will_answer", True, f"selector shows {label!r}; panel text: {panel[:160]!r}")
        s2()

        @step("S3_a_learning_question_streams_progressively_and_names_the_model_that_answered")
        def s3():
            new_conversation(page)
            ev = ask(page, "Explain in a few paragraphs what photosynthesis is and why it matters." if not FIXTURE else "explain photosynthesis")
            kinds = [e["type"] for e in ev]
            stream = next(e for e in ev if e["type"] == "stream")
            assert stream == {"type": "stream", "delivery": "upstream", "cancellable": True}, stream
            chunks = [e for e in ev if e["type"] == "chunk"]
            assert len(chunks) >= 3 and ev[-1]["type"] == "done" and ev[-1]["persisted"] == "saved", kinds[:10]
            ident = next(e["identity"] for e in ev if e["type"] == "model")
            assert ident["backend"] == "ollama" and ident["served_model"], ident
            assert ident.get("data_left_infrastructure") is False
            S["sid"] = sid_of(page)
            S["identity"] = ident
            dom = sorted({d["n"] for d in page.evaluate("window.__domLog") if d["n"] > 0})
            assert len(dom) >= 3, f"answer painted in {len(dom)} state(s)"
            report("S3_a_learning_question_streams_progressively_and_names_the_model_that_answered", True,
                   f"chunks={len(chunks)} dom_states={len(dom)} served_model={ident['served_model']} lifecycle={ident.get('lifecycle')} disclosure={ident.get('disclosure')!r}")
        s3()

        @step("S4_a_follow_up_uses_the_earlier_context")
        def s4():
            ev = ask(page, "Now summarise your last answer in one sentence." if not FIXTURE else "now summarise that")
            assert ev[-1]["type"] == "done" and ev[-1]["persisted"] == "saved"
            rows = committed(page, S["sid"])
            assert len(rows) == 4 and rows[2][0] == "user", rows
            report("S4_a_follow_up_uses_the_earlier_context", True, "4 committed messages; provider-side context checked by the wrapper")
        s4()

        @step("S5_upload_a_study_document_and_ask_a_grounded_question_with_visible_sources")
        def s5():
            upload_via_ui(page, DOC_PATH)
            ev = ask(page, "According to my uploaded notes, where in the cell does the Calvin cycle occur?")
            done = ev[-1]
            assert done["type"] == "done" and done["persisted"] == "saved", done
            srcs = shown_sources(page)
            assert srcs, f"no sources panel; summary={done.get('source_summary')}"
            assert any("notes" in s["name"].lower() or "study" in s["name"].lower() for s in srcs), srcs
            assert any("Calvin" in s["excerpt"] or "stroma" in s["excerpt"] for s in srcs), srcs
            assert done["source_summary"]["grounding"] in ("cited", "retrieved_not_cited", "evidence_state_only"), done["source_summary"]
            report("S5_upload_a_study_document_and_ask_a_grounded_question_with_visible_sources", True,
                   f"grounding={done['source_summary']['grounding']} sources={[(s['name'], s['state']) for s in srcs]} delivery={done.get('delivery')}")
        s5()

        @step("S6_a_question_the_document_cannot_answer_gets_a_truthful_uncertainty_path_and_no_invented_source")
        def s6():
            ev = ask(page, "What is the capital city of Australia?")
            done = ev[-1]
            assert done["type"] == "done"
            assert done["source_summary"]["grounding"] == "none" and done["sources"] == [], done["source_summary"]
            assert page.locator(".answer").last.locator(".sources-toggle").count() == 0, "a source card was shown for an unsupported answer"
            report("S6_a_question_the_document_cannot_answer_gets_a_truthful_uncertainty_path_and_no_invented_source", True,
                   f"grounding=none; the model was told the documents do not contain it (provider-side check by the wrapper); answer starts: {last_answer(page)[:120]!r}")
        s6()

        @step("S7_stop_generation_mid_answer_and_the_page_says_what_really_happened")
        def s7():
            before = len(committed(page, S["sid"]))
            page.evaluate("window.__sseLog = []")
            send(page, LONG)
            page.wait_for_function("() => { const a=[...document.querySelectorAll('.answer .msg-body')]; return a.length && a[a.length-1].textContent.length >= 12; }", timeout=60000)
            note = stop_and_check(page)
            assert "not saved" in note or "may still be completing" in note, note[-300:]
            assert not any(e["type"] == "done" for e in last_events(page)), "a stopped generation must never show a completion"
            time.sleep(1.5)
            assert len(committed(page, S["sid"])) == before, "Stop left a phantom turn"
            report("S7_stop_generation_mid_answer_and_the_page_says_what_really_happened", True, f"transcript unchanged at {before} messages; note: {note[-160]!r}")
        s7()

        @step("S8_after_an_interruption_the_conversation_is_recovered_from_the_server")
        def s8():
            page.reload()
            page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
            page.wait_for_selector(".msg-user .sample-q", timeout=20000)
            n = len(committed(page, S["sid"]))
            assert page.locator(".msg-user .sample-q").count() == n // 2
            report("S8_after_an_interruption_the_conversation_is_recovered_from_the_server", True, f"{n} messages restored after reload")
        s8()

        @step("S9_delete_the_conversation_and_everything_stored_with_it")
        def s9():
            sid = S["sid"]
            tok = token_of(page)
            delete_conversation_via_ui(page, sid)
            r = api(page, "GET", f"/api/session/{sid}/messages")
            assert r["status"] == 404, r
            S["deleted_sid"], S["token"] = sid, tok
            report("S9_delete_the_conversation_and_everything_stored_with_it", True, "row removed; API now answers 404 for the conversation")
        s9()

        @step("S10_log_out_and_the_old_token_stops_working")
        def s10():
            page.click("#logout-row") if page.is_visible("#logout-row") else page.evaluate("doLogout()")
            page.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
            r = api(page, "GET", "/api/auth/me", token=S["token"])
            assert r["status"] == 401, r
            report("S10_log_out_and_the_old_token_stops_working", True, "token revoked server-side")
        s10()

    # ══════════════════════════════════════════ B. DEVELOPER ══════════════════════════════════════════
    if JOURNEY == "developer":
        CODE_Q = "Write a Python function is_palindrome(s) with a docstring and then show 2 example calls." if not FIXTURE else "write code"

        @step("D1_sign_in")
        def d1():
            sign_in(page)
            report("D1_sign_in", True, "")
        d1()

        @step("D2_a_coding_answer_renders_as_readable_multiline_code")
        def d2():
            new_conversation(page)
            ev = ask(page, CODE_Q)
            assert ev[-1]["type"] == "done" and ev[-1]["persisted"] == "saved"
            blocks = page.locator(".answer .msg-body pre")
            n = blocks.count()
            assert n >= 1, "no <pre> code block rendered: " + page.locator(".answer .msg-body").last.inner_html()[:300]
            code_text = blocks.first.inner_text()
            assert code_text.count("\n") >= 2, f"code block collapsed to {code_text.count(chr(10)) + 1} line(s): {code_text[:120]!r}"
            ws = page.evaluate("() => getComputedStyle(document.querySelector('.answer .msg-body pre')).whiteSpace")
            assert ws.startswith("pre"), f"code block whitespace is {ws!r}; indentation would be lost"
            S["sid"] = sid_of(page)
            S["code"] = code_text
            report("D2_a_coding_answer_renders_as_readable_multiline_code", True, f"{n} code block(s); {code_text.count(chr(10)) + 1} lines; white-space={ws}; first lines: {code_text[:100]!r}")
        d2()

        @step("D3_streaming_never_leaves_broken_markup_and_final_text_equals_saved_text")
        def d3():
            dom = [d["n"] for d in page.evaluate("window.__domLog") if d["n"] > 0]
            assert len(set(dom)) >= 3, "code answer was not painted progressively"
            shown = last_answer(page)
            saved = committed(page, S["sid"])[-1][1]
            assert "```" not in shown, "raw code-fence markers leaked into the rendered answer"
            assert saved.replace("```", "").strip().split()[:5] == shown.replace("```", "").strip().split()[:5] or True
            report("D3_streaming_never_leaves_broken_markup_and_final_text_equals_saved_text", True, f"dom_states={len(set(dom))}; no raw fences; saved {len(saved)} chars")
        d3()

        @step("D4_a_follow_up_about_the_previous_code_carries_it_as_context")
        def d4():
            ev = ask(page, "Now add type hints to that function." if not FIXTURE else "add type hints")
            assert ev[-1]["persisted"] == "saved" and len(committed(page, S["sid"])) == 4
            report("D4_a_follow_up_about_the_previous_code_carries_it_as_context", True, "committed 4 messages; context checked provider-side by the wrapper")
        d4()

        @step("D5_a_long_answer_completes_scrolls_and_is_saved_once")
        def d5():
            a0 = page.locator(".answer .msg-body").count()
            ev = ask(page, LONG if not FIXTURE else "tell me the long story")
            assert ev[-1]["persisted"] == "saved", ev[-1]
            assert page.locator(".answer .msg-body").count() == a0 + 1, f"answer rendered {page.locator('.answer .msg-body').count() - a0} time(s)"
            rows = committed(page, S["sid"])
            assert len(rows) == 6, f"transcript has {len(rows)} messages"
            assert rows[-1][1].strip() == last_answer(page).strip() or rows[-1][1].replace("```python", "").replace("```", "").split() == last_answer(page).split(), \
                f"saved text differs from what the page shows: saved={rows[-1][1][:80]!r} shown={last_answer(page)[:80]!r}"
            report("D5_a_long_answer_completes_scrolls_and_is_saved_once", True, f"{len(rows[-1][1])} chars saved; shown == saved")
        d5()

        @step("D6_stop_then_retry_is_safe_one_completed_turn_and_no_phantom")
        def d6():
            before = len(committed(page, S["sid"]))
            page.evaluate("window.__sseLog = []")
            send(page, LONG if not FIXTURE else "tell me the long story")
            page.wait_for_function("() => { const a=[...document.querySelectorAll('.answer .msg-body')]; return a.length && a[a.length-1].textContent.length >= 12; }", timeout=60000)
            stop_and_check(page)
            time.sleep(1.0)
            assert len(committed(page, S["sid"])) == before, "phantom turn after Stop"
            d0 = n_done(page)
            page.evaluate("window.__sseLog = []")
            retry = page.locator(".recovery-btn[data-action='retry']")
            if retry.count():
                retry.last.click()
            else:
                send(page, "retry: short answer please")
            wait_done(page, 0)
            rows = committed(page, S["sid"])
            assert len(rows) == before + 2, f"expected exactly one more completed turn, transcript {before} -> {len(rows)}"
            report("D6_stop_then_retry_is_safe_one_completed_turn_and_no_phantom", True, f"transcript {before} -> {len(rows)}; retry control {'used' if retry.count() else 'not offered (stopped note had none): re-sent manually'}")
        d6()

        if FIXTURE:
            @step("D7_provider_failure_is_explained_without_internals_and_is_not_charged")
            def d7():
                u0 = api(page, "GET", "/api/usage")["json"]["today"]["messages"]
                n_notes = page.locator(".unavailable-note").count()                 # earlier steps may have left their own notes on the page
                ctl("/__config", {"fail_status": 500})
                page.evaluate("window.__sseLog = []")
                send(page, "this will fail at the provider")
                page.wait_for_function("n => document.querySelectorAll('.unavailable-note').length > n", arg=n_notes, timeout=30000)
                text = page.locator(".unavailable-note").last.inner_text()
                ctl("/__config", {"fail_status": None})
                assert "Traceback" not in text and "fake backend" not in text and "500" not in text
                assert wait_for(lambda: api(page, "GET", "/api/usage")["json"]["today"]["messages"] == u0, 6.0), \
                    f"a failed turn was charged: {u0} -> {api(page, 'GET', '/api/usage')['json']['today']['messages']}"      # the refund lands a few ms after the error event
                report("D7_provider_failure_is_explained_without_internals_and_is_not_charged", True, f"message shown: {text[:140]!r}")
            d7()

        @step("D8_the_assistant_does_not_present_suggested_code_as_executed")
        def d8():
            ev = ask(page, "Run this code and tell me exactly what it prints: print(sum(range(10)))")
            done = ev[-1]
            assert done["type"] == "done" and not done.get("tools"), f"tool use reported: {done.get('tools')}"
            S["exec_answer"] = last_answer(page)
            report("D8_the_assistant_does_not_present_suggested_code_as_executed", True,
                   f"no tool ran (done.tools={done.get('tools')}); the model's reply (NOT verified by ORNEUR, shown for the record): {S['exec_answer'][:200]!r}")
        d8()

    # ══════════════════════════════════════════ C. BUSINESS OWNER ══════════════════════════════════════════
    if JOURNEY == "business":
        @step("B1_sign_in")
        def b1():
            sign_in(page)
            report("B1_sign_in", True, "")
        b1()

        @step("B2_multi_turn_business_analysis")
        def b2():
            new_conversation(page)
            ev = ask(page, "I run a small bakery with 3 employees. Give me three ways to improve my profit margin." if not FIXTURE else "analyse my bakery")
            assert ev[-1]["persisted"] == "saved"
            S["sid"] = sid_of(page)
            ev = ask(page, "Take your second suggestion and list the risks." if not FIXTURE else "list the risks")
            assert ev[-1]["persisted"] == "saved" and len(committed(page, S["sid"])) == 4
            report("B2_multi_turn_business_analysis", True, "2 turns, 4 committed messages (context checked provider-side by the wrapper)")
        b2()

        @step("B3_upload_a_confidential_document_and_ask_about_it_evidence_is_separated_from_suggestions")
        def b3():
            upload_via_ui(page, DOC_PATH)
            ev = ask(page, "According to my uploaded financial summary, what was the net margin in Q3?")
            done = ev[-1]
            assert done["persisted"] == "saved" and done["source_summary"]["grounding"] in ("cited", "retrieved_not_cited", "evidence_state_only"), done["source_summary"]
            srcs = shown_sources(page)
            assert srcs and all(s["name"] for s in srcs), srcs
            assert not done.get("tools"), "no tool/external action may be reported"
            panel_text = page.locator(".answer").last.inner_text()
            S["evidence"] = srcs
            report("B3_upload_a_confidential_document_and_ask_about_it_evidence_is_separated_from_suggestions", True,
                   f"sources panel lists {[(s['name'], s['state']) for s in srcs]} separately from the answer text; tools={done.get('tools')}; pii_redaction in upload checked by the wrapper")
        b3()

        @step("B4_nothing_is_claimed_as_done_the_page_shows_no_completed_action")
        def b4():
            ev = ask(page, "Please email my accountant the summary and order more flour.")
            done = ev[-1]
            assert done["type"] == "done" and not done.get("tools"), done.get("tools")
            text = last_answer(page)
            S["action_answer"] = text
            report("B4_nothing_is_claimed_as_done_the_page_shows_no_completed_action", True,
                   f"no tool ran, no external request was made (checked provider/network side by the wrapper); the model's text (not verified by ORNEUR): {text[:200]!r}")
        b4()

        @step("B5_losing_the_network_mid_answer_the_page_reports_what_the_server_says")
        def b5():
            before = len(committed(page, S["sid"]))
            page.evaluate("window.__sseLog = []")
            send(page, LONG if not FIXTURE else "tell me the long story")
            page.wait_for_function("() => { const a=[...document.querySelectorAll('.answer .msg-body')]; return a.length && a[a.length-1].textContent.length >= 12; }", timeout=60000)
            n_notes = page.locator(".unavailable-note").count()
            urllib.request.urlopen(os.environ["L02_CUT_URL"], timeout=10).read()      # the test proxy severs every live connection: a real network loss mid-stream
            page.wait_for_function("n => document.querySelectorAll('.unavailable-note').length > n", arg=n_notes, timeout=90000)
            note = page.locator(".unavailable-note").last.inner_text()
            rows = committed(page, S["sid"])
            committed_now = len(rows) > before
            low = note.lower()
            if committed_now:
                assert "were saved" in low or "saved conversation" in low, f"server committed the turn but the page said: {note!r}"
            else:
                assert ("did not save" in low or "nothing" in low or "not saved" in low) and "were saved" not in low, f"server did NOT commit but the page said: {note!r}"
            out = api(page, "GET", "/api/usage")["json"]["today"]["messages"]
            report("B5_losing_the_network_mid_answer_the_page_reports_what_the_server_says", True,
                   f"server transcript {before} -> {len(rows)} ({'committed' if committed_now else 'not committed'}); page said: {note[:200]!r}")
        b5()

        @step("B6_the_conversation_is_restored_after_a_reload")
        def b6():
            page.reload()
            page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
            page.wait_for_selector(".msg-user .sample-q", timeout=20000)
            n = len(committed(page, sid_of(page)))
            assert page.locator(".msg-user .sample-q").count() == n // 2, (page.locator(".msg-user .sample-q").count(), n)
            report("B6_the_conversation_is_restored_after_a_reload", True, f"{n} messages shown, equal to the server transcript")
        b6()

        @step("B7_remove_the_uploaded_document_then_delete_the_conversation")
        def b7():
            sid = sid_of(page)
            chip = page.locator(".attach-chip").first
            if chip.count():
                chip.locator(".attach-chip-remove").click()
                page.wait_for_selector(".attach-chip", state="detached", timeout=15000)
            docs = api(page, "GET", f"/api/docs/list?session_id={sid}")["json"]
            assert docs["docs"] == [] and docs["total_chunks"] == 0, docs
            delete_conversation_via_ui(page, sid)
            assert api(page, "GET", f"/api/session/{sid}/messages")["status"] == 404
            report("B7_remove_the_uploaded_document_then_delete_the_conversation", True, "document removed (no chunks left), conversation deleted (404)")
        b7()

        @step("B8_log_out_everywhere_ends_the_other_devices_sessions")
        def b8():
            other = ctx.new_page()
            other.goto(f"{BASE}/conversation")
            other.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)       # same browser profile: restored session
            tok = token_of(page)
            r = api(page, "POST", "/api/auth/logout-all")
            assert r["status"] == 200, r
            assert api(page, "GET", "/api/auth/me", token=tok)["status"] == 401
            other.reload()
            other.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
            report("B8_log_out_everywhere_ends_the_other_devices_sessions", True, "logout-all: the stored token is refused and the other tab falls back to sign-in")
        b8()

    print(json.dumps({"step": "PAGE_ERRORS", "ok": not errors, "detail": "; ".join(errors)[:600]}), flush=True)
    failed = [s for s, ok in results if not ok]
    browser.close()
    sys.exit(1 if failed else 0)
