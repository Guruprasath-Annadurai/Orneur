# Antigravity requalification handoff — P0 second recovery (PR #83)

Do not merge. Do not train. Do not treat Linux CI as Darwin qualification.
Do not treat PR #83 as draft-converted; forge refused draft on GitHub-source-of-truth. It is still not merge-ready.

## Stack

| PR | SHA / role |
|---|---|
| #80 | `fc1eb1dd098377e8506485dbcd82d6ed148b52b3` |
| #82 | `177f54801eeaa079b67c9290ed89e3df0b3f6278` |
| #83 FAIL | `cd0f9051a2d0148eb4f1708b91ca71f41e4fb8e8` |
| #83 second recovery | `git rev-parse HEAD` on `cursor/p0-foundation-security-recovery-c04e` |

## Commands

```bash
git rev-parse HEAD
git merge-base --is-ancestor cd0f9051a2d0148eb4f1708b91ca71f41e4fb8e8 HEAD
python3 -m pytest tests/test_darwin_f_getpath_native.py tests/test_authorized_index_adversarial.py tests/test_foundation_lifecycle_grant_liveness.py tests/test_truth_authorized_index.py tests/test_rag_x_foundation.py tests/test_cursor_progress_db_portability.py tests/test_genesis_governance_authorization.py -v
bash scripts/ci/run_deterministic_tests.sh
```

Darwin (authorized Mac only):

```bash
python3 -m pytest tests/test_darwin_f_getpath_native.py tests/test_cursor_progress_db_portability.py tests/test_genesis_data_pipeline.py -v
# test_native_darwin_* and process_corpus must execute, not skip.
```

## Linux results (this engineering VM)

Focused second-recovery suite: 115 passed, 4 skipped (all `test_native_darwin_*` / Darwin `process_corpus`).

## Remaining limits

- HMAC key is in the session directory. Same-UID rewrite of key+pointer+records can mint MACs. See `AUTHORIZED_INDEX_TRUST_BOUNDARY.md`.
- Native macOS F_GETPATH and process_corpus are not claimed from Linux.
- Training remains NO-GO. Ledger `[]` / 0/95.
