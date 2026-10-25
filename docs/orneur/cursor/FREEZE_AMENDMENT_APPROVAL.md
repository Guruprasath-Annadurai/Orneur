# Freeze amendment approval

Schema: `orneur-freeze-amendment-approval/1`

Status: `AWAITING_FOUNDER_SIGNED_APPROVAL`

Activated: false

This file is not an approval. It does not contain a signature, a founder public key, or a permission to train. Placing a JSON document on disk does not change `tests/test_evalinfra_governance.py` and does not make that test pass.

## What a signature must bind

The signed object has exactly these fields:

- `schema_version`: `orneur-freeze-amendment-approval/1`
- `proposal_sha256`: SHA-256 of `docs/orneur/cursor/FREEZE_AMENDMENT_PROPOSAL.md`, which this preparation pins as `08daabb09d79c22b241691bc92c8a519f065519303a368cb44e5afb972f6996a`
- `baseline`: `cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d`
- `decision`: `adopt_files`
- `paths`: the three paths and SHA-256 values below, and no others
- `founder.identity` and `founder.key_id`
- `signature`: 128 lowercase hex characters, the Ed25519 signature over the canonical payload

| Path | SHA-256 |
| --- | --- |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORITY_REGISTRY.json` | `13874861f20d7eabf7da5ed3f4ef8875046467ee51b6fa165b605a6245c75d84` |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORIZATION.json` | `88d0379632963cd4f871701c74ef55d50d54027f4bd8621e07e623081a61ea49` |
| `docs/orneur/authorization/genesis_native_pretraining/REVOCATIONS.json` | `2b5da1678f8fd35b35fc8a9153ed7c011fc8d776a39be31fbfdccfbf7c9300e3` |

The introducing commit for those bytes is `6cd6127b608a0ea6670576ba6a506f8f3a6220b1`. Do not edit the files.

## Canonical payload

`orca.freeze_amendment.canonical_approval_bytes` builds the signed bytes. The `signature` field is omitted. Keys are sorted. The path list is sorted by path. The encoding is UTF-8 JSON with separators `,` and `:` and `ensure_ascii` false. The prefix is the distinct domain `orneur-freeze-amendment-approval/1` followed by a newline.

A signature over `orneur-training-authorization/1` or `orneur-genesis-native-pretraining-authorization/1` does not verify here. The approval object has no `gpu_allowed`, model name, or spend field. Adding one makes it malformed.

## Trust source

The verifying public key has to come from a founder trust source that already exists outside this process. This repository's authority registries are empty. `load_independent_trust` reports `missing_trust_material` and holds no key.

Do not generate a key for this approval and do not ask Cursor to pin a new key as founder authority. Do not treat a chat message as a signature. Do not substitute a test key. A key supplied by the caller, an empty registry, and an expired record are refused. `evaluate` keeps `activated` false when a substituted loader claims a key.

## What remains red

`test_no_frozen_or_private_path_differs_from_the_branch_point` still requires an empty diff against `cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d`. It does not call the freeze-amendment verifier. With history present it fails on the three additions above. That failure is the governance gate until a later commit, after independent verification of a real signature, changes the gate on purpose.

`orca.freeze_amendment.evaluate` rejects a fourth path, a changed byte in one of the three files, a deleted frozen path, a changed acceptance ledger or register graph, a changed training-authorization module, a changed trust-root file, a missing historical commit, a malformed approval, a duplicate approval, and conflicting approvals. None of those results set `activated`.

## Founder actions before activation

1. Recompute the proposal digest and the three file digests. Confirm the baseline commit and the introducing commit.
2. Sign `canonical_approval_bytes` with the Ed25519 key that is already the founder's authorized key. The private key stays outside this repository and outside Cursor.
3. An independent reviewer confirms that the public key is the same key as the external trust source. Agreement of a hash inside this repository is not that confirmation.
4. A later commit may change the governance test only after the founder anchor exists outside this repository. Copying a hash or a public key into this repository does not establish that anchor. This preparation does not change the test.

Until those steps are done, the amendment status stays `AWAITING_FOUNDER_SIGNED_APPROVAL`.

The founder key itself is not yet enrolled. The ceremony, the witness rule, and the absent observation pin are in `docs/orneur/cursor/FOUNDER_AUTHORITY_ENROLLMENT.md`. A synthetic test key cannot satisfy that ceremony.

## Separate runtime review

Antigravity's audit of this amendment is not the macOS qualification of `c27791fe3ad705ff34e6d4fb301c066f4ea93757`. The runtime audit still needs its own evidence on macOS: at least 100 concurrent lock-creation iterations, a fresh journal directory per iteration, at least 16 threads where that is supported, one stable lock inode, no unexpected `ENOENT`, `EEXIST`, or `lock_refused`, symlink, hard-link, and lock-replacement resistance, verification-seal regressions, macOS golden determinism, and the applicable test results. Linux results are not that evidence.

An amendment review can decide whether this preparation adds an authorization source, weakens the `cd6af2a` freeze, accepts a forged approval, or permits a change outside the three files. A pass on that review does not qualify the runtime.
