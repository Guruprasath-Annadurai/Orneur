# Founder bootstrap handover

Status: `AWAITING_INDEPENDENT_ENROLLMENT`

Subject of this package: founder enrollment remains `AWAITING_INDEPENDENT_ENROLLMENT` after the trust-boundary corrections. Governance is not closed. This package does not qualify the runtime and does not replace the separate macOS lock audit of `c27791fe3ad705ff34e6d4fb301c066f4ea93757`. The audited starting commit is `9e2b69bc623c6d7dae6aefbf356f793fafe4d9c5`.

Baseline: `cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d`

Proposal SHA-256: `08daabb09d79c22b241691bc92c8a519f065519303a368cb44e5afb972f6996a`

| Path | SHA-256 |
| --- | --- |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORITY_REGISTRY.json` | `13874861f20d7eabf7da5ed3f4ef8875046467ee51b6fa165b605a6245c75d84` |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORIZATION.json` | `88d0379632963cd4f871701c74ef55d50d54027f4bd8621e07e623081a61ea49` |
| `docs/orneur/authorization/genesis_native_pretraining/REVOCATIONS.json` | `2b5da1678f8fd35b35fc8a9153ed7c011fc8d776a39be31fbfdccfbf7c9300e3` |

## What Antigravity should check

The trust-boundary design and the requalification list are in `docs/orneur/cursor/TRUST_AUTHORITY_BOUNDARY.md`. In short:

- `OPERATIONAL_OBSERVATION_SHA256` is `None`. No founder private key, seed, or pinned public key is in the diff. The ceremony does not recommend a raw seed.
- `establish` on this tree returns `enrollment_absent` with `operational_authority` false and `governance_exception_active` false.
- A synthetic enrollment can verify and still leaves `future_exception_applies` false. The governance test does not import `founder_enrollment`. Repository source, an in-repo hash, and a substituted loader cannot make that function return true.
- A GitHub URL is `publication_not_independent`. One actor creating both keys is `witness_identity_unauthenticated`. Version-2 observation digests change when an authority field changes. Version 1 is `legacy_schema_refused`.
- A witness who uses the founder key is `witness_not_independent`. A caller-supplied public key is refused. A substituted anchor loader is `caller_supplied_anchor_refused`.
- The prepared gate rejects a fourth file, a changed permitted byte, a frozen deletion, a changed acceptance ledger, a changed training-authorization file, a changed trust root, and a missing historical commit.
- Approval binding rejects an identity mismatch, an unknown key, a forged signature, a replayed proposal digest, and a duplicate approval.
- Revocation, rotation, and loss attestation do not enroll a replacement and do not authorize training.
- The three denial files and the acceptance ledger are byte-identical to the digests already recorded. Formal acceptance remains 0/95.

A pass on this bootstrap review does not activate the freeze exception and does not qualify PR #115's runtime.

## Founder actions still outstanding

1. Generate the Ed25519 key on a founder-controlled machine and store it with `write_encrypted_software_key`, outside the repository and outside the agent.
2. Have a different person generate their own key, compare fingerprints in person, and countersign the enrollment statement. Two keys created by one actor are not that witness.
3. Have a third key sign the publication receipt. A GitHub commit URL or release URL is not that receipt.
4. Establish the witness channel and the publisher key outside this repository. Do not transcribe the observation hash into `OPERATIONAL_OBSERVATION_SHA256` and treat that assignment as the anchor.
5. Sign the freeze approval `adopt_files` with the enrolled key, binding the proposal digest, the baseline, and the three paths.
6. Only after those external anchors exist may a later commit change `test_no_frozen_or_private_path_differs_from_the_branch_point`. Editing `future_exception_applies` is not that change.

Ceremony: `docs/orneur/cursor/FOUNDER_AUTHORITY_ENROLLMENT.md`.

Prepared gate: `docs/orneur/cursor/FREEZE_ACTIVATION_PREPARATION.md`.

Approval bytes: `docs/orneur/cursor/FREEZE_AMENDMENT_APPROVAL.md`.
