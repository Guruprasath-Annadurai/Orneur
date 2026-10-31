"""Playwright driver: hostile assistant/user content must never execute on the approved /conversation page (evidence class: BROWSER + FIXTURE provider).

``python browser_p1_xss.py <base_url> <out_dir> <email>`` -- prints one JSON object per line: {"step","ok","detail"}.
The fixture provider answers with attack payloads; the page must render them inert, both live (streaming) and when the conversation is reopened.
"""
import json
import sys
import time

from playwright.sync_api import sync_playwright

BASE, OUT, EMAIL = sys.argv[1:4]
PW = "Journey-Pass-91x"


def report(step, ok, detail=""):
    print(json.dumps({"step": step, "ok": bool(ok), "detail": str(detail)[:900]}), flush=True)


# every payload tries to set window.__pwned (script/handler execution) or open a dialog
SCAN = """() => {
  const root = document.getElementById('reading-container');
  const bad = [];
  for (const el of root.querySelectorAll('*')) {
    const tag = el.tagName.toLowerCase();
    if (['script', 'iframe', 'object', 'embed', 'style', 'link', 'form', 'img', 'video', 'audio', 'meta', 'base'].includes(tag) && !el.closest('.cite-marker')) bad.push('tag:' + tag);
    if (tag === 'svg' && !el.closest('button, .tiny-brand, .copy-btn, [class*="icon"]') && el.parentElement && el.parentElement.closest('.msg-body')) bad.push('tag:svg-in-body');
    for (const a of el.attributes) {
      if (/^on/i.test(a.name)) bad.push('attr:' + a.name);
      if (['href', 'src', 'action', 'formaction', 'srcdoc', 'xlink:href'].includes(a.name.toLowerCase()) && /^\\s*(javascript|data|vbscript)\\s*:/i.test(a.value.replace(/[\\t\\n\\r]/g, ''))) bad.push('url:' + a.name);
    }
  }
  return {bad, pwned: window.__pwned || null};
}"""


def type_and_send(p, text):
    time.sleep(0.6)
    if "Choose model" in p.inner_text("#model-label"):
        p.click("#model-btn")
        p.wait_for_selector("#model-panel.open", timeout=10000)
        p.locator("#model-panel .modelopt:not(.unavailable)").first.click()
    p.fill("#msg-input", text)
    p.click("#send-btn")


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(bypass_csp=True, viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    dialogs, errors = [], []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto(f"{BASE}/conversation")
        page.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
        page.fill("#si-email", EMAIL)
        page.fill("#si-password", PW)
        page.click("#si-btn")
        page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
        hostile_user_text = '<img src=x onerror="window.__pwned=\'user\'"> <script>window.__pwned="u2"</script>'
        type_and_send(page, hostile_user_text)
        page.wait_for_selector(".answer .msg-body", timeout=30000)
        page.wait_for_function("() => document.getElementById('send-btn') && !document.getElementById('send-btn').classList.contains('stop-mode')", timeout=30000)
        time.sleep(1.0)
        sid = page.evaluate("() => sessionId")
        live = page.evaluate(SCAN)
        report("X1_live_render_is_inert", not live["bad"] and not live["pwned"] and not dialogs, json.dumps({"scan": live, "dialogs": dialogs}))
        n_links = page.locator(".answer .msg-body a").count()
        hrefs = page.evaluate("() => [...document.querySelectorAll('.answer .msg-body a')].map(a => a.getAttribute('href'))")
        report("X2_unsafe_link_schemes_are_removed_and_safe_links_kept",
               not any((h or "").lower().replace("\t", "").lstrip().startswith(("javascript", "data", "vbscript")) for h in hrefs) and any((h or "").startswith("https://") for h in hrefs),
               json.dumps(hrefs))
        report("X3_user_message_text_is_shown_as_text", page.locator(".msg-user .sample-q").first.inner_text().startswith("<img"), "")
        # reopen the stored conversation through the history path
        page.reload()
        page.wait_for_selector("#recents-list .rec-row", timeout=20000)
        page.locator(f'#recents-list .rec[data-sid="{sid}"]').first.click()
        page.wait_for_selector(".msg-user .sample-q", timeout=15000)
        time.sleep(1.0)
        again = page.evaluate(SCAN)
        report("X4_reopened_history_is_inert", not again["bad"] and not again["pwned"] and not dialogs, json.dumps({"scan": again, "dialogs": dialogs}))
        injected = page.evaluate("() => document.querySelectorAll('#recents-list img, #recents-list script, #recents-list svg[onload], #recents-list [onerror]').length")
        report("X5_sidebar_title_is_escaped", injected == 0 and not page.evaluate("() => window.__pwned || null"), f"injected elements: {injected}")
        report("X6_no_uncaught_page_errors", not errors, "; ".join(errors)[:400])
    except Exception as exc:
        report("X0_driver", False, f"{type(exc).__name__}: {str(exc)[:600]}")
        try:
            page.screenshot(path=f"{OUT}/xss_FAIL.png")
        except Exception:
            pass
    browser.close()
