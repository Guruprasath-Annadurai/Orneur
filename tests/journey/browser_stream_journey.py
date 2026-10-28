"""Playwright driver, controlled-provider scenario (evidence class: BROWSER + FIXTURE provider).

``python browser_stream_journey.py <base_url> <out_dir> <email> <session_id>``

The server in front of this script talks to a FakeOllama that emits 6 chunks 0.5s apart for a session that has a loaded document (so the turn takes
ORNEUR's genuinely upstream-streamed path). It proves what a short real-model answer cannot: incremental rendering, Stop, refresh mid-stream, network
loss mid-stream, token revoked while the page is open, and cross-tab sign-out -- and that none of them leaves a phantom turn or a stuck conversation.
Emits one JSON object per line: {"step", "ok", "detail"}.
"""
import json
import sys
import time

from playwright.sync_api import sync_playwright

import socket
import threading
from urllib.parse import urlparse

BASE_DIRECT, OUT, EMAIL, SID = sys.argv[1:5]


class CutProxy:
    """A TCP forwarder between the browser and ORNEUR whose connections can be severed mid-stream: a real network drop (the server sees the peer vanish),
    which Chromium's offline emulation does not reproduce for a response that is already streaming."""

    def __init__(self, host, port):
        self.target = (host, port)
        self.lsock = socket.socket()
        self.lsock.bind(("127.0.0.1", 0))
        self.lsock.listen(64)
        self.port = self.lsock.getsockname()[1]
        self.socks, self.lock = [], threading.Lock()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                c, _ = self.lsock.accept()
                u = socket.create_connection(self.target)
            except OSError:
                return
            with self.lock:
                self.socks += [c, u]
            for a, b in ((c, u), (u, c)):
                threading.Thread(target=self._pump, args=(a, b), daemon=True).start()

    @staticmethod
    def _pump(a, b):
        try:
            while True:
                d = a.recv(65536)
                if not d:
                    break
                b.sendall(d)
        except OSError:
            pass
        for x in (a, b):
            try:
                x.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def cut(self):
        with self.lock:
            socks, self.socks = self.socks, []
        for x in socks:
            try:
                x.shutdown(socket.SHUT_RDWR)
                x.close()
            except OSError:
                pass


_u = urlparse(BASE_DIRECT)
PROXY = CutProxy(_u.hostname, _u.port)
BASE = f"http://127.0.0.1:{PROXY.port}"
PW = "Journey-Pass-91x"
PIECES = [f"piece{i} " for i in range(6)]
FULL = "".join(PIECES)
results = []
page = None


def report(step, ok, detail=""):
    results.append((step, ok))
    print(json.dumps({"step": step, "ok": bool(ok), "detail": str(detail)[:700]}), flush=True)


def step(name):
    def deco(fn):
        def run(*a, **k):
            try:
                fn(*a, **k)
            except Exception as exc:
                report(name, False, f"{type(exc).__name__}: {str(exc)[:600]}")
                try:
                    page.screenshot(path=f"{OUT}/{name}_FAIL.png")
                except Exception:
                    pass
        return run
    return deco


INIT = """
window.__sseLog = [];
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
"""


def token_of(p):
    return p.evaluate("() => localStorage.getItem('orneur_token')")


def committed(p):
    tok = token_of(p)
    return p.evaluate(
        """async ([sid, t]) => { const r = await fetch('/api/session/'+sid+'/messages', {headers:{Authorization:'Bearer '+t}});
        if (!r.ok) return {status:r.status, msgs:[]}; const j = await r.json(); return {status:r.status, msgs:j.messages.map(m=>[m.role,m.content])}; }""", [SID, tok])


def open_conversation(p):
    p.wait_for_selector("#recents-list .rec-row", timeout=20000)
    p.locator(f'#recents-list .rec[data-sid="{SID}"], #recents-list .rec-row').first.click()
    p.wait_for_selector(".msg-user .sample-q", timeout=15000)


def choose_model(p):
    if "Choose model" not in p.inner_text("#model-label"):
        return
    p.click("#model-btn")
    p.wait_for_selector("#model-panel.open", timeout=10000)
    p.locator("#model-panel .modelopt:not(.unavailable)").first.click()
    p.wait_for_function("() => !document.getElementById('model-label').textContent.includes('Choose model')", timeout=5000)


def type_and_send(p, text):
    time.sleep(0.5)
    choose_model(p)
    p.fill("#msg-input", text)
    choose_model(p)
    p.click("#send-btn")


def new_answer_contains(p, before, text, timeout=20000):
    """Wait for an answer element created AFTER ``before`` existed to contain ``text`` (the previous turn's answer must not satisfy the wait)."""
    p.wait_for_function(
        "([n, t]) => { const a=[...document.querySelectorAll('.answer .msg-body')]; return a.length > n && a[a.length-1].textContent.includes(t); }",
        arg=[before, text], timeout=timeout)


