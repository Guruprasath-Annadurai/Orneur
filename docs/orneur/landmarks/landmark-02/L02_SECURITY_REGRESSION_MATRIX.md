# LANDMARK-02 — security regression matrix

Classes: `DET` deterministic in-process · `LIVE+FIX` real processes + fixture provider · `LIVE+REAL` real Ollama · `BROWSER` real Chromium · `BASE-RED` fails on baseline `9cb864c`. Everything is engineering-owned; none is independent qualification.

| Area | Invariant | Proof | Class |
|---|---|---|---|
| Deletion | `200` only when every store confirmed; otherwise `202` with per-store status; access revoked immediately; ownership kept until complete | `test_l02_deletion_lifecycle.py`; `test_l02_deletion_live.py` D1–D6 (Redis down, two workers, in-flight generation, restart mid-cleanup, vector failure, real embeddings) | DET, LIVE+FIX, LIVE+REAL, BASE-RED |
| Deletion | temporary chat closure uses the same workflow; closed → 409 (not 404) | `test_temporary_chat_*`, `test_b_conversations.py` | DET |
| Documents | registry-enforced retrieval; deleted/`deleting` docs never retrieved; chunk identity by doc_id | `test_l02_doc_store_deletion.py`, `test_l02_document_rag.py` | DET, BASE-RED |
| Prompt injection | passages never reach scorer/judge unquoted; nonce-quoted untrusted blocks; strict parsers (unparsed = "not judged"); injection screen; lexical abstention floor | `test_l02_judge_trust_boundary.py` (70) | DET, BASE-RED (`l02_02e_baseline_judge_injection_9cb864c.txt`) |
| Tool authority | model-produced tool calls independently authorised: schema/range, provenance (copy-from-untrusted window, user-term overlap), call budget; document text cannot grant authority | `test_l02_tool_authority.py` (12) | DET |
| Uploads | bounded isolated PDF/DOCX extraction (subprocess, rlimits, timeout, killpg); zip pre-checks (entries ≤2000, ≤200 MB, ratio ≤200); external references not followed; safe filenames incl. bidi; per-session (20) / per-user (200 docs, 1 GiB) quotas; sha256 dedupe; atomic limits under concurrency | `test_l02_upload_security.py` (22), `test_l02_upload_parsers_live.py` (real parsers; flate bomb, malformed PDFs, external ref) | DET, LIVE |
| Embeddings | stored dimension vs service checked; mixed spaces refused | `test_l02_embedding_consistency.py` | DET |
| Outcome truth | one durable record per key, same transaction as commit; stale worker cannot commit; outcome_unknown only when unreadable | `test_l02_turn_recovery.py` (21), `test_l02_recovery_live.py` R1–R8 | DET, LIVE+FIX |
| Account | single-use tokens (cross-worker), no enumeration, lockout, constant-time login, no real mail | `test_l02_account_security.py` (22), `test_l02_account_live.py` | DET, LIVE+FIX |
| Resource safety | protected resources never touched; observe-twice; bounded | `test_l02_resource_reconciliation.py` (16) | DET, BASE-RED |
| Operations | drain, admission, deadline, readiness, backup integrity | `test_l02_operational.py` (13), `test_l02_operations_live.py` | DET, LIVE+FIX |
| Truth | no native-model claim, executed-tools only | `test_l02_model_truth.py` (16) | DET |
| Tenant isolation | cross-user access 404, deletion revokes only owner | `test_g006_tenant_isolation.py` (41, one assertion updated – reason recorded) | DET |
| DLP / quota / SQLite / auth (B-01) | unchanged contracts | B-01 suites re-run on the final head (`L02_EXACT_HEAD_CI.md`) | DET, LIVE |
| Secrets | no tokens/credentials in evidence or logs; audit records tool name + reason code only | review of `evidence/` + judge/tool tests | DET |

## Existing assertions changed (reasons)
`test_b_conversations.py` (deleted conversation → 404 and verified-empty store; stronger), `test_temporary_chat_multiprocess.py`, `test_g006_tenant_isolation.py::test_07b`, `test_conversation_context.py` and `test_context_window_bounds.py` (ignore the new constant serving-facts system message), `test_kernel_streaming.py` (same reason), `test_s2_customer_correctness.py::test_rate_limiting_returns_rate_limited` (distinct accounts so the per-IP limiter, not the new per-account lockout, is exercised), `tests/frontend/test_b01_stop_upstream.mjs` harness (`_activeRequestKey: null`). No assertion was weakened to pass.
