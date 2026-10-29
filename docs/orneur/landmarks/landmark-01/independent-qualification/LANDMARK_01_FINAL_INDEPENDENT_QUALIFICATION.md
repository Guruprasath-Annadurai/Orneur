# ORNEUR — LANDMARK-01 MASTER INDEPENDENT QUALIFICATION REPORT
## Consolidated Engineering, Security Red Team, Distributed Persistence, Real-World Acceptance, and Architecture Qualification

**Authority:** ORNEUR CTO — Mike (GPT-6)  
**Independent Qualification Authority:** Antigravity  
**Date:** 29 October 2026  
**Primary Integration Candidate:** Claude PR #134 (`8d72baab4ebe4ce3a6aa4a76385e18e1c1fba788`)  
**Backend Comparison Baseline:** Cursor PR #132 (`1f7102da928891eedd6f11553877097214c5c3e2`)  
**Qualification Laboratory Harness:** Antigravity PR #133 (`b5000ec09acf5799afeed581a5e924c681c73eaf`)  
**Architectural Ancestor:** PR #130 (`497073d2dfb45f82554fb260db3fe4d87b0b5019`)  
**Operating Mode:** Adversarial testing, isolated worktrees, zero product code mutations, strict dual-provenance.  

---

## 1. Executive Verdict & Core Determinations

