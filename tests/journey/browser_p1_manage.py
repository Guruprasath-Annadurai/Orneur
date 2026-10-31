"""Playwright driver: conversation management, tenant isolation and the mobile journey on the approved /conversation page (evidence class: BROWSER + FIXTURE provider).

``python browser_p1_manage.py <base_url> <out_dir> <alice_email> <bob_email> <fake_url>`` -- prints one JSON object per line: {"step","ok","detail"}.
"""
import json
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASE, OUT, ALICE, BOB, FAKE = sys.argv[1:6]
PW = "Journey-Pass-91x"
WORD = "zebracrossing" + str(int(time.time()))[-5:]


def report(step, ok, detail=""):
    print(json.dumps({"step": step, "ok": bool(ok), "detail": str(detail)[:900]}), flush=True)


def stats():
    return json.load(urllib.request.urlopen(FAKE + "/__stats", timeout=10))


def step(name, page_getter=None):
    def deco(fn):
        def run(*a, **k):
            try:
                fn(*a, **k)
                report(name, True, "")
            except Exception as exc:
                report(name, False, f"{type(exc).__name__}: {str(exc)[:700]}")
                try:
                    (page_getter() if page_getter else cur["p"]).screenshot(path=f"{OUT}/{name}_FAIL.png")
                except Exception:
                    pass
        return run
    return deco


cur = {}


def sign_in(p, email):
    p.goto(f"{BASE}/conversation")
    p.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
    p.fill("#si-email", email)
    p.fill("#si-password", PW)
    p.click("#si-btn")
    p.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)


def token(p):
    return p.evaluate("() => localStorage.getItem('orneur_token')")


def api(p, method, path, body=None, tok=None):
    return p.evaluate("""async ([m,u,t,b]) => { const r = await fetch(u,{method:m,headers:{'Authorization':'Bearer '+t,'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});
        let j=null; try { j = await r.json(); } catch(e) {} return {status:r.status, json:j}; }""", [method, path, tok or token(p), body])


def send(p, text):
    time.sleep(0.6)
    if "Choose model" in p.inner_text("#model-label"):
        p.click("#model-btn")
        p.wait_for_selector("#model-panel.open", timeout=10000)
        p.locator("#model-panel .modelopt:not(.unavailable)").first.click()
    p.fill("#msg-input", text)
    p.click("#send-btn")


