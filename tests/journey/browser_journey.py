"""Playwright driver for the approved /conversation page (evidence class: BROWSER).

Runs OUTSIDE the project venv (see harness doc): ``python browser_journey.py <base_url> <out_dir>``.
Emits one JSON object per line on stdout: {"step", "ok", "detail"}.
It never edits the page, never injects scripts into app code, and drives only
visible controls (plus read-only fetches of the same public API for isolation /
revocation probes, made from inside the page with the page's own stored token).
"""
import json
import sys
import time
import uuid

from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

BASE, OUT = sys.argv[1], sys.argv[2]
PW = "Journey-Pass-91x"
results = []


def report(step, ok, detail=""):
    results.append((step, ok))
    print(json.dumps({"step": step, "ok": bool(ok), "detail": str(detail)[:600]}), flush=True)


def step(name):
    def deco(fn):
        def run(*a, **k):
            try:
                fn(*a, **k)
            except Exception as exc:  # a failed step is data, not a crash
                report(name, False, f"{type(exc).__name__}: {str(exc)[:500]}")
                try:
                    shot(globals()["page"], name + "_FAIL")
                except Exception:
                    pass
        return run
    return deco


def shot(page, name):
    try:
        page.screenshot(path=f"{OUT}/{name}.png", full_page=False)
    except Exception:
        pass


def api_signup(email, name):
    import urllib.request
    req = urllib.request.Request(f"{BASE}/api/auth/signup", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"email": email, "password": PW, "name": name}).encode())
    urllib.request.urlopen(req, timeout=30).read()


def sign_in(page, email, password=PW):
    page.goto(f"{BASE}/conversation")
    page.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
    page.fill("#si-email", email)
    page.fill("#si-password", password)
    page.click("#si-btn")


def choose_model(page):
    """The approved composer keeps Send disabled until the user picks a model (B05)."""
    if "Choose model" not in page.inner_text("#model-label"):
        return
    page.click("#model-btn")
    page.wait_for_selector("#model-panel.open", timeout=10000)
    opts = page.locator("#model-panel .modelopt:not(.unavailable)")
    assert opts.count() >= 1, "no selectable model in the picker: " + page.inner_text("#model-panel")
    shot(page, "B0_model_picker_light")
    opts.first.click()
    page.wait_for_function("() => !document.getElementById('model-label').textContent.includes('Choose model')", timeout=5000)


def send(page, text, wait_done=True, timeout=120000):
    time.sleep(0.6)  # composer re-renders after new-conversation / temporary-chat start
    choose_model(page)
    page.fill("#msg-input", text)
    choose_model(page)
    before = page.locator(".answer .msg-body").count()
    page.click("#send-btn")
    page.wait_for_function("n => document.querySelectorAll('.answer .msg-body').length > n", arg=before, timeout=timeout)
    if wait_done:
        # terminal state: Send is usable again and the last answer has text
        page.wait_for_function(
            "() => { const a=[...document.querySelectorAll('.answer .msg-body')].pop();"
            " return a && a.textContent.trim().length>0 && !document.querySelector('.thinking'); }", timeout=timeout)
        time.sleep(1.0)
    return page.locator(".answer .msg-body").last.inner_text()


def http_status(method, path, token, body=None):
    """Plain urllib request from the driver process -- independent of the page -- returns the HTTP status."""
    import urllib.error
    import urllib.request
    headers = {"Authorization": "Bearer " + token}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if path == "/api/stream":
        headers["Idempotency-Key"] = str(uuid.uuid4())
    req = urllib.request.Request(BASE + path, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read(200)
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def api_login(email):
    import urllib.request
    req = urllib.request.Request(f"{BASE}/api/auth/login", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"email": email, "password": PW}).encode())
    return json.loads(urllib.request.urlopen(req, timeout=30).read())["token"]


def token_of(page):
    return page.evaluate("() => localStorage.getItem('orneur_token')")


