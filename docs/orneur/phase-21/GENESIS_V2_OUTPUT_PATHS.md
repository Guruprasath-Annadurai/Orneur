# Genesis Capability Eval V2 — Operational Output Paths (PUBLIC vs. PRIVATE)

There are exactly two output paths for generated V2 content, and they never overlap in mechanism. Nothing in this
document is executed today — it clarifies (and is tested against) the code paths already implemented in
`orca/eval/genesis_v2/`, for whoever eventually writes a real generator.

## Path 1 — `PILOT_TRAIN` and `DEV` (public splits)

These are the public splits (`spec.PUBLIC_SPLITS = ("DEV", "PILOT_TRAIN")`). They are **not secret**, **never
encrypted**, and **never go through the private vault module (`store.py`) at all**.

- Output mechanism: ordinary repository files, added and reviewed through a normal commit / pull request, exactly
  like any other change to this repository. No key, no vault directory, no `write_corpus` call, no
  `GeneratorWriteHandle`.
- Authorization for producing them still goes through `operational_boundary.require_authorization()` /
  `check_authorization()` (the signed `CORPUS_GENERATION_AUTHORIZATION` record, generator identity, code-tree hash
  — all of it), because the ARTIFACT CLASS is still gated the same way regardless of privacy level. What differs is
  what happens AFTER authorization succeeds: there is no vault write step for these two classes.
- **Structural guarantee, not just documentation**: `operational_boundary.protected_generate_write_handle()` never
  constructs or retains ANY vault-capable object when `requested_scope` is purely `PILOT_TRAIN`/`DEV` — the returned
  `GeneratorWriteHandle`'s `_store` is `None`. A generator authorized ONLY for these classes cannot reach the
  encrypted vault through this function, structurally, even if it tried — see
  `tests/test_genesis_v2_operational_boundary.py::test_pilot_train_only_generator_gets_a_handle_with_no_vault_object_at_all`.

## Path 2 — `SCREEN` and `QUALIFICATION_HOLDOUT` (private splits)

These are the private splits (`spec.PRIVATE_SPLITS = ("SCREEN", "QUALIFICATION_HOLDOUT")`). They are secret, always
encrypted, and the ONLY path that ever touches `store.py`'s vault classes.

- Write mechanism: `operational_boundary.protected_generate_write_handle()` returns a `GeneratorWriteHandle` wrapping
  a genuinely write-only `store.EncryptedVaultWriter` (holds only the vault's X25519 PUBLIC key). The handle
  re-enforces its own authorized scope at every `write_corpus()` call.
- Read mechanism (creation-time verification only, pre-freeze): `operational_boundary.authorized_manifest_verification_bytes()`
  / `verify_manifest_digest_only_same_process()`, using a `store.EncryptedVaultReader` (holds the vault's X25519 PRIVATE
  key) obtained by a SEPARATELY CONTROLLED, purpose-restricted verifier identity — never the generator.
- Read mechanism (real qualification, post-freeze only): `operational_boundary.require_private_split_access()`,
  gated by the real `ledger.AccessLedger` and a genuinely `AUTHORIZED` qualification-runner identity.

## Why this separation matters operationally

A generator implementation that handles BOTH kinds of output must not share code paths between them: writing
`PILOT_TRAIN` is "commit a file," writing `SCREEN`/`QUALIFICATION_HOLDOUT` is "call `write_corpus()` through a
write-only handle." Conflating them — e.g. routing a `PILOT_TRAIN` write through the vault "just in case," or
writing `SCREEN` content as an ordinary repository file — would defeat the entire privacy boundary this program
exists to build. The tests above hold the code to this separation whether or not any future generator gets it right
on the first attempt.
