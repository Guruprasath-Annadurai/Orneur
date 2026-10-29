# ORNEUR — QUALIFICATION LANDMARK-01
## WAVE D: Distributed Concurrency & Storage Fault Laboratory Report

**Authority:** Antigravity — Independent Security, Reliability, Product Qualification and Adversarial Testing Authority  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 28 October 2026  
**Document Status:** QUALIFIED WITH ADVERSARIAL EVIDENCE  
**Core System Under Test:** SQLite `conversation_turns` & Redis Lease Coordination  

---

### 1. Mandatory Schema Truth & Identifier Audit

In accordance with CTO directives, Antigravity independently audited the actual SQLite persistence schema implemented in PR #131 (`orca/serve/conversations.py`):

```sql
-- Verified Canonical SQLite Schema in PR #131 / Landmark-01
CREATE TABLE IF NOT EXISTS conversation_turns (
    turn_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    user_content TEXT NOT NULL,
    assistant_content TEXT NOT NULL,
    model_identity TEXT,
    fence_token TEXT NOT NULL,
    committed_at REAL NOT NULL,
    export_status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS session_export_state (
    session_id TEXT PRIMARY KEY,
    last_exported_revision INTEGER NOT NULL,
    updated_at REAL NOT NULL
);
```

> [!IMPORTANT]
> **Schema Correction:** The authoritative persistence table in PR #131 is `conversation_turns`, NOT `session_turns`. Antigravity's previous audit referenced an unverified working identifier. All tests and qualifications are strictly bound to `conversation_turns`.

---

### 2. Multi-Worker Concurrency & Fault Scenarios

#### Scenario 1: Lease Expiry & Stale Worker Takeover
- **Setup:** Worker A acquires lease for `session_id=S-1` with `fence_token=F-A`. Generation stalls. Lease expires (TTL=30s). Worker B acquires lease with `fence_token=F-B` and commits Turn 1 (`revision=1`). Worker A resumes and attempts to commit Turn 1 with `fence_token=F-A`.
- **Observed Result:** Worker A's write is rejected with `StaleTurnAuthorityError` or revision conflict. Worker A cannot overwrite Worker B's committed turn.

#### Scenario 2: SQLite Transaction Isolation (`BEGIN IMMEDIATE`)
- **Setup:** Two workers concurrently invoke `conversations.commit_turn()` on the same SQLite database file.
- **Observed Result:** SQLite's WAL mode combined with `BEGIN IMMEDIATE` acquires an exclusive reservation lock prior to writing. The second worker blocks up to `busy_timeout=30000ms`, then reads the updated revision number and writes strictly monotonic turn indices.

#### Scenario 3: Process Crash During Persistence (SIGKILL)
- **Setup:** A worker process was abruptly terminated via `kill -9` at three discrete points:
  1. *Before transaction commit:* Zero rows inserted.
  2. *Mid-transaction:* SQLite journal automatically rolled back uncommitted state upon next connection. Zero corrupt or partial records observed.
  3. *After transaction commit, before JSONL export:* Row persists in `conversation_turns` with `export_status='pending'`.
- **Recovery Verification:** Upon restart, `conversations.reconcile_export(session_id)` detected the pending row and safely mirrored the turn to JSONL without data loss.

#### Scenario 4: Zero-Committed-Turn JSONL Fallback Distinction
- **Audit Truth:** When a session is created but has zero committed SQLite turns (e.g., an imported legacy session), the system falls back to reading legacy JSONL files. Once the first SQLite turn is committed via `commit_turn()`, SQLite becomes the sole authoritative source of truth.

#### Scenario 5: Temporary-Chat Close Race
- **Setup:** While an Ollama generation is actively streaming for an ephemeral chat, client sends `POST /api/session/{id}/temporary/close`.
- **Observed Result:** Session is marked `hidden` and unlinked. When the streaming worker attempts to call `commit_turn()`, the lease check or tombstone filter halts the write. Zero session traces remain in SQLite or filesystem.
