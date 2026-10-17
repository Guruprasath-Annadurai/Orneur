# ORNEUR — Antigravity Audit #71 Remediation Engineering Report

**Phase**: Critical remediation and requalification against Antigravity's independent adversarial audit (PR #71, `8277be6fb242db9ba7478e9298e5f377e75c2fc3`), overall independent verdict `CONDITIONAL_REMEDIATION_REQUIRED`.

**Scope**: bounded audit-remediation. No native GENESIS training, no NOVUS fine-tuning, no real optimizer execution, no GPU provisioning, no paid-resource consumption, no signing-key issuance, no fabricated founder approvals, no protected-mainline merges, no deployment.

---

## 1. Starting and finishing commit SHAs

All four starting checkpoints were verified against live `git log` output before any change, and matched the directive's stated values exactly.

| Branch | Role | Starting SHA (verified) | Finishing SHA |
|---|---|---|---|
| `claude/genesis-cross-workstream-integration-2026-10-16` | PR #65 (integration) | `24693fb5bd3e20f791d7ed0b91a044303591bf6d` | `ee45676...` (see `git log -1`) |
| `claude/genesis-mission2-native-authorization-2026-10-16` | PR #68 (orchestration) | `19d740383a446ce814e8b3809556b38887b4c1b6` | `f2d26c8...` |
| `claude/genesis-workstream-f-grant-fields-2026-10-16` | PR #69 (grant fields) | `0942169c2753359283e098f0ea1380f85818faeb` | unchanged (no findings assigned here; audit verdict `PASS`) |
| `claude/genesis-workstream-a-hardening-2026-10-16` | PR #70 (data layer) | `f03af2f3aa1f639fa6b4cf591e022e0aed32df12` | `da5e8fb...` |
| `antigravity/genesis-hardening-adversarial-audit` | PR #71 (audit, read-only) | `8277be6fb242db9ba7478e9298e5f377e75c2fc3` | unchanged — inspected and imported from, never written to |

PR #71 was never merged wholesale; only its audit report and adversarial test file were imported (verbatim, unmodified) into PR #65, preserving provenance. PR #69 required no changes — the audit's own verdict for it was `PASS`.

## 2. Each reproduced defect, root cause, and corrective change

### AUDIT-P0-01 — execution-time artifact integrity (orchestration.py, PR #68)
**Root cause**: `_reverify_grant_or_transition()` (called by `start()`, `resume()`, `recovered()`) re-checked the signed grant's integrity, expiry, mandatory revocation, and *in-memory* identity drift — but never re-read or re-hashed the shard files themselves. A shard modified, substituted, or swapped after `authorize()` was invisible to every subsequent transition.

**Fix**: `validate()` now requires a `shard_dir` parameter. It independently computes the real SHA-256 digest of every `shard-*.jsonl` file present (`_compute_authorized_shard_file_digests()` — deliberately re-implemented rather than imported from `orca.genesis.data.pipeline`, so this module keeps no hard dependency on Workstream A) and **rejects at validation time** if the caller's claimed `authorized_shard_digests` do not match those real digests. The full `(filename, digest)` mapping becomes part of `_current_identity_snapshot()`, which `_reverify_grant_or_transition()` already re-derives **fresh, from live disk state, every single call** and compares against the frozen `_AuthorizedIdentitySnapshot`. Because the snapshot is never cached, any post-authorization tampering is caught by the same, already-adversarially-tested `AuthorizedIdentityChangedError` path every other bound field uses — no new, separately-tested check was needed. Binding the full filename→digest mapping (not merely the grant's own digest multiset) additionally closes the "two authorized shards swapped with each other" case a multiset comparison cannot detect.

**Verification-to-use race, honestly scoped**: this closes the authorize→tamper→start/resume window the audit demonstrated. It does not, and cannot, guarantee no modification between this check returning and whatever process later reads the bytes to actually train — documented explicitly in the module docstring as an open requirement for a future training-loop consumer, not an implied guarantee.

