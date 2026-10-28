# ORNEUR — QUALIFICATION LANDMARK-01
## REAL-WORLD USER JOURNEY AND MODEL-TAP EVIDENCE

**Authority:** Antigravity — Independent Security, Reliability, Product Qualification and Adversarial Testing Authority  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 28 October 2026  
**Document Status:** EMPIRICAL JOURNEY EVIDENCE  

---

### 1. Browser User Journey Results (15 Playwright Chromium Steps)

Journeys were executed using headless Chromium driven by Playwright against a live test server on Ubuntu 24.04 WSL2 backed by real Ollama (`llama3.2:1b`) and real Redis (DB 13):

```
========================================================================================================
                                     BROWSER JOURNEY STEP EVIDENCE
========================================================================================================
STEP | NAME                                      | STATUS | EVIDENCE OBSERVATION
-----+-------------------------------------------+--------+---------------------------------------------
A1   | Login form rejects wrong password         | PASSED | 401 response; UI displays invalid creds
A2   | Login succeeds & shell usable             | PASSED | JWT stored in localStorage; chat drawer open
B1   | New conversation streams real answer      | PASSED*| Verified progressive rendering with delay tap
C0   | Sidebar lists conversation without reload | PASSED | Monotonic turn ID synced to sidebar DOM
C1   | Hard page reload restores conversation    | PASSED | Session turns retrieved and rendered
E0   | Same-turn edit available after streaming  | PASSED | Hover edit icon rendered on user message
E1   | Inline edit saves through UI              | PASSED | Edited prompt displayed in message thread
E2   | Follow-up after edit sent from UI         | PASSED | Model answers in context of edited prompt
F1   | Temporary chat via UI                     | PASSED | Ephemeral badge active; memory skipped
F2   | Closing temp chat deletes transcript      | PASSED | Unlinked from disk; API returns 404
G1   | Logout clears UI and revokes token        | PASSED*| Revocation verified via patch 5bbd869
D1   | Second user sees none of first user chats | PASSED | Strict 403 Forbidden on foreign session ID
T1   | Dark theme renders logged-in shell        | PASSED | CSS custom properties apply cleanly
E3   | Model prompt contains edited canary context| PASSED| Outbound OllamaTap confirms edited prompt
ERR  | Zero uncaught browser JavaScript errors   | PASSED | Zero console errors captured by Playwright
========================================================================================================
*Note: B1 and G1 require controlled provider streaming and commit 5bbd869 respectively for automated passes.
```

---

### 2. Outbound Model Payload Evidence (OllamaTap Interception)

To prove that multi-turn history and edited turns genuinely reach the model rather than relying on model recollection, OllamaTap recorded the raw HTTP POST request sent to `http://127.0.0.1:11434/api/generate`:

```json
{
  "model": "llama3.2:1b",
  "prompt": "<|start_header_id|>system<|end_header_id|>\n\nYou are a helpful AI assistant.<|eot_id|><|start_header_id|>user<|end_header_id|>\n\nCANARY_ALPHA_TURN_1: Remember that my code is X99.<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\nUnderstood. I will remember that your code is X99.<|eot_id|><|start_header_id|>user<|end_header_id|>\n\nCANARY_BETA_EDITED_TURN_2: What was the code I just gave you?<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n",
  "stream": true,
  "options": {
    "temperature": 0.2
  }
}
```

**Empirical Verification:**
1. The raw JSON payload transmitted to Ollama explicitly contains `CANARY_ALPHA_TURN_1` from Turn 1.
2. The user's second message contains the edited canary string `CANARY_BETA_EDITED_TURN_2`.
3. The colon-delimited model identifier `"llama3.2:1b"` was preserved without truncation.
