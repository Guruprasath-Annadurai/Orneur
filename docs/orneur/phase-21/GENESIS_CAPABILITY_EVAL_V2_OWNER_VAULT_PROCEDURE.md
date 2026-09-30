# Genesis Capability Eval V2 — Owner Private-Vault Procedure (PREPARATION ONLY — NOT ACTIVATED)

State: the encrypted-artifact backend (X25519 writer/reader split — `store.EncryptedVaultWriter` / `store.EncryptedVaultReader`) is IMPLEMENTED + TESTED but **not configured**. This document is a procedure for the owner. Nothing here has been run; no key, secret, vault or corpus exists. **Every value below is a placeholder** (`<LIKE_THIS>`); never paste a real secret into this repository, a chat, a CI log or shell history.

## ⚠️ Legacy symmetric-key setup — retired, do not use

An earlier round of this program used a single symmetric AES key (`ORNEUR_GENESIS_V2_ENCRYPTION_KEY`) that could both encrypt and decrypt. **That architecture is retired.** The current architecture uses a **X25519 keypair split into two roles**: a PUBLIC key (safe for the generator) and a PRIVATE key (restricted to the creation-time verifier / qualification runner). If you find `ORNEUR_GENESIS_V2_ENCRYPTION_KEY` set anywhere — an old script, a stale secret-manager entry, old documentation — **remove it**. It is read by no code path in the current architecture and grants no access on its own, but its presence is a sign of stale tooling that could cause confusion during a real setup. `store.owner_setup_preflight()` actively warns (not silently) if it detects this variable set — see step 5.

## 0. Preconditions
- Trusted, patched, single-user machine or hardware-backed secret manager. Python environment with `pip install '.[qualification]'`.
- Freeze prerequisites 1–9 are tracked in `GENESIS_CAPABILITY_EVAL_V2_STATUS.json`; this procedure only advances `private_storage_genuinely_configured`.

## 1. Vault location (chosen by the owner, not by the repository)
- Absolute path `<VAULT_DIR>` on encrypted local storage or an owner-controlled mount, **outside every git working tree** and outside the ORNEUR repository, not synced to a public location, not under a backup that lacks access control.
- Parent directory `0700`. No path is committed to the repository. The SAME `<VAULT_DIR>` is used by both the generator (write) and the verifier/qualification-runner (read) — they differ in which KEY they hold, not in which directory they access.

## 2. Permissions
- Directories `0700`, ciphertext files `0400`, no group/world bits, no plaintext siblings, no `.tmp-*` leftovers (the vault scan enforces all of this — unchanged from the prior architecture; permissions are a property of the on-disk ciphertext, independent of which key produced it).

## 3. Secret-manager requirements — the two-key split

Two SEPARATE secret-manager entries, with **separate access-control policies**, not one entry read by two roles:

| Secret | Env var | Who may read it | What it is for |
|---|---|---|---|
| Vault **public** key | `ORNEUR_GENESIS_V2_VAULT_PUBLIC_KEY` | The generator's deployment (CI job / runner) that WRITES `SCREEN`/`QUALIFICATION_HOLDOUT` content | X25519 public key, 32 bytes hex. Can encrypt; cannot decrypt anything with it — see `store.EncryptedVaultWriter`'s own docstring for why this is a mathematical fact, not a convention. |
| Vault **private** key | `ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY` | ONLY the creation-time-verifier deployment and, later, a real qualification-runner deployment — **never the generator's deployment** | X25519 private key, 32 bytes hex. Required to decrypt anything. |
| Corpus secret | `ORNEUR_GENESIS_V2_CORPUS_SECRET` | The benchmark-generation process only | ≥32 random bytes; unrelated to the vault keypair — this seeds item generation, not storage encryption. |
| Store token (remote backends only) | `ORNEUR_GENESIS_V2_STORE_TOKEN` | Only if a remote store (not `ENCRYPTED_ARTIFACT`) is used | Least-privilege credential for that remote store. |

General requirements (both key entries): two custodians; audit log on read; versioned secrets; **CI and public workflows never receive these secrets**; secrets never appear in workflow inputs, logs or artifacts. The critical NEW requirement in this architecture: **the private-key entry's access policy must name a strictly smaller set of identities than the public-key entry's** — if your secret manager would let the generator's service account read the private key, the access-control policy is wrong, independent of anything this codebase can enforce in software. Verify this explicitly (see step 7).

## 4. Key generation (run by the owner, on the trusted machine)

