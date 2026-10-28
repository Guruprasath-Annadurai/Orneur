# ORNEUR — QUALIFICATION LANDMARK-01
## MASTER TEST INVENTORY AND COVERAGE MAP

**Authority:** Antigravity — Independent Security, Reliability, Product Qualification and Adversarial Testing Authority  
**Authorizing CTO:** Mike (GPT-6)  
**Date:** 28 October 2026  
**Document Status:** MASTER INVENTORY  

---

### 1. Independent Qualification Tooling Inventory

The following test suites and orchestration scripts were developed specifically for the Antigravity Independent Qualification Laboratory:

| Test Identifier | Category | Target File Path | Purpose & Assertions |
|---|---|---|---|
| **QUAL-AUTH-01** | Red Team | `tests/qualification/test_auth_adversarial.py` | Validates absent vs garbage vs expired vs revoked JWT tokens; proves 401 response and ZERO model dispatches. |
| **QUAL-AUTH-02** | Red Team | `tests/qualification/test_auth_adversarial.py` | Exercises `/api/auth/logout-all` cross-device session invalidation. |
| **QUAL-AUTH-03** | Red Team | `tests/qualification/test_auth_adversarial.py` | Probes cross-user session isolation and rejection of non-session token types (reset, verify). |
| **QUAL-INF-01** | Red Team | `tests/qualification/test_inference_adversarial.py` | Simulates character-by-character split PEM keys across SSE streaming chunk boundaries. |
| **QUAL-INF-02** | Red Team | `tests/qualification/test_inference_adversarial.py` | Verifies redaction of high-entropy OpenAI, GitHub, and Anthropic API keys. |
| **QUAL-INF-03** | Red Team | `tests/qualification/test_inference_adversarial.py` | Asserts duplicate request ID replay prevention and atomic quota reservation. |
| **QUAL-STOR-01** | Concurrency | `tests/qualification/test_storage_concurrency.py` | Confirms SQLite canonical schema is `conversation_turns` with fence tokens. |
| **QUAL-STOR-02** | Fault Lab | `tests/qualification/test_storage_concurrency.py` | Challenges mutual exclusion during concurrent turn commits and rejects stale workers. |
| **QUAL-STOR-03** | Fault Lab | `tests/qualification/test_storage_concurrency.py` | Simulates worker crash mid-transaction; confirms automatic rollback and zero corrupt state. |
| **QUAL-PRIV-01** | Privacy | `tests/qualification/test_privacy_lifecycle.py` | Injects high-entropy canary into temporary chat; verifies vector memory and KG bypass. |
| **QUAL-PRIV-02** | Lifecycle | `tests/qualification/test_privacy_lifecycle.py` | Verifies immediate unlinking and 404 response upon temporary chat close. |
| **QUAL-REL-01** | Reliability | `tests/qualification/test_reliability_load.py` | Measures TTFT, total turnaround latency, worker memory footprint, and error rate under bounded concurrency. |
| **QUAL-HARN-01** | Automation | `scripts/qualification/lab_launcher.py` | Manages isolated test servers, dedicated Redis DB 13, model recording taps, and clean teardown. |
| **QUAL-HARN-02** | Evidence | `scripts/qualification/run_qualification_suite.py` | Executes the qualification battery, measures telemetry, and emits `QUALIFICATION_01_EVIDENCE_MANIFEST.json`. |

---

### 2. Reused Engineering & Journey Tests

To prevent unnecessary duplication, Antigravity integrates and reuses validated engineering suites:

| Suite Identifier | Source Origin | Reused Test File Path | Covered Capabilities |
|---|---|---|---|
| **JOURNEY-BROWSER** | Claude Reference | `tests/journey/test_journey_browser.py` | 15 Playwright Chromium steps: login, streaming, multi-turn, editing, temp chat, dark mode, signout. |
| **JOURNEY-API** | Claude Reference | `tests/journey/test_journey_api.py` | Live API journey matching browser steps with model tap inspection. |
| **TENANT-ISOLATION** | Cursor Reference | `tests/test_g006_tenant_isolation.py` | Two-user isolation fixtures and cross-tenant session boundary tests. |
| **TRANSCRIPT-COMMIT** | Cursor (PR #131) | `tests/unit/serve/test_p0_transcript_commit.py` | SQLite `conversation_turns` commit durability and fence token validation. |
| **STREAM-DLP** | Cursor (PR #127) | `tests/test_p0_stream_dlp_closure.py` | Streaming boundary DLP regex token tests. |
| **OLLAMA-TAP** | Engineering Tool | `tests/journey/ollama_tap.py` | Non-intrusive reverse proxy intercepting outbound model JSON payloads. |
