# Genesis Capability Eval V2 — Private Corpus Storage, Backup and Recovery Policy

Backend qualified in this phase: **encrypted artifact outside the repository**, using an X25519 write-only / read-only key split (`orca.eval.genesis_v2.store.EncryptedVaultWriter` for writing, `orca.eval.genesis_v2.store.EncryptedVaultReader` for reading). It is qualified by tests only; **no real vault exists and no key or corpus secret has been generated**. `private_storage_genuinely_configured` stays `false` until an owner creates a real vault, generates a real X25519 keypair via `generate_vault_keypair()`, distributes each half to its own separately-scoped secret-manager entry, and the store is independently verified. The private-GitHub-repo and private-object-store descriptors remain descriptions only (no transport is implemented).

A retired, legacy symmetric-key backend (`orca.eval.genesis_v2.store.EncryptedFileStore`, AES-256-GCM with one key usable for both read and write) still exists in the codebase for the owner's own local, full-capability vault self-test tooling only (`vault_admin.py`'s test-round-trip historically used it; the activation path now uses the real X25519 classes instead — see `GENESIS_CAPABILITY_EVAL_V2_OWNER_VAULT_PROCEDURE.md`). It is never used by `operational_boundary.py`'s generator or creation-time-verification paths, and the `ORNEUR_GENESIS_V2_ENCRYPTION_KEY` environment variable it once read has no effect on the current architecture.

## Key architecture: write-only vs. read capability, cryptographically separated

- One X25519 keypair per vault: a PUBLIC key and a PRIVATE key, generated together by `store.generate_vault_keypair()`.
- `EncryptedVaultWriter(vault_dir, public_key)` can WRITE (encrypt) but holds no private-key material anywhere in its object state and defines no decrypt method — there is no code path by which holding a writer object, however it is inspected, yields plaintext. This is what a generator identity is given.
- `EncryptedVaultReader(vault_dir, private_key)` can READ (decrypt); it defines no `write_corpus` method. This is what a creation-time-verifier or (post-freeze) qualification-runner identity is given — never a generator.
- Per write: a FRESH, one-time X25519 ephemeral keypair is generated, ECDH'd against the vault's public key to derive a one-time AES-256-GCM key via HKDF-SHA256, and the ephemeral private key is discarded immediately (never stored, never reused). The ephemeral PUBLIC key travels in the blob header so a genuine reader (holding the vault's real private key) can reproduce the same derivation.
- A caller holding ONLY the public key has no ECDH path to the same derived key without the vault's private key — this is standard ECIES-style asymmetric encryption, not a bespoke scheme.

## Format and guarantees (largely unchanged from the prior symmetric backend; the key material handling is what changed)

- Cipher: X25519 (key agreement) + HKDF-SHA256 (key derivation) + AES-256-GCM (authenticated encryption), fresh 96-bit random nonce per artifact, fresh ephemeral X25519 keypair per artifact.
- Per corpus: `<vault>/<corpus_id>/{SCREEN.enc, QUALIFICATION_HOLDOUT.enc, SEAL.enc}`; `corpus_id = gce2c-<hex>`.
- The header (eval_version, corpus_id, split, plaintext SHA256, ephemeral public key) is bound as associated data: editing it, swapping split files, or moving ciphertext to another corpus identity fails authentication.
- The SEAL (written last) authenticates the corpus digest (SHA256 over the per-split plaintext digests). A corpus without a valid SEAL is a partial write and is never readable. Reads require the expected corpus digest (the caller takes it from the pre-registration).
- Write-once: a corpus id can be used once; artifacts are published with an atomic `link()` that cannot overwrite. Ciphertext is written to an exclusive temp file (never plaintext), fsynced, linked, temp removed, directory fsynced.
- Directories `0700`, files `0400`. The vault must be outside the repository working tree. `scan_vault_dir` verifies permissions and rejects plaintext siblings and stray temp files.
- Any authentication, truncation, metadata, digest, or wrong-key failure raises `PrivateStorageIntegrityError` (fail closed) with no key/plaintext in the message. Neither `EncryptedVaultWriter` nor `EncryptedVaultReader` can be pickled or copied and their `repr()` is redacted.

## Backup and recovery

- Backups are **ciphertext-only**: `EncryptedVaultReader.export_backup` (note: requires the READER, i.e. the PRIVATE key — the writer/generator cannot produce a backup, since producing one requires reading and verifying the SEAL first) copies the three verified `.enc` files verbatim to a location outside the repository. **No plaintext backup** is ever made.
- Each key half is backed up separately, only in a secret manager, with **two custodians per half**, and the two halves must never share a backup location or access-control group with each other, let alone with the ciphertext.
- Recovery: restore the three ciphertext files into `<vault>/<corpus_id>/` and read with the PRIVATE key and the pre-registered corpus digest; a wrong or missing file, or the wrong key half, fails closed.
- **Private-key loss = corpus loss.** Ciphertext without the private key is unrecoverable by design; the remedy is a fresh corpus version (a new V2.x eval version with new items, under a freshly generated keypair), never reconstruction from public material. Public-key loss alone does not lose the corpus (existing ciphertext still needs only the private key to read), but a lost public key means no FURTHER writes can be sealed for that vault until a fresh keypair is generated — treat it as a rotation event.
- Key compromise: treat the corpus as burned if the PRIVATE key is exposed; retire the eval version and create a fresh corpus version under a newly generated keypair. If only the PUBLIC key is exposed, the corpus itself is not readable by the exposure alone (a public key cannot decrypt), but the generator identity that held it must still be revoked and re-authorized before further writes are trusted.
