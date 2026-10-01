# ORNEUR Genesis V2 — Infrastructure-as-Code skeleton

**Status: this directory provisions NOTHING.** No `terraform apply`, `tofu apply`, or any equivalent has ever been run against any file here. Every `.tf` file below is either absent (not yet written) or, where present, contains only variable/output scaffolding with no provider credentials and no `resource` blocks that could create anything — see each subdirectory's own `README.md`.

This layout exists to give the eventual Tier 1+ cloud provisioning work a reviewed, consistent starting structure, per `docs/orneur/phase-21/infrastructure/GENESIS_V2_PROVIDER_DECISION_MATRIX.md` §4 ("introduce IaC now as a skeleton, not a deployment").

## Layout

```
infra/
  README.md                  — this file
  tier0-local/                — NOT Terraform. Plain, reviewed shell scripts for the $0 local/owner-controlled
                                 setup (Tier 0): directory layout, permission-setting, Docker image build commands
                                 for Forge/Witness. No cloud credentials involved at this tier.
  tier1-cloud/
    vault/                    — skeleton for the dedicated Vault storage account (object storage + Object Lock).
                                 variables.tf and outputs.tf only; no provider block, no resource block.
    forge/                    — skeleton for ephemeral Generator compute.
    witness/                  — skeleton for Verifier compute.
    reliquary/                — skeleton for the backup account.
    evidence/                 — skeleton for the immutable evidence store.
  policy/                     — IAM policy JSON/HCL *templates* (placeholders, not bound to any real account ID).
```

## Rules for anyone extending this directory

1. Never commit a `provider` block with real account/project/subscription identifiers.
2. Never commit a `.tfvars` file with real values — `*.tfvars` is gitignored; only `*.tfvars.example` with placeholder values may be committed.
3. Never commit a state file (`.tfstate`) — state lives in a backend the owner configures separately, never in this repository.
4. Any `resource` block added here must be reviewed against `docs/orneur/phase-21/infrastructure/GENESIS_V2_IAM_MATRIX.md` and `GENESIS_V2_NETWORK_POLICY.md` before merge — least-privilege and default-deny are not optional during review.
5. This skeleton is Terraform/OpenTofu-shaped because that's the most portable choice if/when Tier 1 cloud provisioning actually begins — it does not commit the project to a specific cloud provider, which remains an explicit owner decision (`GENESIS_V2_OWNER_DECISIONS_REQUIRED.md`).

## Why Tier 0 has no IaC

Tier 0 is two local processes, a local encrypted directory, and an external drive. Introducing Terraform to manage that would be complexity without benefit — plain, reviewed shell scripts under `tier0-local/` are the right tool, consistent with this package's explicit rejection of complexity-for-its-own-sake (no Kubernetes, no IaC tool where a documented shell command suffices).
