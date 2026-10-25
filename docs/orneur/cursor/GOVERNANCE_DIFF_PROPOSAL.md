# Frozen-path difference against cd6af2a

The governance check compares the worktree with `cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d`. On a full checkout that comparison executes and fails. A depth-1 checkout used to skip it. The deterministic CI job now fetches full history, and a missing branch-point commit is a qualification failure rather than a skip.

This document does not change the authorization files. A founder decision is still required.

## Exact difference

`git diff --name-status cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d -- docs/orneur/authorization` reports three added files and no edits to existing founder documents. `git diff --stat` reports 49 insertions.

| Path | Change |
| --- | --- |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORITY_REGISTRY.json` | added, 4 lines |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORIZATION.json` | added, 41 lines |
| `docs/orneur/authorization/genesis_native_pretraining/REVOCATIONS.json` | added, 4 lines |

`AUTHORITY_REGISTRY.json` is schema `orneur-genesis-native-pretraining-authority-registry/1` with `records: []`.

`AUTHORIZATION.json` is schema `orneur-genesis-native-pretraining-authorization/1` with `status: NOT_AUTHORIZED`. Identity, key, signature, digests, and run id are null. `gpu_allowed` is false, `max_spend_usd` is 0, and `max_wall_clock_minutes` is 0.

`REVOCATIONS.json` is schema `orneur-genesis-native-pretraining-revocations/1` with `revoked_authorization_ids: []`.

No other frozen path in the governance test differs from that commit. The acceptance ledger is not in this diff.

## Proposal, pending founder authorization

These three files are empty `NOT_AUTHORIZED` records introduced with the inherited Workstream F tree. They do not authorize training. Two founder-controlled resolutions were available when this note was written:

1. Adopt the three documents as the new frozen baseline at a founder-chosen commit, and point the governance test at that commit.
2. Remove the three documents in a founder-authorized change if they should not be part of the frozen tree.

Cursor does not edit the files to make the check pass.

## Selected direction

The closure directive selects Option A: retain the three files. That selection is an exact-path and exact-digest exception, not a new baseline. `cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d` stays the historical reference. Resolution 1 above, retargeting the governance test at a newer commit, is not the selected direction.

The exception is prepared in `docs/orneur/cursor/FREEZE_AMENDMENT_PROPOSAL.md` and `orca/freeze_amendment.py`. It is inactive. The governance check still fails on the three additions until a founder signature verifies against an independent trust source that this repository does not contain.
