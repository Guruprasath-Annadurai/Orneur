# Phase 14 §3 — Target Deployment Architecture

## Scope discipline

Per spec §3: "Do not over-engineer a planet-scale architecture. Phase
14 should prove a credible multi-process, multi-worker, multi-service,
multi-instance production deployment." This document describes that
credible topology — it does not describe a topology that has been
stood up on real cloud infrastructure (that is Phase 14B/C/D, gated on
owner-approved cloud access; see `PHASE_14_CLOSURE.md`'s OWNER ACTION
REQUIRED checkpoints).

## Topology

```
                         PUBLIC INTERNET
                               |
                    (Cloudflare edge -- see
                     CLOUDFLARE_ARCHITECTURE.md;
                     design-only, not provisioned)
                               |
                        Load Balancer / ingress
                               |
                 +-------------+-------------+
                 |                           |
           API worker 1                API worker 2  ...N
        (orca.serve.api:app)       (orca.serve.api:app)
                 |                           |
                 +-------------+-------------+
                               |
                      Cognitive Kernel
                     (orca/cognitive/*, request-scoped,
                      no persistence -- runs in-process
                      inside whichever API worker handles
                      the request)
                               |
                        Model Gateway
                     (orca/gateway/*, routes to
                      inference workers by deployment ID)
                               |
                 +-------------+-------------+
                 |                           |
        Inference worker 1          Inference worker 2  ...N
       (checkpoint-bound,          (checkpoint-bound,
        registered via             registered via
        orca/gateway/worker.py)    orca/gateway/worker.py)

        Shared stores (accessed by every API/Kernel/Gateway process):
          - PostgreSQL: Godmode authority (ORNEUR_GODMODE_DATABASE_URL)
          - PostgreSQL: auth/session/audit (ORNEUR_DATABASE_URL)
          - Redis: chat session continuity, rate limits (ORNEUR_REDIS_URL)
          - [known gap, undistributed] gateway worker registry,
            memory stores, model/checkpoint/dataset registries --
            see DEPLOYMENT_PROFILES.md's "known-remaining single-host-
            shaped stores"
```

## Why this shape

- **API workers are stateless w.r.t. anything that must survive a
  restart or be visible to a sibling worker** — the Cognitive Kernel,
  Cognitive Court, Model Society, Truth Fabric, and Simulation Chamber
  are all, by their own existing design (confirmed in
  `CURRENT_DEPLOYMENT_ARCHITECTURE.md`'s audit), request-scoped
  dataclasses with zero persistence. This means scaling API workers
  horizontally requires no new distributed-state work for those
  subsystems — they were already "stateless-per-request" before Phase
  14 touched anything.
- **The Gateway routes to inference workers by registered identity**,
  not by hostname — `orca/gateway/gateway.py`'s `_deployments`/`_workers`
  dicts already key on deployment ID and bind checkpoint/model-family/
  capability metadata (spec §9's requirement was already true of the
  existing code; Phase 14 did not need to add it).
- **Only the mutable, security-sensitive state got a distributed
  backend this phase**: Godmode authority, because it is the one store
  where "two hosts each maintaining an independent copy" is a genuine
  security regression (privilege duplication), not merely a consistency
  inconvenience. Everything else that stayed single-host-shaped in this
  pass (memory, registries, gateway worker file registry) is a real,
  disclosed limitation of the current DISTRIBUTED profile — not
  something this document pretends is solved.

## What is deliberately NOT in this topology

- No service mesh, no sidecar proxies, no separate "authority service"
  microservice (spec §35 offered this as an option; Option B — a shared
  transactional database — was chosen instead as the simpler correct
  answer, see `AUTHORITY_DISTRIBUTION.md`).
- No cross-cloud active-active replication (spec §36/§55-56 explicitly
  scope this phase to "recoverability, not global distributed
  consistency").
- No Kubernetes cluster actually running this topology yet — the
  existing `k8s/deployment.yaml` (updated this phase for `/livez`/
  `/readyz`) remains a single-replica manifest; multi-replica k8s
  configuration is described conceptually here and in `DEPLOYMENT.md`
  but not deployed to a real cluster this phase (no cluster exists in
  this environment).
