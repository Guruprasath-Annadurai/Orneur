# Genesis V2 — 20-item real-deployment acceptance status after the Tier-0 foundation phase

Statuses: `PROVEN_REAL` · `PROVEN_SYNTHETIC_ONLY` · `PARTIAL` · `NOT_YET_PROVEN` · `OWNER_ACTION_REQUIRED`.
**No item is `PROVEN_REAL`.** A passing Python/container test on synthetic fixtures is never promoted to real proof. Evidence = `tests/test_genesis_v2_tier0_local.py` (container tests are local, opt-in) plus the prior synthetic suites.

| # | Item | Status | Basis and what is still missing |
|---|---|---|---|
| 1 | Generator environment exists | `PROVEN_SYNTHETIC_ONLY` | Synthetic Forge container with its own image/UID/mounts. No real Generator credentials or real environment exist. |
| 2 | Verifier environment exists | `PROVEN_SYNTHETIC_ONLY` | Synthetic Witness container, likewise. |
| 3 | Roles are different | `PARTIAL` | Distinct container UIDs and PID/NET/MNT/IPC namespaces, running concurrently. Same host user, same kernel, same machine; no distinct host OS users. |
| 4 | Generator has public key only | `PROVEN_SYNTHETIC_ONLY` | Forge volume holds only `vault_public_key` + synthetic corpus secret; no private-key path. Real keys do not exist yet. |
| 5 | Verifier has private key only | `PROVEN_SYNTHETIC_ONLY` | Witness volume holds only the ephemeral private key; corpus secret absent. |
| 6 | Generator cannot access verifier secret | `PROVEN_SYNTHETIC_ONLY` | Mount-level: the Witness secret volume is not mounted in Forge. Holds only against container compromise short of a kernel/daemon escape. |
| 7 | Verifier cannot access generator corpus secret | `PROVEN_SYNTHETIC_ONLY` | Same, inverted. |
| 8 | Owner key exists outside both | `OWNER_ACTION_REQUIRED` | No real owner key exists (not created by design). A synthetic stand-in volume mounted into neither role is not evidence of a real key's custody. |
| 9 | Encrypted write succeeds | `PROVEN_SYNTHETIC_ONLY` | Forge writes via `EncryptedVaultWriter`; ciphertext only. |
| 10 | Ciphertext transfer succeeds | `PROVEN_SYNTHETIC_ONLY` | Key-less courier copies only magic-prefixed ciphertext with expected names; refuses plaintext/foreign files (tested). |
| 11 | Verifier decrypt succeeds | `PROVEN_SYNTHETIC_ONLY` | Witness decrypts both splits and checks digests with the ephemeral key. |
| 12 | Wrong identity decrypt fails | `PROVEN_SYNTHETIC_ONLY` | Wrong key and wrong digest both fail closed; Forge's own material cannot decrypt. |
| 13 | Backup receives ciphertext only | `PROVEN_SYNTHETIC_ONLY` | Local-volume Reliquary: ciphertext + manifest only; sentinel scan finds no plaintext in any persisted volume. A real external encrypted-drive backup is an owner deployment item. |
| 14 | Restore succeeds | `PROVEN_SYNTHETIC_ONLY` | Restore into a fresh volume, then Witness decrypts from the restored copy. Real restore from a real drive is not performed. |
| 15 | Unexpected network egress is blocked | `PARTIAL` | Per-container `--network none`: no TCP egress, no DNS, no published ports (probed + inspected). No host firewall exists (needs root). |
| 16 | Process isolation verified | `PARTIAL` | Container namespaces/UIDs/caps/no-new-privileges verified by inspection and in-container probes. Shared Linux VM kernel; same host user; not physical separation. |
| 17 | OS/file permissions verified | `PROVEN_SYNTHETIC_ONLY` | In-VM filesystem: vault dirs `0500`, files `0400`, no group/other bits, correct owners. Host-filesystem permissions of a real vault location are not yet established. |
| 18 | Evidence bundle captured | `PROVEN_SYNTHETIC_ONLY` | Witness writes digest-only evidence; prior full synthetic CGA+manifest+receipt E2E test. No real evidence ledger exists. |
| 19 | Cleanup cannot delete unrelated data | `PROVEN_SYNTHETIC_ONLY` | Teardown removes only resources labeled with this run id; pre-existing containers/volumes verified unchanged. |
| 20 | No real corpus content was used | `PARTIAL` | **Unchanged.** Structural/static checks plus staged build context containing no corpus material cannot prove independent authorship of every literal. Owner provenance confirmation not performed. |
