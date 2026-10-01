# Tier 1 — Witness (Creation-Time Verifier) compute skeleton (design only, not applied)

Planned module inputs (not yet written as `.tf`): `witness_identity_principal`, `verifier_code_image_digest` (pinned, never `latest`), `network_egress_allowlist` (vault-transfer + evidence-ledger destinations only), `vault_read_only_credential_ref`, `private_key_secret_ref` (a reference into the secrets manager, never an inline value — see `GENESIS_V2_SECRET_CUSTODY_PLAN.md`).

Must be provisioned in a genuinely separate account/project from `../forge/` — see `GENESIS_V2_TRUST_DOMAIN_MODEL.md` Domain 2 and `GENESIS_V2_REAL_DEPLOYMENT_ACCEPTANCE.md` item 3.

No `provider` block, no `resource` block, no real account identifier exists anywhere in this directory.
