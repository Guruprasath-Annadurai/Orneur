# GENESIS V2 — Backup & Disaster Recovery Plan (ORNEUR Reliquary, Domain 6)

Status: **DESIGN ONLY — NOT PROVISIONED.**

## 1. Principles

- Ciphertext only, always. The Reliquary never receives a private key, a corpus secret, or plaintext. A compromised backup account must not reveal anything the attacker couldn't already get from a copy of the ciphertext alone (which is to say: nothing, per the existing X25519 design).
- Independent credentials from the primary Vault — a Backup Writer identity that can only write to the Reliquary, never read the primary Vault beyond what it's actively backing up, and never write back to the primary Vault at all (one-directional, see `GENESIS_V2_NETWORK_POLICY.md`).
- Geographically or provider-isolated where the tier justifies it — Tier 1+ backup should not share a cloud account, region, or even provider with the primary Vault, so a single provider-level incident cannot take out both copies.
- Immutable retention where the backend supports it (object-lock/WORM), same as the primary Vault.
- No automatic private-key replication into backup storage, ever — this is a hard rule, not a configuration option.
- Restore drills on a schedule, not only "when needed" — an untested backup is not a backup.
- Integrity comparison on every restore drill: the restored ciphertext's digest must match the Evidence Ledger's recorded digest for that corpus, independently of the backup system's own claimed integrity.
- Explicit deletion/revocation procedure that actually removes the backup copy (see Domain-specific destruction notes in `GENESIS_V2_INCIDENT_AND_REVOCATION_RUNBOOK.md`).

## 2. What gets backed up

| Item | Backed up? | Where | Notes |
|---|---|---|---|
| `SCREEN.enc` / `QUALIFICATION_HOLDOUT.enc` / `SEAL.enc` per corpus | **Yes** | Reliquary | Ciphertext only |
| X25519 private key | **No** | n/a | Key custody is handled in `GENESIS_V2_SECRET_CUSTODY_PLAN.md`, deliberately separate from ciphertext backup |
| X25519 public key | Optional | Reliquary or just re-derivable from the private key's owner-side record | Low value to back up separately since it's public and cheap to re-derive/re-publish |
| Corpus secret | **No** | n/a | Secret-manager's own backup policy (`GENESIS_V2_SECRET_CUSTODY_PLAN.md`), never the Reliquary |
| Evidence Ledger records, signed receipts, signed manifests | **Yes** | A separate evidence-backup path (still ciphertext-adjacent in the sense that none of it is plaintext corpus content, but it is not corpus ciphertext either — keep the prefixes separate per `GENESIS_V2_VAULT_STORAGE_DESIGN.md` §3) | This is the provenance trail; losing it is nearly as bad as losing the corpus, since a corpus without its evidence chain is no longer trustworthy output |
| Owner signing key | **No** | n/a | Owner's own custody plan only (hardware-token vendor backup, or a written recovery phrase in a physical safe) — never the Reliquary, never any shared infrastructure |

## 3. Tiered design

- **Tier 0**: a single external encrypted drive (e.g. FileVault/VeraCrypt-encrypted), stored physically separate from the primary machine (a different room/building at minimum), updated after every generation event, with a simple written checklist the owner follows manually. Cost: one-time drive purchase (~$50–150).
- **Tier 1**: automated, scheduled ciphertext sync to a second cloud account/provider from the primary Vault, with object-lock retention matching or exceeding the primary Vault's. Quarterly restore drills, logged in the Evidence Ledger as their own evidence class ("backup verification").
- **Tier 2**: multi-region, multi-provider replication with automated integrity comparison and alerting on drift; a documented, rehearsed full-DR exercise (not just a restore-one-corpus drill) at least annually.

## 4. Restore procedure (design)

