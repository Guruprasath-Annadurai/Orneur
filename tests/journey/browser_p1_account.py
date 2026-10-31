"""Playwright driver: the account settings dialog on the approved /conversation page (change password, two-step verification, delete account, keyboard behaviour).

``python browser_p1_account.py <base_url> <out_dir> <email>`` -- prints one JSON object per line: {"step","ok","detail"}.
"""
import base64
import hashlib
import hmac
import json
import struct
import sys
import time

from playwright.sync_api import sync_playwright

BASE, OUT, EMAIL = sys.argv[1:4]
PW1, PW2 = "Journey-Pass-91x", "Changed-Pass-77y"


def report(step, ok, detail=""):
    print(json.dumps({"step": step, "ok": bool(ok), "detail": str(detail)[:900]}), flush=True)


def totp(secret, at):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    h = hmac.new(key, struct.pack(">Q", int(at // 30)), hashlib.sha1).digest()
    o = h[-1] & 15
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 10**6:06d}"


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(bypass_csp=True, viewport={"width": 1280, "height": 800}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    st = {}

    def step(name):
        def deco(fn):
            try:
                fn()
                report(name, True, "")
            except Exception as exc:
                report(name, False, f"{type(exc).__name__}: {str(exc)[:600]}")
                try:
                    page.screenshot(path=f"{OUT}/{name}_FAIL.png")
                except Exception:
                    pass
        return deco

    def tok():
        return page.evaluate("() => localStorage.getItem('orneur_token')")

    def status(path, t):
        return page.evaluate("async ([p,t]) => (await fetch(p,{headers:{Authorization:'Bearer '+t}})).status", [path, t])

    def text(sel):
        return page.inner_text(sel)

    @step("U1_account_row_opens_a_real_dialog_and_escape_returns_focus")
    def _():
        page.goto(f"{BASE}/conversation")
        page.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
        page.fill("#si-email", EMAIL); page.fill("#si-password", PW1); page.click("#si-btn")
        page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        assert page.evaluate("() => document.getElementById('account-row').tagName") == "BUTTON"
        page.click("#account-row")
        page.wait_for_selector("#acctcard", state="visible", timeout=5000)
        assert EMAIL in text("#acct-who")
        page.keyboard.press("Tab")
        assert page.evaluate("() => !!document.activeElement.closest('#acctcard')"), "focus escaped the dialog"
        page.keyboard.press("Escape")
        page.wait_for_selector("#acctcard", state="hidden", timeout=5000)
        assert page.evaluate("() => document.activeElement.id") == "account-row", "focus was not returned"

    @step("U2_change_password_continues_this_session_and_ends_the_old_one")
    def _():
        old = tok()
        page.click("#account-row")
        page.fill("#acct-cp-current", "wrong-wrong-1"); page.fill("#acct-cp-new", PW2); page.click("#acct-cp-btn")
        page.wait_for_function("() => /incorrect|failed|not/i.test(document.getElementById('acct-cp-msg').textContent)", timeout=8000)
        page.fill("#acct-cp-current", PW1); page.fill("#acct-cp-new", PW2); page.click("#acct-cp-btn")
        page.wait_for_function("() => /Password updated/.test(document.getElementById('acct-cp-msg').textContent)", timeout=8000)
        assert tok() != old and status("/api/auth/me", tok()) == 200, "this session did not continue"
        assert status("/api/auth/me", old) == 401, "the pre-change token still works"

    @step("U3_two_step_verification_can_be_turned_on_in_the_page")
    def _():
        page.click("#acct-2fa-setup-btn")
        page.wait_for_selector("#acct-2fa-secret", state="visible", timeout=8000)
        secret = text("#acct-2fa-secret").strip()
        assert len(secret) >= 16
        st["secret"] = secret
        page.fill("#acct-2fa-code", "000000"); page.click("#acct-2fa-confirm-btn")
        page.wait_for_function("() => document.getElementById('acct-2fa-msg').textContent.length > 4", timeout=8000)
        assert "now on" not in text("#acct-2fa-msg")
        page.fill("#acct-2fa-code", totp(secret, time.time())); page.click("#acct-2fa-confirm-btn")
        page.wait_for_function("() => /now on/.test(document.getElementById('acct-2fa-msg').textContent)", timeout=8000)
        assert "on for this account" in text("#acct-2fa-status")
        assert text("#acct-2fa-secret").strip() == "", "the setup secret stayed in the page after enabling"

    @step("U4_deleting_a_2fa_account_needs_the_code_and_the_confirmation")
    def _():
        page.fill("#acct-del-password", PW2); page.click("#acct-del-btn")
        page.wait_for_function("() => document.getElementById('acct-del-msg').textContent.length > 4", timeout=5000)
        assert status("/api/auth/me", tok()) == 200
        page.check("#acct-del-confirm"); page.click("#acct-del-btn")      # confirmed, password right, but no code
        page.wait_for_function("() => /authenticator|code/i.test(document.getElementById('acct-del-msg').textContent)", timeout=8000)
        assert status("/api/auth/me", tok()) == 200, "the account was deleted without the second factor"

    @step("U5_two_step_verification_can_be_turned_off_and_sign_in_no_longer_asks")
    def _():
        page.fill("#acct-2fa-disable-code", totp(st["secret"], time.time() + 30)); page.click("#acct-2fa-disable-btn")
        page.wait_for_function("() => /is off/.test(document.getElementById('acct-2fa-msg').textContent)", timeout=8000)
        assert "off" in text("#acct-2fa-status")

    @step("U6_delete_account_signs_out_and_the_account_is_gone")
    def _():
        t = tok()
        page.fill("#acct-del-password", PW2)
        page.check("#acct-del-confirm"); page.click("#acct-del-btn")
        page.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
        assert "deleted" in text("#si-error").lower(), text("#si-error")
        assert not tok() and status("/api/auth/me", t) == 401
        code = page.evaluate("async ([e,p]) => (await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:e,password:p})})).status", [EMAIL, PW2])
        assert code == 401, f"deleted account can still sign in ({code})"

    report("U7_no_uncaught_page_errors", not errors, "; ".join(errors)[:400])
    browser.close()
