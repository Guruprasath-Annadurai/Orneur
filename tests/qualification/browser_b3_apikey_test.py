import json
import os
import sys
import time
from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
PW = sys.argv[2]
EMAIL = sys.argv[3]

print(f"[Browser Test] Connecting to {BASE}/app with {EMAIL}")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    
    console_msgs = []
    page.on("console", lambda msg: console_msgs.append(msg.text))
    
    # 1. Sign in on /app
    page.goto(f"{BASE}/app")
    page.wait_for_selector("#auth-overlay", state="visible", timeout=15000)
    page.fill("#si-email", EMAIL)
    page.fill("#si-password", PW)
    page.click("#si-btn")
    page.wait_for_selector("#auth-overlay", state="hidden", timeout=15000)
    print("[Browser Test] Signed in successfully")
    
    # 2. Open Settings -> API Keys
    page.evaluate("openSettings('apikeys')")
    page.wait_for_selector("#stab-panel-apikeys", state="visible", timeout=5000)
    
    # Verify input fields exist and attributes
    pw_type = page.get_attribute("#newkey-password", "type")
    assert pw_type == "password", f"Password input must be type password, got {pw_type}"
    
    totp_mode = page.get_attribute("#newkey-totp", "inputmode")
    assert totp_mode == "numeric", f"TOTP input must be numeric, got {totp_mode}"
    
    # 3. Attempt creation WITHOUT password -> verify alert
    page.fill("#newkey-name", "test-key-no-pw")
    page.click("#create-key-btn")
    page.wait_for_timeout(1000)
    assert len(dialogs) >= 1, "Expected alert dialog on missing password"
    assert "password" in dialogs[-1].lower(), f"Expected password refusal message, got: {dialogs[-1]}"
    print(f"[Browser Test] Missing password blocked with alert: {dialogs[-1]}")
    
    # 4. Attempt creation WITH wrong password -> verify alert
    page.fill("#newkey-password", "WrongPassword123!")
    page.click("#create-key-btn")
    page.wait_for_timeout(1000)
    assert len(dialogs) >= 2, "Expected alert dialog on wrong password"
    print(f"[Browser Test] Wrong password blocked with alert: {dialogs[-1]}")
    
    # 5. Attempt creation WITH correct password -> verify success and clearing
    page.fill("#newkey-name", "test-key-prod")
    page.fill("#newkey-password", PW)
    page.click("#create-key-btn")
    page.wait_for_selector("#new-key-box", state="visible", timeout=5000)
    
    key_val = page.input_value("#new-key-display")
    assert key_val.startswith("athr_"), f"Expected athr_ key prefix, got: {key_val}"
    
    # Check that credentials were completely cleared
    pw_val = page.input_value("#newkey-password")
    totp_val = page.input_value("#newkey-totp")
    name_val = page.input_value("#newkey-name")
    assert pw_val == "", f"Expected cleared password input, got {pw_val}"
    assert totp_val == "", f"Expected cleared totp input, got {totp_val}"
    assert name_val == "", f"Expected cleared name input, got {name_val}"
    print(f"[Browser Test] Key created successfully: {key_val[:10]}... Inputs cleanly cleared")
    
    # Verify console messages do not leak raw password or key
    for c in console_msgs:
        assert PW not in c, f"Password leaked to console log: {c}"
        assert key_val not in c, f"Raw key leaked to console log: {c}"
    print("[Browser Test] Console audit confirmed zero credential leakage")
    
    browser.close()
print("[Browser Test] SUCCESS")
