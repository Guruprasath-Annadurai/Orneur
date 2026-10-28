# ORNEUR — QUALIFICATION LANDMARK-01
## MASTER TEST INVENTORY AND COVERAGE MAP (Corrected)

**Authority:** Antigravity — Independent Security, Reliability, Product Qualification and Adversarial Testing Authority  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 28 October 2026 (Corrected Revision)  
**Document Status:** MASTER INVENTORY  

---

### 1. Independent Qualification Tooling Inventory

The following test suites and orchestration scripts were developed and repaired for the Antigravity Independent Qualification Laboratory:

| Test Identifier | Category | Test Target Function | Control Type | Purpose & Assertions |
|---|---|---|---|---|
| **QUAL-AUTH-NEG** | Auth Red Team | `test_negative_control_historical_swallowing_of_401` | **Negative** | Detects historical fail-open swallowing of 401 in `get_current_user_optional`. |
| **QUAL-AUTH-POS** | Auth Red Team | `test_garbage_bearer_token_handling` | **Positive** | Asserts 401 Unauthorized and ZERO model dispatches on remediated trees. |
| **QUAL-AUTH-EXP** | Auth Red Team | `test_expired_bearer_token_handling` | **Positive** | Asserts 401 Unauthorized on expired JWT credentials. |
| **QUAL-AUTH-REV** | Auth Red Team | `test_revoked_token_after_logout_handling` | **Positive** | Asserts 401 Unauthorized on tokens revoked via `/api/auth/logout`. |
| **QUAL-AUTH-LALL**| Auth Red Team | `test_logout_all_revokes_device_tokens` | **Positive** | Asserts all user device sessions revoked after `/api/auth/logout-all`. |
| **QUAL-AUTH-ISOL**| Auth Red Team | `test_cross_user_session_access_isolation` | **Positive** | Asserts User B cannot read User A's private session title or data. |
| **QUAL-DLP-NEG**  | DLP Red Team  | `test_negative_control_stateless_chunk_scan_leaks_split_secrets` | **Negative** | Demonstrates per-chunk `scan_output` leaks secrets split across deltas. |
| **QUAL-DLP-POS**  | DLP Red Team  | `test_positive_control_stateful_stream_redactor_prevents_leakage` | **Positive** | Verifies stateful `StreamRedactor` holds incomplete prefixes and redacts. |
| **QUAL-DLP-PEM**  | DLP Red Team  | `test_pem_private_key_character_by_character_stateful_streaming` | **Positive** | Verifies character-by-character PEM key streaming redaction. |
| **QUAL-DLP-PATT** | DLP Red Team  | `test_known_secret_patterns_redacted_on_full_payloads` | **Positive** | Validates regex redaction across OpenAI, Anthropic, AWS, GitHub, Bearer. |
| **QUAL-REPLAY**   | Quota / Replay| `test_identical_request_id_cannot_replay_quota_spending` | **Positive** | Validates duplicate `request_id` detection and anti-double-spend. |
| **QUAL-STOR-NEG** | Storage Fault | `test_negative_control_legacy_jsonl_append_lacks_transactional_rollback`| **Negative** | Demonstrates uncommitted JSONL files lack transaction rollback on crash. |
| **QUAL-STOR-POS** | Storage Durab | `test_positive_control_sqlite_conversation_turns_schema` | **Positive** | Verifies canonical `conversation_turns` table in SQLite (PR #131+). |
| **QUAL-STOR-STALE**| Storage Fencing| `test_stale_worker_rejected_by_authority_check` | **Positive** | Verifies `commit_turn` rejects stale worker with `reason="stale_worker"`. |
| **QUAL-STOR-MONO** | Storage Durab | `test_valid_worker_commits_turn_monotonically` | **Positive** | Verifies monotonic revision increment in SQLite `conversation_turns`. |
| **QUAL-STOR-WAL**  | Storage Fault | `test_sqlite_crash_mid_transaction_rollback_durability` | **Positive** | Verifies SQLite WAL `BEGIN IMMEDIATE` transaction rollback durability. |
| **QUAL-PRIV-STD** | Privacy Base  | `test_standard_session_persists_transcript_baseline` | **Baseline** | Verifies standard sessions preserve chat history. |
| **QUAL-PRIV-TEMP**| Privacy Ephem | `test_temporary_chat_lifecycle_and_canary_purge` | **Positive** | Verifies `POST /api/sessions/temporary` skips ingestion & unlinks on close. |
| **QUAL-REL-FUNC** | Reliability   | `test_deterministic_fake_provider_functional` | **Functional**| Verifies baseline serving path via in-process ASGI TestClient. |
| **QUAL-REL-CONC** | Reliability   | `test_concurrent_client_load_fake_provider` | **Concurrency** | Verifies 4 concurrent client threads complete without drops or errors. |
| **QUAL-REL-OLL**  | Reliability   | `test_live_ollama_real_latency_and_ttft` | **Live Ollama** | Empirical TTFT & turnaround benchmark on real `llama3.2:1b`. |

---

### 2. Orchestration & Harness Tooling

- `scripts/qualification/run_qualification_suite.py`: Dual-provenance test orchestrator with strict candidate PYTHONPATH isolation.
- `scripts/qualification/measure_real_ollama.py`: Standalone empirical latency benchmark capturing raw sample timings.
