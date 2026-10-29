# ORNEUR LANDMARK-01 — ARCHITECTURE COMPARISON MATRIX
## Cursor Foundation (PR #132) vs Claude Integrated Chatbot (PR #134)

**Qualification Authority:** Antigravity  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 29 October 2026  
**Candidate Under Test:** Claude PR #134 (`8d72baab4ebe4ce3a6aa4a76385e18e1c1fba788`)  
**Comparison Baseline:** Cursor PR #132 (`1f7102da928891eedd6f11553877097214c5c3e2`)  
**Common Ancestor:** PR #130 (`497073d2dfb45f82554fb260db3fe4d87b0b5019`)  

---

### 1. Executive Assessment

Cursor delivered an authoritative backend foundation in PR #132 (`VERIFIED_ENGINEERING`), centralizing admission into `orca/serve/admission.py`. Claude integrated this foundation with the complete multi-turn conversation product lineage in PR #134.

Both branches share PR #130 ancestry and use SQLite-authoritative fencing with epochs. Crucially, **Claude's PR #134 preserves every critical backend guarantee established by Cursor, and actually strengthens several key concurrency and refund mechanisms**, while implementing the full browser user experience.

---

### 2. Contract-by-Contract Comparison Matrix

| Evaluation Domain | Cursor PR #132 Behavior | Claude PR #134 Behavior | Contract Status | Technical Evidence & Analysis |
| :--- | :--- | :--- | :---: | :--- |
| **Authentication: Optional Route Downgrade** | `get_current_user_optional` returns `None` ONLY if no header is supplied; raises `HTTP 401` on invalid, expired, or revoked bearer tokens. | Identical implementation in `orca/auth/middleware.py`. Zero anonymous downgrade for malformed credentials. | **`EQUIVALENT`** | Tested by `test_auth_invalid_bearer_refused.py` (12/12 passed). Both refuse garbage and expired tokens with 401. |
| **Authentication: Cross-Tab Logout Synchronization** | Invalidates tokens in Redis session store. Frontend has no storage listener. | Invalidates tokens in Redis session store AND installs `window.addEventListener("storage", ...)` in `conversation.html`. | **`STRONGER` (Claude)** | Claude handles multi-tab logout: logging out in Tab 1 immediately triggers unauthenticated modal in Tab 2 (`test_logout_revocation.mjs`). |
| **Authentication: Cross-User Isolation** | `check_session_access` enforces ownership. Foreign session IDs return 404 without leaking existence. | `_check_session_ownership` enforces ownership with identical 404 refusal and zero metadata leakage. | **`EQUIVALENT`** | Tested by `test_D1_another_user_cannot_read_stream_into_or_edit_a_conversation` and `test_g006_tenant_isolation`. |
| **Inference Admission: Architecture** | Centralized `orca/serve/admission.py::admit_serving` gate. | Route-level integration using `_QuotaTicket` and `_admit_quota` across all inference routes. | **`EQUIVALENT`** | Contract is identical: quota reserved atomically before dispatch, refunded on abort, consumed on response. |
| **Quota: Atomic Reservation** | Single conditional SQL `UPDATE usage_reservations` via `reserve_quota`. | Same `reserve_quota` conditional SQL update; encapsulated in `_QuotaTicket`. | **`EQUIVALENT`** | Tested by `test_49_of_50_concurrent_chat_requests_admit_exactly_one` (admitted exactly 1 of 50). |
| **Quota: Reservation Heartbeat / Theft Prevention** | Lacked heartbeat for live reservations. Generations > 45s risked quota refund and subsequent double-spending. | Added `orca.auth.store.renew_quota` and background `_QuotaTicket._keepalive()` task running every 30s. | **`STRONGER` (Claude)** | Tested by `test_heartbeat_keeps_a_long_reservation_from_being_refunded_as_stale`. Eliminates reservation theft during long model inference. |
| **Quota: Prompt Assembly Refund Safety** | In `inference.py`, `_prompt_with_session` was called before the `try/finally` block. A SQLite error during prompt assembly leaked reserved quota. | `_prompt_with_session` moved *inside* the `try` block, ensuring any prompt construction failure immediately triggers `release_quota`. | **`STRONGER` (Claude)** | Tested by `test_inference_prompt_assembly_failure_refunds_the_reservation`. Prevents quota leakage on store glitch. |
| **Quota: Route Coverage** | Covered `/api/chat`, `/api/stream`, `/api/inference/*`, `/api/cognitive/execute`, and `/api/ultra`. | Covers `/api/chat`, `/api/stream`, `/api/inference/*`, `/api/cognitive/execute`, and `/api/ultra`. | **`EQUIVALENT`** | Tested by `test_canonical_quota_admission.py`. |
| **Storage: Fencing Engine** | PR #130 SQLite `session_authority` table with fencing epochs. | Selected PR #130 SQLite `session_authority` table with fencing epochs (PR #131 rejected). | **`EQUIVALENT`** | Single transactional commit sequence in SQLite `conversation_turns`. |
| **Storage: Authority Heartbeat on Long Runs** | Authority had 45s TTL renewed once before commit. Inference generations > 45s lost commit rights (`stale_worker`). | Added `_authority_heartbeat` in `inference.py` and `_TurnAuthority._beat()` in `api.py` renewing authority every 10s. | **`STRONGER` (Claude)** | Tested by `test_a_generation_longer_than_the_authority_ttl_still_commits_on_the_inference_routes`. |
| **Storage: Read Contention** | Reads could acquire advisory lease. | Explicitly decoupled reads: transcript reads use read-only transactions, never acquiring or stranding turn authority leases. | **`STRONGER` (Claude)** | Tested by `test_reading_the_transcript_never_blocks_or_strands_the_next_turn`. |
| **Storage: Temporary Chat Lifecycle** | Temporary sessions closed via Redis flag. | Added `closing` transition state, inode-verified locking, SQLite `secure_delete=ON`, and WAL file truncation. | **`STRONGER` (Claude)** | Tested by `test_temporary_chat_multiprocess.py` (5/5 passed). Zero residual byte leakage in WAL. |
| **DLP & Redaction** | Output DLP executed before commit and memory ingestion. | Output DLP executed before commit and memory ingestion, plus stateful `StreamRedactor` for chunk-boundary secret splits. | **`EQUIVALENT`** | Tested by `test_canonical_route_dlp.py` (8/8 passed). |
| **Frontend Integration** | No real browser frontend included (backend-only milestone). | Complete `/conversation` UI with inline message editing, sidebar restoration, honest persistence badges, and theme toggle. | **`MISSING` in #132 / `DELIVERED` in #134** | Tested by Playwright Chromium suites (19/19 passed). |
| **Streaming Delivery (B-01)** | Documented shadow execution; no browser streaming client. | Delivers full text in a single labelled replay chunk on default path (`stream.delivery: "replayed"`). | **`WEAKER` (Both share B-01)** | Default plain chat is non-streaming; documented as P1 blocker B-01. |

---

### 3. Conclusion on Architectural Parity

PR #134 achieves complete parity with Cursor's PR #132 while fixing three distinct backend vulnerabilities present in Cursor's implementation:
1. **Quota Theft During Long Inference:** Solved via `renew_quota` heartbeat.
2. **Quota Leakage During Prompt Assembly:** Solved by moving prompt assembly inside the refund-safe `try` block.
3. **Commit Rejection on Long Generations:** Solved via `_authority_heartbeat`.

**Verdict:** PR #134 is authoritatively certified as preserving and strengthening all engineering guarantees of PR #132. It can serve as the canonical integration candidate without loss of backend integrity.
