# ORNEUR — QUALIFICATION LANDMARK-01
## REAL-WORLD USER JOURNEY AND MODEL-TAP EVIDENCE (Corrected)

**Authority:** Antigravity — Independent Security, Reliability, Product Qualification and Adversarial Testing Authority  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 28 October 2026 (Corrected Revision)  
**Document Status:** EMPIRICAL JOURNEY EVIDENCE  

---

### 1. Chromium Browser Journey Provenance & Results

Journeys were executed using Playwright Chromium 1.49.1 (`headless_shell 1148` with `libnss3` dynamic library injection) against live serving servers on Ubuntu 24.04 WSL2:

- **Target Candidate Evaluated:** PR #129 Head (`0170e3b11d12157754195c4e6a3ca9d17e6c078d`)
- **Frontend Reference Integrated:** Claude tested commit `f7c004f1c297c93906099180a9dab00fc843fc01`
- **Journey Harness Reference:** Claude commit `adfd73bc4edabf57603e2f2902e59dbf5e45e4d9`
- **Real Infrastructure:** Ollama 0.6.5 (`llama3.2:1b`), Redis 7.2.4 (Docker DB 13)

```
========================================================================================================
                                     BROWSER JOURNEY STEP EVIDENCE
========================================================================================================
STEP | NAME                                      | STATUS | EVIDENCE OBSERVATION
-----+-------------------------------------------+--------+---------------------------------------------
A1   | Login form rejects wrong password         | PASSED | 401 response; UI displays invalid creds
A2   | Login succeeds & shell usable             | PASSED | JWT stored in localStorage; chat drawer open
B1   | New conversation streams real answer      | NOTE*  | Fast loopback returns 3-chunk completion; progressive
     |                                           |        | rendering independently confirmed via delayed tap
C0   | Sidebar lists conversation without reload | PASSED | Monotonic turn ID synced to sidebar DOM
C1   | Hard page reload restores conversation    | PASSED | Session turns retrieved and rendered
E0   | Same-turn edit available after streaming  | PASSED | Hover edit icon rendered on user message
E1   | Inline edit saves through UI              | PASSED | Edited prompt displayed in message thread
E2   | Follow-up after edit sent from UI         | PASSED | Model answers in context of edited prompt
F1   | Temporary chat via UI                     | PASSED | Ephemeral badge active; memory skipped
F2   | Closing temp chat deletes transcript      | PASSED | Unlinked from disk; API returns 404
G1   | Logout clears UI and revokes token        | FAILED | Historical fail-open bug accepts revoked token
D1   | Second user sees none of first user chats | PASSED | Strict 403 Forbidden on foreign session ID
T1   | Dark theme renders logged-in shell        | PASSED | CSS custom properties apply cleanly
E3   | Model prompt contains edited canary context| PASSED| Outbound OllamaTap confirms edited prompt
ERR  | Zero uncaught browser JavaScript errors   | PASSED | Zero console errors captured by Playwright
========================================================================================================
*Note on B1 & G1: G1 failed on PR #129 because commit 0170e3b does not yet contain the 5bbd869 auth patch.
```

---

### 2. Outbound Model Payload Evidence (OllamaTap Interception)

Captured directly from `http://127.0.0.1:11434/api/generate` during Step E3 on PR #129:

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
1. The outbound payload contains prior turns (`CANARY_ALPHA_TURN_1`) and edited prompt (`CANARY_BETA_EDITED_TURN_2`).
2. Colon-delimited model ID `"llama3.2:1b"` was preserved without truncation.
