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

## 4. Key generation (run by the owner, on the trusted machine, OWNER-CONTROLLED CONTEXT ONLY)

**This section describes a PROCEDURE, not an executable script.** This document cannot know which secret manager
you use, so it deliberately does NOT give you a copy-pasteable shell command that combines both key halves into one
stream — doing so was a real mistake in an earlier draft of this document (both halves printed to `stderr` and piped
through a single combined-stream shell redirect into a fictitious two-value-at-once command that no real secret manager provides). Follow
the procedure below with YOUR secret manager's own SDK; do not invent a CLI incantation to make it look executable.

**Procedure:**

1. On the trusted machine, in a single interactive Python process (or a script whose entire output is consumed
   programmatically — never a script that `print`s to a terminal or a shared log), call `generate_vault_keypair()`:
   ```python
   from orca.eval.genesis_v2.store import generate_vault_keypair
   priv, pub = generate_vault_keypair()
   ```
2. Pass `priv` and `pub` DIRECTLY, as in-memory Python values, to your secret manager's own SDK create/put call —
   e.g. (illustrating the SHAPE of such a call, not any specific real SDK) `secret_client.create_secret(name=...,
   value=priv.hex())`. Make TWO SEPARATE calls, to TWO SEPARATE secret entries with DIFFERENT access-control
   policies (see step 3's table). Do this in the SAME process that generated the keys — never write `priv`/`pub` to
   a variable that outlives this step, never `print()`/`sys.stdout.write()`/`sys.stderr.write()` either value, never
   combine both values into one output stream or one combined-redirect pipe.
3. If your secret manager's ONLY interface is a CLI that reads a single secret from stdin, pipe ONE value at a time,
   directly from the Python process that generated it, with your shell's history disabled for that command (e.g.
   `set +o history`, or run in a subshell with `HISTFILE=/dev/null`) — and run this as two entirely separate
   invocations for the two halves, never as one combined pipeline.
4. Once you know your actual secret-manager provider, replace this section with THAT provider's own real, tested,
   executable single-secret-write command. Until then, this section stays deliberately non-executable prose — do
   not treat any code block above as a command to paste into a terminal.

```bash
# The corpus secret is a SEPARATE, single random value (unrelated to the vault keypair) with no combined-stream
# risk -- one value flows through one pipe. This pattern IS safe to use as-is once <SECRET_MANAGER_CLI> is your
# real CLI's name: a single `openssl rand` output piped once into a single secret write.
openssl rand -hex 32 | <SECRET_MANAGER_CLI> put ORNEUR_GENESIS_V2_CORPUS_SECRET --stdin
```

Never echo any of these values, never store them in a file inside a repository, and never generate them in CI. The
corpus secret is validated by `orca.eval.genesis_v2.secret.validate_secret` (length, diversity, not
public-derivable); the vault keypair's SHAPE (64 hex chars each) and MATCH (the private key genuinely derives the
stated public key) are validated ONLY by `store.owner_setup_preflight()` (the owner-controlled, both-halves-visible
context) — see step 5. That pair-matching check itself fails closed if the `cryptography` package is unavailable or
the key material is otherwise invalid; it never silently treats an unverifiable pair as matching.

## 5. Preflight and expected output — ROLE-SEPARATED, never run the combined check from a real deployment

`scripts/genesis_v2_preflight.py` takes `--role {owner,generator,verifier}`. Each role's preflight checks ONLY that
role's own key material — **a generator's deployment must never be asked for the private key, and a
verifier's/qualification-runner's deployment must never be asked for the public key.** Only `--role owner` checks
both halves together (and is the only role that cross-validates the pair actually matches); run it ONLY in a
context where you, the owner, legitimately have visibility into both halves at once — never as a real generator's
or verifier's own deployment health check.

```bash
# Run FROM the generator's own deployment environment:
python scripts/genesis_v2_preflight.py --role generator   # expect exit 0, status GENERATOR_CONFIGURED_UNVERIFIED,
                                                            # violations: [] (a non-empty violations list here means
                                                            # the private key leaked into this environment -- treat
                                                            # that as a security incident, not a config gap)

# Run FROM the verifier's / qualification-runner's own deployment environment:
python scripts/genesis_v2_preflight.py --role verifier    # expect exit 0, status VERIFIER_CONFIGURED_UNVERIFIED

# Run ONLY in the owner's own, both-halves-visible context (e.g. immediately after key generation, step 4):
python scripts/genesis_v2_preflight.py --role owner       # expect exit 0, status PRIVATE_STORAGE_CONFIGURED_UNVERIFIED

python scripts/genesis_v2_vault_verify.py --vault <VAULT_DIR>  # expect exit 0 and "VAULT ISOLATION PASS"
```
- Unconfigured today: every role's preflight exits **2** (`GENERATOR_NOT_CONFIGURED` / `VERIFIER_NOT_CONFIGURED` /
  `PRIVATE_STORAGE_NOT_CONFIGURED`).
- `--role owner`, given a mismatched pair (a copy-paste error, an old key half paired with a new one), reports
  `"does not match the supplied private key"` and still reports `PRIVATE_STORAGE_NOT_CONFIGURED` — a mismatched
  pair is never accepted as configured. If `cryptography` is not installed, or the key material fails to parse
  despite matching the hex-shape check, the SAME fail-closed report applies — never silently accepted.
- If `ORNEUR_GENESIS_V2_ENCRYPTION_KEY` (the legacy symmetric var) is set in the environment any preflight role runs
  in, the report's `warnings` list includes an entry naming it explicitly — check for this on every environment.
- Any vault isolation check false ⇒ `VAULT ISOLATION FAIL`, exit 2.
- `CONFIGURED_UNVERIFIED` is not proof of privacy: the owner independently confirms access control on the vault and
  BOTH secret-manager entries, with their DIFFERENT scopes (step 3).

## 6. Proving public Git cannot reach the vault
`vault_verify` checks: absolute, existing, non-symlink directory; real path outside the repository tree; **not inside any git work tree**; no tracked symlink resolves into the vault; no `.enc` artifact tracked or untracked in the repo; vault permissions and no plaintext siblings. Independently: `git -C <REPO> ls-files | grep -c '\.enc$'` must print `0`, and `git -C <VAULT_DIR> rev-parse --is-inside-work-tree` must fail. The public CI privacy scan additionally fails on any `.enc`, corpus path or secret in the repo. None of this changed with the key-split — isolation is a property of the DIRECTORY, orthogonal to which key any given process holds.

## 7. Credential-boundary verification (the step this architecture specifically adds)

Before generating any real content, verify — on the actual deployment, not just by reading this document:

1. **The generator's deployment environment has `ORNEUR_GENESIS_V2_VAULT_PUBLIC_KEY` set and does NOT have `ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY` set, accessible, or derivable.** Run `python scripts/genesis_v2_preflight.py --role generator` FROM that deployment and confirm `violations` is empty — a non-empty entry there means the private key IS visible to this environment, a genuine finding, not a checklist item. Also check the generator's actual secret-manager grant, not just its env-var list — a broader IAM role that happens to also grant the private-key secret defeats the split even if the generator's own script never reads it.
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