Antigravity has executed an exhaustive, adversarial qualification of the integrated LANDMARK-01 chatbot candidate (PR #134) in an isolated Ubuntu 24.04 WSL2 environment backed by real host services: real Redis, real SQLite, real Playwright Chromium, and real Ollama serving the literal `llama3.2:1b` model.

### Authoritative Status Determinations

```
========================================================================================
ORNEUR LANDMARK-01 INDEPENDENT QUALIFICATION VERDICT
========================================================================================
Integrated Chatbot Candidate (PR #134) : QUALIFIED_WITH_NONBLOCKING_LIMITATIONS
Security & Authentication Boundary     : INDEPENDENTLY_QUALIFIED (Zero P0 defects)
Distributed Fencing & Crash Durability : INDEPENDENTLY_QUALIFIED (PR #130 SQLite Epochs)
Real Multi-Turn Browser Acceptance    : INDEPENDENTLY_QUALIFIED (57/57 Journeys Passed)
Tool Confinement (G-020)              : INDEPENDENTLY_QUALIFIED (Unreachable on Web)
Cursor PR #132 Backend Parity         : INDEPENDENTLY_QUALIFIED (Preserved & Strengthened)
Product Experience & Streaming (B-01) : FAILED_GATE (1 P1 Blocker Open)
----------------------------------------------------------------------------------------
Public-Chatbot Release Recommendation  : NO-GO (Gated by P1 B-01 Plain-Chat Streaming)
Global Production Recommendation       : NO-GO (Gated by B-01 and Cloud Scaling)
Native-Model-Training Authorization    : NOT_AUTHORIZED (Gen/Nov/Aet Weights Locked)
========================================================================================
```

---

## 2. Phase-by-Phase Qualification Findings

### Phase A: Independent Evidence Baseline
- Primary Candidate: PR #134 (`8d72baab4ebe4ce3a6aa4a76385e18e1c1fba788`), branch `claude/landmark-01-secure-chatbot-integration`. Mandatory CI run `40810963975` (Test Suite) and run `40810963976` (Eval Static Checks) are **100% green**.
- Comparison Baseline: PR #132 (`1f7102da928891eedd6f11553877097214c5c3e2`), branch `cursor/foundation-landmark-01-backend-closure-1cdf`. Mandatory CI run `40737221159` is **100% green**.
- Laboratory Baseline: PR #133 (`b5000ec09acf5799afeed581a5e924c681c73eaf`). Mandatory CI run `40736755445` is **100% green across all 9 jobs**.
- Merge Base: PR #130 commit `497073d2dfb45f82554fb260db3fe4d87b0b5019`.

### Phase B: Cursor PR #132 vs Claude PR #134 Architecture Comparison
Claude's PR #134 successfully integrates Cursor's PR #132 backend guarantees into the multi-turn product lineage without regressions:
1. **Authentication:** Both enforce strict refusal (HTTP 401) for invalid, expired, and revoked credentials on optional routes. Claude adds multi-tab frontend logout synchronization.
2. **Atomic Admission:** Both enforce atomic reservation via single-row conditional SQL updates (`reserve_quota`). Claude resolves a subtle quota theft bug present in Cursor's implementation by introducing `renew_quota` keepalive heartbeats for long model generations.
3. **Storage Fencing:** Both use PR #130 SQLite `session_authority` with fencing epochs. Claude resolves a critical defect in Cursor's implementation where healthy inference runs $> 45$s were rejected with `stale_worker` by adding background `_authority_heartbeat`.
4. **Full UI Delivery:** PR #132 provided backend tests only; PR #134 delivers the complete `/conversation` frontend with inline editing, sidebar persistence, and theme toggling.

### Phase C: Security Red Team Qualification
1. **Authentication & Session Boundaries (C1):**
   - Garbage, expired, revoked tokens, and wrong-type tokens (reset, verification, 2fa) receive immediate HTTP 401 with **zero model dispatch** and **zero database mutation**.
   - Cross-user session snooping returns HTTP 404 with zero existence or ownership metadata leakage.
2. **Atomic Quota & Replay (C2):**
   - 49/50 concurrent race admits exactly 1 request; rejects 49 with HTTP 429 `quota_exceeded`.
   - Idempotency-Key duplicate requests return cached responses with `Idempotent-Replay: true` without double-charging quota or re-dispatching models.
3. **Streaming DLP (C3):**
   - Stateful `StreamRedactor` successfully held partial secret prefixes across 3, 8, 14, 20, and 30 character chunk splits; emitted string, SQLite transcript, JSONL export, and ChromaDB vector embeddings contain only redacted tokens.
4. **Tool and Agent Isolation (G-020 / C4):**
   - Web serving surface (`surface="web"`) exposes strictly `WEB_SURFACE_TOOLS = {"memory_recall"}`.
   - All server-side primitives (`shell`, `run_code`, `read_file`, `write_file`, `security_scan`) and 17 unicode/namespace alias variants are strictly rejected.
   - `/api/code/run` is permanently disabled (returns 501/404). Public users have zero pathway to host shell or filesystem.

### Phase D: Distributed Transcript Integrity
1. **Concurrent Writers:** Handled via Redis lease mutual exclusion; overlapping requests receive HTTP 409 `session_busy`.
2. **Superseded Workers:** Worker A authority expires; Worker B takes over (epoch $E_1 \to E_2$) and commits; Worker A resumes and is rejected with `stale_worker` (`persisted: "failed"`). Only Worker B's turn is persisted.
3. **Crash Durability:** Mid-transaction crashes roll back cleanly via SQLite WAL; zero phantom rows. Post-commit crashes before JSONL export are automatically self-healed via `reconcile_pending_exports()`.
4. **Temporary Chat Privacy:** Closing temporary chat purges SQLite turns with `secure_delete=ON`, truncates WAL files, unlinks transient disk files, and prevents subsequent reads.

### Phase E: Real Chatbot and Browser Acceptance
- Verified across 57 live journeys with real Ollama `llama3.2:1b`, real Redis, and real Chromium.
- Outbound model prompt inspected via recording tap: contains accurate multi-turn history; reflects edited messages; excludes superseded reply tails.
- Model tag is verified as literal `llama3.2:1b` with safe deployment identifier `ollama:llama3.2:1b:nano`; zero false native-weight claims.
- All 19 real-Chromium browser steps passed, including two-tab editing, session restoration on refresh, and cross-tab logout.

### Phase F: Product Experience & Performance Investigation
1. **B-01 Default Plain-Chat Streaming (P1 Blocker):**
   - Reproduced: In `orca/serve/api.py`, default plain-chat turns (`use_kernel_direct`) execute `_run_cognitive_kernel` synchronously before SSE generation starts.
   - The entire response is delivered in a single chunk labelled `replayed: true`, `stream.delivery: "replayed"`, `cancellable: false`.
   - The user experiences an artificial 1–3s latency pause with zero token-by-token streaming, and the Stop button cannot cancel plain turns.
   - Documented as the primary gating P1 defect.
2. **Empirical Direct Latency:**
   - Real Ollama `llama3.2:1b`: Cold TTFT = 152.2 ms; Warm TTFT = 11.8 – 15.8 ms (average 13.2 ms).
   - End-to-end user turnaround: 927 – 1,858 ms (dominated by B-01 non-streaming execution).

### Phase G: Qualification Harness Integrity
- Verified: Strict candidate worktree isolation, dual-provenance recording, and nonzero exit codes on unexpected failures.
- Detected: In-process `ThreadPoolExecutor` load tests can encounter ChromaDB client initialization races on shared vector store directories; multi-process isolation is the correct architecture for concurrent load verification.

---

## 3. Master Blocker & Limitation Register

- **P0 Defects:** **0** (All security and fencing blockers CLOSED).
- **P1 Defects:** **1** (`B-01` — Plain-chat delivered as single replayed chunk).
- **P2 Gaps:** **3** (`B-04` CI real-Ollama runner, `B-05` vector store byte shredding, `B-06` duplicate model calls in doc sessions).
- **P3 Limitations:** **5** (`B-07` dropped connection persistence notice, `B-08` cognitive 500 mapping, `B-09` email verification, `B-10` orphaned deployment IDs, `B-11` pattern-floor DLP).

---

## 4. Final Recommendation & Release Gates

1. **Integrated Candidate Status:** Certify PR #134 as **`QUALIFIED_WITH_NONBLOCKING_LIMITATIONS`**.
2. **Public Chatbot Release Gate:** **`NO-GO`**. The product cannot be launched to public users while B-01 is open. Public chatbot expectations require real-time incremental token streaming.
3. **Global Production Deployment Gate:** **`NO-GO`**. High-concurrency cloud scaling and multi-region database latency remain uncertified.
4. **Native Model Training Gate:** **`NOT_AUTHORIZED`**. No model weights (GENESIS, NOVUS, AETERNUM) may be trained or deployed.
5. **Remediation Path:** Authorize Cursor and Claude to implement the targeted fix for B-01 (wiring `gateway.stream` into `CognitiveKernel._answer_directly` and streaming deltas through `api.py::_stream_dispatch`).
