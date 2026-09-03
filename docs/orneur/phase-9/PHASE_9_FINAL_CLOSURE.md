# Phase 9.1 — Enterprise Connector Final Qualification — Closure

**Repository**: orca | **Branch**: session-update-2026-08-25
**Starting SHA (9.1)**: 3b5107f | **Ending SHA**: c03e927 (+ this doc's commit)

## What Phase 9's original closure got wrong

The Phase 9 report's "SECURITY: 107 passed / 0 failed (12 files)" figure
undercounted the platform's real security-relevant test surface by
relying on filename pattern (`test_*security*.py`) instead of content
review. Phase 9.1 reviewed all 160 test files by content and produced a
64-file authoritative inventory (`SECURITY_SUITE_INVENTORY.md`,
`security_suite_files.txt`) — 522 tests, 0 failures, deterministic
portion; +1 passed live-Ollama test.

## Full results (fresh runs, this qualification pass)

| Suite | Result |
|---|---|
| Full application suite (`pytest -m "not live_ollama_smoke"`) | 1180 passed, 0 failed, 40 deselected |
| Authoritative security suite, deterministic (`scripts/run_security_suite.sh`) | 522 passed, 0 failed, 1 deselected |
| Authoritative security suite, live portion (`scripts/run_security_suite.sh --live`) | 1 passed, 0 failed |
| Live/integration suite (`pytest -m live_ollama_smoke`, all 8 files) | 40 passed, 0 failed |
| Connector eval harness | 24/24 (100%) |
| Connector test count | 83 tests across 13 files |

## New real findings and fixes this pass

`ConnectorHealth.retry_after_s` existed as a typed field since Phase 9
but was never set or consulted anywhere — a RATE_LIMITED connector had
no path back to routable except a manually-recorded success. Fixed:
`record_failure(..., retry_after_s=...)` records it, and `is_routable()`
now honors it (unroutable until the provider's own cooldown genuinely
elapses; permanently unroutable if no cooldown was ever supplied, rather
than guessed). This closes Phase 9.1 spec §19's "Retry-After honored"
requirement, which Phase 9 had not implemented.

## Disclosed, unresolved limitations (not gaps that block THIS qualification)

1. No cross-subagent shared token-bucket/collective-quota limiter exists
   per connector instance — health-state gating (a coarser, shared,
   per-instance primitive) bounds runaway retries but does not enforce a
   fine-grained concurrent-call cap. See CONNECTOR_AUTHORITY_AUDIT.md §9.
2. `ConnectorInstance` has no `workspace_id`/per-principal scoping field,
   so `authorized_connector_tool_specs()` narrows by tenant + health
   only, not by workspace/project/principal. Execution still
   independently reauthorizes regardless. See CONNECTOR_AUTHORITY_AUDIT.md §11.
3. Only DOCUMENT_STORE has a REAL_ADAPTER; all other connector families
   remain CONTRACT_ONLY, exercised only via FAKE_TEST_PROVIDER — carried
   over from Phase 9, unchanged, and correctly not "closed" by fabricating
   OAuth flows or SaaS clients (explicitly out of scope per spec §29).

None of these three represent a live exploit path found and left
unfixed — they are documented incompleteness in defense-in-depth breadth
(rate-limit fairness across concurrent callers, visibility pre-filter
granularity, and provider breadth), with the actual authorization
boundary (tenant + capability + policy, checked twice) intact and
independently verified in every case.

## Final audit counters

| Counter | Value |
|---|---|
| CROSS_TENANT_CONNECTOR_READ | 0 |
| CROSS_TENANT_CONNECTOR_WRITE | 0 |
| CONNECTOR_SCOPE_BYPASS | 0 |
| CONNECTOR_POLICY_BYPASS | 0 |
| CONNECTOR_CAPABILITY_BYPASS | 0 |
| AGENT_DIRECT_CONNECTOR_BYPASS | 0 |
| CREDENTIAL_EXPOSURE | 0 |
| APPROVAL_REPLAY_BYPASS | 0 |
| CROSS_CONNECTOR_EXFILTRATION_BYPASS | 0 |
| CONNECTOR_CACHE_SCOPE_LEAK | 0 |
| VECTOR_SCOPE_LEAK | 0 |
| UNVERIFIED_CONNECTOR_FACT_PROMOTION | 0 |
| UNACCOUNTED_CONNECTOR_READ | 0 |
| UNACCOUNTED_CONNECTOR_WRITE | 0 |
| DOUBLE_COUNTED_CONNECTOR_OPERATION | 0 |
| RAW_CHAIN_OF_THOUGHT_STORAGE | 0 |

**READY TO ADVANCE TO PHASE 10: YES**