def api_from_page(page, method, path, token, body=None):
    return page.evaluate(
        """async ([m,p,t,b]) => { const r = await fetch(p,{method:m,headers:{'Authorization':'Bearer '+t,'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});
        return {status:r.status, text:(await r.text()).slice(0,400)}; }""", [method, path, token, body])


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    alice_email = f"ui-alice-{uuid.uuid4().hex[:6]}@example.com"
    bob_email = f"ui-bob-{uuid.uuid4().hex[:6]}@example.com"
    api_signup(alice_email, "Alice")
    api_signup(bob_email, "Bob")
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    console_errors = []
    page.on("pageerror", lambda e: console_errors.append(str(e)))
    state = {}

    @step("A1_login_form_rejects_wrong_password")
    def a1():
        sign_in(page, alice_email, "wrong-password-1")
        page.wait_for_function("() => document.getElementById('si-error').textContent.trim().length>0", timeout=15000)
        assert page.locator("#auth-overlay").is_visible()
        report("A1_login_form_rejects_wrong_password", True, page.inner_text("#si-error"))
    a1()

    @step("A2_login_succeeds_and_shell_is_usable")
    def a2():
        page.fill("#si-password", PW)
        page.click("#si-btn")
        page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        assert token_of(page)
        assert "Alice" in page.inner_text("#sidebar-account-label") or alice_email in page.inner_text("#sidebar-account-label")
        shot(page, "A2_logged_in_light")
        report("A2_login_succeeds_and_shell_is_usable", True, page.inner_text("#sidebar-account-label"))
    a2()

    @step("B1_new_conversation_streams_real_answer")
    def b1():
        seen = []
        choose_model(page)
        page.fill("#msg-input", "Write about 90 words describing the sea.")
        page.click("#send-btn")
        page.wait_for_selector(".answer .msg-body", timeout=120000)
        end = time.time() + 120
        while time.time() < end:
            t = page.locator(".answer .msg-body").last.inner_text()
            if not seen or seen[-1] != len(t):
                seen.append(len(t))
            if t.strip() and not page.locator(".thinking").count() and len(seen) > 1 and time.time() - last_change(seen) > 1.5:
                break
            time.sleep(0.04)
        final = page.locator(".answer .msg-body").last.inner_text()
        assert final.strip(), "no answer text rendered"
        assert len([s for s in seen if s > 0]) >= 2, f"answer appeared in one piece: {seen}"
        state["answer1"] = final
        shot(page, "B1_streamed_answer_light")
        report("B1_new_conversation_streams_real_answer", True, f"distinct lengths seen while streaming: {seen[:12]}")

    _lc = {"t": time.time(), "n": None}

    def last_change(seen):
        if _lc["n"] != seen[-1]:
            _lc["n"], _lc["t"] = seen[-1], time.time()
        return _lc["t"]
    b1()

    @step("C0_sidebar_lists_the_conversation_without_a_reload")
    def c0():
        try:
            page.wait_for_selector("#recents-list .rec-row", timeout=8000)
        except PWTimeout:
            shot(page, "C0_sidebar_stale")
            raise AssertionError("sidebar still says: %r after a completed turn (list is only refreshed at the 'session' event, before the turn is persisted)" % page.inner_text("#recents-list")[:60])
        report("C0_sidebar_lists_the_conversation_without_a_reload", True, "")
    c0()

    @step("C1_reload_restores_conversation")
    def c1():
        page.reload()
        page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        page.wait_for_selector("#recents-list .rec-row", timeout=20000)
        page.locator("#recents-list .rec-row").first.click()
        page.wait_for_selector(".msg-user .sample-q", timeout=15000)
        assert "sea" in page.locator(".msg-user .sample-q").first.inner_text()
        assert page.locator(".answer .msg-body").last.inner_text().strip(), "assistant answer missing after reload"
        shot(page, "C1_reloaded_conversation_light")
        report("C1_reload_restores_conversation", True, "sidebar row + full transcript restored after reload")
    c1()

    @step("E0_same_turn_edit_is_available_after_streaming")
    def e0():
        page.evaluate("() => { if (typeof newConversation === 'function') newConversation(); }")
        page.wait_for_selector("#empty-view", state="visible", timeout=10000)
        send(page, "My favourite fruit is pineapple.")
        page.locator(".msg-user .edit-msg-btn").first.click()
        try:
            page.wait_for_function("() => { const b=document.querySelector('.msg-user [data-action=save]'); return b && !b.disabled; }", timeout=6000)
        except PWTimeout:
            shot(page, "E0_same_turn_edit_disabled")
            raise AssertionError("Save edit stays disabled right after a streamed turn: the done event carries user_message_id but the page never binds it")
        report("E0_same_turn_edit_is_available_after_streaming", True, "")
    e0()

    @step("E1_inline_edit_saves_through_the_ui")
    def e1():
        # the path that works today: reopen the conversation from the sidebar (ids come from GET .../messages)
        page.wait_for_selector("#recents-list .rec-row", timeout=20000)
        page.reload()
        page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        page.wait_for_selector("#recents-list .rec-row", timeout=20000)
        page.locator("#recents-list .rec-row").first.click()
        page.wait_for_selector(".msg-user .sample-q", timeout=15000)
        assert "pineapple" in page.locator(".msg-user .sample-q").first.inner_text()
        page.locator(".msg-user .edit-msg-btn").first.click()
        page.locator(".msg-user .edit-msg-textarea").first.fill("My favourite fruit is mango.")
        page.wait_for_function("() => { const b=document.querySelector('.msg-user [data-action=save]'); return b && !b.disabled; }", timeout=20000)
        page.locator(".msg-user [data-action=save]").first.click()
        page.wait_for_selector(".msg-user .edited-badge", timeout=20000)
        shot(page, "E1_edited_light")
        report("E1_inline_edit_saves_through_the_ui", True, "Edited badge visible after reopen + save")
    e1()

    @step("E2_follow_up_after_edit_sent_from_ui")
    def e2():
        reply = send(page, "Which fruit did I say is my favourite? Answer with one word.")
        state["e2_reply"] = reply
        report("E2_follow_up_after_edit_sent_from_ui", True, f"MARKER_E2 reply={reply[:80]!r}")
    e2()

    @step("F1_temporary_chat_via_ui")
    def f1():
        page.evaluate("() => { if (typeof newConversation === 'function') newConversation(); }")
        page.click("#temp-mode-btn")
        page.wait_for_selector("#temp-mode-start", state="visible", timeout=10000)
        page.click("#temp-mode-start")
        page.wait_for_function("() => document.getElementById('temp-mode-active') && !document.getElementById('temp-mode-active').hidden || document.getElementById('relay-badge')", timeout=15000)
        rows_before = page.locator("#recents-list .rec-row").count()
        send(page, "Temp secret: quokka-5521.")
        time.sleep(2.5)  # long enough for any (wrongly) triggered sidebar refresh to land
        assert page.locator("#recents-list .rec-row").count() == rows_before, "a temporary chat added a sidebar row"
        recents = page.inner_text("#recents-list")
        assert "quokka" not in recents.lower(), "temporary chat appears in history"
        shot(page, "F1_temporary_light")
        state["temp_sid"] = page.evaluate("() => sessionId")
        report("F1_temporary_chat_via_ui", True, "not listed in recents")
    f1()

    @step("F2_closing_a_temporary_chat_in_the_ui_deletes_the_transcript")
    def f2():
        sid = state["temp_sid"]
        assert sid, "no temporary session id"
        tok = token_of(page)
        page.click("#temp-mode-btn")
        page.wait_for_selector("#temp-mode-close-chat", state="visible", timeout=10000)
        page.click("#temp-mode-close-chat")
        time.sleep(2)
        got = api_from_page(page, "GET", f"/api/session/{sid}/messages", tok)
        assert "quokka" not in got["text"].lower(), f"transcript survived close: {got}"
        shot(page, "F2_temporary_closed_light")
        report("F2_closing_a_temporary_chat_in_the_ui_deletes_the_transcript", True, f"transcript GET -> {got['status']}")
    f2()

    @step("G1_logout_clears_ui_and_revokes_token")
    def g1():
        tok = token_of(page)
        assert tok
        other_session = api_login(alice_email)  # a second, independent session for the same account
        assert http_status("GET", "/api/auth/me", other_session) == 200
        page.click("#logout-row")
        page.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
        page.wait_for_function("() => document.getElementById('si-error').textContent.includes('signed out')", timeout=15000)
        assert page.inner_text("#si-error").strip() == "You have been signed out.", page.inner_text("#si-error")
        assert not token_of(page), "token still in localStorage after logout"
        body_text = page.inner_text("body")
        assert "pineapple" not in body_text.lower() and "quokka" not in body_text.lower(), "prior conversation content still in DOM after logout"
        # the old token is dead on the server: plain HTTP from outside the page AND from inside it
        for path, method in (("/api/auth/me", "GET"), ("/api/sessions", "GET")):
            assert http_status(method, path, tok) == 401, f"revoked token still valid for {path}"
        assert http_status("POST", "/api/stream", tok, {"message": "after logout", "session_id": None, "model_variant": "core"}) == 401, \
            "revoked token reached /api/stream"
        me = api_from_page(page, "GET", "/api/auth/me", tok)
        assert me["status"] == 401, f"revoked token still valid: {me['status']}"
        # logout ends THIS session only
        assert http_status("GET", "/api/auth/me", other_session) == 200, "logout revoked a different session"
        page.reload()
        page.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
        shot(page, "G1_logged_out_light")
        report("G1_logout_clears_ui_and_revokes_token", True, "confirmed message shown; old token 401 on me/sessions/stream (HTTP + in-page); other session still 200")
    g1()

    @step("G2_logout_with_server_unreachable_is_reported_honestly")
    def g2():
        c = browser.new_context(viewport={"width": 1280, "height": 800})
        p2 = c.new_page()
        sign_in(p2, alice_email)
        p2.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        tok = token_of(p2)
        p2.route("**/api/auth/logout", lambda route: route.abort())
        p2.click("#logout-row")
        p2.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
        p2.wait_for_function("() => document.getElementById('si-error').textContent.includes('did not confirm')", timeout=20000)
        msg = p2.inner_text("#si-error")
        assert "may remain valid" in msg and "signed out everywhere" not in msg.lower()
        assert not token_of(p2), "token kept locally after a failed revocation"
        # the truth the message admits: the server never heard about it, so the token is still live
        still = http_status("GET", "/api/auth/me", tok)
        shot(p2, "G2_logout_unconfirmed_light")
        c.close()
        report("G2_logout_with_server_unreachable_is_reported_honestly", True, f"local state cleared; message admits non-confirmation; server still accepts token (HTTP {still}) as disclosed")
    g2()

    @step("D1_second_user_sees_none_of_the_first_users_conversations")
    def d1():
        ctx2 = browser.new_context(viewport={"width": 1280, "height": 800})
        p2 = ctx2.new_page()
        sign_in(p2, bob_email)
        p2.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        time.sleep(1.5)
        text = p2.inner_text("body").lower()
        assert "colours" not in text and "pineapple" not in text and "mango" not in text, "Alice's content visible to Bob"
        shot(p2, "D1_other_user_light")
        ctx2.close()
        report("D1_second_user_sees_none_of_the_first_users_conversations", True, "Bob's shell shows none of Alice's content")
    d1()

    @step("E4_two_tabs_edit_their_own_messages_by_authoritative_id")
    def e4():
        c = browser.new_context(viewport={"width": 1280, "height": 800})
        tab_a = c.new_page()
        sign_in(tab_a, alice_email)
        tab_a.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        send(tab_a, "alpha one")
        tab_a.locator(".msg-user .edit-msg-btn").first.click()
        tab_a.wait_for_function("() => { const b=document.querySelector('.msg-user [data-action=save]'); return b && !b.disabled; }", timeout=6000)
        sid = tab_a.evaluate("() => sessionId")
        # tab B: same browser profile (shared token), opens the SAME conversation from the sidebar
        tab_b = c.new_page()
        tab_b.goto(f"{BASE}/conversation")
        tab_b.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        tab_b.wait_for_selector("#recents-list .rec-row", timeout=20000)
        tab_b.locator(f'#recents-list .rec[data-sid="{sid}"]').first.click()  # rows are untitled: match on the session id
        tab_b.wait_for_selector(".msg-user .sample-q", timeout=15000)
        send(tab_b, "beta two")
        # each tab edits ITS OWN just-sent message, immediately, with the ids the server returned
        tab_b.locator(".msg-user .edit-msg-btn").last.click()
        tab_b.wait_for_function("() => { const bs=[...document.querySelectorAll('.msg-user [data-action=save]')]; return bs.length && !bs[bs.length-1].disabled; }", timeout=6000)
        tab_b.locator(".msg-user .edit-msg-textarea").last.fill("beta edited")
        tab_b.locator(".msg-user [data-action=save]").last.click()
        tab_b.wait_for_selector(".msg-user .edited-badge", timeout=20000)
        tab_a.locator(".msg-user .edit-msg-textarea").first.fill("alpha edited")
        tab_a.locator(".msg-user [data-action=save]").first.click()
        tab_a.wait_for_selector(".msg-user .edited-badge", timeout=20000)
        tok = token_of(tab_a)
        import urllib.request
        req = urllib.request.Request(f"{BASE}/api/session/{sid}/messages", headers={"Authorization": "Bearer " + tok})
        msgs = json.loads(urllib.request.urlopen(req, timeout=30).read())["messages"]
        users = [m["content"] for m in msgs if m["role"] == "user"]
        assert users == ["alpha edited", "beta edited"], f"edits landed on the wrong messages: {users}"
        shot(tab_a, "E4_tab_a_light")
        c.close()
        report("E4_two_tabs_edit_their_own_messages_by_authoritative_id", True, f"server transcript user lines: {users}")
    e4()

    @step("C2_each_new_conversation_appears_in_the_sidebar_without_reload")
    def c2():
        c = browser.new_context(viewport={"width": 1280, "height": 800})
        pg = c.new_page()
        sign_in(pg, alice_email)
        pg.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        pg.wait_for_selector("#recents-list .rec-row", timeout=20000)
        before = pg.locator("#recents-list .rec-row").count()
        send(pg, "Fresh topic: lighthouses.")
        pg.wait_for_function("n => document.querySelectorAll('#recents-list .rec-row').length === n + 1", arg=before, timeout=10000)
        shot(pg, "C2_new_row_light")
        c.close()
        report("C2_each_new_conversation_appears_in_the_sidebar_without_reload", True, f"rows {before} -> {before + 1}")
    c2()

    @step("T1_dark_theme_renders_logged_in_shell")
    def t1():
        sign_in(page, alice_email)
        page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        page.click(".themebtn")
        time.sleep(0.4)
        shot(page, "T1_dark")
        report("T1_dark_theme_renders_logged_in_shell", True, "")
    t1()

    if console_errors:
        report("PAGE_ERRORS", False, "; ".join(console_errors[:5]))
    browser.close()
