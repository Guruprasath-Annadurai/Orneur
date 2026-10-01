# GENESIS V2 — Vault Storage Design (ORNEUR Vault, Domain 4)

Status: **DESIGN ONLY — NOT PROVISIONED.** `private_storage_state: "NOT_CONFIGURED"`. This document designs the real storage backend for the already-implemented `store.EncryptedVaultWriter` / `store.EncryptedVaultReader` crypto layer — it does **not** modify that layer. Per the audit's own instruction, the accepted X25519 crypto implementation is not redesigned here.

## 1. What the existing code already requires (constraints, not choices)

From `store.py` (inspected directly, not assumed):

- On-disk layout per corpus: `<vault_dir>/<corpus_id>/{SCREEN.enc, QUALIFICATION_HOLDOUT.enc, SEAL.enc}`.
- `corpus_id` must match `gce2c-[0-9a-f]{16,64}`.
- Directory permissions `0700`, file permissions `0400` — already enforced by the writer/reader code on a POSIX filesystem; any storage backend substituted for a plain local directory must preserve equivalent access-control semantics (bucket policy / object ACL / IAM condition achieving the same "only this one identity can read this one object" property).
- Write-once per `corpus_id`: `EncryptedVaultWriter.write_corpus()` uses `cdir.mkdir(exist_ok=False)` — a second write to the same `corpus_id` must fail, not silently overwrite. Any object-storage backend must preserve this (e.g. refuse-if-exists semantics, or object-lock/versioning configured so an overwrite is detectable even if not technically blocked).
- `KINDS = ("PRIVATE_GITHUB_REPO", "PRIVATE_OBJECT_STORE", "ENCRYPTED_ARTIFACT")` — only `ENCRYPTED_ARTIFACT` has a real operational implementation today; `operational_storage_backend` in `STATUS.json` is already set to `"ENCRYPTED_ARTIFACT"`. This design targets that backend; the other two remain descriptor-only unless a future phase implements real network transport for them (explicitly out of scope here — "the owner supplies it").
- `PrivateStoreConfig.problems()` already rejects an insecure `http://` location and any location matching the public repository slug — the real location chosen below must satisfy those checks.

## 2. Requirements checklist (from the task) mapped to design decisions

| Requirement | Design decision |
|---|---|
| Ciphertext at rest | Already guaranteed by `EncryptedVaultWriter` — nothing written to storage is ever plaintext. |
| X25519 envelope model preserved | Unchanged — this document only chooses *where* the `.enc` files + `SEAL.enc` live, never how they're produced. |
| No plaintext persistence | Structural guarantee: the Vault storage layer never receives plaintext input in the first place (Forge never holds decrypt capability). |
| Write-once semantics | See §1 — refuse-if-exists at the storage layer, matching the existing code's own `mkdir(exist_ok=False)` semantics. |
| Corpus-specific immutable directories/objects | One prefix/directory per `corpus_id`; Tier 1+ should additionally enable object-lock/WORM on that prefix once written. |
| Integrity evidence | Already provided by `SEAL.enc` (the existing seal mechanism, unchanged) plus, at Tier 1+, the storage backend's own content-checksum feature as a second, independent integrity signal. |
| Metadata separation | Corpus content (`SCREEN.enc`/`QUALIFICATION_HOLDOUT.enc`/`SEAL.enc`) lives under `genesis-v2/vault/<corpus-id>/`; evidence (receipts, manifests, ledger exports) lives under a **separate** prefix/bucket, `genesis-v2/evidence/<corpus-id>/` — never co-mingled, so an IAM policy can grant Vault-read without implicitly granting Evidence-read or vice versa. |
| Restricted access | Per `GENESIS_V2_IAM_MATRIX.md` — Generator: write-only to its own corpus prefix. Verifier: read-only. Nobody else. |
| Audit logging | Tier 1+: storage backend's native access-log feature, piped to Sentinel. Tier 0: filesystem access is local-machine-only; owner's own session is the audit trail. |
| Ciphertext-only backup | See `GENESIS_V2_BACKUP_AND_DR_PLAN.md`. |
| Recovery procedure | See `GENESIS_V2_BACKUP_AND_DR_PLAN.md` and `GENESIS_V2_INCIDENT_AND_REVOCATION_RUNBOOK.md`. |
| Revocation procedure | Delete the corpus's vault prefix + its secret-manager key entries; mark the corpus retired in the Evidence Ledger (never silently deleted from evidence — the *fact* that it existed and was retired is itself evidence). |
| Corruption detection | `SEAL.enc` mismatch already causes `EncryptedVaultReader.read_split()` to fail closed (`PrivateStorageIntegrityError`) — unchanged; Tier 1+ adds storage-level checksum verification as a second layer. |
| No public exposure | Default-private bucket/directory at every tier; public-access block enabled at the storage-account level, not just the object level (defense in depth against misconfiguration). |

