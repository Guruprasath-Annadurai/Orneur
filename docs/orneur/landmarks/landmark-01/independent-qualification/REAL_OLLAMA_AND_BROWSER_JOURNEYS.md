# ORNEUR LANDMARK-01 — REAL SYSTEM & BROWSER QUALIFICATION
## Real-Ollama Model Inference, Redis Integration, and Playwright Chromium Acceptance

**Qualification Authority:** Antigravity  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 29 October 2026  
**Candidate Under Test:** Claude PR #134 (`8d72baab4ebe4ce3a6aa4a76385e18e1c1fba788`)  
**Test Environment:** Ubuntu 24.04 WSL2  
**Service Versions:** Ollama 0.4.x (`llama3.2:1b`), Redis 7-alpine (Docker port 6379), Chromium 130.0.6723.58  
**Evidence Class:** `VERIFIED_REAL`  
**Verdict:** **`PASS — 57 OF 57 LIVE JOURNEYS PASSING`**  

---

### 1. Executive Summary

Antigravity independently executed the full suite of live API, browser, and concurrency journeys against PR #134 using **real Ollama running the literal `llama3.2:1b` model**, real Redis, and real Playwright headless Chromium driving the production `/conversation` frontend.

**Key Findings:**
1. Real multi-turn conversations operate cleanly in the browser.
2. The outbound payload sent to Ollama carries accurate prior context and excludes superseded turn tails after inline editing.
3. The served model tag is the literal `llama3.2:1b` model tag; internal deployment identifiers are properly isolated and do not claim native GENESIS/NOVUS/AETERNUM training weights.
4. All 57 live journeys passed without a single failure or skipped step.

---

### 2. Comprehensive 20-Step Real-User Browser Qualification

The following 20 user journey steps were verified end-to-end:

| Step # | Test Step Description | Real System Execution & Verification | Observed Result | Verdict |
| :---: | :--- | :--- | :--- | :---: |
| **1** | Registration & Login | User registers and logs in via UI form. Invalid password rejected with error alert. | Valid token issued and stored in browser session. | **PASS** |
| **2** | Start New Conversation | User clicks "New Chat". Conversation shell initializes; sidebar updates without reload. | Unique `session_id` generated. | **PASS** |
| **3** | Send Prompt to Real Ollama | User sends: *"What is my lucky number? Remember it is 7."* | Request dispatched to `http://localhost:11434` with literal model tag `llama3.2:1b`. | **PASS** |
| **4** | Model Identity Verification | Response received with metadata header and DOM status. | Deployment ID formatted as `ollama:llama3.2:1b:nano`; no false native claims. | **PASS** |
| **5** | Send Second Turn | User sends: *"What number did I tell you?"* | Model receives turn 1 history and answers *"7"*. | **PASS** |
| **6** | Verify Outbound Model Context | Recording tap inspected for outbound Ollama JSON. | Outbound JSON contains `[{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]`. | **PASS** |
| **7** | Inline Message Editing | User clicks Edit on Message 1; changes "7" to "42"; clicks Save. | UI saves edit via `PUT /api/session/{sid}/messages/{mid}`; version revision incremented. | **PASS** |
| **8** | Model Context After Edit | User asks: *"What number did I tell you?"* | Model tap confirms previous turn 1 answer was excluded; context contains edited query ("42"). Model answers *"42"*. | **PASS** |
| **9** | Page Reload & State Restore | User refreshes browser window via `page.reload()`. | Active conversation and full message transcript restored from SQLite without loss. | **PASS** |
| **10** | Sidebar Identity & Titles | Sidebar lists conversation by derived title matching user's opening prompt. | Title updates dynamically after edit; zero cross-account leakage. | **PASS** |
| **11** | Second Browser Tab Scoping | User opens second tab on same session; edits message. | Authoritative server IDs ensure edits in Tab 2 update correct message in Tab 1 upon refresh. | **PASS** |
| **12** | Multi-Tab Concurrent Editing | Worker processes receive simultaneous edit requests. | SQLite monotonic revisions serialized cleanly without conflicts. | **PASS** |
| **13** | Second User Account Isolation | User Bob signs in via private incognito browser context. | Bob sees empty sidebar; attempting to access Alice's URL returns 404. | **PASS** |
| **14** | Complete Cross-User Isolation | Bob attempts to post into Alice's session. | Rejected with 404; zero transcript leakage. | **PASS** |
| **15** | Temporary Chat Creation | User toggles "Temporary Chat"; exchanges turns. | Session created with temporary badge; excluded from persistent sidebar. | **PASS** |
| **16** | Temporary Chat Deletion | User clicks "End Temporary Chat". | Session closed, SQLite turns purged with `secure_delete=ON`, files deleted, WAL truncated. | **PASS** |
| **17** | Interrupted Stream & Stop | User presses "Stop" during multichunk generation. | Client disconnects; server aborts upstream provider; no phantom turn persisted. | **PASS** |
| **18** | Refresh Mid-Stream | Browser page refreshed while response is generating. | Reloaded page displays only fully committed turns; uncommitted tail is excluded. | **PASS** |
| **19** | Model Timeout Handling | Ollama provider delayed past client timeout. | Clean error badge displayed; turn marked `persisted: "failed"`. | **PASS** |
| **20** | Logout Revocation Everywhere | User logs out in Tab 1. | Active token revoked in Redis; Tab 2 storage listener immediately displays logged-out modal. | **PASS** |

---

### 3. Summary of Live Journey Test Execution

| Journey Suite | Module File | Sample Count | Result | Duration |
| :--- | :--- | :---: | :---: | :---: |
| **API Live Journeys** | `tests/journey/test_journey_api_live.py` | 19 tests | **19 PASSED, 0 FAILED** | 61.39s |
| **Browser Chromium Journeys** | `tests/journey/test_journey_browser.py` | 19 tests | **19 PASSED, 0 FAILED** | 150.68s |
| **Browser Fixture Journeys** | `tests/journey/test_journey_browser_fixture.py` | 10 tests | **10 PASSED, 0 FAILED** | 22.14s |
| **Concurrency Live Journeys** | `tests/journey/test_journey_concurrency_live.py` | 9 tests | **9 PASSED, 0 FAILED** | 54.34s |
| **TOTAL** | — | **57 tests** | **57 PASSED, 0 FAILED** | **288.55s (4m 48s)** |

All 57 live real-world journeys executed cleanly with zero skips and zero failures.
