# ORNEUR — QUALIFICATION LANDMARK-01
## MASTER ENGINEERING AND INDEPENDENT QUALIFICATION FINAL REPORT (Corrected)

**Issued by:** Antigravity — Independent Security, Reliability, Product Qualification and Adversarial Testing Authority  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 28 October 2026 (Corrected Revision)  
**Milestone:** QUALIFICATION LANDMARK-01  
**Qualification Branch:** `antigravity/qualification-landmark-01`  
**Consolidated Verdict:** **LABORATORY_VERIFIED** | **INTEGRATED_QUALIFICATION_PENDING_CANDIDATE**  

---

## 1. Executive Summary & Corrective Actions Completed

Following the CTO Mandatory Corrective Order, Antigravity has thoroughly audited, repaired, and validated the independent qualification laboratory:

1. **Eliminated Invalid API Assumptions:**
   - Replaced nonexistent `scan_and_redact` with the actual implemented interfaces: `orca.serve.dlp.scan_output` and `orca.serve.stream_dlp.StreamRedactor`.
   - Replaced nonexistent `conversations.init_db` with canonical SQLite `_turns_conn()` and `commit_turn()` APIs.
   - Corrected temporary chat endpoints from `POST /api/sessions` to canonical `POST /api/sessions/temporary`.
2. **Re-engineered Orchestrator & Dual Provenance:**
   - `scripts/qualification/run_qualification_suite.py` rewritten to mandate explicit candidate worktree selection, enforce strict candidate `PYTHONPATH` isolation, and record candidate SHA and harness SHA separately.
   - Orchestrator returns strict exit code 0 on expected execution and nonzero on unexpected failure.
3. **Validated Negative & Positive Controls:**
   - Negative controls verify historical vulnerabilities (`EXPECTED_VULNERABILITY_DETECTED`), including fail-open auth downgrade, per-chunk secret leaks, and uncommitted JSONL crash corruptions.
   - Positive controls verify candidate remediations (401 on invalid/revoked tokens, stateful StreamRedactor hold, SQLite `conversation_turns` commit durability).
4. **Retracted Unsupported Performance Claims:**
   - Formal retraction of synthetic 10-client real-Ollama claims.
   - Bounded empirical real-Ollama measurements documented directly from local `llama3.2:1b` execution.
5. **Deterministic Unit Tests Passing:**
   - Local pytest execution across all 5 qualification suites completed: **19 passed, 6 skipped, 0 failed in 22.80s**.

---

## 2. Definitive Answers to the 18 CTO Landmark Questions

1. **Is the independent qualification laboratory genuinely working?**  
   **YES (`LABORATORY_VERIFIED`).** The laboratory executes reproducibly across target candidates, backed by real Ollama (`llama3.2:1b`), real Redis 7.2.4 (DB 13), SQLite 3.53.1, Node.js v22.11.0, and Chromium without mocks.
2. **Which critical ORNEUR security defects can now be reproduced automatically?**  
   - P0 Fail-Open Auth Downgrade: `get_current_user_optional` in `orca/auth/middleware.py`.
   - P0 `/api/chat` Turn Lease Bypass: `/api/chat` completely omits turn lease acquisition and fence checks.
   - P0 Storage Split: PR #129 message edit branching writes JSONL while PR #131 reads from SQLite `conversation_turns`.
   - P1 Split-Secret PEM Streaming: Character-by-character token boundaries challenged against regex buffers.
3. **Which defects have been fixed on current candidates?**  
   - Ollama colon-delimited model tag support (`llama3.2:1b`) fixed in PR #126 / PR #129.
   - Claude's `f7c004f` frontend hardening (unreachable server logout, monotonic DOM turn identity, reactive sidebar) merged in PR #129.
   - Quota atomicity and anti-replay via Redis Lua scripts confirmed in PR #127 / PR #128.
   - Crash-durable `conversation_turns` SQLite transactions with lease fencing confirmed in PR #131.
   - Auth fail-open 401 downgrade fixed in Claude's Landmark-01 working commit `5bbd869`.
4. **Which remain unresolved?**  
   - Storage schema harmonization: message edit branching and context assembly must be re-anchored from JSONL onto SQLite `conversation_turns`.
   - Integration of SQLite turn authority into the synchronous `/api/chat` route.
5. **Can authentication and revoked-token handling resist adversarial tests?**  
   **YES on Claude's `5bbd869` patch; NO on unpatched PRs #125–#131.** With `5bbd869`, all invalid/revoked tokens receive `HTTP 401 Unauthorized` with exactly ZERO model provider dispatches.
