# ORNEUR — QUALIFICATION LANDMARK-01
## WAVE B: Independent Authentication & Access-Control Red Team Report

**Authority:** Antigravity — Independent Security, Reliability, Product Qualification and Adversarial Testing Authority  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 28 October 2026  
**Document Status:** RED TEAM QUALIFIED  
**Severity:** CRITICAL (P0) — Fail-Open Authentication Downgrade  

---

### 1. Executive Red Team Finding: The Fail-Open Downgrade Vulnerability

During adversarial testing against candidate branches (PRs #125, #126, #127, #128, #129, #130, #131), Antigravity confirmed a critical systemic access control defect in `orca/auth/middleware.py`:

```python
# orca/auth/middleware.py (Vulnerable historical implementation)
async def get_current_user_optional(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[User]:
    if not creds:
        return None
    try:
        return await get_current_user(creds)
    except HTTPException:
        return None  # <-- DEFECT: Catches 401 and converts it to anonymous access!
```

#### The Exploit Mechanism & Observable Failure
When an attacker or logged-out client presents an expired JWT, a revoked JWT (revoked via `/api/auth/logout`), or complete garbage (`Bearer not-a-valid-token`), `get_current_user()` raises `HTTPException(status_code=401, detail="Token revoked")`.

Because `get_current_user_optional` caught all `HTTPException`s and returned `None`, FastAPI treated the request as an **anonymous unauthenticated user**. On endpoints that permit optional authentication (such as `/api/chat`, `/api/stream`, `/api/sessions`), the request was:
1. Admitted into the serving pipeline instead of being rejected with `401 Unauthorized`.
2. Allocated anonymous quota. In our automated tests, this resulted in an immediate `402 Payment Required` (or unmetered anonymous inference) rather than `401 Unauthorized`.
3. Allowed to consume backend resources and dispatch inference queries to Ollama.

```
========================================================================================================
                               AUTHENTICATION ADVERSARIAL MATRIX
========================================================================================================
Probe Type                 | Target Endpoint   | Vulnerable Branches Result   | Patched Landmark-01 Result
---------------------------+-------------------+------------------------------+---------------------------
Absent Authorization Hdr   | GET /api/sessions | 200 OK (Anonymous Allowed)   | 200 OK (Anonymous Allowed)
Garbage Bearer Token       | POST /api/chat    | 402 / Anonymous Admission    | 401 Unauthorized (ZERO Ollama)
Expired JWT Bearer         | POST /api/chat    | 402 / Anonymous Admission    | 401 Unauthorized (ZERO Ollama)
Revoked JWT (Post-Logout)  | POST /api/stream  | 402 / Anonymous Admission    | 401 Unauthorized (ZERO Ollama)
Logout-All Revoked Token   | POST /api/chat    | 402 / Anonymous Admission    | 401 Unauthorized (ZERO Ollama)
Reset Token as Bearer      | POST /api/chat    | 402 / Anonymous Admission    | 401 Unauthorized (ZERO Ollama)
Cross-User Session Query   | GET /api/session  | 403 / 404 (Isolated)         | 403 / 404 (Isolated)
========================================================================================================
```

### 2. Empirical Verification & Model Dispatch Proof

To verify whether rejected probes reach the model backend, Antigravity used the `FakeOllama` tap:

```
[Red Team Probe Log]
TARGET: POST /api/chat
HEADERS: Authorization: Bearer <revoked-jwt-token>
EXPECTATION: HTTP 401 Unauthorized, Delta Ollama Dispatches = 0

VULNERABLE RUN (PR #129 / PR #131):
- HTTP Status: 402 Payment Required (Handled as anonymous user hitting daily limits)
- Ollama Dispatch Delta: Leaked requests when anonymous quota remained.

REMEDIATED RUN (Commit 5bbd869 in Landmark-01):
- HTTP Status: 401 Unauthorized
- Error Detail: "Token has been revoked"
- Ollama Dispatch Delta: EXACTLY 0 (Provider was never called)
```

### 3. Remediation Analysis

Claude's commit `5bbd869` (`claude/landmark-01-secure-chatbot-integration`) closed this vulnerability by removing the try-except wrapper:
```python
async def get_current_user_optional(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[User]:
    if not creds:
        return None
    return await get_current_user(creds)
```

**Qualification Requirement:** Any candidate submitted for LANDMARK-01 integration MUST incorporate this strict non-swallowing credential validation.
