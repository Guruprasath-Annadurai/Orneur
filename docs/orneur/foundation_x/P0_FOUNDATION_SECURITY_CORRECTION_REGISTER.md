# P0 foundation security correction register

Audited baselines (unchanged, not merged):

- PR #80 `fc1eb1dd098377e8506485dbcd82d6ed148b52b3`
- PR #82 `177f54801eeaa079b67c9290ed89e3df0b3f6278`

Remediation is stacked on PR #82. The exact recovery head is the tip of `cursor/p0-foundation-security-recovery-c04e` (`git rev-parse HEAD`). Training remains NO-GO. The acceptance ledger remains `[]` (0/95). Claude PRs #79 and #81 were not modified.

| Finding | Root cause | Fix | Pre-fix reproduction | Post-fix test | Status |
|---|---|---|---|---|---|
| P0-01 Native Darwin crash | Variadic `ctypes` `libc.fcntl` `F_GETPATH` on Apple Silicon | `fcntl.fcntl(fd, F_GETPATH, bytearray)` with buffer, NUL, decode, and identity checks. Linux still uses `/proc/self/fd`. | `tests/test_darwin_f_getpath_native.py` plus Darwin hardware must call `_darwin_descriptor_path` at the audited SHA. Linux cannot reproduce the ARM ctypes crash. | `tests/test_darwin_f_getpath_native.py` (Linux refuse + source contract; Darwin native tests skip here) | PARTIAL — code fixed on Linux; native Darwin execution not run on authorized Mac hardware |
| P0-02 Parent symlink traversal | `O_NOFOLLOW` only on the final leaf | Descriptor-relative walk from `/` with `O_NOFOLLOW\|O_DIRECTORY` on every component; sticky world-write ancestors only; IO via `dir_fd` | `test_symlinked_parent_directory_is_refused`, `test_directory_replacement_does_not_follow_a_new_symlink` | `tests/test_authorized_index_adversarial.py` | ENGINEERING FIXED — independent audit pending |
| P0-03 Neural identity spoofing | `identity="nomic-embed-text"` on a caller callable plus HTTP probe | `production_neural` only if `TrustedOllamaEncoder.qualified()` after a real embed that returns the model field. Probe does not qualify. Synthetic hash remains refused. | `test_spoofed_nomic_callable_is_not_production_neural`, `test_probe_does_not_qualify_a_trusted_adapter` | same | ENGINEERING FIXED — independent audit pending |
| P0-04 Expired/revoked grants | Lifecycle used `verify_integrity()` only | `grant_time_validity_reasons` / `grant_revocation_reasons` reused by lifecycle and `assert_execution_permitted`. Integrity remains MAC-only. | `tests/test_foundation_lifecycle_grant_liveness.py` at exact expiry and before `issued_at` | same plus existing `assert_execution_permitted` tests | ENGINEERING FIXED — independent audit pending |
| P0-05 Atomic storage | Predictable temps, no fsync/dir fsync, weak sweep | Unique `.leaf.pid.tid.32hex.tmp`, write+fsync, `renameat`, directory fsync, flock, stale-tmp sweep that does not drop committed rows | `test_stale_temporary_files_are_swept_without_dropping_committed_rows`, `test_truncated_replace_leaves_the_committed_leaf`, process flock test | same | ENGINEERING FIXED on Linux — independent audit pending |
| P1-01 Authenticated index integrity | SHA-256 of text lived in the same untrusted JSONL line | HMAC-SHA256 over tenant/session/doc/version/text/digest; key in `.mac.key`, not in the index body; verify before search/replay; rotation re-MACs | `test_coordinated_text_and_digest_edit_is_integrity_mismatch` | same | ENGINEERING FIXED — MAC does not protect an attacker who also controls `.mac.key` |
| P1-02 Evaluation correctness | Q1 reporting omitted 15/12/7/4/1; X2 allowed either hypothesis outcome | `QualificationResult.source_documents=15`, `evaluation_items=12`; X2 locks baseline 2 / treatment 0 / loss 0 and `x2_hypothesis` negative path; copula + uncertain lexical scan | `test_pre_registered_qualification_separates_synthetic_from_models`, `test_contradiction_first_experiment_is_frozen_and_recorded`, `test_natural_language_conflicts_and_uncertain_without_a_model` | same | ENGINEERING FIXED for the frozen fixtures — not a general contradiction model |

## Readiness

Final engineering status: **ENGINEERING PARTIAL — SPECIFIED BLOCKERS**

Specified blockers:

1. Native Darwin `F_GETPATH` has not been executed on authorized Mac hardware in this run.
2. Independent Antigravity requalification has not been performed at the new head.
3. Training, GPU spend, deployment, and ledger mutation remain forbidden.

Training: **NO-GO**.
