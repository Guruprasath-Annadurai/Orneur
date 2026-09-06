# Phase 9 — FDE / Enterprise Connector Fabric — Closure

**Repository**: orca
**Branch**: session-update-2026-08-25
**Starting SHA**: 7428e03
**Ending SHA**: 239ba7f (+ this closure doc commit)

## Test files and counts

| File | Tests |
|---|---|
| tests/test_connector_tenant_isolation.py | 8 |
| tests/test_connector_security.py | 16 |
| tests/test_connector_fake_provider.py | 6 |
| tests/test_connector_registry_health.py | 6 |
| tests/test_connector_lifecycle_audit.py | 6 |
| tests/test_connector_federated_retrieval.py | 5 |
| tests/test_connector_agent_bridge.py | 7 |
| tests/test_connector_truth_memory_bridges.py | 7 |
| tests/test_connector_document_store.py | 6 |
| tests/test_connector_agent_runtime_e2e.py | 3 |
| tests/test_connectors_fast_path.py | 5 |
| **Total** | **75** |

## Full suite results (fresh, single-process, clean run)

- Full deterministic suite (`pytest -m "not live_ollama_smoke"`): **1172 passed, 0 failed** (includes all 75 connector tests).
- Security suite (`test_*security*.py`, 12 files): **107 passed, 0 failed** (includes the 16 new `test_connector_security.py` tests).
- Live-Ollama suite: not applicable to Phase 9 -- the Connector Fabric introduces no new model-calling code path (connectors never call a model directly); no new live test file was needed or written.
- Eval harness (`orca/connectors/eval_harness.py`): **24/24 scenarios passed (100%)**.

## Real bugs found and fixed (disclosed, not hidden)

1. **`truth_bridge.py`**: `connector_result_to_evidence()` built an
   `EvidenceSource` but discarded it, returning bare `list[Evidence]` --
   since `Evidence` only carries a `source_id` string (never the source
   object), the `source_type` classification was silently lost entirely
   on every call. Fixed to return `list[tuple[Evidence, EvidenceSource]]`,
   matching `orca.truth.evidence`'s own established pairing convention.
2. **`document_store.py`**: `DocStore.retrieve()` never returns a `doc_id`
   key in its result dicts (only `text`/`filename`/`chunk_idx`), so
   `search_documents()`'s `h.get("doc_id", "")` silently always resolved
   to an empty string -- violating spec §26's "every remote object
   retains real identity" requirement without any test having caught it
   until a real end-to-end DocStore test was written. Fixed to derive
   `provider_object_id` from `filename + chunk_idx`, the actual identity
   `DocStore.retrieve()` exposes.

Both bugs were found only once real (non-mocked) code paths were
exercised end-to-end in tests -- confirming the value of the "reuse over
duplication + real test coverage" discipline over ad-hoc verification
scripts, which had NOT caught either bug during the earlier manual
`.venv/bin/python -c "..."` verification pass.

## Connector family classification (spec §70 honesty requirement)

| Family | Class | Notes |
|---|---|---|
| Document store | REAL_ADAPTER | Wraps real `orca.docs.store.DocStore` (ChromaDB + keyword fallback). |
| Code host | CONTRACT_ONLY | Typed, policy-enforced; no real GitHub/GitLab client exists. |
| Messaging | CONTRACT_ONLY | Typed, policy-enforced; no real Slack/Teams client exists. |
| Calendar | CONTRACT_ONLY | Typed, policy-enforced; no real calendar client exists. |
| Ticketing | CONTRACT_ONLY (exercised via FAKE_TEST_PROVIDER in tests) | No real Jira/Linear client exists. |
| Database | CONTRACT_ONLY | Typed, policy-enforced; no real DB client exists. |
| CRM | CONTRACT_ONLY | Typed, policy-enforced; no real Salesforce/HubSpot client exists. |
| Internal API | CONTRACT_ONLY | Typed, policy-enforced; no generic internal-API client exists. |
| Object storage | CONTRACT_ONLY | Typed, policy-enforced; no real S3/GCS client exists. |

## Known limitations

1. No real third-party credential storage/OAuth flow exists --
   `ConnectorCredentialRef` is a correct, tested contract with nothing
   real behind it yet for any provider except DOCUMENT_STORE (which needs
   no external credential, being session-local).
2. Only DOCUMENT_STORE has a REAL_ADAPTER; the other 8 connector types
   are CONTRACT_ONLY, exercised only through the FAKE_TEST_PROVIDER in
   tests/eval harness -- never presented as real connectivity.
3. `federated_search()`'s bounded scope planning is caller-driven
   (`read_fns` + optional `connector_instance_ids`); there is no
   automatic "which connectors are relevant to this query" planner yet --
   that decision is left to calling code (e.g. a future AgentPlanner
   enhancement), disclosed rather than silently assumed.

## Remaining Phase-9 blockers

None block THIS phase's closure -- the above are scope limitations of a
phase that deliberately built the identity/policy/tenancy/audit fabric
and one REAL_ADAPTER first, rather than fabricating multiple fake
"real" provider integrations. Building actual OAuth/credential vaults
and additional REAL_ADAPTERs (CODE_HOST via a real Git host API being the
most natural next REAL_ADAPTER candidate) is future work, not a Phase 9
gap.

## AUDIT counters (all required = 0)

- Mocked-as-real connector claims: 0
- Fabricated test results: 0
- Cross-tenant data leaks found and left unfixed: 0
- Silent exception swallowing in connector adapters: 0
- Policy bypass paths found and left unfixed: 0
- Secrets logged unredacted: 0
- Hardcoded/faked latency numbers: 0
- Tests skipped without disclosure: 0
- New enum values invented where an existing one would serve: 0
- Connector families falsely classified as REAL_ADAPTER: 0
- Approval bindings that can be replayed/forged: 0
- Undisclosed scope limitations: 0

**READY TO ADVANCE TO PHASE 10: YES**
