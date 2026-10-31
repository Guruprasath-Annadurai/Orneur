"""Captures real screenshots of the served approved page (fixture provider for the reply text). Usage: python p1_screenshots.py <outdir>"""
import os, subprocess, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, ".")
from tests.fake_ollama import FakeOllama
from tests.journey.harness import JOURNEY_MODEL, LiveServer, User
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
fake = FakeOllama(models=(JOURNEY_MODEL,), reply="Here is a short, calm answer.\n\n- First point\n- Second point\n\n`inline code` and a [link](https://example.com).")
fake.__enter__()
srv = LiveServer(Path(tempfile.mkdtemp(prefix="p1shot-")), extra_env={"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host}); srv.wait_ready()
User(srv.base, "burn"); u = User(srv.base, "shots")
code = f'''
import time
from playwright.sync_api import sync_playwright
B="{srv.base}"; O="{OUT}"
def login(p):
    p.goto(B+"/conversation"); p.wait_for_selector("#auth-overlay",state="visible")
    p.fill("#si-email","{u.email}"); p.fill("#si-password","Journey-Pass-91x"); p.click("#si-btn"); p.wait_for_selector("#auth-overlay",state="hidden")
def send(p):
    time.sleep(.6)
    if "Choose model" in p.inner_text("#model-label"):
        p.click("#model-btn"); p.wait_for_selector("#model-panel.open"); p.locator("#model-panel .modelopt:not(.unavailable)").first.click()
    p.fill("#msg-input","Give me a short answer with a list."); p.click("#send-btn"); p.wait_for_selector(".answer .msg-body"); time.sleep(1.2)
with sync_playwright() as pw:
    b=pw.chromium.launch()
    c=b.new_context(viewport={{"width":1280,"height":800}}); p=c.new_page(); p.goto(B+"/conversation"); p.wait_for_selector("#auth-overlay",state="visible")
    p.screenshot(path=O+"/01_desktop_signin.png")
    p.click("#si-forgot-btn"); p.screenshot(path=O+"/02_desktop_forgot_password.png"); p.click("text=Back to sign in")
    login(p); p.screenshot(path=O+"/03_desktop_empty_conversation.png")
    send(p); p.screenshot(path=O+"/04_desktop_answer_dark.png")
    p.evaluate("()=>applyTheme(false)"); time.sleep(.3); p.screenshot(path=O+"/05_desktop_answer_light.png")
    p.click("#account-row"); p.wait_for_selector("#acctcard",state="visible"); p.screenshot(path=O+"/06_desktop_account_dialog.png")
    m=b.new_context(viewport={{"width":390,"height":844}},device_scale_factor=2,has_touch=True,is_mobile=True); q=m.new_page(); login(q); send(q)
    q.screenshot(path=O+"/07_mobile_answer.png"); q.tap("#mobilemenu-btn"); time.sleep(.5); q.screenshot(path=O+"/08_mobile_navigation_drawer.png")
    t=b.new_context(viewport={{"width":820,"height":1180}},has_touch=True); r=t.new_page(); login(r); r.wait_for_selector("#recents-list .rec-row"); r.screenshot(path=O+"/09_tablet_conversation_list.png")
    b.close()
'''
tools = Path(os.environ.get("ORNEUR_JOURNEY_TOOLS", "/home/pc/projects/.journey-tools"))
r = subprocess.run([str(tools / ".venv/bin/python"), "-c", code], capture_output=True, text=True, env=dict(os.environ, LD_LIBRARY_PATH=f"{tools}/libs/usr/lib/x86_64-linux-gnu:{os.environ.get('LD_LIBRARY_PATH','')}"), timeout=300)
print(r.stdout[-300:], r.stderr[-800:])
srv.stop(); fake.__exit__(None, None, None)
