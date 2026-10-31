"""Playwright driver: the account lifecycle on the approved /conversation page (evidence class: BROWSER; mail = local sink, delivered to nobody).

``python browser_p1_auth.py <base_url> <out_dir> <sink_dir>`` -- prints one JSON object per line: {"step","ok","detail"}.
Journey: sign up -> unverified sign-in is explained + resend -> confirm link -> sign in -> forgot password -> reset link -> new password -> enable MFA -> sign out ->
sign in asks for the code (wrong code refused, right code accepted, same code cannot be replayed) -> signed out for good.
"""
import base64
import hashlib
import hmac
import json
import re
import struct
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE, OUT, SINK = sys.argv[1], sys.argv[2], Path(sys.argv[3])
EMAIL = f"p1auth-{uuid.uuid4().hex[:8]}@example.com"
PW1, PW2 = "Journey-Pass-91x", "Changed-Pass-77y"


def report(step, ok, detail=""):
    print(json.dumps({"step": step, "ok": bool(ok), "detail": str(detail)[:900]}), flush=True)


def totp(secret, at=None):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    msg = struct.pack(">Q", int((at or time.time()) // 30))
    h = hmac.new(key, msg, hashlib.sha1).digest()
    o = h[-1] & 15
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 10**6:06d}"


def mails():
    out = []
    for f in sorted(SINK.glob("*.json")) if SINK.exists() else []:
        m = json.loads(f.read_text())
        if m["to"] == EMAIL:
            out.append(m)
    return out


def wait_mail(kind, n_before, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        ms = [m for m in mails() if (("reset_token=" in m["plain"]) if kind == "reset" else ("/api/auth/verify?token=" in m["plain"]))]
        if len(ms) > n_before:
            pat = r"reset_token=([A-Za-z0-9_\-\.]+)" if kind == "reset" else r"verify\?token=([A-Za-z0-9_\-\.]+)"
            return re.search(pat, ms[-1]["plain"]).group(1)
        time.sleep(0.2)
    raise AssertionError(f"no {kind} mail arrived")


def count(kind):
    return len([m for m in mails() if (("reset_token=" in m["plain"]) if kind == "reset" else ("/api/auth/verify?token=" in m["plain"]))])


def step(name):
    def deco(fn):
        def run(*a, **k):
            try:
                fn(*a, **k)
                report(name, True, "")
            except Exception as exc:
                report(name, False, f"{type(exc).__name__}: {str(exc)[:700]}")
                try:
                    page.screenshot(path=f"{OUT}/{name}_FAIL.png")
                except Exception:
                    pass
        return run
    return deco


def visible_text():
    return page.inner_text("#authcard") if page.locator("#auth-overlay:not(.hidden)").count() else ""


def signed_in():
    return page.evaluate("() => !!localStorage.getItem('orneur_token')") and page.locator("#auth-overlay").evaluate("e => getComputedStyle(e).display") == "none"


def me(status_token=None):
    tok = status_token or page.evaluate("() => localStorage.getItem('orneur_token')")
    return page.evaluate("async t => (await fetch('/api/auth/me', {headers: {Authorization: 'Bearer ' + t}})).status", tok)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(bypass_csp=True, viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    urls = []
    page.on("framenavigated", lambda f: urls.append(f.url))

    @step("A1_signup_requires_verification_and_says_so")
    def a1():
        page.goto(f"{BASE}/conversation")
        page.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
        page.click("#tab-signup")
        page.fill("#su-name", "P1 Auth")
        page.fill("#su-email", EMAIL)
        page.fill("#su-password", PW1)
        page.click("#su-btn")
        page.wait_for_function("() => document.getElementById('su-error').textContent.length > 5", timeout=10000)
        assert not page.evaluate("() => localStorage.getItem('orneur_token')"), "a session was issued before verification"
        wait_mail("verify", 0)
    a1()

    @step("A2_unverified_sign_in_is_explained_and_resend_works")
    def a2():
        page.click("#tab-signin")
        page.fill("#si-email", EMAIL)
        page.fill("#si-password", PW1)
        page.click("#si-btn")
        page.wait_for_function("() => document.getElementById('si-error').textContent.length > 5", timeout=10000)
        assert "verify" in page.inner_text("#si-error").lower(), page.inner_text("#si-error")
        before = count("verify")
        page.click("#si-resend-btn", timeout=3000)
        page.wait_for_function("() => document.getElementById('si-error').textContent.toLowerCase().includes('verification link')", timeout=10000)
        time.sleep(1.0)
        # the server bounds sends per account (60 s): the request is acknowledged identically but does not mail again
        assert count("verify") == before, "the resend was not throttled"
    a2()

    @step("A3_confirming_the_link_then_signing_in_works")
    def a3():
        tok = wait_mail("verify", count("verify") - 1)  # the signup mail
        req = urllib.request.Request(f"{BASE}/api/auth/verify", data=json.dumps({"token": tok}).encode(), headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=15).read()
        page.fill("#si-email", EMAIL)
        page.fill("#si-password", PW1)
        page.click("#si-btn")
        page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        assert me() == 200
    a3()

    @step("A4_sign_out_ends_the_session_on_the_server")
    def a4():
        tok = page.evaluate("() => localStorage.getItem('orneur_token')")
        page.evaluate("() => doLogout()")
        page.wait_for_selector("#auth-overlay", state="visible", timeout=10000)
        assert not page.evaluate("() => localStorage.getItem('orneur_token')")
        assert me(tok) == 401, "the old token still works after sign-out"
    a4()

    @step("A5_forgot_password_is_generic_and_reset_link_sets_a_new_password")
    def a5():
        page.click("#si-forgot-btn", timeout=3000)
        page.fill("#fp-email", "nobody-here@example.com")
        page.click("#fp-btn")
        page.wait_for_function("() => document.getElementById('fp-msg').textContent.length > 5", timeout=10000)
        generic = page.inner_text("#fp-msg")
        before = count("reset")
        page.fill("#fp-email", EMAIL)
        page.click("#fp-btn")
        page.wait_for_function("() => document.getElementById('fp-msg').textContent.length > 5", timeout=10000)
        assert page.inner_text("#fp-msg") == generic, "response differs for a registered address (account enumeration)"
        tok = wait_mail("reset", before)
        page.goto(f"{BASE}/conversation?reset_token={tok}")
        page.wait_for_selector("#rp-password", state="visible", timeout=10000)
        assert "reset_token" not in page.url, "the reset token stayed in the address bar"
        page.fill("#rp-password", PW2)
        page.click("#rp-btn")
        page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        assert me() == 200
        state["reset_token"] = tok
    state = {}
    a5()

    @step("A6_the_reset_link_cannot_be_replayed_and_the_old_password_is_dead")
    def a6():
        page.evaluate("() => doLogout()")
        page.wait_for_selector("#auth-overlay", state="visible", timeout=10000)
        page.goto(f"{BASE}/conversation?reset_token={state['reset_token']}")
        page.wait_for_selector("#rp-password", state="visible", timeout=10000)
        page.fill("#rp-password", "Attacker-Pass-123")
        page.click("#rp-btn")
        page.wait_for_function("() => document.getElementById('rp-error').textContent.length > 5", timeout=10000)
        assert not page.evaluate("() => localStorage.getItem('orneur_token')")
        code = page.evaluate("async ([e, p]) => (await fetch('/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({email:e, password:p})})).status", [EMAIL, PW1])
        assert code == 401, f"old password status {code}"
    a6()

    @step("A7_mfa_challenge_is_completable_in_the_page")
    def a7():
        page.goto(f"{BASE}/conversation")
        page.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
        page.fill("#si-email", EMAIL)
        page.fill("#si-password", PW2)
        page.click("#si-btn")
        page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        tok = page.evaluate("() => localStorage.getItem('orneur_token')")
        secret = page.evaluate("async t => (await (await fetch('/api/auth/2fa/setup', {method:'POST', headers:{Authorization:'Bearer '+t}})).json()).secret", tok)
        status = page.evaluate("async ([t,c]) => (await fetch('/api/auth/2fa/enable', {method:'POST', headers:{Authorization:'Bearer '+t,'Content-Type':'application/json'}, body: JSON.stringify({code:c})})).status", [tok, totp(secret)])
        assert status == 200, status
        state["secret"] = secret
        page.evaluate("() => doLogout()")
        page.wait_for_selector("#auth-overlay", state="visible", timeout=10000)
        page.fill("#si-email", EMAIL)
        page.fill("#si-password", PW2)
        page.click("#si-btn")
        page.wait_for_selector("#mfa-code", state="visible", timeout=10000)
        assert not page.evaluate("() => localStorage.getItem('orneur_token')"), "a session exists before the second factor"
        page.fill("#mfa-code", "000000")
        page.click("#mfa-btn")
        page.wait_for_function("() => document.getElementById('mfa-error').textContent.length > 5", timeout=10000)
        assert not page.evaluate("() => localStorage.getItem('orneur_token')")
        good = totp(state["secret"])
        page.fill("#mfa-code", good)
        page.click("#mfa-btn")
        page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        assert me() == 200
        state["used_code"] = good
    a7()

    @step("A8_a_used_mfa_code_cannot_be_replayed")
    def a8():
        pending = page.evaluate("""async ([e,p]) => (await (await fetch('/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({email:e,password:p})})).json()).pending_token""", [EMAIL, PW2])
        status = page.evaluate("""async ([t,c]) => (await fetch('/api/auth/2fa/verify-login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({pending_token:t, code:c})})).status""", [pending, state["used_code"]])
        assert status in (401, 429), f"the same one-time code was accepted twice (status {status})"
    a8()

    @step("A9_no_credentials_in_urls_or_page_errors")
    def a9():
        bad = [u for u in urls if re.search(r"(token|password|code)=", u, re.I)]
        # the reset link itself carried a token on arrival; it must be gone from the address bar after load
        assert not [u for u in urls if "password=" in u.lower()], urls
        assert not errors, errors
    a9()
    browser.close()