```bash
# Generates ONE X25519 keypair and writes each half to its OWN secret-manager entry with its OWN access policy.
# (Placeholder commands, NOT executed here.) The private() function's return value MUST be piped straight to a
# secret-manager scoped to the verifier/qualification-runner identity; the public() value is separately scoped to
# the generator identity. Do not write both to the same secret or the same access-controlled group.
python -c "
from orca.eval.genesis_v2.store import generate_vault_keypair
priv, pub = generate_vault_keypair()
import sys
sys.stderr.write('private (verifier/qualification-runner ONLY, pipe to its own secret): ' + priv.hex() + chr(10))
sys.stderr.write('public  (generator, safe to distribute to that identity): ' + pub.hex() + chr(10))
" 2>&1 | <SECRET_MANAGER_CLI> put-both --split-by-line \
    ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY:<VERIFIER_SCOPE> \
    ORNEUR_GENESIS_V2_VAULT_PUBLIC_KEY:<GENERATOR_SCOPE>

# corpus secret: unrelated to the vault keypair, generated separately, same handling
openssl rand -hex 32 | <SECRET_MANAGER_CLI> put ORNEUR_GENESIS_V2_CORPUS_SECRET --stdin
```

Never echo these values, never store them in a file inside a repository, and never generate them in CI. `python -c "..."` above is illustrative — the point is that the script MUST NOT print the private key to a location the generator's identity can read (stdout piped to a shared CI log, for instance, defeats the entire point of the split). Generate on a trusted machine, pipe directly into the secret manager, never leave a copy on disk. The corpus secret is validated by `orca.eval.genesis_v2.secret.validate_secret` (length, diversity, not public-derivable); the vault keypair's SHAPE (64 hex chars each) and MATCH (the private key genuinely derives the stated public key) are validated by `store.owner_setup_preflight()` — see step 5.

## 5. Preflight and expected output
```bash
python scripts/genesis_v2_preflight.py                       # expect exit 0 and status PRIVATE_STORAGE_CONFIGURED_UNVERIFIED
python scripts/genesis_v2_vault_verify.py --vault <VAULT_DIR>  # expect exit 0 and "VAULT ISOLATION PASS"
```
- Unconfigured today: preflight exits **2** with `PRIVATE_STORAGE_NOT_CONFIGURED`, listing `ORNEUR_GENESIS_V2_VAULT_PUBLIC_KEY` and `ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY` (among others) as missing.
- If the two key values are present but do not form a genuine keypair (a copy-paste error, an old key half paired with a new one), preflight reports `"does not match the supplied private key"` against `ORNEUR_GENESIS_V2_VAULT_PUBLIC_KEY` and still reports `PRIVATE_STORAGE_NOT_CONFIGURED` — a mismatched pair is never accepted as configured.
- If `ORNEUR_GENESIS_V2_ENCRYPTION_KEY` (the legacy symmetric var) is set anywhere in the environment preflight runs in, the report's `warnings` list includes an entry naming it explicitly — check for this on every environment you run preflight in, not just the one you intend to configure.
- Any vault isolation check false ⇒ `VAULT ISOLATION FAIL`, exit 2.
- `CONFIGURED_UNVERIFIED` is not proof of privacy: the owner independently confirms access control on the vault and BOTH secret-manager entries, with their DIFFERENT scopes (step 3).

## 6. Proving public Git cannot reach the vault
`vault_verify` checks: absolute, existing, non-symlink directory; real path outside the repository tree; **not inside any git work tree**; no tracked symlink resolves into the vault; no `.enc` artifact tracked or untracked in the repo; vault permissions and no plaintext siblings. Independently: `git -C <REPO> ls-files | grep -c '\.enc$'` must print `0`, and `git -C <VAULT_DIR> rev-parse --is-inside-work-tree` must fail. The public CI privacy scan additionally fails on any `.enc`, corpus path or secret in the repo. None of this changed with the key-split — isolation is a property of the DIRECTORY, orthogonal to which key any given process holds.

## 7. Credential-boundary verification (the step this architecture specifically adds)

Before generating any real content, verify — on the actual deployment, not just by reading this document:

1. **The generator's deployment environment has `ORNEUR_GENESIS_V2_VAULT_PUBLIC_KEY` set and does NOT have `ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY` set, accessible, or derivable.** Check the generator's actual secret-manager grant, not just its env-var list — a broader IAM role that happens to also grant the private-key secret defeats the split even if the generator's own script never reads it.
2. **The creation-time-verifier identity is registered in `QUALIFICATION_RUNNER_REGISTRY.json` with `allowed_purposes` that do NOT include `QUALIFICATION_RUN`** (only `CREATION_TIME_VERIFICATION`) — `operational_boundary.authorized_manifest_verification_bytes()` enforces this in code (denies a dual-purpose identity), but the registry entry itself is owner-authored, so get it right at registration time.
3. **The real qualification-runner identity (used only after V2 is frozen) is a DIFFERENT `runner_id` than the creation-time verifier**, even though both may legitimately hold the private key. Register them as separate rows.
4. **One dedicated generator identity** with write-only access to the vault (public key + the vault directory's write path) and the corpus secret; no read access to `ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY`; no push rights beyond what `generator_registry.py`'s `credential_scope` declares (`vault_read: false` is REQUIRED and validated); no provider or GPU credentials unless a signed model-execution authorization allows them.
5. Register the generator as a pre-registered process (`generator_id`, `code_sha256`, `allowed_artifact_classes`, `credential_scope`) in `CORPUS_GENERATOR_REGISTRY.json`, and the qualification runner as a pre-registered process in the frozen preregistration (`runner_identity` binding) AND in the access ledger's registry. Only a genuinely `AUTHORIZED` identity in each respective registry can act — the code enforces this; the owner's job is to keep the registry rows honest.

Synthetic demonstrations of every check above (using ephemeral test keys, never real ones) are in `tests/test_genesis_v2_identity_credential_boundaries.py`.

## 8. Public vs. private output path — do not conflate them

`PILOT_TRAIN` and `DEV` are **public** splits: they are never encrypted, never go through this vault, and never need either key. They are written as ordinary files, reviewed via a normal commit/PR like any other repository change (see `GENESIS_V2_OUTPUT_PATHS.md`). Only `SCREEN` and `QUALIFICATION_HOLDOUT` go through the encrypted vault described in this document. A generator authorized ONLY for `PILOT_TRAIN`/`DEV` is never even handed a vault-capable write object — see `operational_boundary.protected_generate_write_handle()`'s own docstring.

## 9. Backup, recovery, rotation
- Backup: ciphertext-only via `EncryptedVaultReader.export_backup` (requires the PRIVATE key — a generator, holding only the public key, cannot produce a backup; this is deliberate, since a backup is a form of read), key backed up separately with two custodians per key half, never together, never across the two halves either. Recovery: restore the three `.enc` files and read with the PRIVATE key + pre-registered corpus digest.
- Rotation: key rotation = generate a fresh X25519 keypair and create a **fresh corpus version** under it (never re-encrypt in place, ledger and commitments are bound to the corpus digest); rotate the store token every 90 days or on personnel change. Rotating ONLY the public key (leaving old ciphertext under the old keypair) makes no sense in this scheme — the keypair is a unit; treat a rotation as a full fresh-corpus-version event, same as the prior architecture's key rotation.
- Private-key loss = corpus loss (nothing can decrypt it). Public-key loss alone does not lose the corpus (a new public key can be generated and used for FUTURE writes, but existing ciphertext still needs the ORIGINAL private key to read) — do not treat public-key loss as equivalent to private-key loss; they have different blast radii.

## 10. Emergency revocation
1. Revoke the affected identity's secret-manager grant (the private-key grant if a verifier/qualification-runner credential is compromised; the public-key grant if a generator credential is compromised — these are now separately revocable, unlike the prior single-key scheme). 2. Disable the runner/generator identity in its registry (`state` → `REVOKED`). 3. Remove the affected key half from the secret manager (keep an audit copy of *metadata*, not the key). 4. Record the event (ledger anchor + incident record). 5. Treat the corpus as burned if the PRIVATE key was exposed; if only the PUBLIC key was exposed, the corpus is NOT automatically burned (the public key cannot decrypt), but the compromised generator identity must still be revoked and any writes it made after compromise must be treated as untrusted pending re-authorization.

## 11. What is a privacy incident
Any of: private prompts/answers/ground truth/seeds/keys/secrets appear in git, a CI log, an artifact, a chat, a screenshot or a public file; the vault or a backup becomes readable by an unregistered identity; the PRIVATE key becomes accessible to the generator's identity or any identity not in step 7's list; a private item is sent to any external service; the access ledger shows an access by an unregistered process; the ledger head does not match its anchor.

## 12. Incident response
1. Stop all qualification runs. 2. Preserve evidence (ledger, anchors, logs — not private content). 3. Revoke access (section 10). 4. Determine scope by commitments/ids (never re-publish content). 5. If any item leaked: retire the affected eval version; create a **fresh version with a new corpus secret and a fresh vault keypair**; results computed on a leaked corpus are void for private qualification. 6. Record the incident and lessons in the V2 status record; independent audit before resuming.

## 13. Destruction / retirement
After formal retirement of a holdout (ledger `POST_RETIREMENT_DISCLOSURE`), ground truth may be disclosed. To destroy: overwrite-free secure deletion of the ciphertext and **destroy BOTH key-custody records first** (public and private); record the destruction (corpus id, date, custodians) in the status record. A destroyed corpus can never qualify anything again.
