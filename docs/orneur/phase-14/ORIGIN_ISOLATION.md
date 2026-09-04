# Phase 14 §4-6, §78-81 — Origin Isolation and Compromise Containment (DESIGN ONLY)

**Status: NOT_EXECUTED against real infrastructure** — no cloud origin
exists to test direct-bypass against, no multi-cloud IAM boundary exists
to test compromise containment against. Design recorded for Phase 14B+.

## Origin hiding (spec §4-6)

Covered in `CLOUDFLARE_ARCHITECTURE.md` — Cloudflare Tunnel as the
preferred mechanism, direct-origin-bypass test (`DIRECT_ORIGIN_BYPASS`
audit counter) deferred to real infrastructure.

## Cloud metadata / SSRF protection (spec §78) — partially checkable locally, not executed

Cloud instance metadata endpoints (`169.254.169.254` on GCP/AWS/Azure)
are a real, common SSRF target once ORNEUR runs on any of those
clouds. **No SSRF-prone code path was found in this codebase's request
handling** during the Phase 14 audit — `orca/serve/api.py`'s endpoints
do not proxy or fetch arbitrary user-supplied URLs on the server's
behalf (a common SSRF vector). Connector calls (`orca/connectors/*`)
target pre-registered, admin-configured provider endpoints, not
user-supplied URLs. This is a structural observation from reading the
code, not a penetration test against a real cloud metadata endpoint
(which does not exist in this environment) — the `CLOUD_METADATA_SSRF`
audit counter is reported as **NOT_EXECUTED** rather than a fabricated
0, per spec §78's explicit "test on each deployed cloud where
possible."

## Compromise containment models (spec §54, §80-81)

Design principles (not independently verified against real
infrastructure this phase):

- **One cloud's credential compromise must not grant another cloud's
  access** (spec §54) — achievable structurally by never sharing one
  IAM identity across GCP/Azure/AWS, and never storing one cloud's
  service-account key as an environment variable reachable from
  another cloud's workload. No cross-cloud credential exists yet to
  verify this against.
- **One compromised API worker must not own Cloudflare administration,
  other cloud roots, or all tenant connector credentials** (spec §81) —
  achievable by scoping the API worker's own runtime identity to only
  what serving requests needs (the Godmode authority DB connection,
  the auth DB connection, per-tenant connector credentials it is
  actively using) and never provisioning it with account-level cloud
  IAM roles or Cloudflare API tokens. This is a deployment-configuration
  discipline, not application code — recorded here as the requirement
  to enforce once real IAM roles are created (Phase 14B+).

## Audit counters affected

`DIRECT_ORIGIN_BYPASS`, `CLOUD_METADATA_SSRF`,
`CROSS_CLOUD_CREDENTIAL_ESCALATION` — all **NOT_EXECUTED**.