## 3. Conceptual path structure

```
genesis-v2/
  vault/<corpus-id>/SCREEN.enc
  vault/<corpus-id>/QUALIFICATION_HOLDOUT.enc
  vault/<corpus-id>/SEAL.enc
  evidence/<corpus-id>/generation-receipt.json      # signed, digest-only content
  evidence/<corpus-id>/manifest.json                 # signed corpus manifest
  evidence/<corpus-id>/ledger-export.json            # periodic AccessLedger export
  receipts/<corpus-id>/attestation-record.json       # owner attestation metadata (never the signing key)
```

This mirrors the existing code's own `corpus_id`-keyed addressing scheme (already used by `store.py`) rather than inventing a new one — `genesis-v2/vault/<corpus-id>/...` is a direct, deliberate extension of the local on-disk layout the writer/reader already produce, not a redesign.

## 4. Backend options evaluated

| Backend | Verdict | Reasoning |
|---|---|---|
| Hardened local filesystem (Tier 0 default) | **Recommended for Tier 0** | Already exactly what `store.py` targets today; zero additional cost; strongest "no third party ever touches this" property; weakest availability. |
| Encrypted block storage (local LUKS/FileVault volume) | **Recommended addition at Tier 0/1** | Adds at-rest disk encryption underneath the application-layer X25519 encryption — defense in depth, cheap, no architecture change. |
| Object storage with immutability/WORM (e.g. S3-compatible + Object Lock, or equivalent) | **Recommended for Tier 1+** | Gives write-once enforcement *at the storage layer itself* (not just application-level `mkdir(exist_ok=False)`), immutable retention, geographic redundancy, native access logging. The specific provider is an owner decision (see decision card below) — the property required is "S3-compatible object storage with a genuine object-lock/WORM feature," not a specific brand. |
| Dedicated storage VM (self-managed) | Viable Tier 1 alternative | More operational burden than managed object storage for no clear security benefit at ORNEUR's current scale; only preferred if the owner specifically wants to avoid any managed cloud storage product. |
| Physically separate verifier storage | **Always required, at every tier** | This is not an alternative to the above — it is the standing rule that Witness's local read-side copy of a corpus (post-transfer) must live in storage genuinely separate from Forge's write-side copy, satisfying the Domain 1/2 isolation contract. |

## 5. OWNER DECISION REQUIRED — Vault storage backend

- **Option A**: Tier 0 hardened local filesystem + encrypted volume, no cloud component. Security: strongest custody, weakest availability. Operational: owner manages backups manually. Cost: $0 recurring, optional one-time external-drive cost. **Recommended starting point.**
- **Option B**: Tier 1 S3-compatible object storage with Object Lock, in a dedicated cloud account used for nothing else. Security: strong immutability + availability; custody depends on correctly scoped IAM. Operational: requires real cloud ops discipline. Cost: see `GENESIS_V2_COST_MODEL.md` (typically low tens of USD/month at Genesis V2's data volumes).
- **Option C**: Dedicated self-managed storage VM with encrypted block storage. Security: comparable to B for confidentiality, weaker for immutability unless the owner builds WORM semantics manually. Operational: higher burden than B. Cost: comparable to a small cloud VM.

**Technical recommendation**: start at Option A now (no cost, no new account, matches current `NOT_CONFIGURED` state exactly), graduate to Option B only when/if the owner wants real multi-machine availability and is ready to take on a dedicated cloud account for it.
