# Genesis Capability Eval V2 — Private Corpus Storage, Backup and Recovery Policy

Backend qualified in this phase: **encrypted artifact outside the repository** (`orca.eval.genesis_v2.store.EncryptedFileStore`). It is qualified by tests only; **no real store exists and no key or corpus secret has been generated**. `private_storage_genuinely_configured` stays `false` until an owner creates a real vault, supplies a key from a secret manager, and the store is independently verified. The private-GitHub-repo and private-object-store descriptors remain descriptions only (no transport is implemented).

## Format and guarantees

- AES-256-GCM, 32-byte key, fresh 96-bit random nonce per artifact.
- Per corpus: `<vault>/<corpus_id>/{SCREEN.enc, QUALIFICATION_HOLDOUT.enc, SEAL.enc}`; `corpus_id = gce2c-<hex>`.
- The header (eval_version, corpus_id, split, plaintext SHA256) is bound as associated data: editing it, swapping split files, or moving ciphertext to another corpus identity fails authentication.
- The SEAL (written last) authenticates the corpus digest (SHA256 over the per-split plaintext digests). A corpus without a valid SEAL is a partial write and is never readable. Reads require the expected corpus digest (the caller takes it from the pre-registration).
- Write-once: a corpus id can be used once; artifacts are published with an atomic `link()` that cannot overwrite. Ciphertext is written to an exclusive temp file (never plaintext), fsynced, linked, temp removed, directory fsynced.
- Directories `0700`, files `0400`. The vault must be outside the repository working tree. `scan_vault_dir` verifies permissions and rejects plaintext siblings and stray temp files.
- Any authentication, truncation, metadata or digest failure raises `PrivateStorageIntegrityError` (fail closed) with no key/plaintext in the message. The store object cannot be pickled or copied and its repr is redacted.

## Backup and recovery

- Backups are **ciphertext-only**: `export_backup` copies the three verified `.enc` files verbatim to a location outside the repository. **No plaintext backup** is ever made.
- The key is backed up separately, only in a secret manager, with **two custodians**; key and ciphertext must never share a backup location.
- Recovery: restore the three ciphertext files into `<vault>/<corpus_id>/` and read with the key and the pre-registered corpus digest; a wrong or missing file fails closed.
- **Key loss = corpus loss.** Ciphertext without the key is unrecoverable by design; the remedy is a fresh corpus version (a new V2.x eval version with new items), never reconstruction from public material.
- Key compromise: treat the corpus as burned; retire the eval version and create a fresh corpus version under a new key.