### AUDIT-P0-02 — durable progress persistence (pipeline.py, PR #70)
**Root cause**: `_commit_batch()` began with `if not pending: return` — `pending` holds only *kept* records. A corpus ending in all-rejected/corrupt/duplicate records, or a trailing run of such records after the last kept batch, left the progress row, rejection counters, and near-dup window **entirely unpersisted** at that boundary.

**Reproduced**: a 5-line all-corrupt corpus left zero rows in the `progress` table; 1 kept record followed by 5 trailing duplicates (commit_batch_size=1) left the persisted `resume_offset` frozen at 1 instead of 6, and `exact_duplicates` at 0 instead of 5.

**Fix**: removed the early-return guard entirely. Progress, rejection counters, and the near-dup window are now committed at every batch boundary and at loop exit, regardless of whether anything was kept.

### AUDIT-P0-03 — content-aware shard recovery (pipeline.py, PR #70)
**Root cause**: `_verify_and_recover_missing_or_corrupted_shard_output()` compared only `actual_size >= safe_offset`. Replacing a flushed shard's content with equal-size junk bytes passed this check completely undetected.

**Fix**: every `_flush_pending_shard_rows()` write now also records the file's real SHA-256 digest (over exactly the safe byte offset, streamed, never loading the whole file) at both the pre-write and post-write steps — a new `safe_byte_digest` column, added via a migration-safe `ALTER TABLE` for pre-existing `output_dir`s (defaulting to an empty string, which deliberately never matches a real digest, so a legacy directory's first check fails closed and verifies once rather than silently trusting an unverified prior record). Recovery now requires **both** size and digest to match; any mismatch is treated exactly like a missing file and triggers regeneration from SQLite's own durable `kept_records` truth — never from the corrupted file itself.

### AUDIT-P0-04 — manifest normalization-rule identity (manifest.py, PR #70)
**Root cause**: `_binding_fields()` (the shared formula both `build()` and `load()` use to compute/verify `manifest_id`) omitted `normalization_rule`. A saved manifest's `normalization_rule` could be hand-edited to an arbitrary string with `manifest_id` left unchanged, and `load()` accepted it with zero complaint.

**Decision**: `normalization_rule` **is** part of the provenance contract — it states which concrete normalization implementation produced `source_content_digest`, the same category of claim `transformation_lineage` already makes. Bound it into `_binding_fields()`; bumped `MANIFEST_SCHEMA_VERSION` to `/3` (the identity formula changed, and `load()` already rejects an unrecognized `schema_version` — this correctly invalidates manifests built under the prior formula rather than silently accepting them under a new rule they were never computed against).

## 3. P1 boundaries (Phase 2) — resolved by honest documentation, not code change

