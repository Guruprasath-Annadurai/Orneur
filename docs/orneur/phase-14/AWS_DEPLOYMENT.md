# Phase 14D — AWS Deployment (NOT EXECUTED — OWNER ACTION REQUIRED)

**Status: NOT_EXECUTED.** AWS CLI is not installed on this machine
(confirmed: `which aws` returns nothing). No AWS resources were
created. Gated on Phase 14B (GCP) completing first, per spec §32's
sequencing.

## OWNER ACTION REQUIRED — AWS

```
Provider: AWS
Purpose: Third-cloud portability + reliability qualification (Phase 14D)
         -- image portability, config, secrets, state connectivity,
         readiness, smoke, artifact validation
Resource: An AWS account, IAM Identity Center (or a scoped IAM role),
          a region, EKS quota OR a simpler container deployment target
          if credits don't justify a full EKS cluster (spec §32
          explicitly permits "appropriately simpler container
          deployment")
Authentication method preferred: AWS IAM Identity Center SSO or a
          temporary-credential CLI profile (`aws sso login`) --
          explicitly NOT permanent AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY
          where avoidable, per spec §33
Secret/API key required in chat: NO
Owner action: install the AWS CLI in an environment this session can
          access, set up IAM Identity Center or a scoped role, run
          `aws sso login` (or equivalent) to establish a session
Verification command: `aws sts get-caller-identity`
Expected cost category: lowest of the three clouds in this plan (10%
          allocation per spec §2) -- a minimal container deployment for
          a portability smoke test only
Can continue without this action: YES -- independent of Phase 14A
          local-foundation work
```

Until this action is taken (and the AWS CLI is installed), all AWS
deployment, portability, and reliability testing is **NOT_EXECUTED**.

## Phase 14A.3 update

Same provider-neutral `k8s/distributed-overlay.yaml` base applies —
an EKS-specific overlay would wire the two required database URLs to
RDS PostgreSQL via AWS Secrets Manager + the Secrets Store CSI driver.
Not created this phase — still gated on the OWNER ACTION REQUIRED
checkpoint above.

## Phase 14A.4 update

Same core-database fail-startup enforcement now applies to
`ORNEUR_DATABASE_URL`. Not created this phase — still gated on the
OWNER ACTION REQUIRED checkpoint above.
