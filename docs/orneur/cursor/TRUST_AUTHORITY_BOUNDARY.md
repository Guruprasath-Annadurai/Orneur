# Trust authority boundary

Status: `AWAITING_INDEPENDENT_ENROLLMENT`

This file records the trust-boundary design. It does not enroll a founder, a witness, or a publisher. It does not activate the freeze exception. `operational_authority` and `governance_exception_active` stay false. No secret and no organizational setting is configured here.

Audited starting commit: `9e2b69bc623c6d7dae6aefbf356f793fafe4d9c5`

Historical baseline: `cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d`

Proposal SHA-256: `08daabb09d79c22b241691bc92c8a519f065519303a368cb44e5afb972f6996a`

| Path | SHA-256 |
| --- | --- |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORITY_REGISTRY.json` | `13874861f20d7eabf7da5ed3f4ef8875046467ee51b6fa165b605a6245c75d84` |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORIZATION.json` | `88d0379632963cd4f871701c74ef55d50d54027f4bd8621e07e623081a61ea49` |
| `docs/orneur/authorization/genesis_native_pretraining/REVOCATIONS.json` | `2b5da1678f8fd35b35fc8a9153ed7c011fc8d776a39be31fbfdccfbf7c9300e3` |

## What was weak at the starting commit

1. The ceremony told the founder to write a raw Ed25519 seed with `path.write_bytes` and then `chmod`.
2. A GitHub URL that matched a regex was treated as founder publication. An agent that can push a commit can mint that URL. Git author text, an email address, and a verified badge were not a signature.
3. Two different keypairs were treated as two people. One actor can create both.
4. `observation_of` omitted the timestamps, the witness identity and key id, the publication receipt, and the signatures. Changing those fields left `observation_sha256` unchanged. Putting the observation hash inside the object that produces it would have been circular.

Inactive safeguards at that commit still refused a caller-supplied anchor, a synthetic operational identity, a revoked or expired key, a fourth frozen file, and a changed acceptance ledger or training-authorization file. Those refusals stay. They were not operational founder authority.

## Signing

The compatible software procedure is `orca/founder_key_store.py`. It writes PBES2 / PBKDF2-HMAC-SHA256 / AES-256-CBC with 600000 iterations, created with `O_EXCL|O_NOFOLLOW` and mode `0o600`. `BestAvailableEncryption` is not that procedure. SSH `ed25519-sk` is `hardware_sk_not_compatible` with the raw Ed25519 verifier. No operational private key is generated or stored by this commit.

## Publication

`github_url_is_not_publication` returns `publication_not_independent` for every input, including a well-formed commit URL on this repository. `git_identity_is_not_publication` returns `git_identity_not_publication` for an author, an email, and a badge.

The publication object is a separate receipt, schema `orneur-founder-publication-receipt/1`. It binds:

- `statement_sha256`, which is also `immutable_id`
- `observation_sha256`
- the channel `external-signed-receipt`
- the publisher key id and fingerprint

The publisher signature is verified against a key that was enrolled earlier and is not the founder key, the witness key, or a key carried inside the receipt. `load_external_publisher_anchor` returns `publisher_anchor_absent` and does not read this repository, an environment variable, or GitHub. A caller-supplied key on the operational path is `caller_supplied_publisher_refused`. A synthetic test key can make `publication_verified` true and still returns `publisher_not_enrolled`. An unsigned receipt is `receipt_unsigned`. A wrong signature is `receipt_signature_invalid`. A substituted statement or observation digest is `receipt_not_bound`. A `cursoragent` publisher id is `agent_publication_refused`.

## Witness

`witness_identity_authenticated` returns false. A substituted witness loader returns false as well. Operational review of a signature-valid enrollment whose two keys differ is `witness_identity_unauthenticated`. The witness ceremony is two people, two machines, and an in-person fingerprint comparison. The witness countersigns only after reading the statement. Private keys are not given to an agent. The comparison channel is not a GitHub badge and is not a file in this repository.

## Observation

Version 2 canonicalization has three stages:

1. The founder signs `orneur-founder-enrollment/2` plus the canonical statement. The statement has identities, key ids, the founder public key and fingerprint, the witness public key, the scope, the timestamps, and `publication_channel`. It has no signature and no observation hash.
2. The witness countersigns the founder signing bytes and the founder signature. `observation_of` is then built. It adds the witness fingerprint, both signatures, the repository, the baseline, the proposal digest, and `publication_immutable_id` set to the statement digest. The observation does not contain `observation_sha256`, so the hash is not a hash of a structure that contains itself.
3. The publisher signs the receipt, which names that observation digest. The receipt is not embedded back into the observation. Changing the receipt does not change the observation hash. Changing the statement changes the statement digest, the observation, and any receipt that was bound to the old digest.

A version-1 document is `legacy_schema_refused`. Its signature is not checked as version 2. The version-1 projection, which omitted timestamps and witness identity, is reproduced only in `tests/test_founder_enrollment.py` to show that those mutations left the old digest unchanged and change the version-2 digest.