- **AUDIT-P1-01 (replay/concurrency)**: re-confirmed, unchanged. Marker-deletion reclaim and the absence of cross-host replay protection are structural consequences of the `O_CREAT|O_EXCL` local-filesystem design (already documented in the module docstring's P1-03 section from the prior phase). No shared/networked trust anchor exists for this module to use; building one is out-of-scope infrastructure work, documented as an explicit limitation, not an implied guarantee.
- **AUDIT-P1-02 (contamination)**: `find_near_duplicates_across_splits()`'s `max_total_records=5000` ceiling (added in the prior phase) already satisfies the directive's own permitted alternative to a full indexed implementation — an **explicit** scalability limit, not a silent gap. The audit's "batching blind spot" is a property of calling the function on an incomplete view of the data, not a code defect: a new regression test (`test_remediation_p1_02_calling_once_over_the_combined_corpus_catches_what_chunking_misses`) confirms the correct calling convention (one call over the complete corpus, bounded by `max_total_records`) does catch what two separate sub-5000 calls miss. No code change was made; the existing bound and its documentation were judged sufficient and are re-confirmed here, per the directive's own allowance to "prove it with source and adversarial-test evidence and move on" for an already-implemented control.

## 4. Tests before and after remediation

**Imported audit evidence** (`tests/test_audit_genesis_hardening_adversarial.py`, verbatim from PR #71, unmodified):

| Test | Before fix | After fix |
|---|---|---|
| `test_audit_p0_01_post_authorization_shard_tampering_undetected` | PASSED (vulnerability demonstrated) | **FAILS** (`TypeError`: `validate()` now requires `shard_dir`) |
| `test_audit_p0_02_progress_not_persisted_when_run_ends_with_rejected_records` | PASSED | **FAILS** (assertion inverted: row is now present) |
| `test_audit_p0_02_progress_trailing_duplicates_not_persisted` | PASSED | **FAILS** (offset now correctly advances to 6) |
| `test_audit_p0_03_artifact_recovery_fooled_by_same_size_tampering` | PASSED | **FAILS** (`unflushed_count` is now 1, not 0) |
| `test_audit_p0_04_manifest_id_invariant_under_normalization_rule_mutation` | PASSED | **FAILS** (`ManifestTamperedError` now raised) |
| `test_audit_p1_01_marker_deletion_allows_replay_and_no_cross_host_isolation` | PASSED | PASSES (documented limitation, unchanged by design) |
| `test_audit_p1_02_cross_split_screening_limits_and_batching_leakage_blindspot` | PASSED | PASSES (documented boundary, unchanged by design) |

Every P0 test now failing is the **intended outcome** of remediation — a vulnerability demonstration can no longer succeed. This is recorded honestly per the directive's Phase 3 instruction, not silently glossed over.

**New corrected regression suite** (`tests/test_audit_genesis_hardening_remediation.py`, 7 tests, all new): asserts the secure behavior directly for all four P0 findings (including a positive control proving the P0-01 fix has no false-positive effect on an untampered run) plus the P1-02 correct-usage demonstration. **7/7 passing.**

**Targeted regression** (orchestration + cross-workstream + data-layer + audit suites): **192 passed.**

**Per-branch isolated regression** (confirming no cross-workstream coupling was introduced):
- PR #70 branch alone (manifest/pipeline/contamination/multilingual/v3-builder): 107 passed, 1 skipped.
- PR #68 branch alone (orchestration, with no `pipeline.py` present on that branch at all): 88 passed.

**Full GENESIS-prefixed suite regression** (all 61 `tests/test_genesis*.py` + the two imported/new audit files, 3,156 tests collected — this is "existing GENESIS test suites" per the directive; the wider ~9,500-test whole-repository suite spans many unrelated subsystems, e.g. chemistry/OCL, website generation, and was not run to completion as out of scope for this phase):

- **3,130 passed, 20 skipped, 0 unexpected failures.**
- The only 6 observed failures on the first pass were investigated individually, not dismissed:
  - **5** were the audit's own P0 reproduction tests failing exactly as intended (listed in the table above) — the correct outcome of remediation.
  - **1** (`test_genesis_v2_sandbox_containment.py::test_oversized_stdout_is_capped_and_killed`, a file this phase never touched) failed once under heavy concurrent system load from unrelated processes on this machine, then **passed cleanly in isolation** on re-run — confirmed as environment flakiness, not a regression.
- An **independent baseline run** of the same suite against the unmodified starting commit (`24693fb`, in a separate git worktree) was also executed for comparison: **3,122 passed, 20 skipped, 0 failed** (this baseline predates the two new audit test files, hence the lower total). This directly confirms no pre-existing GENESIS test broke as a side effect of this phase's changes.
- An intermediate run surfaced 6 additional apparent failures (3 in `test_genesis_v2_final_pre_corpus_closure.py`, 2 in `test_genesis_v2_owner_preflight.py`, 1 in `test_genesis_v2_privacy.py`) that were fully root-caused, not ignored: this session's own scratch Python virtualenv (`.venv_audit/`, created to install `torch`/`numpy` for test execution) was sitting *inside* the repository working directory, and the repository's own privacy/corpus-scanning scripts (which these tests exercise against the real repo tree) flagged its contents as suspicious/private-corpus-like. Relocating the virtualenv outside the repository tree and re-running made all 6 disappear with zero code changes — conclusively an artifact of this session's own tooling placement, not the audit remediation.

## 5. Local and exact-head CI results

- PR #66 (prior, unrelated chain): confirmed 9/9 checks passing, `mergeable: true`, `mergeStateStatus: CLEAN` (sanity baseline only).
- PR #65, #68, #70 exact-head GitHub Actions results for this phase's commits (`ee45676`, `f2d26c8`, `da5e8fb`) are **pending** at the time of writing — not assumed, not fabricated. Will be reported honestly once observed in a later turn, consistent with this session's standing instruction never to proactively poll CI.

## 6. Unfixed P0/P1 findings

None of the four P0 findings remain unfixed. Both P1 findings remain **intentionally** unresolved by code change, for the reasons in Section 3 — both are explicit, documented architectural boundaries, not silent gaps, and both already satisfy the directive's own stated "document the limitation" alternative.

## 7. Actual execution-integrity guarantees and limitations

- A `GenesisTrainingRun` whose `shard_dir` content changes after `authorize()` is now **guaranteed** to be denied at `start()`, `resume()`, and `recovered()` — confirmed both by the audit's own (now-failing) reproduction and by this phase's new positive/negative regression pair.
- This guarantee does **not** extend across a process boundary this module doesn't control: it verifies at the moment of each transition, not continuously, and cannot constrain how a hypothetical future training-loop consumer opens the files afterward (no such consumer exists in this codebase).
- Progress/rejection-counter persistence is now guaranteed at every batch boundary and loop exit, independent of whether anything was kept that batch.
- Shard-output recovery is now guaranteed to detect equal-size content tampering, not only size/truncation changes — but only for `output_dir`s this module itself has written through (a directory populated out-of-band, with no prior `shard_file_safe_offsets` row, has nothing to compare against and is accepted as-is on first sight, same as before this fix).
- Manifest identity is now guaranteed to change if `normalization_rule` is mutated.
- Cross-host replay protection and fully-general cross-batch contamination screening remain explicitly **not** guaranteed, by documented design choice, not oversight.

## 8. Remaining Audit #017 requirements

Unchanged from the prior phase: PR #58's Workstream B/D/Mission 1A conditional-remediation requirements remain unmerged and unaccepted, carried forward into PR #65 unresolved. This phase did not touch those files and makes no new claim about their status.

## 9. Antigravity re-audit handoff

Explicit items for independent re-verification://
1. Confirm `_compute_authorized_shard_file_digests()`'s re-implementation (rather than import) genuinely introduces no exploitable drift from `orca.genesis.data.pipeline.compute_shard_digests()`'s own digest computation.
2. Confirm the `shard_file_safe_offsets` migration (`ALTER TABLE ... ADD COLUMN safe_byte_digest`) behaves correctly against a real pre-existing `output_dir` created before this phase (this repository has none to test against; only synthetic, freshly-created directories were exercised).
3. Re-run the full adversarial suite (`tests/test_audit_genesis_hardening_adversarial.py`) independently and confirm the same pass/fail pattern reported in Section 4.
4. Assess whether the P1-01/P1-02 "document, don't fix" decisions are acceptable for a successor verdict, or whether they should be escalated to P0 in a future phase.

## 10. GENESIS training authorization state

**Unchanged: `NOT_AUTHORIZED`.** The real founder-acceptance ledger and authority registry remain empty, as committed in this repository; nothing in this phase altered either file. No training, no GPU use, no optimizer step, no paid resource, and no signing key were used or issued anywhere in this phase.

---

## Verdict

**`READY_FOR_INDEPENDENT_REAUDIT`** for the four P0 findings and the two P1 boundaries addressed in this phase, conditioned on:
- Exact-head CI results for PR #65/#68/#70 landing green (pending, Section 5).
- Antigravity's own independent re-verification of the four items in Section 9.

Only the independent auditor may issue the successor qualification verdict; this report records engineering evidence and a self-assessed starting point for that re-audit, not a self-declared PASS.
