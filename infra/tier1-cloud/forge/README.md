# Tier 1 — Forge (Generator) compute skeleton (design only, not applied)

Planned module inputs (not yet written as `.tf`): `forge_identity_principal`, `generator_code_image_digest` (pinned, never `latest`), `network_egress_allowlist` (empty by default — see `GENESIS_V2_NETWORK_POLICY.md`), `vault_write_only_credential_ref` (a reference into the secrets manager, never an inline value).

No `provider` block, no `resource` block, no real account identifier exists anywhere in this directory.