## Activation

`repository_material_cannot_authorize` returns `repository_logic_not_authority` for source text, a digest, and a pin. `environment_cannot_authorize` returns `environment_not_authority`. `future_exception_applies` returns false when the defect lists are empty, when the anchor loader is substituted, and when the repository-material function is substituted. The live test `test_no_frozen_or_private_path_differs_from_the_branch_point` does not import `founder_enrollment` and still requires an empty diff against `cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d`. That test is the enforcement an ordinary edit of this repository does not satisfy. It remains red on the three denial files above.

Exact-path and exact-digest permission stays those three files. `classify_diff` still rejects a fourth file, a changed permitted byte, a frozen deletion, a changed acceptance ledger, a changed training-authorization file, a changed trust root, and a missing baseline. `scope_cannot_authorize_training` returns `freeze_scope_does_not_authorize_training` for the freeze scope. Training, GPU, spending, corpus generation, and model selection locks stay false.

There is no caller-supplied operational public key. A test identity is `synthetic_key_refused` on the operational path. Expired enrollments are `stale_enrollment`. Revoked keys are `key_revoked`. A signature over `orneur-founder-enrollment/1`, the witness domain, the receipt domain, the training domain, the genesis domain, or the freeze-approval domain is `signature_invalid` when presented as the founder enrollment signature.

## GitHub controls are not the anchor

This commit does not change rulesets, branch protection, actions permissions, environments, or secrets.

A ruleset or a required check on this repository can be changed by an organization owner, a repository administrator, and anyone holding a token with those rights. GitHub Support can change them as well. A verified badge and a protected-branch merge do not prove the founder signed the enrollment. A workflow file in this repository is editable by anyone who can push a branch the agent is allowed to push. Required verification has to live in a workflow repository the founder controls and the agent cannot write, and the trust anchor that workflow compares against has to be established outside both repositories. Even that arrangement fails closed if the organization owner retargets the ruleset or if the external anchor is absent. Absence is the current state. Do not put the founder private key, the publisher private key, or the witness private key into an Actions secret.

Separation of duties, once the founder chooses to perform it, is three roles: the founder holds the enrollment key, a different person holds the witness key and is identified out of band, and a third publisher key signs the receipt. The person who can edit `orca/founder_enrollment.py` is not, by that access, any of those three. This commit does not appoint them.

## What Antigravity should recheck

- The ceremony document no longer recommends a raw seed, `PrivateFormat.Raw`, or `write_bytes`.
- `describe_encrypted_private_key` reports PBES2, PBKDF2-HMAC-SHA256, 600000 iterations, and AES-256-CBC from the file bytes. `BestAvailableEncryption` still has no cipher attribute.
- A GitHub URL and a git author do not verify a receipt. Unsigned, mis-signed, substituted, self-published, and `cursoragent` receipts fail. The operational publisher anchor stays absent.
- One process creating both keys and both names stays `witness_identity_unauthenticated` with `signature_ok` true and `operational_authority` false.
- Mutating any authority field listed above changes `observation_sha256`. The observation object has no `observation_sha256` field. Version 1 is refused.
- Substituting either external loader, an environment value, or the text of this repository cannot make `future_exception_applies` return true.
- Domain replay, expiry, revocation, a fourth frozen file, and a changed acceptance ledger or training-authorization file still fail closed.
- The governance test is still unwired and still fails on the three denial files. Formal acceptance stays 0/95. No founder key, enrollment file, or signed approval is in the tree.
- macOS lock qualification of `c27791fe3ad705ff34e6d4fb301c066f4ea93757` is a separate review.

A pass on that recheck does not activate governance and does not replace the founder ceremony.

## Founder actions still outstanding

1. Generate the Ed25519 key on a founder-controlled machine and store it only with `write_encrypted_software_key`, outside the repository and outside the agent. Keep an offline backup and a separate password.
2. Have a different person generate their own key, compare fingerprints in person, read the statement, and countersign it. Record that comparison outside this repository.
3. Have a third key sign the publication receipt over the statement digest and the observation digest. Establish that publisher key outside this repository.
4. Do not treat a commit URL, a release URL, or a hash written into `OPERATIONAL_OBSERVATION_SHA256` as those anchors.
5. Sign the freeze approval `adopt_files` with the enrolled key only after those anchors exist. Bind the proposal digest, the baseline, and the three paths.
6. Only a later commit, after that independent establishment, may wire `test_no_frozen_or_private_path_differs_from_the_branch_point` to a check that still cannot be satisfied by editing this repository alone.

Ceremony: `docs/orneur/cursor/FOUNDER_AUTHORITY_ENROLLMENT.md`.

Prepared gate: `docs/orneur/cursor/FREEZE_ACTIVATION_PREPARATION.md`.

Approval bytes: `docs/orneur/cursor/FREEZE_AMENDMENT_APPROVAL.md`.
