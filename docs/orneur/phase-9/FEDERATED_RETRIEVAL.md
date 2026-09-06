# Phase 9 — Federated Enterprise Retrieval

`orca.connectors.federated_retrieval.federated_search()` queries only:

- connector instances **visible to the requesting tenant** -- via
  `registry.list_for_tenant()` by default, or an explicit
  `connector_instance_ids` list (which itself goes through
  `registry.get_for_tenant()`, so a cross-tenant instance ID in that list
  raises `TenantIsolationError` rather than silently being skipped or
  included);
- connector instances that are **currently healthy/routable** (via
  `registry.is_routable()`) -- an offline/unauthorized/rate-limited
  connector is recorded in `skipped_unhealthy`, never silently queried
  anyway;
- connector instances that **pass policy** for the READ capability --
  a policy-denied instance is recorded in `failed_connectors` with the
  denial reason, never silently omitted without explanation.

## Honest partial results

`FederatedSearchResult.is_partial` is True whenever `failed_connectors`
or `skipped_unhealthy` is non-empty. There is no code path that reports
"complete" coverage when any connector was skipped or failed -- spec
§61's requirement that a federated result never silently implies
exhaustive coverage.

## Bounded search

`federated_search()` never queries "every connector on every request" by
default (spec §34) -- the caller decides read_fn coverage (`read_fns`
maps `connector_type.value -> read_fn`), and an explicit
`connector_instance_ids` list further bounds which instances are
consulted for a specific, planned retrieval.
