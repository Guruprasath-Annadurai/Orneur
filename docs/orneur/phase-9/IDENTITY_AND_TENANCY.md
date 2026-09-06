# Phase 9 — Identity and Tenant Isolation

## Reused, not reinvented

`ConnectorIdentity.tenant_id` = the existing `org_id` from
`orca.auth.org_store`/`orca.auth.db`. Phase 9 introduces zero new
identity/multi-tenancy primitives -- the real substrate already existed
(`OrgMember`, `org_id`) and is reused directly.

## Enforcement layers (defense in depth)

1. **`ConnectorRegistry.get_for_tenant(tenant_id, connector_instance_id)`**
   is the ONLY lookup method. A tenant can never even enumerate another
   tenant's instances -- `list_for_tenant()` filters strictly, and
   `get_for_tenant()` raises `TenantIsolationError` (never returns `None`
   ambiguously, never returns another tenant's instance) on any mismatch.
2. **`orca.connectors.policy.evaluate_connector_policy()`** checks tenant
   match FIRST, before capability or sensitivity checks -- a cross-tenant
   request is unconditionally DENIED, never degraded to
   REQUIRE_APPROVAL.
3. **Adapter-level structural assertion** -- e.g.
   `document_store.search_documents()` and `fake_provider.fake_read/write()`
   independently assert `instance.tenant_id == identity.tenant_id` and
   raise `PermissionError` if not, even though registry+policy should
   already have caught it. Never trust a single check.
4. **Vector-store namespacing** -- `document_store._scoped_session_id()`
   derives DocStore's own ChromaDB collection name from
   `sanitize(tenant_id) + "-" + connector_instance_id`, so even a
   hypothetical bug upstream cannot make one tenant's ChromaDB collection
   resolve to another's. Verified directly with a real two-tenant DocStore
   round-trip in `tests/test_connector_document_store.py`.
5. **Cache-key isolation** -- `orca.connectors.security.tenant_cache_key()`
   hashes `tenant_id + connector_instance_id + scope + query_identity`
   together (SHA-256), so no two tenants can ever collide onto the same
   cache key even with identical queries.
6. **Memory scope isolation** -- connector-derived memory candidates use
   `MemoryScope.TENANT` + `scope_id=tenant_id`; `orca.memory.firewall.check()`
   (Phase 5, unchanged) already refuses cross-tenant TENANT-scoped reads.

## Verified adversarial scenarios

See `tests/test_connector_tenant_isolation.py`,
`tests/test_connector_document_store.py::test_search_documents_vector_isolation_across_tenants`,
`tests/test_connector_federated_retrieval.py::test_federated_search_explicit_cross_tenant_instance_list_blocked`,
and `orca/connectors/eval_harness.py` scenarios 1-3, 12-13.
