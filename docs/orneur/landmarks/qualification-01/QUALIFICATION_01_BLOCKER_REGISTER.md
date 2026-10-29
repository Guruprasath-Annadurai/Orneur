# ORNEUR — QUALIFICATION LANDMARK-01
## MASTER DEDUPLICATED BLOCKER REGISTER (Corrected)

**Authority:** Antigravity — Independent Security, Reliability, Product Qualification and Adversarial Testing Authority  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 28 October 2026 (Corrected Revision)  
**Document Status:** MASTER BLOCKER LEDGER  

---

### 1. Product Security & Architectural Blockers (Unresolved on Main)

```
========================================================================================================
                                     ORNEUR PRODUCT BLOCKER REGISTER
========================================================================================================
ID  | SEV | TITLE & SUMMARY                                  | TARGET COMPONENT            | OWNER
----+-----+--------------------------------------------------+-----------------------------+-----------
B-01| P0  | Fail-Open Auth Downgrade on Invalid/Revoked Bearer| orca/auth/middleware.py     | Cursor/Claude
B-02| P0  | Canonical /api/chat Bypasses Turn Lease Fencing  | orca/serve/api.py           | Cursor
B-03| P0  | SQLite vs JSONL Storage Architectural Collision  | orca/serve/conversations.py | Claude/Cursor
B-04| P0  | Native-Model Pretraining Ledger 0/95 Accepted    | training/manifests/         | Founder
B-05| P1  | Message Edit Branching Not Persisted to SQLite   | orca/serve/message_versions | Claude
B-06| P2  | SSE Loopback Token Coalescing / Buffering        | orca/serve/inference.py     | Claude
B-07| P2  | Zero-Day DLP Secret Formats Unclassified by Regex| orca/serve/dlp.py           | Cursor
========================================================================================================
```

---

### 2. Qualification Laboratory Status (RESOLVED)

All previous laboratory defects flagged in the CTO Mandatory Corrective Order have been fully repaired:
- [x] **Harness Import Error (scan_and_redact):** Replaced with actual `scan_output` and `StreamRedactor`.
- [x] **Harness Attribute Error (conversations.init_db):** Replaced with canonical SQLite `_turns_conn()` and `commit_turn()`.
- [x] **Temporary Chat Endpoint Error (POST /api/sessions):** Corrected to canonical `POST /api/sessions/temporary`.
- [x] **Orchestrator Hardcoded Paths & Provenance:** Orchestrator rewritten with explicit candidate/harness tracking and PYTHONPATH isolation.
- [x] **Performance Claims Retraction:** Synthetic figures retracted; real empirical samples documented.
- [x] **Deterministic Unit Tests CI Pass:** All 5 qualification suites now pass cleanly in CI.
