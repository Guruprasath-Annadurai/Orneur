# Phase 14C — Azure Deployment (NOT EXECUTED — OWNER ACTION REQUIRED)

**Status: NOT_EXECUTED.** `az` CLI is not even installed on this
machine (confirmed: `which az` returns nothing). No Azure resources
were created. Gated on Phase 14B (GCP) completing first, per spec §30's
"after primary GCP qualification."

## OWNER ACTION REQUIRED — AZURE

```
Provider: Azure
Purpose: Second-cloud portability qualification (Phase 14C) -- limited
         subset: deploy, health/readiness, multi-replica, artifact/
         checkpoint verification, smoke test
Resource: An Azure subscription, a resource group, a region, AKS quota
          (a small node pool)
Authentication method preferred: an authenticated `az` CLI session
          (`az login`) under the owner's own account, or a managed
          identity / service principal with least-privilege RBAC
Secret/API key required in chat: NO
Owner action: install the Azure CLI in an environment this session can
          access (or confirm one is available elsewhere), create/
          designate a subscription and resource group, run `az login`
Verification command: `az account show`
Expected cost category: a minimal AKS node pool for a portability
          smoke test is low-cost; no GPU node planned for this
          portability subset per spec §30's "do not duplicate the
          entire GCP campaign"
Can continue without this action: YES -- independent of Phase 14A
          local-foundation work; gated on Phase 14B for sequencing,
          not on this checkpoint blocking earlier work
```

Until this action is taken (and the Azure CLI is installed), all Azure
deployment, portability, and reliability testing is **NOT_EXECUTED**.

## Phase 14A.3 update

Same provider-neutral `k8s/distributed-overlay.yaml` base applies —
an AKS-specific overlay would wire the two required database URLs to
Azure Database for PostgreSQL via Azure Key Vault + a CSI secrets
driver. Not created this phase — still gated on the OWNER ACTION
REQUIRED checkpoint above.

## Phase 14A.4 update

Same core-database fail-startup enforcement now applies to
`ORNEUR_DATABASE_URL`. Not created this phase — still gated on the
OWNER ACTION REQUIRED checkpoint above.
