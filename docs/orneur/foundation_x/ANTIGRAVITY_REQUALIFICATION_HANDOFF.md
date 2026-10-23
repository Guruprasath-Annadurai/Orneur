# Antigravity requalification handoff — Genesis Darwin lock race

Do not merge. Do not train. Do not treat Linux CI as Darwin qualification.
Do not treat skipped `test_native_darwin_*` tests as PASS.
PR #83 remains not merge-ready. This correction is isolated on
`cursor/genesis-darwin-lock-race-c04e` against that baseline.

## Verdict

**ENGINEERING PASS — INDEPENDENT NATIVE AUDIT PENDING**

## Stack

| PR / branch | SHA / role |
|---|---|
| #80 | `fc1eb1dd098377e8506485dbcd82d6ed148b52b3` |
| #82 | `177f54801eeaa079b67c9290ed89e3df0b3f6278` |
| #83 portability closeout (baseline) | `3833f55cad4d236a8023649918edbbf8be57de5e` |
| Darwin lock-race correction | `git rev-parse HEAD` on `cursor/genesis-darwin-lock-race-c04e` |

## Root cause

`process_corpus()` opens the output directory with `_open_directory_leaf()`,
then `_open_regular_at(dir_fd, ".process_corpus.lock", O_RDWR|O_CREAT)`
before `fcntl.flock()`.

This is a **lock-file create-visibility race**, not a first-time mkdir
failure and not a stale directory descriptor:

1. `_open_directory_leaf(create=True)` mkdir's the leaf (FileExistsError
   ignored) and openat's it with `O_DIRECTORY|O_NOFOLLOW`. A live
   directory fd is already held when the lock open runs.
2. Concurrent writers then `openat(O_RDWR|O_CREAT|O_NOFOLLOW)` the same
   new name. On Darwin/APFS that open can return `ENOENT` even though
   the parent fd is valid. `FileNotFoundError` escapes before flock.
3. `O_NOFOLLOW|O_CREAT` is kept. The failure is not "symlink followed".
4. Linux ext4 in this VM did **not** reproduce naive ENOENT (0 failures
   in 20×8 naive opens). Linux is not a substitute for Apple Silicon.
5. A Darwin kernel defect is **not** asserted. The working hypothesis is
   a namei/create-visibility race under concurrent `O_CREAT|O_NOFOLLOW`.

Application-level serialization after a successful open remains
`fcntl.flock(LOCK_EX)` on that regular file.

## Fix

`_open_regular_at()`:

- Always `O_NOFOLLOW|O_CLOEXEC`.
- Refuses `O_TRUNC` and path separators.
- Requires `dir_fd` to be a live directory; retries only while
  `(st_dev, st_ino)` is unchanged.
- Retries `ENOENT` at most 8 times, **only** when `O_CREAT` is set.
- Re-raises persistent ENOENT, EACCES, ENOSPC, and symlink errnos.
- After open, rejects non-regular leaves. Directories raise
  `IsADirectoryError` (not a false symlink claim).

The lock is still `O_RDWR|O_CREAT` without `O_TRUNC`, then exclusive
flock. Success is not reported without that lock and a durable SQLite
commit.

## Native command (authorized Mac)

```bash
python3 scripts/repro_darwin_corpus_lock_race.py --rounds 100 --writers 8
python3 -m pytest tests/test_genesis_corpus_lock_concurrency.py tests/test_genesis_data_pipeline.py tests/test_darwin_f_getpath_native.py tests/test_cursor_progress_db_portability.py -v
# test_native_darwin_* must execute, not skip.
```

## Linux results (this engineering VM)

Focused suite (pipeline, lock concurrency, Darwin contract, AuthorizedIndex,
grant liveness, RAG-X, governance, portability): **187 passed, 5 skipped**.

Skipped (not PASS):

- `test_native_darwin_f_getpath_returns_the_open_directory`
- `test_native_darwin_rejects_invalid_closed_and_replaced_directories`
- `test_native_darwin_process_corpus_uses_f_getpath_sqlite`
- `test_native_darwin_symlink_path_is_not_the_descriptor_identity`
- `test_native_darwin_synchronized_corpus_lock_stress_100_rounds`

Linux reproducer 20×8: naive 0 ENOENT; `process_corpus` 0 failures;
script exits 2 because `sys.platform != "darwin"`.

## Remaining risk

- Native Apple Silicon has not re-run the original concurrent-writer
  failure at this HEAD. Until Antigravity does, the Darwin ENOENT is
  engineering-fixed with tests, not natively closed.
- Same-UID unlink of `.process_corpus.lock` while a holder has flock
  can still create a second inode (`O_CREAT` recreates). Production
  never unlinks the lock. This predates the retry.
- HMAC key remains in the session directory. Same-UID rewrite can mint
  MACs. See `AUTHORIZED_INDEX_TRUST_BOUNDARY.md`.
- Training remains **NO-GO**. Acceptance ledger `[]` / 0/95.
