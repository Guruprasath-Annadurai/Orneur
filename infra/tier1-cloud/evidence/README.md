# Tier 1 — Evidence Ledger store skeleton (design only, not applied)

Planned module inputs (not yet written as `.tf`): `evidence_prefix` (separate from the vault prefix — see `GENESIS_V2_VAULT_STORAGE_DESIGN.md` §3), `immutable_retention_days`, `evidence_writer_principal_arns` (Witness's post-verification identity only), `evidence_auditor_principal_arns` (owner, read-only).

Must never store SCREEN/QUALIFICATION_HOLDOUT plaintext, any secret key, the corpus secret, or the owner private key — see `GENESIS_V2_TRUST_DOMAIN_MODEL.md` Domain 5.

No `provider` block, no `resource` block, no real account identifier exists anywhere in this directory.
