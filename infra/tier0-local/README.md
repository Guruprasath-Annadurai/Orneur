# Tier 0 — local/owner-controlled setup (design only, not executed)

No script in this directory has been run. This describes the exact commands the owner would run, later, under their own authorization — see `docs/orneur/phase-21/infrastructure/GENESIS_V2_OWNER_SIGNING_CEREMONY.md` and `GENESIS_V2_REAL_DEPLOYMENT_ACCEPTANCE.md` for the procedure these scripts would be run as part of.

## Planned scripts (not yet written — placeholders for the next phase, once the owner approves Tier 0 provisioning)

- `create_forge_user.sh` — creates a dedicated, unprivileged local OS user for the Generator process, with no access to the Verifier's key material.
- `create_witness_user.sh` — creates a dedicated, unprivileged local OS user for the Verifier process, with no access to the Generator's corpus secret.
- `init_vault_directory.sh` — creates the local vault directory with `0700` permissions, owned by neither the Forge nor Witness user directly but mounted/shared per the cross-machine (or cross-user) transfer procedure already documented in `GENESIS_V2_CROSS_MACHINE_TRANSFER_PROCEDURE.md`.
- `build_forge_image.sh` / `build_witness_image.sh` — build minimal, pinned-digest Docker images for each role, following the same discipline already used for `docker/genesis_v2_sandbox/Dockerfile` (pinned digest, hermetic, no network).

None of these exist yet as runnable scripts. They are named here so the IaC layout is legible before they are written, and so review of the *layout* can happen before review of the *content*.
