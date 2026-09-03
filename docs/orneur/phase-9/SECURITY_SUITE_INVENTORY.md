# Phase 9.1 — Security Suite Inventory

The Phase 9 closure report's "107 tests / 12 files" figure covered only
files literally matching `test_*security*.py`. That undercounted the
platform's real security-relevant test surface — files like
`test_web_ssrf_guard.py`, `test_mcp_fs_server_sandbox.py`,
`test_auth_store.py`, `test_stripe_hook.py`, and `test_agent_delegation.py`
carry no "security" substring in their filename but test genuinely
security-relevant behavior (SSRF, path traversal, auth/tenancy, webhook
signature verification, capability/budget non-escalation). This document
is the corrected, full inventory.

## Method

Every file under `tests/test_*.py` (160 total, excluding `conftest.py`
and `ollama_test_support.py`) was read (docstring + content) and
classified by what it actually protects against, not by filename
pattern alone.

## Classification counts

| Classification | Files | Meaning |
|---|---|---|
| CORE_SECURITY | 26 | Auth, tenancy, sandboxing (fs/shell/MCP), SSRF, DLP, PII, moderation/jailbreak/red-team, path-traversal (registry IDs), webhook signature verification, backup/restore safety, budget invariants, deletion. |
| GATEWAY_SECURITY | 3 | Failure-injection resilience, circuit breaker, test-isolation-from-real-`~/.orca` regression. |
| TRUTH_SECURITY | 3 | Fetch-time injection/safety scanning, robots.txt enforcement. |
| MEMORY_SECURITY | 6 | Memory Firewall, scope/authority enforcement, deletion cascade, agent memory scoping. |
| DELIBERATION_SECURITY | 1 | Deliberation Fabric adversarial/authority tests. |
| MODEL_SOCIETY_SECURITY | 3 | Model Society authority + budget-ledger integrity. |
| AGENT_SECURITY | 8 | Agent Runtime capability/policy/secret-leak/cancellation/delegation non-escalation. |
| CONNECTOR_SECURITY | 11 | Phase 9 connector fabric (tenant isolation, redaction, approval, exfiltration, etc). |
| LIVE_SECURITY | 1 | `test_agent_planner_live.py` (`@pytest.mark.live_ollama_smoke`) — live-model planner schema-validation regression. |
| **Total security-relevant** | **62** | |
| NON_SECURITY | 98 | Routing, registry mechanics, eval judges, training-data pipelines, API passthrough, gateway deployment/scheduling mechanics, cognitive-quality tests, etc. |

Full per-file classification: `docs/orneur/phase-9/security_suite_files.txt`
(the exact 62-file list, one path per line — this file IS the
authoritative test selection, not a marker or keyword filter).

## Why this list, not `-m security` or `test_*security*.py`

No `security` pytest marker exists in this codebase
(`pyproject.toml`'s `markers` list has no such entry), and the filename
convention `test_*security*.py` is inconsistently applied — many of the
most safety-critical tests in the repo (SSRF guard, filesystem/shell
sandboxing, webhook signature verification, budget invariants, auth
store) never adopted that naming convention. A curated, reviewed file
list is more honest than either shortcut and is checked in
(`security_suite_files.txt`) so it stays a single source of truth rather
than a re-derived guess each time.
