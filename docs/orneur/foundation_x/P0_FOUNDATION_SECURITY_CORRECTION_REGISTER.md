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
| P1 HMAC trust boundary | Key in the same session directory as the records | Documented and tested: HMAC is not authenticity against same-UID directory rewrite | `test_same_directory_hmac_is_not_a_same_uid_authenticity_boundary` | `AUTHORIZED_INDEX_TRUST_BOUNDARY.md` | Honest limitation, not a stronger claim |
| P1-02 Q1/X2 (kept) | Incomplete counts; weak X2 assertion | 15/12/7/4/1 locked; X2 2/0/0 + negative path | qualification + research tests | same | Kept |

## Key-rotation commit design

1. Stage `g{N+1}.mac.key`, `g{N+1}.chunks.jsonl`, `g{N+1}.revoked.txt` with fsync.
2. Directory fsync.
3. Atomically replace `.generation` (hashed key/chunks/revoked). **This is the only commit.**
4. Directory fsync.
5. Activate in-memory state only after the pointer is published.
6. Sweep uncommitted generations and tmp files. Interrupted cleanup leaves extras that the next recover deletes.

## Readiness

Final engineering status: **ENGINEERING PARTIAL — SPECIFIED BLOCKERS**

1. Native Darwin `F_GETPATH` and `process_corpus()` have not been executed on authorized Mac hardware in this run.
2. Independent Antigravity requalification at the new head.
3. Training remains NO-GO.

Training: **NO-GO**.
