# Phase 11 — Connector Simulation

`orca/simulation/connector_sim.py::simulate_connector_write()`.

## Honest scope

Only `ConnectorType.TICKETING` gets a real preview mechanism — Phase 9's
deterministic `FakeProviderState`/`fake_write()`, run against an
ISOLATED, throwaway state object created fresh per simulation call
(never the tenant's real fake-provider state, and obviously never a real
SaaS API). Every other connector family (`CRM`, `MESSAGING`, `CALENDAR`,
`CODE_HOST`, `DATABASE`, `INTERNAL_API`, `OBJECT_STORAGE`) returns
`supported=False` with an explicit `unavailable_reason` — never a
fabricated preview.

`DOCUMENT_STORE` (Phase 9's one REAL_ADAPTER) is ALSO `supported=False`
for simulation, because Phase 9 never built a write path for it (its
adapter is read-oriented) — there is nothing to preview. Per spec §27,
a real preview would need to operate through an isolated test
collection, never the tenant's real one; since no write path exists at
all, this is disclosed as MISSING rather than implemented against a
nonexistent write.

## OUTCOME_UNKNOWN_RISK flagging

Any simulated write with no `idempotency_key` is flagged
`OUTCOME_UNKNOWN_RISK` in the result's warnings — this does not mean the
outcome WILL be unknown, only that the commit-then-response-lost race
exists (spec §29). It is independent of whether the preview itself
succeeds.

## Reversibility

A real ticketing/CRM/messaging system's actual reversibility semantics
are unknown to this codebase — `Reversibility.UNKNOWN` is used rather
than guessed.

## Cross-tenant simulation is blocked before any preview runs

`chamber.py::run_simulation()` checks `instance.tenant_id !=
identity.tenant_id` BEFORE calling `simulate_connector_write()` at all —
a cross-tenant simulation attempt never even reaches the fake-provider
preview logic, verified directly in
`tests/test_simulation_security.py::test_cross_tenant_simulation_blocked_for_connectors`.
