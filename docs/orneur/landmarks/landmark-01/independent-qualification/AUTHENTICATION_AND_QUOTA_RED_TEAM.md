# ORNEUR LANDMARK-01 — SECURITY RED TEAM REPORT
## Authentication, Session Integrity, and Atomic Quota Enforcement

**Qualification Authority:** Antigravity  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 29 October 2026  
**Candidate Under Test:** Claude PR #134 (`8d72baab4ebe4ce3a6aa4a76385e18e1c1fba788`)  
**Evidence Class:** `VERIFIED_REAL` and `VERIFIED_DETERMINISTIC`  
**Verdict:** **`PASS — NO VULNERABILITIES DETECTED`**  

---

### 1. Executive Summary

Antigravity subjected candidate PR #134 to an adversarial red-team qualification across authentication middleware, session isolation, cross-worker logout invalidation, and atomic quota accounting.

**Key Finding:** The critical authentication downgrade vulnerability that affected earlier candidate baselines (where invalid/revoked tokens were silently downgraded to anonymous requests) has been **completely eliminated**. In PR #134, presented credentials are strictly validated; invalid, expired, or revoked credentials deterministically receive HTTP 401 Unauthorized with **zero model dispatch** and **zero state mutation**.

---

### 2. C1: Authentication and Session Security Adversarial Testing

All attacks were executed against the live candidate application:

| Attack Scenario | Injected Payload / Method | Expected Refusal | Observed Response | Model Dispatched? | Result |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Garbage Bearer Token** | `Authorization: Bearer not-a-valid-token-garbage` | HTTP 401 | `401 Unauthorized` (`token_invalid`) | **NO (0 calls)** | **PASS** |
| **Expired JWT Token** | Token with `exp: now - 3600` | HTTP 401 | `401 Unauthorized` (`token_expired`) | **NO (0 calls)** | **PASS** |
| **Revoked JWT (Post-Logout)** | Valid token used after `POST /api/auth/logout` | HTTP 401 | `401 Unauthorized` (`token_revoked`) | **NO (0 calls)** | **PASS** |
| **Wrong Token Type: Reset** | Token signed with `type: "reset"` | HTTP 401 | `401 Unauthorized` (`token_invalid`) | **NO (0 calls)** | **PASS** |
| **Wrong Token Type: Verification** | Token signed with `type: "email_verification"` | HTTP 401 | `401 Unauthorized` (`token_invalid`) | **NO (0 calls)** | **PASS** |
| **Wrong Token Type: 2FA Pending** | Token signed with `type: "2fa_pending"` | HTTP 401 | `401 Unauthorized` (`token_invalid`) | **NO (0 calls)** | **PASS** |
| **Password Change Invalidation** | Token issued at $t_0$, password changed at $t_1 > t_0$ | HTTP 401 | `401 Unauthorized` (`token_revoked`) | **NO (0 calls)** | **PASS** |
| **Revoked API Key** | `Authorization: Bearer orca_ak_revoked...` | HTTP 401 | `401 Unauthorized` (`api_key_invalid`) | **NO (0 calls)** | **PASS** |
| **Cross-User Session Snooping** | User Bob querying `GET /api/session/{alice_sid}/messages` | HTTP 404 | `404 Not Found` (session existence masked) | **NO (0 calls)** | **PASS** |
| **Cross-User Session Hijacking** | User Bob streaming into `POST /api/stream` with Alice's `session_id` | HTTP 404 | `404 Not Found` (session existence masked) | **NO (0 calls)** | **PASS** |
| **Global Logout-All** | `POST /api/auth/logout_all` executed on Worker 1 | HTTP 401 on Worker 2 | Every active device token immediately revoked in Redis | **NO (0 calls)** | **PASS** |

#### Cryptographic Isolation Verification
- Anonymous access is strictly confined to missing authorization headers on optional routes (`GET /api/sessions`, `POST /api/chat`, `POST /api/stream`).
- When no authorization header is sent, an anonymous session is established with strict IP rate-limiting (`ratelimit.CHAT_ANY`) and no durable SQLite transcript persistence.
- Any credential presented that fails cryptographic signature, expiry, or revocation checks fails immediately at the middleware boundary before route execution.

---

### 3. C2: Atomic Quota Accounting & Replay Resistance

Adversarial load testing was conducted against the quota reservation boundary:

#### Test 1: The 49/50 Daily Limit Race
- **Setup:** A user on a tier with 50 messages/day is seeded with 49 spent messages.
- **Attack:** 50 concurrent requests are fired simultaneously across threads.
- **Result:**
  - Exactly **1 request** received HTTP 200 and spent the final billable unit.
  - Exactly **49 requests** received HTTP 429 `quota_exceeded` with zero model dispatch.
  - Subsequent total usage in database was exactly 50 (no over-allocation).

#### Test 2: Idempotency & Replay Protection
- **Setup:** Authenticated request sent with header `Idempotency-Key: idemp-test-key-001`.
- **Attack:** Fired duplicate request with identical key and payload.
- **Result:**
  - First request executed model inference and returned response.
  - Second request immediately returned cached response with header `Idempotent-Replay: true`.
  - Quota spent: **Exactly 1 unit** (no double-billing).
  - Outbound model dispatches: **Exactly 1 call**.

#### Test 3: Backend Failure Refund Safety
- **Setup:** Model provider configured to raise connection timeout / HTTP 500 midway through request.
- **Result:**
  - `_QuotaTicket` caught the failure during route execution.
  - `release_quota(request_id)` executed inside `finally` block.
  - The reserved quota unit was immediately refunded to the user's daily balance.

#### Test 4: Reservation Heartbeat Durability
- **Setup:** Generation simulated to last 90 seconds (exceeding standard 45s reservation TTL).
- **Result:**
  - Background `_keepalive()` task successfully executed `renew_quota(request_id)` every 30 seconds.
  - Reservation remained active; another concurrent request from the same user could not steal the unit.
  - Model answer committed and unit was consumed cleanly.

---

### 4. Summary & Verification

Red-team testing confirms that candidate PR #134 satisfies all P0 security and accounting criteria. No bypasses, anonymous downgrades, cross-tenant leaks, or quota double-spend races were observable.
