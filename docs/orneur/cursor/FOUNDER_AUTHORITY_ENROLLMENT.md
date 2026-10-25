# Founder authority enrollment

Schema: `orneur-founder-enrollment/2`

Status: `AWAITING_INDEPENDENT_ENROLLMENT`

Operational observation pin: absent

Publisher anchor: absent

Witness identity channel: absent

This document is the ceremony. It is not an enrollment, not a public key, and not a freeze approval. The registering actor that wrote it cannot certify its own authority by committing a key, a fingerprint, a GitHub URL, or this file.

The only scope this ceremony can name is `freeze-amendment-adopt-files/1`. That scope retains three denial documents. It does not authorize training, a GPU, spending, corpus access, or model selection.

Proposal SHA-256: `08daabb09d79c22b241691bc92c8a519f065519303a368cb44e5afb972f6996a`

Historical baseline: `cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d`

| Path | SHA-256 |
| --- | --- |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORITY_REGISTRY.json` | `13874861f20d7eabf7da5ed3f4ef8875046467ee51b6fa165b605a6245c75d84` |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORIZATION.json` | `88d0379632963cd4f871701c74ef55d50d54027f4bd8621e07e623081a61ea49` |
| `docs/orneur/authorization/genesis_native_pretraining/REVOCATIONS.json` | `2b5da1678f8fd35b35fc8a9153ed7c011fc8d776a39be31fbfdccfbf7c9300e3` |

`orneur-founder-enrollment/1` is a legacy schema. `review_enrollment` returns `legacy_schema_refused` and does not verify those bytes as version 2. The publication and witness design is in `docs/orneur/cursor/TRUST_AUTHORITY_BOUNDARY.md`.

## What the founder keeps

The private signing key stays on a machine the founder controls, outside the repository and outside any AI-agent execution context. Do not generate the key in Cursor, in a cloud agent, or in CI. Do not paste the private key into chat, into a pull request, or into an agent prompt. Do not commit a seed, a PKCS#8 file, or a public key and then treat that commit as the enrollment.

Ed25519 is the signature algorithm. The public key is 32 raw bytes, recorded as 64 lowercase hex characters. The fingerprint is the SHA-256 of those raw bytes. The verifier calls `Ed25519PublicKey.verify` on a 64-byte signature over `domain || canonical JSON`.

## Hardware keys are not compatible yet

SSH `ed25519-sk` is not a founder key for this protocol. An SK signature is produced over an SSH/FIDO message, not over the enrollment domain bytes, and it does not verify as a raw Ed25519 signature. `ssh_ed25519_sk_is_not_enrollment_compatible` returns `hardware_sk_not_compatible`. Do not use `ssh-keygen -t ed25519-sk` for this ceremony. No hardware-backed path is claimed until a device is shown to sign those exact bytes and to export a raw 32-byte public key.

## Encrypted software key

`BestAvailableEncryption` does not name a cipher or a KDF. In cryptography 50.0.2 the class stores only a password. On this host, OpenSSL 3.0.13 turned that call into PBES2 with PBKDF2-HMAC-SHA256, AES-256-CBC, and 2048 iterations. That count is OpenSSL's default. A later library can change it without renaming the class, so the ceremony does not use that API and does not describe 2048-round output as the founder key.

`orca.founder_key_store.write_encrypted_software_key` builds the file itself. `describe_encrypted_private_key` reads the algorithm back from the bytes. The file must show:

- PBES2, OID `1.2.840.113549.1.5.13`
- PBKDF2-HMAC-SHA256, OIDs `1.2.840.113549.1.5.12` and `1.2.840.113549.2.9`
- 600000 iterations, a 16-byte salt, and a 32-byte derived key
- AES-256-CBC, OID `2.16.840.1.101.3.4.1.42`, a 16-byte IV

The password is at least 16 bytes and is stored separately from the file. 600000 iterations do not make a short password safe. If `describe_encrypted_private_key` does not report those OIDs and that iteration count, do not use the file.

The writer creates the file with `os.open` flags `O_CREAT|O_EXCL|O_NOFOLLOW|O_WRONLY` and mode `0o600`, through a parent directory opened with `O_DIRECTORY|O_NOFOLLOW`. It refuses a relative path, an existing file, a symlink, a path inside a git worktree, and a path whose name contains Dropbox, iCloud, OneDrive, Google Drive, or Mobile Documents. It does not generate a key. Quit agent sessions before the key exists in process memory. A founder-run call, which this repository does not execute, is:

```python
from pathlib import Path
from orca.founder_key_store import describe_encrypted_private_key, write_encrypted_software_key
destination = Path("/founder-offline/orneur-founder-ed25519.pem")
described = write_encrypted_software_key(destination, key, password)
print(described["kdf"], described["iterations"], described["cipher"])
print(describe_encrypted_private_key(destination.read_bytes())["iterations"])
```

Print only the public key and the fingerprint. The encrypted file and the password stay outside the repository.

## Backup, loss, and revocation

Keep a second encrypted copy on another offline medium the founder controls. Do not put either copy in cloud sync, in the repository, or on a machine an agent can read. Store the password apart from both copies. Losing the password is the same as losing the key. If the file or the password may have been copied, revoke the key and do not reuse it. Revocation, rotation, and recovery are below. None of them enrolls a replacement by itself.

## Offline steps

Run these steps on the founder's machine. The witness uses a different machine. Neither private key is typed into an agent.