1. Owner (or delegated Backup Reader / Restore Operator, Tier 1+) initiates an explicit, out-of-band restore request — never an automatic failover for Genesis V2's write-rarely, verify-carefully workload.
2. Ciphertext is copied from Reliquary into a **fresh**, separate staging location — never directly back into the live primary Vault path, to avoid silently reintroducing a corrupted or stale copy.
3. `SEAL.enc` / digest verification is run against the restored copy using the existing `store.EncryptedVaultReader` integrity checks, and separately cross-checked against the Evidence Ledger's recorded digest for that corpus.
4. Only after both checks pass does the restored copy become the new primary Vault copy, with the restore event itself logged as evidence.

## 5. Data destruction (see also `GENESIS_V2_INCIDENT_AND_REVOCATION_RUNBOOK.md`)

When a corpus is retired:
- Ciphertext deleted from the primary Vault and the Reliquary (both copies, explicitly, not just one).
- Any object-lock/retention hold is respected — if the backend's immutability window hasn't elapsed, deletion is deferred to the window's end and tracked as a pending-deletion evidence record, not silently skipped.
- Key destruction (deleting the X25519 keypair from secret management) is the **stronger and preferred guarantee** over attempting to overwrite every cloud replica of the ciphertext: once the private key is genuinely destroyed (and no other copy exists per the custody plan), every remaining ciphertext copy anywhere is permanently unrecoverable by design, regardless of whether every physical/cloud replica of the ciphertext itself has been individually located and erased. This document states that guarantee explicitly rather than implying a false promise of literal ciphertext erasure from every possible cloud snapshot/replica.
- Evidence Ledger retention is **not** deleted when a corpus is retired — the ledger's record that corpus X existed, was generated under authorization Y, and was later retired is itself part of ORNEUR's audit trail and is kept per the owner's chosen legal/audit retention policy.

## 6. Disaster scenarios (see also final report §I / `GENESIS_V2_THREAT_AND_COMPROMISE_MATRIX.md`)

| Scenario | Recoverable? | From where | Never reconstructed | Abandon-and-regenerate threshold |
|---|---|---|---|---|
| Generator (Forge) destroyed | Yes | Rebuild from pinned code digest + registry re-authorization | Nothing was irrecoverable there — Forge never held decrypt capability | n/a — Forge loss alone never forces corpus regeneration |
| Verifier (Witness) destroyed | Yes | Rebuild from pinned code digest; re-provision the X25519 private key from the owner's secure backup of the keypair-generation event | The private key itself, if the owner's own backup of it was also lost — see custody plan | If the private key is truly gone and no backup exists, the corpus under that key must be regenerated under a fresh keypair |
| Primary Vault lost | Yes | Restore from Reliquary (§4) | n/a | If Reliquary is also lost/corrupted, regenerate |
| Evidence store lost | Partially | Re-derive what's re-derivable (code hashes, registry state) from git history; the owner's and verifier's own signed records if they kept local copies | The precise sequence/timing evidence if no copy survives anywhere | Treat any corpus whose full evidence chain cannot be reconstructed as **evidentially unproven**, even if the ciphertext itself survives — do not claim it as authorized-generation output |
| Owner signing workstation/token lost | Partially | A second registered authority key (`DELEGATED_OWNER`), if the owner has set one up in advance, can continue operations | The lost key's private material — never reconstructed; it is revoked (`revoked: true`) and replaced | n/a — this does not force corpus regeneration by itself, but does require revocation + re-registration before any *new* authorization can be signed |
| Backup corrupted | Yes, from primary | Primary Vault, if still intact | n/a | If both primary and backup are corrupted/lost, regenerate |
| Cloud provider outage (Tier 1+) | Yes, if multi-provider | The non-affected provider's copy | n/a | n/a, assuming the multi-provider design was actually followed |
| GitHub unavailable | Yes, temporarily | Local clones of the repository (every contributor/CI runner has one); GitHub is not the sole copy of anything code-level | n/a | n/a — GitHub is a convenience substrate for registries/evidence snapshots, not Genesis V2's only copy of anything |