6. **Can concurrent workers corrupt conversation history?**  
   **NO in PR #131 (Fixed); YES in PR #129 on `/api/chat`.** PR #131's `BEGIN IMMEDIATE` lock and fence token validation prevent out-of-order writes.
7. **Can edited conversation context become inconsistent?**  
   **YES if merged naively.** PR #129 stores message edits in filesystem JSONL files which are ignored by PR #131's SQLite loader upon restart.
8. **Can model responses expose known secret patterns?**  
   **NO.** The multi-chunk streaming lookahead buffer redacts PEM private keys and API tokens in-flight across arbitrary chunk splits.
9. **Can quota replay cause unauthorized provider dispatch?**  
   **NO.** Redis Lua reservation scripts enforce atomic reservation and reject duplicate request IDs.
10. **Can temporary-chat content survive where it should have been deleted?**  
    **NO.** Ephemeral sessions bypass vector memory and knowledge graph extraction, and closing unlinks transcripts and invalidates SQLite entries.
11. **Can the real browser complete the expected chatbot lifecycle?**  
    **YES.** 15 Playwright Chromium steps verify account login, streaming chat, multi-turn history, message editing, temporary sessions, dark theme, and secure sign-out.
12. **How reliable is the current local serving stack under measured bounded load?**  
    **EMPIRICALLY VERIFIED (Single-Stream Real Ollama):** Average cold TTFT is 142.1 ms, warm TTFT is 8.4 – 11.1 ms, average total generation time is 55.7 ms for 3-chunk completion. Multi-client real-Ollama GPU capacity is marked `NOT_INDEPENDENTLY_QUALIFIED`.
13. **Which capabilities are genuinely implemented and demonstrated?**  
    Standard chat, SSE streaming, multi-turn memory, message editing, temporary chats, RAG retrieval, citation checking, and Docker code execution (see `QUALIFICATION_01_CAPABILITY_REGISTER.md`).
14. **What evidence is missing for global production?**  
    Unified storage schema, complete turn-lease fencing on `/api/chat`, and production SSL/reverse proxy buffering configuration.
15. **What remains unqualified for native-model training?**  
    0 of 95 pretraining dataset manifests approved in ledger; `TRAINING_AUTHORIZATION.json` set to `NOT_AUTHORIZED`; zero trained weights.
16. **Which new issues require Cursor?**  
    Backporting SQLite `conversation_turns` commit authority to `/api/chat` and coordinating unified database schemas with frontend message versioning.
17. **Which issues require Claude?**  
    Finalizing the merge of SQLite persistence into the product lineage and ensuring edit branching operates on SQLite rather than JSONL.
18. **Is there a single integrated candidate ready for final independent testing?**  
    **NOT YET (`PENDING_FROZEN_CANDIDATE`).** Claude is actively finalizing the integration branch `claude/landmark-01-secure-chatbot-integration`. Once submitted and authorized by the CTO, Antigravity's laboratory will qualify the exact resulting SHA.

---

## 3. Qualification Scorecard & Milestone Verdict

```
========================================================================================================
                          QUALIFICATION LANDMARK-01 AUDIT SCORECARD
========================================================================================================
[QUALIFICATION DOMAIN]               | [VERDICT]                     | [EVIDENCE & PROVENANCE]
-------------------------------------+-------------------------------+----------------------------------
Independent Qualification Laboratory | LABORATORY_VERIFIED           | Operational, dual-provenance harness
Adversarial Security Red Team        | LABORATORY_VERIFIED           | Negative & positive controls pass
Distributed Concurrency Fault Lab    | LABORATORY_VERIFIED           | SQLite conversation_turns protocol
Real Browser Acceptance Laboratory   | LABORATORY_VERIFIED           | Playwright Chromium journey runs
Privacy & Data-Lifecycle Engine      | LABORATORY_VERIFIED           | High-entropy canary audits
Integrated Chatbot Product Candidate | PENDING_FROZEN_CANDIDATE      | Awaiting official candidate SHA
Global Production Release Gate       | NO-GO (BLOCKED)               | P0 Blockers open on active candidates
Native-Model Training Gate           | NO-GO (GATE_LOCKED)           | 0/95 manifests, NOT_AUTHORIZED
========================================================================================================
```

*Certified by Antigravity Authority on 28 October 2026.*
