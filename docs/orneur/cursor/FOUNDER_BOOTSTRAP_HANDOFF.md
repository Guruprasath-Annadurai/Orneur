# Founder bootstrap handover

Status: `AWAITING_INDEPENDENT_ENROLLMENT`

Subject of this package: the commit that adds `orca/founder_enrollment.py`. Governance is not closed. This package does not qualify the runtime and does not replace the separate macOS lock audit of `c27791fe3ad705ff34e6d4fb301c066f4ea93757`.

Baseline: `cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d`

Proposal SHA-256: `08daabb09d79c22b241691bc92c8a519f065519303a368cb44e5afb972f6996a`

| Path | SHA-256 |
| --- | --- |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORITY_REGISTRY.json` | `13874861f20d7eabf7da5ed3f4ef8875046467ee51b6fa165b605a6245c75d84` |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORIZATION.json` | `88d0379632963cd4f871701c74ef55d50d54027f4bd8621e07e623081a61ea49` |
| `docs/orneur/authorization/genesis_native_pretraining/REVOCATIONS.json` | `2b5da1678f8fd35b35fc8a9153ed7c011fc8d776a39be31fbfdccfbf7c9300e3` |

## What Antigravity should check

- `OPERATIONAL_OBSERVATION_SHA256` is `None`. No founder private key, seed, or pinned public key is in the diff.
- `establish` on this tree returns `enrollment_absent` with `operational_authority` false and `governance_exception_active` false.
- A synthetic enrollment can verify and still leaves `future_exception_applies` false. The governance test does not import `founder_enrollment`.
- A witness who uses the founder key is `witness_not_independent`. A caller-supplied public key is refused. A substituted anchor loader is `caller_supplied_anchor_refused`.
- The prepared gate rejects a fourth file, a changed permitted byte, a frozen deletion, a changed acceptance ledger, a changed training-authorization file, a changed trust root, and a missing historical commit.
- Approval binding rejects an identity mismatch, an unknown key, a forged signature, a replayed proposal digest, and a duplicate approval.
- Revocation, rotation, and loss attestation do not enroll a replacement and do not authorize training.
- The three denial files and the acceptance ledger are byte-identical to the digests already recorded. Formal acceptance remains 0/95.

A pass on this bootstrap review does not activate the freeze exception and does not qualify PR #115's runtime.

## Founder actions still outstanding

1. Generate the Ed25519 key on a founder-controlled machine, outside the repository and outside the agent.
2. Have a separate witness generate a different key and countersign the enrollment statement.
3. Publish the observation hash on a founder-controlled GitHub commit or release that an agent did not create.
4. Have a reviewer who is neither the key holder nor the preparing agent transcribe that hash into `OPERATIONAL_OBSERVATION_SHA256`.
5. Sign the freeze approval `adopt_files` with the enrolled key, binding the proposal digest, the baseline, and the three paths.
6. Only after those checks may a later commit wire `test_no_frozen_or_private_path_differs_from_the_branch_point` to `future_exception_applies`.

Ceremony: `docs/orneur/cursor/FOUNDER_AUTHORITY_ENROLLMENT.md`.

Prepared gate: `docs/orneur/cursor/FREEZE_ACTIVATION_PREPARATION.md`.

Approval bytes: `docs/orneur/cursor/FREEZE_AMENDMENT_APPROVAL.md`.
