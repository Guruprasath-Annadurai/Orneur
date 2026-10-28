# ORNEUR — QUALIFICATION LANDMARK-01
## CURSOR & CLAUDE ENGINEERING HANDOFF SPECIFICATION

**Authority:** Antigravity — Independent Security, Reliability, Product Qualification and Adversarial Testing Authority  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 28 October 2026  
**Document Status:** OFFICIAL MILESTONE HANDOFF  

---

### 1. Handoff to Cursor (FOUNDATION LANDMARK-01 Owner)

Cursor owns the backend foundation, quota enforcement, authoritative transcript persistence, Redis/SQLite coordination, and serving reliability.

#### Required Remediation Items:
1. **Extend Turn Authority to `/api/chat`:**
   - The synchronous `/api/chat` endpoint (`_chat_impl` in `orca/serve/api.py`) currently executes without acquiring session leases or verifying fence tokens. Port the `_TurnAuthority` class (implemented in Claude's working branch) or equivalent Redis lease fencing to `/api/chat`.
2. **Standardize SQLite Authoritative Storage:**
   - Confirm that the canonical table name is `conversation_turns` (as verified in PR #131) and ensure all session read/commit operations execute within `BEGIN IMMEDIATE` transactions.
3. **Quota Reservation Heartbeats:**
   - Adopt the `renew_quota` keepalive mechanism to ensure long-running generations (>30s) are not prematurely refunded by TTL cleaners while generation is active.

---

### 2. Handoff to Claude (LANDMARK-01 Product Owner)

Claude owns official product integration, frontend behavior, multi-turn conversations, streaming UI, message editing, and full browser user journeys.

#### Required Remediation Items:
1. **Preserve Authentication 401 Patch (`5bbd869`):**
   - Ensure the correction in `orca/auth/middleware.py#get_current_user_optional` (returning 401 directly instead of swallowing exceptions) is retained in the integrated landmark candidate.
2. **Re-architect Message Versioning onto SQLite:**
   - The message edit branching logic in `orca/serve/message_versions.py` currently reads and writes filesystem JSONL files. Port this logic to read from and commit to SQLite's `conversation_turns` table, ensuring edit history survives server restarts.
3. **Streaming Response Buffer Flushing:**
   - Ensure FastAPI `StreamingResponse` sets `headers={"X-Accel-Buffering": "no"}` and invokes immediate flush on token yields to prevent short responses from coalescing into single chunks.

---

### 3. Integrated Candidate Qualification Protocol

Once Cursor and Claude deliver their respective milestone implementations, the authorizer (CTO) will designate a single integrated candidate SHA.

Antigravity will independently checkout that exact SHA and execute the automated qualification suite:
```bash
/home/pc/projects/Orneur/.venv/bin/python scripts/qualification/run_qualification_suite.py --worktree /path/to/integrated-worktree
```
No manual sign-off or self-certified merge will be accepted without passing automated qualification evidence.
