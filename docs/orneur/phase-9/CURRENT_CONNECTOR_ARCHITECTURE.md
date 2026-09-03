# Current Connector Architecture Audit (Phase 9 spec §2)

## `orca/mcp/fs_server.py`

**REAL, TENANT_SAFE (trivially -- single-machine local sandbox), READ+WRITE_CAPABLE.**
An MCP filesystem server with its own `_safe_path()` sandboxing (Phase 8's
audit already classified this SECURE). No enterprise/multi-tenant concept
at all -- it is a local developer sandbox, not an enterprise connector.

## `orca/docs/store.py::DocStore`

**REAL, PARTIAL tenant safety.** A genuinely per-session vector/keyword
document store -- `docs_{session_id[:12]}` is the actual ChromaDB
collection name, so retrieval is naturally session-scoped (a real,
existing form of the vector-isolation spec §50 asks for, though scoped to
SESSION, not to an organizational `tenant`/`org_id`). `list_docs()`/
`register_doc()` key their registry by `session_id` too. **Not
`TENANT_SAFE` in the Phase 9 sense**: nothing here checks `org_id`/
`principal` identity at all -- isolation is an accident of session-scoped
naming, not an enforced authorization boundary. This is the REAL_ADAPTER
foundation Phase 9's `DOCUMENT_STORE` connector builds on.

## `orca/tools/web.py`, `orca/truth/fetch.py`

**REAL, UNSCOPED (by design -- public web, no tenant concept applies).**
SSRF-hardened (Phase 4.1/8, unchanged). Not an enterprise connector --
correctly out of Phase 9's tenant-isolation concern (there is no "tenant"
for the public internet).

## `orca/auth/org_store.py`, `orca/auth/db.py` (`org_id`, `OrgMember`)

**REAL, the actual existing multi-tenancy substrate.** Organizations
(`org_id`), members, seats, roles already exist and are tested
(`tests/test_org_store.py`). **This is the real identity Phase 9's
`tenant_id` maps to** -- Phase 9 does NOT invent a parallel "tenant"
concept; `ConnectorIdentity.tenant_id` is `org_id` from this existing
system, reused directly (spec §6's "identity comes from platform/runtime
context," not invented fresh).

## `orca/auth/store.py` (`User`), `orca/auth/rbac.py`

**REAL.** `User.id`/`tier` and `has_permission()`/`require_role()` are the
existing principal/permission primitives -- reused as
`ConnectorIdentity.principal` and an input to `ConnectorPolicy`, not
reimplemented.

## Credential storage

**MISSING for third-party enterprise providers.** Only first-party model
API keys exist (`orca.config.CONFIG.backends.openai_api_key`/
`anthropic_api_key`, environment-variable-sourced) -- there is no OAuth
token store, no per-org credential vault, no secrets manager integration
of any kind for GitHub/Slack/Drive/Calendar/Ticketing/CRM/database
providers. **No real credentials exist to reference for any of these
provider families.**

## GitHub / Slack / Drive / Calendar / Ticketing / CRM / Database clients

**MISSING entirely.** No code in this repository connects to GitHub,
Slack, Google Drive, a calendar provider, a ticketing system, a CRM, or
an external database. Building "real adapters" for these this phase would
mean fabricating credentials/connectivity that does not exist -- explicitly
forbidden (spec §27-31's repeated "do not fake X if no authenticated
integration exists"). Phase 9 therefore builds:
- **One REAL_ADAPTER**: `DOCUMENT_STORE`, adapting the real `DocStore`.
- **CONTRACT_ONLY** abstractions (typed interfaces, policy/capability
  wiring, tested against a `FAKE_TEST_PROVIDER`) for `CODE_HOST`,
  `MESSAGING`, `CALENDAR`, `TICKETING`, `CRM`, `DATABASE`, `INTERNAL_API`.
- A **FAKE_TEST_PROVIDER** deterministic connector (in-memory, no network)
  used only by the evaluation harness and test suite to exercise the full
  identity/scope/policy/capability/audit machinery end-to-end without
  claiming any real external connectivity.

See `PHASE_9_CLOSURE.md`'s "Connector Families" table for the exact,
final REAL_ADAPTER / CONTRACT_ONLY / FAKE_TEST_PROVIDER classification
per family (spec §70's explicit requirement).

## Summary

No enterprise connector fabric, tenant-aware policy engine, or
connector-specific budget dimension existed before this phase. The real,
reusable substrate this phase builds on: `DocStore` (document retrieval),
`org_store`/`auth.store` (tenant/principal identity), Phase 8's
`Capability`/`Policy`/`ToolRegistry`/`AgentRuntime` (the authorization and
execution boundary connector actions now flow through), and Phase 7's
`Model Society`/`TruthFabric`/`Memory Continuum` (for connector-derived
cognition/evidence/memory integration).
