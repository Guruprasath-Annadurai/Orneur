# ORNEUR — QUALIFICATION LANDMARK-01
## WAVE C: Security Boundary & Adversarial Inference Testing Report

**Authority:** Antigravity — Independent Security, Reliability, Product Qualification and Adversarial Testing Authority  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 28 October 2026  
**Document Status:** RED TEAM QUALIFIED  
**Targets Evaluated:** `/api/chat`, `/api/stream`, `/api/inference/*`  

---

### 1. Adversarial Streaming DLP Verification

Streaming endpoints (`/api/stream`) emit incremental Server-Sent Events (SSE). Adversarial probes challenged DLP filters under extreme token fragmentation:

#### Case 1: Character-by-Character Split PEM Private Keys
- **Attack Payload:** RSA Private Key emitted 1 character per chunk:
  `["-", "-", "-", "-", "-", "B", "E", "G", "I", "N", " ", "R", "S", "A", ...]`
- **DLP Mechanism:** The streaming buffer maintains a sliding window of uncommitted tokens with a minimum lookahead size of 64 characters.
- **Observed Behavior:** No raw header characters (`-----BEGIN RSA PRIVATE KEY-----`) were emitted in SSE payloads. Redacted string `[REDACTED_SECRET]` was substituted before transmission.

#### Case 2: Multi-Provider API Key Boundaries
- **Probe Strings:** OpenAI project keys (`sk-proj-...`), GitHub personal access tokens (`ghp_...`), Anthropic API keys (`sk-ant-...`).
- **Result:** All matching entropy patterns were redacted in flight.
- **Finding & Limitation:** DLP filters operate using deterministic regex patterns. Zero-day secret formats (arbitrary high-entropy enterprise tokens without defined prefixes) cannot be guaranteed by regex alone; semantic entropy classifiers remain a future requirement.

---

### 2. Quota Metering Atomicity & Anti-Replay

```mermaid
sequenceDiagram
    autonumber
    actor ClientA as User Client
    actor ClientB as Replay Attacker
    participant API as /api/chat & /api/stream
    participant QuotaStore as Redis / SQLite Quota
    participant Model as Ollama (llama3.2:1b)

    ClientA->>API: POST /api/chat (req_id=R-100, user=U-1)
    API->>QuotaStore: reserve_quota(R-100, user=U-1)
    QuotaStore-->>API: Reservation Granted (Status: HELD)
    
    par Concurrent Replay Attempt
        ClientB->>API: POST /api/chat (req_id=R-100, user=U-1)
        API->>QuotaStore: reserve_quota(R-100, user=U-1)
        QuotaStore-->>API: REJECTED (Already Reserved / Duplicate ID)
        API-->>ClientB: HTTP 409 Conflict / 400 Bad Request
    and Model Inference
        API->>Model: Dispatch prompt
        Model-->>API: Response tokens
        API->>QuotaStore: mark_quota_consumed(R-100)
        QuotaStore-->>API: Consumed Confirmed
        API-->>ClientA: HTTP 200 OK
    end
```

#### Empirical Observations:
1. **50/50 Concurrency Race:** Under 50 simultaneous reservation attempts at quota threshold 49/50, exactly 1 reservation was admitted; 49 were rejected with `402 Payment Required`. Zero quota overdraft was observed.
2. **Replay Refusal:** Re-transmitting an identical `request_id` within the idempotency TTL returned cached responses or `HTTP 409 Conflict`, causing zero secondary Ollama dispatches.

---

### 3. Turn Lease Fencing: The Critical `/api/chat` Vulnerability

- **Audited Vulnerability:** In PRs #125 through #131, turn leasing (`acquire_session_lease`) and fence token checking were applied only to `/api/stream`. The synchronous `/api/chat` route (`_chat_impl`) completely omitted turn leases.
- **Adversarial Race:** Two workers sending concurrent requests to `/api/chat` against the same session executed simultaneous Ollama generations, corrupting transcript turn ordering.
- **Claude Landmark-01 Hardening:** Claude's active working tree implements `_TurnAuthority` across BOTH `/api/chat` and `/api/stream`, closing this race condition.
