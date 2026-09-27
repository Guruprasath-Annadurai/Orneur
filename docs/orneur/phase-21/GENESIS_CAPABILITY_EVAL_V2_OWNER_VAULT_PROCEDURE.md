# Genesis Capability Eval V2 — Owner Private-Vault Procedure (PREPARATION ONLY — NOT ACTIVATED)

State: the encrypted-artifact backend is IMPLEMENTED + TESTED but **not configured**. This document is a procedure for the owner. Nothing here has been run; no key, secret, vault or corpus exists. **Every value below is a placeholder** (`<LIKE_THIS>`); never paste a real secret into this repository, a chat, a CI log or shell history.

## 0. Preconditions
- Trusted, patched, single-user machine or hardware-backed secret manager. Python environment with `pip install '.[qualification]'`.
- Freeze prerequisites 1–9 are tracked in `GENESIS_CAPABILITY_EVAL_V2_STATUS.json`; this procedure only advances `private_storage_genuinely_configured`.

## 1. Vault location (chosen by the owner, not by the repository)
- Absolute path `<VAULT_DIR>` on encrypted local storage or an owner-controlled mount, **outside every git working tree** and outside the ORNEUR repository, not synced to a public location, not under a backup that lacks access control.
- Parent directory `0700`, owned by the qualification-runner user. No path is committed to the repository.

## 2. Permissions
- Directories `0700`, ciphertext files `0400`, no group/world bits, no plaintext siblings, no `.tmp-*` leftovers (the vault scan enforces all of this).

## 3. Secret-manager requirements
- Two custodians; audit log on read; versioned secrets; access limited to the registered qualification-runner identity; **CI and public workflows never receive these secrets**; secrets never appear in workflow inputs, logs or artifacts.
- Secret names (placeholders): `ORNEUR_GENESIS_V2_ENCRYPTION_KEY`, `ORNEUR_GENESIS_V2_CORPUS_SECRET`, `ORNEUR_GENESIS_V2_STORE_TOKEN` (only if a remote store is used).

## 4. Key and corpus-secret generation (run by the owner, on the trusted machine)
```bash
# AES-256 key: 32 random bytes, written straight into the secret manager (placeholder command, NOT executed here)
openssl rand -hex 32 | <SECRET_MANAGER_CLI> put ORNEUR_GENESIS_V2_ENCRYPTION_KEY --stdin
# corpus secret: >= 32 random bytes, generated once, same handling
openssl rand -hex 32 | <SECRET_MANAGER_CLI> put ORNEUR_GENESIS_V2_CORPUS_SECRET --stdin
```
Never echo these values, never store them in a file inside a repository, and never generate them in CI. The secret is validated by `orca.eval.genesis_v2.secret.validate_secret` (length, diversity, not public-derivable).

## 5. Preflight and expected output
```bash
python scripts/genesis_v2_preflight.py                       # expect exit 0 and status PRIVATE_STORAGE_CONFIGURED_UNVERIFIED (env vars present, valid entropy)
python scripts/genesis_v2_vault_verify.py --vault <VAULT_DIR>  # expect exit 0 and "VAULT ISOLATION PASS"
```
- Unconfigured today: preflight exits **2** with `PRIVATE_STORAGE_NOT_CONFIGURED` listing what is missing. Any vault check false ⇒ `VAULT ISOLATION FAIL`, exit 2.
- `CONFIGURED_UNVERIFIED` is not proof of privacy: the owner independently confirms access control on the vault and the secret manager.

## 6. Proving public Git cannot reach the vault
`vault_verify` checks: absolute, existing, non-symlink directory; real path outside the repository tree; **not inside any git work tree**; no tracked symlink resolves into the vault; no `.enc` artifact tracked or untracked in the repo; vault permissions and no plaintext siblings. Independently: `git -C <REPO> ls-files | grep -c '\.enc$'` must print `0`, and `git -C <VAULT_DIR> rev-parse --is-inside-work-tree` must fail. The public CI privacy scan additionally fails on any `.enc`, corpus path or secret in the repo.

## 7. Runner credential scope and identity registration
- One dedicated runner identity with read-only access to the vault and the two secrets; no push rights; no other repository access; no provider or GPU credentials unless a signed model-execution authorization allows them.
- Register the runner as a pre-registered process (`process_id`, `code_sha256`, allowed purposes and splits) in the frozen preregistration (`runner_identity` binding). Only that identity may open `SCREEN` / `QUALIFICATION_HOLDOUT` (access ledger enforces it).

## 8. Backup, recovery, rotation
- Backup: ciphertext-only via `EncryptedFileStore.export_backup`, key backed up separately with two custodians, never together. Recovery: restore the three `.enc` files and read with key + pre-registered corpus digest.
- Rotation: key rotation = create a **fresh corpus version** under a new key (never re-encrypt in place, ledger and commitments are bound to the corpus digest); rotate the store token every 90 days or on personnel change.
- Key loss = corpus loss ⇒ fresh corpus version.

## 9. Emergency revocation
1. Revoke the runner's secret-manager grant and store token. 2. Disable the runner identity. 3. Remove the affected key from the secret manager (keep an audit copy of *metadata*, not the key). 4. Record the event (ledger anchor + incident record). 5. Treat the corpus as burned if any secret was exposed.

## 10. What is a privacy incident
Any of: private prompts/answers/ground truth/seeds/keys/secrets appear in git, a CI log, an artifact, a chat, a screenshot or a public file; the vault or a backup becomes readable by an unregistered identity; a private item is sent to any external service; the access ledger shows an access by an unregistered process; the ledger head does not match its anchor.

## 11. Incident response
1. Stop all qualification runs. 2. Preserve evidence (ledger, anchors, logs — not private content). 3. Revoke access (section 9). 4. Determine scope by commitments/ids (never re-publish content). 5. If any item leaked: retire the affected eval version; create a **fresh version with a new corpus secret and vault**; results computed on a leaked corpus are void for private qualification. 6. Record the incident and lessons in the V2 status record; independent audit before resuming.

## 12. Destruction / retirement
After formal retirement of a holdout (ledger `POST_RETIREMENT_DISCLOSURE`), ground truth may be disclosed. To destroy: overwrite-free secure deletion of the ciphertext and **destroy the key custody records first**; record the destruction (corpus id, date, custodians) in the status record. A destroyed corpus can never qualify anything again.
