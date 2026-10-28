# ORNEUR — QUALIFICATION LANDMARK-01
## MASTER DEDUPLICATED BLOCKER REGISTER

**Authority:** Antigravity — Independent Security, Reliability, Product Qualification and Adversarial Testing Authority  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 28 October 2026  
**Document Status:** MASTER BLOCKER LEDGER  

---

### 1. Deduplicated Blocker Inventory

```
========================================================================================================
                                     ORNEUR BLOCKER REGISTER
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

### 2. Blocker Impact Analysis

- **B-01 (Auth Downgrade):** Prevents secure public release. A user who logs out or has an expired token can continue spending model quota as an anonymous user.
- **B-02 (`/api/chat` Unfenced):** Concurrent browser tabs or parallel API workers calling `/api/chat` against the same session bypass Redis turn leases, resulting in out-of-order transcript mutations.
- **B-03 (Storage Collision):** PR #129 (product features) and PR #131 (crash-durable persistence) cannot be integrated without unified SQLite storage for message versions.
- **B-04 (Training Governance):** Distributed GPU pretraining cannot commence without dataset validation and founder signature.
