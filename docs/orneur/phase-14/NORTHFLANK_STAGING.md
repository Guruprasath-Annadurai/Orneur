# Phase 14B — Northflank Staging Record

Status: **PARTIAL_EXECUTION — real remote build proven; runtime qualification pending.**

This document records the real provider-neutral staging path selected after the original VPS-only owner checkpoint could not be satisfied at zero cost. It does not claim that a managed PaaS container is equivalent to a raw VPS for host-hardening evidence. Items that require root/host control remain NOT_EXECUTED.

## Real infrastructure now provisioned

- Provider: Northflank Cloud, Developer Sandbox/free project
- Project: `orneur-phase14b-staging`
- Region: Europe - West (London)
- Service: `orneur-api-a`
- Service type: combined Git build + deploy
- Repository: `Guruprasath-Annadurai/Orneur`
- Branch: `session-update-2026-08-25`
- Runtime plan: `nf-compute-20` — 0.2 shared vCPU, 512 MB RAM
- Instances: 1
- Runtime ephemeral storage: 1 GB
- Application port: `7337/TCP`
- Port exposure: private only
- Autoscaling: unavailable on free project
- SSH: disabled
- Northflank liveness probe: HTTP `GET /livez` on port 7337, initial delay 20s, interval 30s, timeout 5s, max failures 3

## Shared distributed state

Two real Supabase PostgreSQL projects are in use. Connection credentials are intentionally not documented here.

- Core project ref: `rqupsugllpxscirandhm`
  - backs `ORNEUR_DATABASE_URL`
  - also backs `ORNEUR_GODMODE_DATABASE_URL` for shared authority/audit state
- Security-root project ref: `ttfpohasqgdeifpjfodu`
  - backs `ORNEUR_SECURITY_ROOT_DATABASE_URL`
  - intentionally separate from the core/authority database

Both application connection strings were configured using Supabase Session Pooler URIs and are stored only in Northflank secret storage.

## Runtime secret group

Northflank secret group: `orneur-phase14b-runtime`

Scope: Runtime only. Values are secret and must never be committed or copied into this document.

Expected keys:

- `ORNEUR_DEPLOYMENT_PROFILE=DISTRIBUTED`
- `ORNEUR_DATABASE_URL`
- `ORNEUR_GODMODE_DATABASE_URL`
- `ORNEUR_SECURITY_ROOT_DATABASE_URL`
- `ORNEUR_AUDIT_KEY`
- `ORNEUR_GODMODE_LEASE_SECRET`
- `ORNEUR_AUTH_SECRET`

The group is currently unrestricted at the project level only because `orneur-api-a` did not exist when the group was created. Before any second workload is added, restrict the group so only the intended ORNEUR API service can inherit these values.

## First real build finding and closure

The first Northflank image build against commit `586d83f95f4063cb148b07671b92c39f1bb62ce6` failed in Hatchling metadata validation:

`OSError: Readme file does not exist: README.md`

Root cause: the root Dockerfile copied `pyproject.toml` and `orca/`, but `pyproject.toml` declares `README.md` as project metadata and the README had not yet been copied into the build image.

The container patch committed as `d2f58822b51cbeabf6b135cd9099c5abbd47db85` fixed three concrete deployment issues together:

1. copies `README.md` before package installation;
2. installs `.[postgres]` so the distributed PostgreSQL runtime has `psycopg`;
3. changes the image-level Docker HEALTHCHECK to `/livez` and gives startup 20 seconds.

Northflank's commit/build status for that patched commit returned **success**. That is evidence for remote image-build success only; it is not yet evidence that the running container completed startup or that all distributed backends are reachable.

## What must be proven next

Do not mark Phase 14B complete until executable evidence exists for all applicable items below:

1. `orneur-api-a` reaches Running/Healthy state and remains stable.
2. Runtime logs contain no secret values and show no configuration fallback.
3. `/livez` succeeds repeatedly through the Northflank health system.
4. The real Supabase core database is reachable from the remote service.
5. The real Supabase security-root database is reachable from the remote service.
6. Distributed startup refuses to fall back to local auth/authority/security-root storage.
7. The secret group is restricted to the intended workload before Service B exists.
8. A second real worker or approved Host B proves cross-worker auth/session/authority visibility.
9. Kill-switch propagation, one-use lease race, tenant isolation, and durable Godmode audit are proven across the real staging boundary, not only local multiprocessing.
10. Public ingress, if added, goes through the approved Cloudflare path; port 7337 remains non-public.
11. `/readyz` is added as a routing/readiness gate only when the model runtime dependency required by ORNEUR's readiness contract is actually reachable.
12. Load/soak, rolling update, bad-candidate, outage, and restore tests are rerun against this real staging topology.

## Evidence boundaries

Northflank gives ORNEUR a real remote Linux container and therefore resolves the previous "no remote infrastructure at all" blocker for application-level distributed staging. It does **not** provide the raw-host/root surface required to honestly claim VPS firewall, SSH hardening, kernel tuning, host package baseline, or direct-origin host controls. Those VPS-specific checks remain NOT_EXECUTED unless a real host with that control surface is later provisioned.

No Phase 15 certification claim follows from this document.