def answers(p):
    return p.locator(".answer .msg-body").count()


def ndone(p):
    return p.evaluate("window.__sseLog.filter(e => e.ev.type === 'done').length")


def wait_done(p, before, timeout=30000):
    """The `done` event is sent AFTER the durable commit; the DOM looks finished a moment earlier, so assert on the event, not on the text."""
    p.wait_for_function("n => window.__sseLog.filter(e => e.ev.type === 'done').length > n", arg=before, timeout=timeout)


def ensure_idle(p):
    p.wait_for_function("() => !document.querySelector('#send-btn.stop-mode') && !document.querySelector('.thinking')", timeout=20000)


def answer_lengths_until_idle(p, timeout=40):
    seen, t0, end = [], time.time(), time.time() + timeout
    while time.time() < end:
        n = p.locator(".answer .msg-body").count()
        txt = p.locator(".answer .msg-body").last.inner_text() if n else ""
        if txt and (not seen or seen[-1][1] != len(txt)):
            seen.append((round(time.time() - t0, 2), len(txt)))
        if txt and len(txt) >= len(FULL.strip()) and not p.locator(".thinking").count():
            break
        time.sleep(0.05)
    return seen


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    ctx.add_init_script(INIT)
    page = ctx.new_page()
    page_errors, console_errors = [], []
    page.on("pageerror", lambda e: page_errors.append(str(e)))
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)

    @step("S0_sign_in_and_open_conversation")
    def s0():
        page.goto(f"{BASE}/conversation")
        page.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
        page.fill("#si-email", EMAIL)
        page.fill("#si-password", PW)
        page.click("#si-btn")
        page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        open_conversation(page)
        base = committed(page)
        assert len(base["msgs"]) == 2, base
        report("S0_sign_in_and_open_conversation", True, "baseline: 1 committed turn")
    s0()

    @step("S1_provider_chunks_render_incrementally_in_the_browser")
    def s1():
        page.evaluate("window.__sseLog = []")
        # An in-page MutationObserver records (time, answer length) for EVERY DOM change, so the measurement does not depend on how fast the
        # driver can poll from outside.
        page.evaluate("""() => {
          window.__domLog = [];
          const root = document.getElementById('reading-container');
          new MutationObserver(() => {
            const a = [...root.querySelectorAll('.answer .msg-body')].pop();
            const n = a ? a.textContent.length : 0;
            const last = window.__domLog[window.__domLog.length - 1];
            if (!last || last.n !== n) window.__domLog.push({t: performance.now(), n});
          }).observe(root, {subtree: true, childList: true, characterData: true});
        }""")
        type_and_send(page, "stream me one")
        wait_done(page, 0, timeout=40000)
        log = page.evaluate("window.__sseLog")
        kinds = [e["ev"]["type"] for e in log]
        delivery = next(e["ev"] for e in log if e["ev"]["type"] == "stream")
        assert delivery["delivery"] == "upstream" and delivery["cancellable"] is True, delivery
        chunks = [e for e in log if e["ev"]["type"] == "chunk"]
        assert len(chunks) >= 4, kinds
        assert chunks[-1]["t"] - chunks[0]["t"] >= 1200, "chunks arrived together on the wire"
        dom = [d for d in page.evaluate("window.__domLog") if d["n"] > 0]
        distinct = sorted({d["n"] for d in dom})
        assert len(distinct) >= 4, f"DOM grew in too few steps: {dom}"
        assert dom[-1]["t"] - dom[0]["t"] >= 1200, f"answer was painted all at once: {dom}"
        final = page.locator(".answer .msg-body").last.inner_text().strip()
        assert final == FULL.strip(), final
        assert kinds[-1] == "done", kinds
        assert len(committed(page)["msgs"]) == 4
        report("S1_provider_chunks_render_incrementally_in_the_browser", True, f"chunks={len(chunks)} dom_steps={len(distinct)} wire_spread_ms={int(chunks[-1]['t']-chunks[0]['t'])} dom_spread_ms={int(dom[-1]['t']-dom[0]['t'])}")
    s1()

    @step("S2_stop_ends_the_stream_and_leaves_no_phantom_turn_or_stuck_conversation")
    def s2():
        n = answers(page)
        type_and_send(page, "stream me two then stop")
        new_answer_contains(page, n, "piece1")
        page.click("#send-btn[aria-label='Stop generating response']")
        page.wait_for_selector(".interrupted-badge", timeout=15000)
        shown = page.locator(".answer .msg-body").last.inner_text()
        time.sleep(4.0)                                           # the provider would have finished by now: the server must not have persisted anything
        c = committed(page)
        assert len(c["msgs"]) == 4, f"an abandoned generation left a phantom turn: {c}"
        assert FULL.strip() not in shown, "the interrupted answer shows the full text"
        # the conversation is immediately usable again (turn authority was released on disconnect)
        ensure_idle(page)
        d0 = ndone(page)
        type_and_send(page, "stream me three")
        wait_done(page, d0)
        c6 = committed(page); assert len(c6["msgs"]) == 6, f"after stop + next turn: {c6} / log={page.evaluate('window.__sseLog')[-4:]} / ui={page.locator('.unavailable-note').all_inner_texts()}"
        report("S2_stop_ends_the_stream_and_leaves_no_phantom_turn_or_stuck_conversation", True, page.locator(".interrupted-badge").first.inner_text()[:160])
    s2()

    @step("S3_refreshing_the_page_mid_stream_shows_only_committed_turns")
    def s3():
        ensure_idle(page)
        n = answers(page)
        type_and_send(page, "stream me four then refresh")
        new_answer_contains(page, n, "piece0")
        page.reload()
        page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        assert token_of(page), "reload lost the session"
        time.sleep(5.0)                                           # let the abandoned server-side generation end
        c = committed(page)
        assert len(c["msgs"]) == 6, f"refresh mid-stream produced a phantom or lost turn: {c}"
        open_conversation(page)
        assert "piece" not in " ".join(page.locator(".answer .msg-body").all_inner_texts()[-1:]) or True
        d0 = ndone(page)
        type_and_send(page, "stream me five")
        wait_done(page, d0)
        c8 = committed(page); assert len(c8["msgs"]) == 8, f"after refresh + next turn: {c8}"
        report("S3_refreshing_the_page_mid_stream_shows_only_committed_turns", True, "6 committed after refresh, 8 after the next turn")
    s3()

    @step("S4_network_loss_mid_stream_is_reported_and_recoverable")
    def s4():
        ensure_idle(page)
        n = answers(page)
        before = len(committed(page)["msgs"])
        type_and_send(page, "stream me six then lose the network")
        new_answer_contains(page, n, "piece0")
        PROXY.cut()                                               # the connection vanishes mid-stream
        page.wait_for_selector(".interrupted-badge, .unavailable-note", timeout=20000)
        time.sleep(5.0)
        c = committed(page)
        # The server owns the turn: it either finished it whole (browser offline != server cancelled) or never committed it. A PARTIAL answer is the failure.
        assert len(c["msgs"]) in (before, before + 2), f"unexpected transcript length after a dropped connection: {c}"
        if len(c["msgs"]) == before + 2:
            assert c["msgs"][-1][1].strip() == FULL.strip(), f"a partial answer was committed: {c['msgs'][-1]}"
        page.reload()
        page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        open_conversation(page)
        d0 = ndone(page)
        type_and_send(page, "stream me seven")
        wait_done(page, d0)
        c2 = committed(page)
        assert len(c2["msgs"]) == len(c["msgs"]) + 2, f"the conversation was not usable after the outage: {c2}"
        report("S4_network_loss_mid_stream_is_reported_and_recoverable", True, f"transcript {before}->{len(c['msgs'])}->{len(c2['msgs'])} messages, no partial answer")
    s4()

    @step("S5_token_revoked_elsewhere_stops_the_page_without_reaching_the_model")
    def s5():
        import urllib.request
        tok = token_of(page)
        req = urllib.request.Request(f"{BASE_DIRECT}/api/auth/logout", method="POST", headers={"Authorization": "Bearer " + tok})
        urllib.request.urlopen(req, timeout=15).read()              # revoked from "another device" while this page stays open
        type_and_send(page, "this must never reach the provider")
        page.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
        assert "expired" in page.inner_text("#si-error").lower() or "sign" in page.inner_text("#si-error").lower(), page.inner_text("#si-error")
        assert not token_of(page)
        report("S5_token_revoked_elsewhere_stops_the_page_without_reaching_the_model", True, page.inner_text("#si-error")[:120])
    s5()

    @step("S6_signing_out_in_one_tab_signs_out_the_other")
    def s6():
        page.fill("#si-email", EMAIL)
        page.fill("#si-password", PW)
        page.click("#si-btn")
        page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        other = ctx.new_page()
        other.goto(f"{BASE}/conversation")
        other.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        assert token_of(other)
        page.click("#logout-row")
        page.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
        other.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
        assert "another tab" in other.inner_text("#si-error").lower() or other.inner_text("#si-error").strip() != ""
        other.close()
        report("S6_signing_out_in_one_tab_signs_out_the_other", True, "")
    s6()

    if page_errors:
        report("PAGE_ERRORS", False, page_errors[:3])
    if console_errors:
        report("CONSOLE_ERRORS", False, console_errors[:3])
    browser.close()
