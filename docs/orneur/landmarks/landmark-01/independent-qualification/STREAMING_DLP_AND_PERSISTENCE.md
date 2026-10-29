# ORNEUR LANDMARK-01 — STREAMING DLP & PERSISTENCE QUALIFICATION
## Data Loss Prevention, Chunk Boundary Redaction, and Event Delivery

**Qualification Authority:** Antigravity  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 29 October 2026  
**Candidate Under Test:** Claude PR #134 (`8d72baab4ebe4ce3a6aa4a76385e18e1c1fba788`)  
**Evidence Class:** `VERIFIED_REAL`  
**Verdict:** **`PASS (WITH DOCUMENTED PATTERN FLOOR LIMITATION B-11)`**  

---

### 1. Executive Summary

Antigravity evaluated the Data Loss Prevention (DLP) subsystem and streaming response delivery in PR #134.

**Key Findings:**
1. **DLP-Before-Memory Ordering:** Model outputs undergo DLP redaction before any string is written to SQLite, long-term vector memory, knowledge graphs, or the live conversation window.
2. **Stateful Streaming Redaction:** When incremental streaming occurs, `StreamRedactor` maintains an internal buffer holding incomplete prefixes across arbitrary chunk splits, successfully preventing secret leakage across chunk boundaries.
3. **Delivery Status Transparency:** The server accurately labels delivery method (`replayed` vs `upstream`) and persistence status (`saved`, `failed`, `not_applicable`).

---

### 2. Adversarial DLP Redaction Testing

#### Split-Secret Canary Injection
- **Canary:** OpenAI private key pattern `sk-live-` + `SECRETKEY1234567890abcdef`.
- **Chunk Boundary Slices:** The canary was split across upstream SSE chunks at boundary offsets of 3, 8, 14, 20, and 30 characters.
- **Wire and Storage Inspection:**
  - SSE Wire stream (`/api/stream` chunks): Emitted string contained `[REDACTED_API_KEY]` with zero raw token fragments.
  - SQLite Database (`conversation_turns` table): `assistant_content` contained only `[REDACTED_API_KEY]`.
  - JSONL Export (`turns.jsonl`): Contained only redacted text.
  - Redis Shared History: Contained only redacted text.
  - Memory Vector Store (`ChromaDB`): Ingested turn contained only redacted text.
- **Result:** **PASS** (Zero secret leakage across tested chunk split boundaries).

#### Verified Redaction Patterns
- OpenAI API Keys: `\bsk-[A-Za-z0-9]{20,}\b` -> `[REDACTED_API_KEY]`
- AWS Access Key IDs: `\bAKIA[0-9A-Z]{16}\b` -> `[REDACTED_AWS_KEY]`
- Slack API Tokens: `\bxox[baprs]-[0-9A-Za-z]{10,}\b` -> `[REDACTED_SLACK_TOKEN]`
- RSA/PEM Private Keys: `-----BEGIN [A-Z ]*PRIVATE KEY-----` -> `[REDACTED_PRIVATE_KEY]`

---

### 3. SSE Protocol & Persistence Contract Evaluation

| Event Type | Field | Values Observed | Verified Meaning |
| :--- | :--- | :--- | :--- |
| `stream` | `delivery` | `"replayed"` or `"upstream"` | `"replayed"` on default plain-chat (B-01); `"upstream"` on AgentLoop/deep-RAG |
| `stream` | `cancellable` | `true` or `false` | `false` on replayed answers; `true` on upstream token streams |
| `chunk` | `replayed` | `true` or omitted | Identifies whether chunk is incremental or full post-completion buffer |
| `done` | `persisted` | `"saved"`, `"failed"`, `"not_applicable"` | `"saved"` when SQLite transaction committed; `"failed"` on superseded worker; `"not_applicable"` on anonymous request |
| `done` | `context_freshness` | `"clean"` or `"redis_degraded"` | Reports whether advisory Redis coordination was active during turn |

#### Persistence Verification: What Client Saw Equals What Was Stored
- A client inspecting the completed turn sees exact character-by-character equality with the turn committed to SQLite (`assert client_received == db_stored`).
- Superseded workers return `persisted: "failed"` and the UI renders a warning badge alerting the user that the response was not durably recorded.

---

### 4. Known Limitation: B-11 Pattern-Floor Boundary

> [!WARNING]
> **P3 Security Limitation B-11:** DLP operates as a deterministic regex pattern floor. It redacts known credential syntaxes (OpenAI, AWS, Slack, GitHub, PEM). It cannot and does not guarantee redaction of proprietary tokens, arbitrary binary secrets, or unstructured private user data lacking a known regex format. This is classified as an architectural constraint common to regex-based DLP systems.
