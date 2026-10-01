# Tier 1 — Reliquary (Backup) skeleton (design only, not applied)

Planned module inputs (not yet written as `.tf`): `reliquary_bucket_name` (in a provider/account distinct from `../vault/`), `object_lock_enabled` (true), `backup_writer_principal_arns` (one-directional write only — never granted vault-read beyond what it's actively backing up), `restore_operator_principal_arns` (owner-triggered only).

No `provider` block, no `resource` block, no real account identifier exists anywhere in this directory. See `GENESIS_V2_BACKUP_AND_DR_PLAN.md`.
