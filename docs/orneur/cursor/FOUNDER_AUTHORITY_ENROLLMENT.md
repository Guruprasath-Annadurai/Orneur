# Founder authority enrollment

Schema: `orneur-founder-enrollment/1`

Status: `AWAITING_INDEPENDENT_ENROLLMENT`

Operational observation pin: absent

This document is the ceremony. It is not an enrollment, not a public key, and not a freeze approval. The registering actor that wrote it cannot certify its own authority by committing a key, a fingerprint, or this file.

The only scope this ceremony can name is `freeze-amendment-adopt-files/1`. That scope retains three denial documents. It does not authorize training, a GPU, spending, corpus access, or model selection.

Proposal SHA-256: `08daabb09d79c22b241691bc92c8a519f065519303a368cb44e5afb972f6996a`

Historical baseline: `cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d`

| Path | SHA-256 |
| --- | --- |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORITY_REGISTRY.json` | `13874861f20d7eabf7da5ed3f4ef8875046467ee51b6fa165b605a6245c75d84` |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORIZATION.json` | `88d0379632963cd4f871701c74ef55d50d54027f4bd8621e07e623081a61ea49` |
| `docs/orneur/authorization/genesis_native_pretraining/REVOCATIONS.json` | `2b5da1678f8fd35b35fc8a9153ed7c011fc8d776a39be31fbfdccfbf7c9300e3` |

## What the founder keeps

The private signing key stays on a machine the founder controls, outside the repository and outside any AI-agent execution context. Do not generate the key in Cursor, in a cloud agent, or in CI. Do not paste the private key into chat, into a pull request, or into an agent prompt. Do not commit a seed, a PKCS8 file, or a public key and then treat that commit as the enrollment.

Ed25519 is the signature algorithm. The public key is 32 raw bytes, recorded as 64 lowercase hex characters. The fingerprint is the SHA-256 of those raw bytes.

## Offline steps

Run these steps on the founder's machine, from a checkout of the commit that contains `orca/founder_enrollment.py`. Quit agent sessions before the key exists in process memory.

1. Install Python 3.11 or newer and a `cryptography` build the founder trusts. Confirm `git config user.email` is not `cursoragent@cursor.com`.
2. Generate the keypair in a local process. Write the private seed only to a path outside every git worktree. Print only the public key and the fingerprint. A founder-run snippet, which this repository does not execute, is:

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
import hashlib, pathlib
key = Ed25519PrivateKey.generate()
raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
path = pathlib.Path.home() / "orneur-founder-ed25519.seed"  # outside the repo
path.write_bytes(raw)
path.chmod(0o600)
print(public.hex())
print(hashlib.sha256(public).hexdigest())
```

3. Choose `identity` and `key_id`. They are not secret. They must match the later freeze-approval fields.
4. Ask a witness, who is not the founder and not the agent, to generate their own Ed25519 key the same way on their own machine. The witness public key must differ from the founder public key. The witness identity and key id must differ from the founder's.
5. Build the enrollment statement with `orca.founder_enrollment.statement_of`. Set `scope` to `freeze-amendment-adopt-files/1`, `enrolled_at` and `expires_at` in `YYYY-MM-DDTHH:MM:SSZ`, and a validity window no longer than 366 days.
6. Compute the observation with `observation_of` and its SHA-256 with `observation_sha256`. The observation binds the repository `github.com/Guruprasath-Annadurai/Orneur`, the baseline, the proposal digest, both fingerprints, and the scope. Put that digest in `provenance.observation_sha256`.
7. The founder signs `founder_signing_bytes`. The domain is `orneur-founder-enrollment/1` plus a newline. The witness then countersigns `witness_signing_bytes`, which covers the founder signature. The witness domain is `orneur-founder-enrollment-witness/1` plus a newline. Neither private key enters the repository.
8. Publish the observation JSON and its SHA-256 on one independent channel the agent cannot write:
   - `founder-controlled-git-commit`: a commit on `https://github.com/Guruprasath-Annadurai/Orneur/commit/<sha>` created with the founder's own GitHub credentials, or
   - `founder-controlled-https-release`: a release tag URL `https://github.com/Guruprasath-Annadurai/Orneur/releases/tag/<tag>` created the same way.

   `git log` author text is not that channel. A commit authored inside an agent session is not that channel. The channel URL must not contain `cursoragent` or `cursor.com/agents`.

9. A reviewer who did not generate the founder key, and who is not the agent that prepared this ceremony, reads the observation hash from that channel. Only a later reviewed commit may copy it into `OPERATIONAL_OBSERVATION_SHA256`. This commit leaves that pin `None`.

Committing `docs/orneur/cursor/founder_enrollment/enrollment.json` does not enroll the key. `establish` keeps `operational_authority` false while the pin is absent. A caller-supplied public key is `caller_supplied_key_refused`. An identity that starts with `synthetic-` is refused on the operational path.

## Provenance contract

`review_enrollment` accepts a statement cryptographically only when all of the following hold:

- The schema, scope, and key formats match this ceremony.
- The fingerprint equals SHA-256 of the raw public key.
- The founder signature verifies under that public key.
- The witness signature verifies under a different public key, over the founder signature.
- `provenance.observation_sha256` equals `observation_sha256` of the statement, which embeds the proposal digest and the baseline above.
- The channel is one of the two founder-controlled URLs.
- `enrolled_at` is not in the future, `expires_at` is still ahead, and the window is at most 366 days.
- No valid revocation record names the key.

Cryptographic acceptance is not operational authority. Operational authority also requires the independent observation pin. That pin is not established here. `governance_exception_active` stays false.

## Revocation

The founder revokes a key they still hold by signing a record of schema `orneur-founder-enrollment-revocation/1` over the domain `orneur-founder-enrollment-revocation/1`. The record names the identity, key id, fingerprint, and `revoked_at`. A valid revocation makes `review_enrollment` return `key_revoked`. A revocation with a bad signature is `revocation_invalid` and is not ignored. Revocation does not authorize a replacement key and does not authorize training.

## Rotation

Rotation is a revocation of the old key plus a new enrollment of a new key, a new witness, and a new out-of-band observation. `review_rotation` returns `rotation_requires_new_enrollment`. A rotation object that sets `activates` or widens the scope returns `rotation_cannot_activate`. The old key cannot sign the new key into operational authority by itself.

## Recovery

If the private key is lost, the witness may sign a loss attestation of schema `orneur-founder-enrollment-loss/1`. A valid attestation returns `recovery_requires_new_enrollment`. It does not restore the lost key, does not bind a replacement public key, and does not activate the freeze exception. Recovery is a new key, a new witness, and a new independent observation. A loss document that carries `replacement_public_key_hex` is `recovery_cannot_bind_replacement`.

## What remains blocked

The governance test `test_no_frozen_or_private_path_differs_from_the_branch_point` still fails on the three files. The prepared gate is `future_exception_applies` in `orca/founder_enrollment.py`. The governance test does not call it. Signing the freeze approval is a separate act, described in `docs/orneur/cursor/FREEZE_AMENDMENT_APPROVAL.md`, and it waits until this enrollment is independently pinned.
