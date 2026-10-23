# P0 foundation security correction register

Audited baselines (unchanged, not merged):

- PR #80 `fc1eb1dd098377e8506485dbcd82d6ed148b52b3`
- PR #82 `177f54801eeaa079b67c9290ed89e3df0b3f6278`
- PR #83 first recovery FAIL `cd0f9051a2d0148eb4f1708b91ca71f41e4fb8e8`

Remediation remains stacked on PR #82. Training remains NO-GO. The acceptance ledger remains `[]` (0/95). Claude PRs #79 and #81 were not modified. GitHub did not allow converting PR #83 to draft on this source-of-truth path; treat it as not merge-ready.

| Finding | Root cause | Fix | Pre-fix reproduction | Post-fix test | Status |
|---|---|---|---|---|---|
| P0-01 Darwin F_GETPATH TypeError | `fcntl.fcntl(..., bytearray)` is rejected on macOS; tests mocked mutable-buffer semantics | Immutable `b"\\x00" * MAXPATHLEN`; parse **returned** bytes; TypeError fail-closed | Antigravity on macOS at `cd0f905`; Linux mocks that mutate the input | `tests/test_darwin_f_getpath_native.py` | PARTIAL — Linux contract tests pass; native macOS tests skip on this VM |
| P0-02 Parent symlink (kept) | Final-leaf `O_NOFOLLOW` only | Descriptor walk from `/` | `test_symlinked_parent_directory_is_refused` | same | Kept |
| P0-03 Neural spoofing (kept) | Callable + `nomic-embed-text` | `TrustedOllamaEncoder.qualified()` after embed | `test_spoofed_nomic_callable_is_not_production_neural` | same | Kept |
| P0-04 Grant liveness (kept) | Lifecycle used MAC only | Time + revocation helpers | `tests/test_foundation_lifecycle_grant_liveness.py` | same | Kept |
| P0-05/P0-02′ Key-first rotation crash | `.mac.key` replaced before re-MACed rows | Versioned `gN.{mac.key,chunks.jsonl,revoked.txt}` with one `.generation` pointer as the commit | Inject faults at `before-key` … `after-cleanup` | `test_rotation_interruption_preserves_or_commits_one_generation` | ENGINEERING FIXED on Linux; audit pending |
| P0-03′ Cross-instance revocation | Stale `_revoked` / cache / MAC key on a second handle | Exclusive flock, refresh+hash-verify generation on every mutating and search path | Two handles, `os.fork` delete, cached search, rotate-while-open, revoked-file tamper | `tests/test_authorized_index_adversarial.py` | ENGINEERING FIXED on Linux; audit pending |
| P0 recovery sweep | `_recover()` swept `gN.*` when the pointer was missing/unreadable, then created an empty store | Sweep only `.tmp` until a pointer is validated. Missing pointer with existing `gN.*` files fails closed and preserves bytes. Mutations fail closed on non-revocation row-integrity errors | Missing/malformed pointer on a store with docs+revocations; integrity-failed admit/delete | `test_missing_generation_pointer_does_not_wipe_an_existing_store`, `test_malformed_generation_pointer_preserves_generation_files`, `test_partial_integrity_failure_does_not_discard_rows_on_admit` | ENGINEERING FIXED on Linux; audit pending |
| P1 HMAC trust boundary | Key in the same session directory as the records | Documented and tested: HMAC is not authenticity against same-UID directory rewrite | `test_same_directory_hmac_is_not_a_same_uid_authenticity_boundary` | `AUTHORIZED_INDEX_TRUST_BOUNDARY.md` | Honest limitation, not a stronger claim |
| P1-02 Q1/X2 (kept) | Incomplete counts; weak X2 assertion | 15/12/7/4/1 locked; X2 2/0/0 + negative path | qualification + research tests | same | Kept |
| P0 Darwin corpus lock ENOENT | Concurrent `openat(O_RDWR\|O_CREAT\|O_NOFOLLOW)` of `.process_corpus.lock` can return ENOENT before `flock` on Darwin/APFS. Not claimed as a kernel defect. Linux did not reproduce the race. | Bounded (8) ENOENT retry only when `O_CREAT` is set, `dir_fd` remains the same live directory, `O_NOFOLLOW` stays on, `O_TRUNC` is refused. Persistent ENOENT/EACCES/ENOSPC re-raised. | Antigravity: `test_concurrent_writers_to_the_same_output_dir_are_serialized_not_corrupted`. Standalone: `scripts/repro_darwin_corpus_lock_race.py` | `tests/test_genesis_corpus_lock_concurrency.py` | ENGINEERING FIXED on Linux; native Darwin 100-round test SKIPPED here, not PASS |

## Key-rotation commit design

1. Stage `g{N+1}.mac.key`, `g{N+1}.chunks.jsonl`, `g{N+1}.revoked.txt` with fsync.
2. Directory fsync.
3. Atomically replace `.generation` (hashed key/chunks/revoked). **This is the only commit.**
4. Directory fsync.
5. Activate in-memory state only after the pointer is published.
6. Sweep uncommitted generations and tmp files. Interrupted cleanup leaves extras that the next recover deletes.

## Readiness

Final engineering status: **ENGINEERING PASS — INDEPENDENT NATIVE AUDIT PENDING**

Linux engineering for the corpus lock race is in. Native Apple Silicon confirmation is not. Skipped Darwin tests are not PASS.

1. Native Darwin `F_GETPATH`, `process_corpus()`, and 100-round lock stress have not been executed on authorized Mac hardware in this run. Use `scripts/repro_darwin_corpus_lock_race.py --rounds 100 --writers 8`.
2. Independent Antigravity requalification at the new head.
3. Training remains NO-GO. Ledger `[]` / 0/95.

Training: **NO-GO**.
