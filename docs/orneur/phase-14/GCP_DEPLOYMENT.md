# Phase 14B — GCP Deployment (NOT EXECUTED — OWNER ACTION REQUIRED)

**Status: NOT_EXECUTED.** `gcloud` CLI is installed on this machine but
no authenticated session or billing-enabled project was available/used
this phase. Per spec §0's critical execution rule, no GCP resources
were created, no GKE cluster was provisioned, and no load/soak/canary/
backup/restore test was run against real GCP infrastructure. Everything
below is the design to execute once the owner completes the checkpoint.

## Intended architecture (spec §28)

```
Cloudflare -> private/protected GCP ingress -> GKE
  -> ORNEUR API (2+ replicas) -> Kernel -> Gateway -> inference workers
Shared services: Cloud SQL PostgreSQL (Godmode authority + auth),
  Memorystore Redis (sessions/rate-limits), GCS (artifacts),
  Artifact Registry (container images), Secret Manager, Cloud Monitoring
```

This maps directly onto the `ORNEUR_GODMODE_DATABASE_URL`/
`ORNEUR_DATABASE_URL`/`ORNEUR_REDIS_URL` environment-variable contract
already built and tested locally this phase (`DEPLOYMENT_PROFILES.md`)
— Cloud SQL and Memorystore are simply real, managed instances of the
same PostgreSQL/Redis this phase already proved the application code
works against.

## OWNER ACTION REQUIRED — GCP

```
Provider: GCP
Purpose: Primary distributed-qualification environment (Phase 14B) --
         real GKE deployment, multi-replica API, centralized authority,
         rolling update, canary, load/soak, fault injection, backup/restore
Resource: A billing-enabled GCP project, a chosen region, GKE quota
          (a small node pool is sufficient to start -- no GPU needed
          for infrastructure qualification per spec §39), Cloud SQL
          PostgreSQL instance, Artifact Registry repository
Authentication method preferred: an authenticated `gcloud` CLI session
          (`gcloud auth login` / `gcloud auth application-default login`)
          under the owner's own account, or a scoped service account
          with Workload Identity Federation -- not a long-lived
          downloaded service-account JSON key where avoidable
Secret/API key required in chat: NO
Owner action: create or designate a GCP project with billing enabled;
          run `gcloud auth login` (or configure Workload Identity) in
          an environment this session can access; confirm project ID,
          region, and any pre-existing quota limits (GKE node quota,
          Cloud SQL availability) for that project
Verification command: `gcloud projects describe <PROJECT_ID>` and
          `gcloud auth list`
Expected cost category: a minimal GKE node pool (e.g. 2x e2-small) plus
          a small Cloud SQL instance is low-cost (order of a few
          dollars/day) for infrastructure qualification; GPU nodes
          would be provisioned only transiently for the specific
          GPU-worker test in spec §39-40 and destroyed immediately after
Can continue without this action: YES -- Phase 14A local-foundation
          work (already substantially complete) does not depend on this
```

Until this action is taken: GKE deployment, real multi-replica rolling
update, real canary, real load/soak against cloud infrastructure, real
fault injection against real nodes, and real backup/restore against a
managed Cloud SQL instance are all **NOT_EXECUTED**.

## Phase 14A.3 update

`k8s/distributed-overlay.yaml` (see `DEPLOYMENT.md`) is the
provider-neutral base a future GCP-specific overlay would extend —
e.g. wiring `ORNEUR_GODMODE_DATABASE_URL`/`ORNEUR_SECURITY_ROOT_DATABASE_URL`
to two separate Cloud SQL PostgreSQL instances via Secret Manager +
`external-secrets` (or an equivalent CSI driver), rather than a raw
Kubernetes Secret. Not created this phase — still gated on the same
OWNER ACTION REQUIRED checkpoint above.
