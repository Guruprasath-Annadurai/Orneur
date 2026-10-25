# Freeze amendment proposal 1

Schema: `orneur-freeze-amendment-proposal/1`

Status: `PROPOSED`

Activated: false

This document does not change a frozen file, the governance test, or the baseline commit. It does not authorize training, a GPU, a model, or spending. Founder approval is absent.

## Baseline that stays in force

The governance check in `tests/test_evalinfra_governance.py` compares the worktree with `cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d`. That commit remains the baseline. This proposal does not retarget the test.

Every path in that check stays frozen:

- `docs/orneur/acceptance`
- `docs/orneur/authorization`
- `docs/orneur/phase-21/rse`
- `orca/rse`
- `orca/train/authorization.py`
- `docs/orneur/acceptance/register_graph.json`
- `docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_STATUS.json`
- `eval_private`

A difference on any of those paths fails the check. An added or modified file other than the three named below is an unauthorized fourth change and fails the same check. A changed byte in one of the three files also fails it, because the diff is byte-level.

## The three additional files

`git diff --name-status cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d -- docs/orneur/acceptance docs/orneur/authorization docs/orneur/phase-21/rse orca/rse orca/train/authorization.py docs/orneur/acceptance/register_graph.json docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_STATUS.json eval_private` lists only these additions. They were introduced together by `6cd6127b608a0ea6670576ba6a506f8f3a6220b1` (`feat(genesis): Workstream F -- native pretraining training governance foundation`, 16 October 2026, 13:29 IST). Their bytes at that commit match the bytes in this worktree.

| Path | SHA-256 |
| --- | --- |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORITY_REGISTRY.json` | `13874861f20d7eabf7da5ed3f4ef8875046467ee51b6fa165b605a6245c75d84` |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORIZATION.json` | `88d0379632963cd4f871701c74ef55d50d54027f4bd8621e07e623081a61ea49` |
| `docs/orneur/authorization/genesis_native_pretraining/REVOCATIONS.json` | `2b5da1678f8fd35b35fc8a9153ed7c011fc8d776a39be31fbfdccfbf7c9300e3` |

## Fail-closed contents

`AUTHORITY_REGISTRY.json` uses schema `orneur-genesis-native-pretraining-authority-registry/1` and `records` is empty.

`AUTHORIZATION.json` uses schema `orneur-genesis-native-pretraining-authorization/1`. `status` is `NOT_AUTHORIZED`. Identity, key, signature, digests, and run id are null. `gpu_allowed` is false. `max_spend_usd` is 0. `max_wall_clock_minutes` is 0.

`REVOCATIONS.json` uses schema `orneur-genesis-native-pretraining-revocations/1` and `revoked_authorization_ids` is empty.

`orca.genesis.governance.authorization` and `orca.train.authorization` do not treat this proposal as a grant. `training_authorized()` in `orca.rse.imp1.locks` stays false.

## How founder approval would be recorded

Approval is not this file. A future founder authorization would be a separate signed record, schema `orneur-freeze-amendment-approval/1`, that contains all of the following and nothing that widens a training limit:

- this proposal's SHA-256
- baseline `cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d`
- the three paths and the SHA-256 values above
- one decision: `adopt_files` or `remove_files`
- the approving identity, key id, and an Ed25519 signature over those fields

The signature would have to verify against a founder key that is not in this repository today. The committed authority registries are empty. This process cannot sign the approval. An approval record must not set `gpu_allowed`, name a model, or set a non-zero spend, and it must not be accepted by `authorize_native_pretraining` or `training_authorized`.

`adopt_files` would mean a later founder-identified commit updates the governance test to keep `cd6af2a` for every other frozen path and to allow only these three digests. `remove_files` would mean that commit deletes the three files. Until that commit exists and an independent check shows the governance test passing for that reason, the check remains a failure.

## Independent verification while this proposal is inactive

1. Recompute the three SHA-256 values and compare them with the table.
2. Confirm `git diff --name-only cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d` on the frozen paths prints only the three files.
3. Confirm `AUTHORIZATION.json` is `NOT_AUTHORIZED` with `gpu_allowed` false and `max_spend_usd` 0.
4. Confirm `test_no_frozen_or_private_path_differs_from_the_branch_point` still fails on those three names and does not skip when `cd6af2a` is present.
5. Confirm this file's status is `PROPOSED` and activated is false.
