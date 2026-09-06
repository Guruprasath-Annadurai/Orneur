# Phase 10 — Connector Elevation

`orca.godmode.connector_elevation.evaluate_connector_policy_with_elevation()`
wraps Phase 9's `evaluate_connector_policy()` UNCHANGED — it never
replaces it. Flow:

1. Run the normal connector policy check.
2. If ALLOW, return it immediately (no lease ever consulted for an
   already-permitted action).
3. If the DENY was because `instance.tenant_id != identity.tenant_id`,
   return immediately without even attempting lease resolution — a
   cross-tenant request is never elevation-eligible (spec §24's
   "Godmode must NEVER permit cross-tenant access merely because
   authority is high" — enforced here structurally, not just by
   `resolve_lease()`'s own tenant check, which would ALSO catch it: two
   independent layers).
4. Otherwise, if a `lease_id` was given, resolve it against
   `capability_domain=CONNECTOR`, `capability=<requested capability
   value>`, `resource_scope=f"{connector_instance_id}:{resource}"`,
   `operation_scope=<operation>`.

## Why the resource_scope embeds the connector instance id

A lease's `resource_scope` is always
`f"{connector_instance_id}:{resource_path}"`, never the bare resource
path alone. This makes it structurally impossible for a lease issued for
one connector instance to match a request against a DIFFERENT instance
that happens to have a resource with the same name — verified in
`tests/test_godmode_security.py::test_connector_resource_alias_does_not_cross_connector_instances`
(a lease scoped to `instance_a:customer/123` correctly denies the
identical resource path on `instance_b`).

## Narrow, never a connector/tenant switch (spec §23)

A connector write lease cannot: switch connector (structurally
impossible per the above), switch tenant (both the base policy and
`resolve_lease()` independently enforce exact tenant match), or access a
broader folder/repo/table (resource_scope match is exact, canonically
normalized — see `resolution.py`'s `_canonicalize()`).

## Verified end-to-end (spec §60)

`tests/test_godmode_concurrency_and_e2e.py::test_connector_godmode_end_to_end`:
normal write denied (READ_ONLY connector) -> approved narrow elevated
lease issued -> exact write allowed -> a DIFFERENT resource on the SAME
connector denied -> lease forcibly expired -> next write denied. Uses
Phase 9's `FakeProviderState`/`fake_write()` — no real SaaS credentials
required or fabricated.
