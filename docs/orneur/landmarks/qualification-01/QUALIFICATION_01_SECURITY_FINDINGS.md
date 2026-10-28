# ORNEUR — QUALIFICATION LANDMARK-01
## MASTER SECURITY FINDINGS AND VULNERABILITY REGISTER

**Authority:** Antigravity — Independent Security, Reliability, Product Qualification and Adversarial Testing Authority  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 28 October 2026  
**Document Status:** CONFIRMED VULNERABILITIES  

---

### Finding SEC-01: Fail-Open Authentication Downgrade on Invalid/Revoked Bearer Tokens

- **Severity:** **CRITICAL (P0)**
- **Vulnerability Classification:** CWE-287: Improper Authentication (Fail-Open Authorization)
- **Target File:** [`orca/auth/middleware.py`](file:///home/pc/projects/Orneur/orca/auth/middleware.py#L57-L65)
- **Observed Behavior:**
  In historical PRs #125 through #131, `get_current_user_optional()` catches `HTTPException(401)` and returns `None`. When an attacker presents a revoked JWT, expired JWT, or garbage string, optional-auth endpoints (`/api/chat`, `/api/stream`, `/api/sessions`) silently admit the request as an anonymous user instead of rejecting it with `HTTP 401 Unauthorized`.
- **Exploitation Impact:**
  A logged-out user or attacker holding a revoked token continues dispatching queries to model providers and spending system quota.
- **Reproduction:**
  `pytest tests/qualification/test_auth_adversarial.py::TestAuthenticationRedTeam::test_garbage_bearer_token_refused_with_401_and_zero_dispatches`
- **Recommended Corrective Owner:** Cursor & Claude (Resolved in Claude's Landmark-01 commit `5bbd869`).

---

### Finding SEC-02: Turn Lease Fencing Bypass on Canonical `/api/chat` Route

- **Severity:** **CRITICAL (P0)**
- **Vulnerability Classification:** CWE-362: Concurrent Execution without Mutual Exclusion
- **Target File:** [`orca/serve/api.py`](file:///home/pc/projects/Orneur/orca/serve/api.py#L1120-L1180)
- **Observed Behavior:**
  While `/api/stream` acquires a Redis session lease and verifies fence tokens before publishing, the synchronous route `POST /api/chat` (`_chat_impl`) omits turn lease acquisition and fence validation entirely.
- **Exploitation Impact:**
  Two concurrent requests sent to `/api/chat` against the same session execute simultaneous model inference and corrupt conversation history turn ordering.
- **Reproduction:**
  `pytest tests/qualification/test_inference_adversarial.py`
- **Recommended Corrective Owner:** Cursor (FOUNDATION LANDMARK-01) & Claude.

---

### Finding SEC-03: Architectural Desynchronization between SQLite and JSONL Transcripts

- **Severity:** **CRITICAL (P0)**
- **Vulnerability Classification:** State Inconsistency & Data Loss
- **Target Files:** `orca/serve/conversations.py` vs `orca/serve/conversation_context.py` vs `orca/serve/message_versions.py`
- **Observed Behavior:**
  PR #131 establishes SQLite (`conversation_turns` table) as the single authoritative source of truth. However, PR #129's message edit branching and context assembly read and modify filesystem JSONL files.
- **Exploitation Impact:**
  Edits made via the UI are not reflected in the SQLite database used for crash recovery, causing conversations restored after restarts to lose edits.
- **Recommended Corrective Owner:** Claude & Cursor (Joint Architecture Harmonization).

---

### Finding SEC-04: Streaming Response Token Coalescing

- **Severity:** **MEDIUM (P2)**
- **Vulnerability Classification:** UX / Protocol Degradation
- **Target File:** `orca/serve/inference.py`
- **Observed Behavior:**
  Under high-throughput loopback conditions, short model completions drain rapidly through FastAPI's `StreamingResponse`, causing the Playwright browser observer to receive the response in a single coalesced chunk rather than incremental tokens.
- **Reproduction:**
  `pytest tests/journey/test_journey_browser.py -k test_browser_step[B1_new_conversation_streams_real_answer]`
- **Recommended Corrective Owner:** Claude (LANDMARK-01 Frontend / Streaming).