1. Install Python 3.11 or newer and a `cryptography` build the founder trusts. Confirm `git config user.email` is not `cursoragent@cursor.com`. Re-read the encrypted file with `describe_encrypted_private_key` before trusting a different cryptography or OpenSSL build.
2. Create the key in a local process and store it only through `write_encrypted_software_key`, outside every git worktree.
3. Choose `identity` and `key_id`. They are not secret. They must match the later freeze-approval fields.
4. The witness is a different person. The witness creates their own encrypted key the same way. Different key bytes, a different identity string, and a different key id do not prove that second person exists. The witness reads their public-key fingerprint aloud from their own screen. The founder writes that fingerprint down. A GitHub account, a git author line, an email address, and a verified badge are not that comparison. This commit has no external witness channel, so operational review returns `witness_identity_unauthenticated`.
5. Build the statement with `statement_of`. Set `scope` to `freeze-amendment-adopt-files/1`, `publication_channel` to `external-signed-receipt`, and `enrolled_at` and `expires_at` in `YYYY-MM-DDTHH:MM:SSZ`. The validity window is at most 366 days. The statement does not contain an observation hash, a signature, or a publication receipt.
6. The founder signs `founder_signing_bytes`. The domain is `orneur-founder-enrollment/2` plus a newline. The witness reads the statement, checks the scope, the baseline, the proposal digest, and the three file digests, then countersigns `witness_signing_bytes` on the witness machine. The witness domain is `orneur-founder-enrollment-witness/2` plus a newline. The witness signature covers the founder signature.
7. Compute `observation_of` only after both signatures exist. Its SHA-256 is `observation_sha256`. The observation binds the founder identity and key id, the founder fingerprint, the witness identity, key id, and fingerprint, both timestamps, the scope, the repository, the baseline, the proposal digest, the publication channel, the statement digest as `publication_immutable_id`, and both signatures. The observation object does not contain `observation_sha256`.
8. A publisher who is neither the founder nor the witness signs a receipt of schema `orneur-founder-publication-receipt/1` over `orneur-founder-publication-receipt/1`. The receipt names the statement digest, the observation digest, and that same statement digest as `immutable_id`. The publisher public key is not placed inside the receipt and is not committed here. A GitHub commit URL, a release URL, git author text, an email, and a verified badge are not a receipt. `github_url_is_not_publication` returns `publication_not_independent`.
9. The publisher key and the witness identity have to be established outside this repository before either one can satisfy operational review. This commit does not establish them. Copying the observation digest into `OPERATIONAL_OBSERVATION_SHA256` does not establish them either. That constant stays `None`.

Committing `docs/orneur/cursor/founder_enrollment/enrollment.json` does not enroll the key. `establish` keeps `operational_authority` false. A caller-supplied public key is `caller_supplied_key_refused`. An identity that starts with `synthetic-` is refused on the operational path. An unauthenticated witness is `witness_identity_unauthenticated`.

## Provenance contract

`review_enrollment` accepts a statement cryptographically only when all of the following hold:

- The schema is version 2. Version 1 is `legacy_schema_refused`.
- The scope and key formats match this ceremony.
- `publication_channel` is `external-signed-receipt`. A URL is `publication_not_independent`.
- The fingerprint equals SHA-256 of the raw public key.
- The founder signature verifies under that public key over the version-2 domain.
- The witness signature verifies under a different public key, over the founder signature.
- `enrolled_at` is not in the future, `expires_at` is still ahead, and the window is at most 366 days.
- No valid revocation record names the key.

Cryptographic acceptance is not operational authority. Operational enrollment also requires an external witness channel and an external publisher anchor. Both are absent. `witness_authenticated` stays false. `governance_exception_active` stays false. A synthetic receipt can verify under a test key and still returns `publisher_not_enrolled`.

## Revocation

The founder revokes a key they still hold by signing a record of schema `orneur-founder-enrollment-revocation/1` over the domain `orneur-founder-enrollment-revocation/1`. The record names the identity, key id, fingerprint, and `revoked_at`. A valid revocation makes `review_enrollment` return `key_revoked`. A revocation with a bad signature is `revocation_invalid` and is not ignored. Revocation does not authorize a replacement key and does not authorize training.

## Rotation

Rotation is a revocation of the old key plus a new enrollment of a new key, a new witness, and a new external publication receipt. `review_rotation` returns `rotation_requires_new_enrollment`. A rotation object that sets `activates` or widens the scope returns `rotation_cannot_activate`. The old key cannot sign the new key into operational authority by itself.

## Recovery

If the private key or its password is lost, the witness may sign a loss attestation of schema `orneur-founder-enrollment-loss/1`. A valid attestation returns `recovery_requires_new_enrollment`. It does not restore the lost key, does not bind a replacement public key, and does not activate the freeze exception. Recovery is a new key, a new witness, a new external identity comparison, and a new publication receipt. A loss document that carries `replacement_public_key_hex` is `recovery_cannot_bind_replacement`.

## What remains blocked

The governance test `test_no_frozen_or_private_path_differs_from_the_branch_point` still fails on the three files. The prepared gate is `future_exception_applies` in `orca/founder_enrollment.py`, and in this commit it returns false. The governance test does not call it. Editing that function, or replacing a hash in this repository, is not founder authority. Signing the freeze approval is a separate act, described in `docs/orneur/cursor/FREEZE_AMENDMENT_APPROVAL.md`.
