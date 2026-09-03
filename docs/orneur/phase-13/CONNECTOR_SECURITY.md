# Phase 13 — Connector Security

Audited, not newly re-tested this phase beyond reuse in the cross-layer
chain tests:

| Spec item | Existing test |
|---|---|
| §30 tenant escape (ID guessing, cache key manipulation) | `tests/test_connector_tenant_isolation.py` |
| §31 credential extraction via error/debug/audit/WorldState | `tests/test_connector_security.py`, `tests/test_agent_secret_and_trace_security.py` |
| §32 cross-connector exfiltration (private doc → messaging) | `tests/test_connector_authority_regressions.py` (destination-authorization-independent design) |
| Rate limit / budget abuse | `tests/test_connector_rate_limit_and_budget.py` |
| Lifecycle/tombstone | `tests/test_connector_lifecycle_audit.py` |

`tests/test_redteam_cross_layer_chains.py` reuses the real
`ConnectorRegistry`/`ConnectorInstance`/`DocStore` fixtures from
`tests/test_connector_agent_runtime_e2e.py` to build its malicious
document, confirming these connector primitives compose correctly with
the new adversarial content without any special-casing needed.

## Result

`CONNECTOR_EXFILTRATION_BYPASS = 0`, `CROSS_TENANT_READ = 0`,
`CROSS_TENANT_WRITE = 0` (connector-specific) — confirmed by pre-existing,
passing tests.
