# ORNEUR LANDMARK-01 — FINAL BLOCKER REGISTER
## Master Defect, Limitation, and Architectural Gap Inventory

**Qualification Authority:** Antigravity  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 29 October 2026  
**Candidate Under Test:** Claude PR #134 (`8d72baab4ebe4ce3a6aa4a76385e18e1c1fba788`)  
**Audit Scope:** Full Platform, Security, Serving, and User Experience  

---

### 1. Executive Summary

- **Outstanding P0 Defects:** **0** (All security and distributed-persistence P0 blockers from previous milestones are CLOSED).
- **Outstanding P1 Blockers:** **1** (`B-01` — Plain-chat non-streaming delivery).
- **Outstanding P2 Gaps:** **3** (`B-04`, `B-05`, `B-06`).
- **Outstanding P3 Limitations:** **5** (`B-07`, `B-08`, `B-09`, `B-10`, `B-11`).

---

### 2. Detailed Blocker Register

| ID | Sev | Title | Component | Reproducible? | Reachable by Public? | Impact | Engineering Owner | Minimal Remediation |
| :---: | :---: | :--- | :--- | :---: | :---: | :--- | :---: | :--- |
| **B-01** | **P1** | Default plain-chat answers delivered as single *replayed* chunk | `orca/cognitive/kernel.py` + `orca/serve/api.py` | **YES** | **YES** | User experiences 1–3s latency delay before whole answer appears; no incremental token streaming; "Stop" button cannot cancel plain turns. Blocks public chatbot experience. | **Cursor (Kernel) + Claude (API/UI)** | Add `on_chunk` streaming callback to `CognitiveRequest`; call `ModelGateway.stream(...)` inside `_answer_directly`; pipe deltas through `StreamRedactor` in `api.py`. |
| **B-04** | **P2** | Real-Ollama journeys workstation-only, not in GitHub Actions CI | `.github/workflows/test.yml` | **YES** | NO (Developer only) | CI verifies fixture-provider journeys; real Ollama models are not pulled or executed on standard GitHub runners. | **Claude / Devops** | Add workflow job using self-hosted runner or tiny pinned model artifact. |
| **B-05** | **P2** | Physical byte reclamation of deleted vector data is best-effort | `orca/memory/turn_ingest.py` | **YES** | NO (Security) | SQLite turns are wiped with `secure_delete=ON`, but ChromaDB embedding unlinks rely on vector store vacuum/truncate policies. | **Cursor (Memory)** | Implement deterministic shredding/vacuum for vector store collections upon session close. |
| **B-06** | **P2** | Discarded Kernel answer when session has documents without plan | `orca/serve/api.py` | **YES** | **YES** | When documents exist without an evidence plan, Kernel direct answer is discarded and model called again (≥ 2 calls per turn). | **Cursor (Kernel)** | Route document sessions directly to RAG planner before calling direct gateway. |
| **B-07** | **P3** | Persistence status uncertain after severed connection | `orca/serve/api.py` | **YES** | **YES** | If client disconnects while server is committing to SQLite, UI cannot display whether commit succeeded upon reconnect. | **Claude (Frontend)** | Add turn acknowledgment reconciliation endpoint on frontend reconnect. |
| **B-08** | **P3** | `/api/cognitive/execute` surfaces kernel error as unhandled 500 | `orca/serve/api.py` | **YES** | **YES** | Unmapped cognitive failures return generic HTTP 500 without structured error taxonomy. | **Cursor (Serve)** | Map cognitive exceptions to coded `PublicError` models. |
| **B-09** | **P3** | Sign-up has no email verification; anonymous callers have IP-only limits | `orca/auth/routes.py` | **YES** | **YES** | Anonymous requests share IP rate limit bucket; accounts can be created with unverified email strings. | **Cursor (Auth)** | Add email verification tokens and stricter IP fingerprinting. |
| **B-10** | **P3** | Orphaned deployment records after family-aware ID change | `orca/gateway/wiring.py` | **YES** | NO (Operator) | Old deployment records stored prior to `stable_deployment_id` format are orphaned in registry. | **Cursor (Gateway)** | Add migration script to update legacy deployment rows. |
| **B-11** | **P3** | DLP is a deterministic pattern floor | `orca/serve/dlp.py` | **YES** | NO (Architectural) | Pattern-based regex DLP cannot redact unknown or proprietary secret syntaxes. | **Cursor (Security)** | Document DLP boundaries in security policy; add semantic DLP in future phase. |

---

### 3. Historical P0 Blockers Certified Closed

1. **P0-1 Auth Downgrade on Invalid/Revoked Token:** CLOSED. `get_current_user_optional` returns 401 Unauthorized; zero model dispatch.
2. **P0-2 Unfenced `/api/chat` Route:** CLOSED. `_TurnAuthority` acquired before generation and re-validated inside SQLite commit.
3. **P0-3 Divergent Storage Lineages:** CLOSED. Consolidated onto PR #130 SQLite `session_authority` with fencing epochs.
4. **P0-4 Quota 49/50 Concurrency Race:** CLOSED. Atomic reservation via `_QuotaTicket` conditional SQL updates.
5. **P0-5 Streaming DLP Chunk-Split Leakage:** CLOSED. Stateful `StreamRedactor` holds partial prefixes across chunk boundaries.
6. **P0-6 Stale Writer Lease Takeover:** CLOSED. Fencing epoch bump in SQLite transaction rejects superseded workers.
