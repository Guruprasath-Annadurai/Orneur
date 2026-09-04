# Phase 14A.3 — Deployment Manifests (Provider-Neutral, Not Provisioned)

**Status**: design/config artifacts only. Nothing here has been applied
to any real cluster — no GCP, Azure, or AWS resource exists (see
`GCP_DEPLOYMENT.md`, `AZURE_DEPLOYMENT.md`, `AWS_DEPLOYMENT.md`'s own
OWNER ACTION REQUIRED checkpoints, still unresolved).

## SOVEREIGN (unchanged)

`k8s/deployment.yaml` remains exactly as it was — single replica,
local `ORCA_HOME` persistent volume, `/livez`/`/readyz` probes (Phase
14A). This is the correct manifest for the SOVEREIGN profile and was
not touched this phase (spec §4's explicit requirement to preserve it).

## DISTRIBUTED (new overlay, not provisioned)

`k8s/distributed-overlay.yaml` — a provider-neutral patch on top of
`deployment.yaml`'s base, adding:

- `ORNEUR_DEPLOYMENT_PROFILE=DISTRIBUTED` (a plain value — this is not
  a secret).
- `ORNEUR_GODMODE_DATABASE_URL`, `ORNEUR_SECURITY_ROOT_DATABASE_URL`,
  `ORNEUR_DATABASE_URL`, `ORNEUR_REDIS_URL` — **all** via
  `secretKeyRef` against a single `orneur-distributed-secrets` Secret
  an operator creates out-of-band. **No connection string, password,
  or credential is ever embedded in the manifest source** (spec §11's
  explicit requirement), matching the existing pattern
  `deployment.yaml` already used for `ORNEUR_AUTH_SECRET`.
- `replicas: 3` — DISTRIBUTED implies more than one worker.

**What happens if the Secret is missing or wrong**: the pod crashes on
startup. `orca/serve/api.py`'s module-level
`validate_deployment_config()` call (Phase 14A.3) raises
`DeploymentConfigError` the instant the module is imported — the
container process exits, Kubernetes never marks the pod Ready, and no
traffic is ever routed to it. This is the same "fail startup for
missing/invalid critical configuration" behavior spec §2 requires,
now expressed at the manifest level: there is no code path, in this
overlay or in the application, that falls back to local file storage
when the Secret is absent.

## Cloud provider overlays (GCP/Azure/AWS) — not yet created

Per spec §11's explicit instruction to prepare, not provision: no
provider-specific overlay (e.g. a GKE-specific Ingress annotation, an
AKS-specific storage class, an EKS-specific IAM role annotation) has
been written yet. `k8s/distributed-overlay.yaml` is intentionally
provider-neutral so that whichever cloud Phase 14B targets first can
layer its own provider-specific pieces (managed Postgres connection
details still delivered via the same Secret mechanism, a
provider-specific Ingress/LoadBalancer, provider IAM annotations for
workload identity) on top of it without needing three divergent base
manifests.

## Cloudflare independence (spec §12)

Nothing in either manifest gives Cloudflare — or any edge/ingress layer
— any role in kill-switch, security-epoch, or Godmode authority state.
Those all flow through `ORNEUR_SECURITY_ROOT_DATABASE_URL` and
`ORNEUR_GODMODE_DATABASE_URL` directly to the application's own
Postgres connections; an edge outage or misconfiguration cannot alter
either, since the edge layer never sits between the application and
these backends in this architecture (see `CLOUDFLARE_ARCHITECTURE.md`
for the ingress topology this doesn't touch).
