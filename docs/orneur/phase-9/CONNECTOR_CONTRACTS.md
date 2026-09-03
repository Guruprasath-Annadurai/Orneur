# Phase 9 — Connector Contracts

All defined in `orca/connectors/contracts.py`. No arbitrary connector-
specific dict is ever the system boundary.

## Taxonomy

- `ConnectorType` (9): DOCUMENT_STORE, CODE_HOST, MESSAGING, CALENDAR, TICKETING, DATABASE, CRM, OBJECT_STORAGE, INTERNAL_API
- `ConnectorImplementationClass`: REAL_ADAPTER | CONTRACT_ONLY | FAKE_TEST_PROVIDER (spec §70's honesty requirement -- every family classified, never silently implied more connected than it is)
- `ConnectorCapabilityKind`: CONNECTOR_READ | CONNECTOR_WRITE | CONNECTOR_SEARCH | CONNECTOR_DELETE
- `DataSensitivity`: PUBLIC | INTERNAL | PRIVATE | SENSITIVE
- `ConnectorHealthState`: HEALTHY | DEGRADED | UNAUTHORIZED | RATE_LIMITED | OFFLINE | DISABLED

## Identity

`ConnectorIdentity` (frozen): `tenant_id` (= `org_id`, the existing real
multi-tenancy identity from `orca.auth.org_store`), `principal_id` (=
`User.id`), `workspace_id`, `effective_permissions`. Never model-produced
-- constructed by platform code from `orca.auth` primitives BEFORE any
connector request exists. Structurally, no model-facing dataclass
(`AgentAction`, `ToolSpec`) ever carries a `ConnectorIdentity` field --
it only ever flows as a direct function parameter from platform code.

## Credentials

`ConnectorCredentialRef` (frozen) is an OPAQUE reference -- never the
secret value itself. Only the connector execution boundary resolves it;
it never appears in a prompt, WorldState, Memory, TruthResult, or
AgentTrace.

## Scope

`ConnectorScope` (frozen): `resource_path` + `sub_scopes` -- explicit and
narrow, never "the whole enterprise account."

## Instance

`ConnectorInstance.structurally_rejects_write()` returns True whenever
`read_write_mode != "READ_WRITE"` OR `CONNECTOR_WRITE` is not in
`enabled_capabilities` -- a read-only connector structurally rejects
writes, never relying on a remote API failure to enforce it.

## Requests / Results

`ConnectorRequest` / `ConnectorReadRequest` (+ `query`) /
`ConnectorWriteRequest` (+ `idempotency_key`). `ConnectorObjectRef`
retains real remote identity (`provider_object_id`, `version`,
`last_modified`) -- never just a display name. `OutcomeStatus` is a
three-state enum: SUCCESS | FAILURE | OUTCOME_UNKNOWN (spec §13 -- never
report FAILED when external success is genuinely unknown, e.g. a
connection break after a write was sent).