def wait_saved(p, n_messages, timeout=60):
    end = time.time() + timeout
    sid = None
    while time.time() < end:
        sid = p.evaluate("() => sessionId")
        if sid:
            r = api(p, "GET", f"/api/session/{sid}/messages")
            if r["status"] == 200 and len(r["json"]["messages"]) >= n_messages and not p.evaluate("() => document.getElementById('send-btn').classList.contains('stop-mode')"):
                return sid
        time.sleep(0.3)
    raise AssertionError(f"conversation never reached {n_messages} saved messages")


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    errors = []

    # ---------------------------------------------------------------- desktop, two independent users
    ca = browser.new_context(viewport={"width": 1280, "height": 800})
    cb = browser.new_context(viewport={"width": 1280, "height": 800})
    pa, pb = ca.new_page(), cb.new_page()
    for p in (pa, pb):
        p.on("pageerror", lambda e: errors.append(str(e)))
    state = {}

    @step("M1_a_new_conversation_is_created_answered_and_listed", lambda: pa)
    def m1():
        cur["p"] = pa
        sign_in(pa, ALICE)
        send(pa, f"Please remember the code word {WORD} for later")
        sid = wait_saved(pa, 2)
        state["sid"] = sid
        pa.wait_for_selector(f'#recents-list .rec[data-sid="{sid}"]', timeout=15000)
    m1()

    @step("M2_rename_from_the_menu_persists_across_reload", lambda: pa)
    def m2():
        sid = state["sid"]
        row = pa.locator("#recents-list .rec-row").first          # alice has exactly one conversation; the row loses its :has(.rec) match while the title is edited
        assert pa.locator("#recents-list .rec-row").count() == 1
        row.hover()
        row.locator(".rec-more-btn").click()
        row.locator(".rec-menu-item", has_text="Rename").click()
        inp = row.locator(".rec-rename-input")
        inp.fill("Quarterly zebra plan")
        inp.press("Enter")
        pa.wait_for_function("sid => { const b = document.querySelector('#recents-list .rec[data-sid=\"'+sid+'\"]'); return b && b.textContent.includes('Quarterly zebra plan'); }", arg=sid, timeout=10000)
        server_title = [s for s in api(pa, "GET", "/api/sessions")["json"]["sessions"] if s["id"] == sid][0]
        assert "Quarterly zebra plan" in json.dumps(server_title), server_title
        pa.reload()
        pa.wait_for_selector(f'#recents-list .rec[data-sid="{sid}"]', timeout=20000)
        assert "Quarterly zebra plan" in pa.locator(f'#recents-list .rec[data-sid="{sid}"]').inner_text()
    m2()

    @step("M3_search_finds_own_conversation_by_content_and_never_anothers", lambda: pa)
    def m3():
        sid = state["sid"]
        pa.fill("#conv-search-input", WORD)
        pa.wait_for_selector(f'#recents-list .rec[data-sid="{sid}"]', timeout=15000)
        found = pa.locator("#recents-list .rec").count()
        assert found == 1, f"{found} results for alice"
        pa.fill("#conv-search-input", "")
        sign_in(pb, BOB)
        send(pb, "bob asks about something entirely different")
        state["bob_sid"] = wait_saved(pb, 2)
        pb.wait_for_selector(f'#recents-list .rec[data-sid="{state["bob_sid"]}"]', timeout=15000)
        pb.fill("#conv-search-input", WORD)
        pb.wait_for_function("() => /No matching/.test(document.getElementById('recents-list').textContent)", timeout=15000)
        assert pb.locator("#recents-list .rec").count() == 0, "bob found alice's conversation"
        assert "No matching" in pb.inner_text("#recents-list"), pb.inner_text("#recents-list")[:200]
    m3()

    @step("M4_another_user_cannot_read_modify_stream_into_or_delete_the_conversation", lambda: pb)
    def m4():
        sid = state["sid"]
        tb = token(pb)
        reads = [api(pb, "GET", f"/api/session/{sid}/messages")["status"], api(pb, "GET", f"/api/session/{sid}/export?format=json")["status"]]
        mods = [api(pb, "PATCH", f"/api/session/{sid}/title", {"title": "pwned"})["status"], api(pb, "DELETE", f"/api/session/{sid}")["status"]]
        assert all(s in (403, 404) for s in reads + mods), (reads, mods)
        before = stats()["requests"]
        st = pb.evaluate("""async ([t,sid]) => { const r = await fetch('/api/stream', {method:'POST', headers:{'Authorization':'Bearer '+t,'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()}, body: JSON.stringify({message:'inject', session_id:sid, model:'orca-nano'})}); return r.status; }""", [tb, sid])
        assert st in (403, 404), f"streaming into another user's session returned {st}"
        assert stats()["requests"] == before, "a refused cross-user stream still reached the model"
        # the UI path: opening the foreign id shows nothing of the transcript
        pb.evaluate("sid => openSession(sid, 'x')", sid)
        time.sleep(1.5)
        assert WORD not in pb.inner_text("body"), "foreign transcript text appeared in bob's page"
        # alice's data is intact
        assert len(api(pa, "GET", f"/api/session/{sid}/messages")["json"]["messages"]) == 2
    m4()

    @step("M5_reopen_after_close_and_login_restores_the_exact_transcript", lambda: pa)
    def m5():
        sid = state["sid"]
        before = api(pa, "GET", f"/api/session/{sid}/messages")["json"]["messages"]
        ca.close()
        c2 = browser.new_context(viewport={"width": 1280, "height": 800})
        p2 = c2.new_page()
        sign_in(p2, ALICE)
        p2.wait_for_selector(f'#recents-list .rec[data-sid="{sid}"]', timeout=20000)
        p2.locator(f'#recents-list .rec[data-sid="{sid}"]').click()
        p2.wait_for_selector(".msg-user .sample-q", timeout=15000)
        assert WORD in p2.inner_text("#reading-container")
        after = api(p2, "GET", f"/api/session/{sid}/messages")["json"]["messages"]
        assert [m["content"] for m in before] == [m["content"] for m in after]
        cur["p2"] = p2
        state["p2"] = p2
    m5()

    @step("M6_delete_needs_confirmation_then_removes_it_everywhere", lambda: state["p2"])
    def m6():
        p2, sid = state["p2"], state["sid"]
        row = p2.locator(f'#recents-list .rec-row:has(.rec[data-sid="{sid}"])')
        row.hover()
        row.locator(".rec-more-btn").click()
        item = row.locator(".rec-menu-item.danger")
        item.click()
        assert api(p2, "GET", f"/api/session/{sid}/messages")["status"] == 200, "deleted without confirmation"
        item.click()
        p2.wait_for_function("sid => !document.querySelector('#recents-list .rec[data-sid=\"'+sid+'\"]')", arg=sid, timeout=10000)
        assert api(p2, "GET", f"/api/session/{sid}/messages")["status"] in (404, 410)
        p2.reload()
        p2.wait_for_selector("#recents-list", timeout=15000)
        time.sleep(1.0)
        assert not p2.locator(f'#recents-list .rec[data-sid="{sid}"]').count()
    m6()

    # ---------------------------------------------------------------- mobile (touch) journey
    cm = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, has_touch=True, is_mobile=True)
    pm = cm.new_page()
    pm.on("pageerror", lambda e: errors.append(str(e)))

    @step("N1_mobile_navigation_send_stream_stop_and_reopen", lambda: pm)
    def n1():
        sign_in(pm, BOB)
        hscroll = pm.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
        assert hscroll <= 1, f"page scrolls horizontally on mobile by {hscroll}px"
        pm.tap("#mobilemenu-btn")
        pm.wait_for_selector(".sidebar.mobile-open", timeout=5000)
        assert pm.locator("#sidebar-veil.show").count() == 1
        pm.tap("#sidebar-veil", position={"x": 380, "y": 400})
        pm.wait_for_function("() => !document.querySelector('.sidebar.mobile-open')", timeout=5000)
        before_aborts = stats()["stream_aborts"]
        send(pm, "tell me the long story")
        pm.wait_for_function("() => document.getElementById('send-btn').classList.contains('stop-mode')", timeout=20000)
        pm.wait_for_function("() => { const a=[...document.querySelectorAll('.answer .msg-body')]; return a.length && a[a.length-1].textContent.length > 3; }", timeout=20000)
        t0 = time.time()
        pm.tap("#send-btn")
        pm.wait_for_function("() => !document.getElementById('send-btn').classList.contains('stop-mode')", timeout=10000)
        state["stop_ui_s"] = round(time.time() - t0, 2)
        end = time.time() + 10
        while time.time() < end and stats()["stream_aborts"] <= before_aborts:
            time.sleep(0.2)
        assert stats()["stream_aborts"] > before_aborts, "Stop on mobile did not hang up on the provider"
        sid = pm.evaluate("() => sessionId")
        time.sleep(1.0)
        msgs = api(pm, "GET", f"/api/session/{sid}/messages")["json"]["messages"] if sid else []
        assert not any(m["role"] == "assistant" and m["content"].startswith("w0 w1 w2 w3 w4 w5 w6 w7 w8 w9 w10 w11 w12 w13 w14 w15") for m in msgs), "a stopped turn was stored as complete"
        pm.reload()
        pm.tap("#mobilemenu-btn")
        pm.wait_for_selector("#recents-list .rec-row", timeout=20000)
        report("N1_detail", True, json.dumps({"stop_ui_s": state["stop_ui_s"], "messages_after_stop": [m["role"] for m in msgs]}))
    n1()

    @step("N2_mobile_touch_targets_and_layout", lambda: pm)
    def n2():
        pm.goto(f"{BASE}/conversation")
        pm.wait_for_selector("#mobilemenu-btn", timeout=15000)
        small = pm.evaluate("""() => [...document.querySelectorAll('#mobilemenu-btn, #send-btn, #model-btn, #msg-input')].filter(e => e.offsetParent !== null)
            .map(e => { const r = e.getBoundingClientRect(); return {id: e.id, w: Math.round(r.width), h: Math.round(r.height)}; }).filter(o => o.w < 24 || o.h < 24)""")
        assert not small, f"targets below the WCAG 2.2 AA minimum of 24x24 CSS px: {small}"
        assert pm.evaluate("() => document.documentElement.scrollWidth - window.innerWidth") <= 1
    n2()

    # ---------------------------------------------------------------- accessibility basics (desktop + mobile)
    @step("H1_controls_have_accessible_names_and_visible_focus", lambda: pm)
    def h1():
        pd = browser.new_context(viewport={"width": 1280, "height": 800}).new_page()
        pd.goto(f"{BASE}/conversation")
        pd.wait_for_selector("#auth-overlay", timeout=15000)
        for p in (pd, pm):
            if p is pm:
                p.goto(f"{BASE}/conversation")
                p.wait_for_selector("#mobilemenu-btn", timeout=15000)
            nameless = p.evaluate("""() => [...document.querySelectorAll('button, input, select, textarea, [role=button], a[href]')].filter(e => e.offsetParent !== null && !e.closest('[aria-hidden=true]'))
                .filter(e => { const n = (e.getAttribute('aria-label') || e.getAttribute('aria-labelledby') || e.textContent || e.getAttribute('title') || e.getAttribute('placeholder') || '').trim(); return !n; })
                .map(e => e.id || e.className || e.tagName)""")
            assert not nameless, f"controls with no accessible name: {nameless[:8]}"
        assert pd.evaluate("() => document.documentElement.lang") == "en"
        pd.keyboard.press("Tab")
        ring = pd.evaluate("() => { const e = document.activeElement; const s = getComputedStyle(e); return {tag: e.tagName, outline: s.outlineStyle + ' ' + s.outlineWidth, shadow: s.boxShadow}; }")
        assert ring["outline"].split()[0] != "none" or ring["shadow"] != "none", f"no visible focus indicator: {ring}"
    h1()

    @step("H2_reduced_motion_is_honoured", lambda: pm)
    def h2():
        c = browser.new_context(reduced_motion="reduce")
        p = c.new_page()
        p.goto(f"{BASE}/conversation")
        p.wait_for_selector("#auth-overlay", timeout=15000)
        durations = p.evaluate("""() => [...document.querySelectorAll('*')].map(e => getComputedStyle(e)).filter(s => parseFloat(s.animationDuration) > 0.2 && s.animationIterationCount !== '1').length""")
        assert durations == 0, f"{durations} looping animations still run under prefers-reduced-motion"
    h2()

    report("Z_no_uncaught_page_errors", not errors, "; ".join(errors)[:400])
    browser.close()
