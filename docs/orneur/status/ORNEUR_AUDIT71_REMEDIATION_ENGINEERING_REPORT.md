# ORNEUR — Antigravity Audit #71 Remediation Engineering Report

**Phase**: Critical remediation and requalification against Antigravity's independent adversarial audit (PR #71, `8277be6fb242db9ba7478e9298e5f377e75c2fc3`), overall independent verdict `CONDITIONAL_REMEDIATION_REQUIRED`.

**Scope**: bounded audit-remediation. No native GENESIS training, no NOVUS fine-tuning, no real optimizer execution, no GPU provisioning, no paid-resource consumption, no signing-key issuance, no fabricated founder approvals, no protected-mainline merges, no deployment.

---

## 1. Starting and finishing commit SHAs

All four starting checkpoints were verified against live `git log` output before any change, and matched the directive's stated values exactly.

| Branch | Role | Starting SHA (verified) | Finishing SHA |
|---|---|---|---|
| `claude/genesis-cross-workstream-integration-2026-10-16` | PR #65 (integration) | `24693fb5bd3e20f791d7ed0b91a044303591bf6d` | `5acc8cf821f4848bae3a46688caac43e6cb34df7`* |
| `claude/genesis-mission2-native-authorization-2026-10-16` | PR #68 (orchestration) | `19d740383a446ce814e8b3809556b38887b4c1b6` | `f2d26c8a2a0106b6fbfebf980533a39a9e958f79` |
| `claude/genesis-workstream-f-grant-fields-2026-10-16` | PR #69 (grant fields) | `0942169c2753359283e098f0ea1380f85818faeb` | unchanged (no findings assigned here; audit verdict `PASS`) |
| `claude/genesis-workstream-a-hardening-2026-10-16` | PR #70 (data layer) | `f03af2f3aa1f639fa6b4cf591e022e0aed32df12` | `da5e8fb6785bb99b57d5d84ad5d1f2523a6a84d2` |
| `antigravity/genesis-hardening-adversarial-audit` | PR #71 (audit, read-only) | `8277be6fb242db9ba7478e9298e5f377e75c2fc3` | unchanged — inspected and imported from, never written to |

\* PR #65's finishing SHA passed through two intermediate, independently verifiable commits during this closure phase: `ee45676` (first remediation push, exact SHA independently confirmed by the directive that opened this phase) → `4123f56` (engineering report) → `5acc8cf` (CI collection-gate fix, this phase's actual final state — see Section 5).

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
- PR #68 (`f2d26c8`) and PR #70 (`da5e8fb`): confirmed **9/9 checks passing** on exact head, independently observed via `gh pr checks`, including both parallel `Deterministic Unit Tests` runs (16m53s and 13m14s respectively).
- PR #65: at commit `ee45676` (this phase's first push), independently observed **TWO FAILED** `Deterministic Unit Tests` checks (all 17 other checks passing). Both failures were inspected directly from their actual GitHub Actions logs (`gh run view --log-failed`), not assumed:

  **Root cause**: this job's CI script (`scripts/ci/run_deterministic_tests.sh`) runs `pytest -m "not live_ollama_smoke" --ignore=tests/test_trainprep_sentinel.py` — a broad collection pass across effectively the whole `tests/` directory, in an environment that does **not** install `torch`. The verbatim-imported `tests/test_audit_genesis_hardening_adversarial.py` (Section 1) unconditionally imports `orca.genesis.training.orchestration`, which imports `torch` transitively — and, unlike every torch-dependent test file this repository's own suite writes (which guard with `pytest.importorskip("torch")` at module level), the audit's file carries no such guard, since it was written for the auditor's own, torch-available harness, not this repository's CI matrix. The result was a hard **collection ERROR** (`ModuleNotFoundError: No module named 'torch'`), which aborts pytest's entire collection phase — not a per-file skip, and not the 5 now-intentional P0 assertion failures (those never had a chance to run at all; collection itself never got past this file). Both of the two failed checks were the same underlying job running in parallel shards, hence an identical failure in both logs.

  **Investigated separately, per the directive's item 2**: even with `torch` available, would this file's P0 tests have been reported as CI failures anyway? Yes — they now intentionally assert the opposite of what remediation produces (Section 4), and a plain, ungated `pytest` run has no way to distinguish "a real regression" from "a historical vulnerability demonstration correctly no longer reproducing." Fixing only the `torch` import would not have been sufficient; the file genuinely needed to be excluded from this job's pass/fail gate by design, matching the directive's item 3 exactly.

  **Fix** (`5acc8cf`): added `--ignore=tests/test_audit_genesis_hardening_adversarial.py` to the one CI script that does broad collection (every other job in `.github/workflows/test.yml` already runs an explicit, narrow file list — `test_train_losses.py`/`test_transformers_adapter.py`, the Genesis V2 security/sandbox file lists, etc. — none of which ever touch this file). The corrected, secure-behavior counterpart `tests/test_audit_genesis_hardening_remediation.py` (which **does** carry the standard `importorskip("torch")` guard, written by this repository, not imported) is untouched by this ignore and remains fully inside normal CI collection and gating. The historical file itself is untouched, fully present in the repository, and runnable on demand (`pytest tests/test_audit_genesis_hardening_adversarial.py`) — only excluded from this one job's automated pass/fail surface.

  **Verified locally before pushing**: a fresh virtualenv built outside the repository tree, with `torch` deliberately NOT installed (mirroring this job's real environment), now collects the full suite with **zero collection errors** (previously one hard error); the four GENESIS test files that depend on `torch` correctly **skip** (not error) in that environment; the pure-Python data-layer suite (manifest/pipeline/contamination, no `torch` dependency at all) passes 86/86 in the same environment.

  **Confirmed on exact head after the fix (`5acc8cf`)**: both parallel `Deterministic Unit Tests` runs now **PASS** (17m16s and 17m14s) — exit code 0 from `gh pr checks 65`, 19/19 total checks green, zero pending, zero failing.

## 5a. Environment-pollution issues investigated and ruled out (not silently dismissed)

Two apparent-failure patterns surfaced locally during this phase's own re-verification work and were fully root-caused before being excluded as "unrelated," per the directive's explicit instruction not to label failures as unrelated without baseline evidence:

1. **6 failures in `test_genesis_v2_final_pre_corpus_closure.py` / `test_genesis_v2_owner_preflight.py` / `test_genesis_v2_privacy.py`**, none of which import anything this phase touched. Reproduced in isolation on this phase's own branch (6 failed, 85 passed) and compared against an independent baseline run of the unmodified starting commit `24693fb` in a separate git worktree (0 failed, 91 passed). The differentiator: this session's own scratch Python virtualenv (`.venv_audit/`), used to install `torch`/`numpy` for local test execution, was sitting *inside* the repository working directory. These three test files exercise the repository's own real privacy/corpus/preflight-scanning scripts against the actual repo tree, which picked up the virtualenv's contents (a `secrets.pyi` typeshed stub matched a secret-filename rule; the virtualenv's presence also tripped the "no private corpus exists" check). Relocating the virtualenv outside the repository tree and re-running made all 6 disappear with **zero code changes** — conclusively a local tooling-placement artifact of this session, never present in the actual CI environment (which has no such stray directory), and not reflective of any code regression.
2. **1 failure in `test_genesis_v2_sandbox_containment.py::test_oversized_stdout_is_capped_and_killed`** (a file this phase never touched), observed once during a 3,156-test run under heavy concurrent system load from unrelated processes sharing this machine. Re-run in isolation: passed cleanly. Timing/resource-sensitive test, consistent with transient load rather than a real regression.

Both were investigated to a concrete, falsifiable conclusion (moved/removed the suspected cause, re-ran, confirmed the effect disappeared) rather than asserted as "probably unrelated."

## 5b. Audit #017 review (directive item 6)

Reviewed `docs/orneur/status/GENESIS_AUDIT017_REMEDIATION.md` (PR #58) directly, not assumed from memory: all 6 originally reported defects (DEFECT-01 through DEFECT-06) plus the Mission 1A provenance-bypass continuation are self-reported as fixed and regression-tested there, with a stated verdict of `AUDIT017_REMEDIATION_READY_FOR_INDEPENDENT_RETEST`. Checked the live PR list: unlike Audit #016 (which has a successor retest PR, #57, `antigravity/audit016-successor-retest`), **no successor retest PR exists for Audit #017** — PR #58 remains open, draft, and has never received an independent re-verification from Antigravity. This is unchanged from the prior phase and **still blocks** independent qualification of anything built on top of it: PR #65's ancestry includes PR #58's Workstream B/D/Mission 1A work by construction (Section 7 of the prior-phase report), so that work's self-reported-but-unverified status is a standing, carried-forward precondition for any eventual merge to `main` — independent of, and not resolved by, this phase's Audit #71 remediation, which was scoped only to PRs #65/#68/#69/#70.

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

## 8b. Integration-branch ancestry verification (directive item 7)

Independently verified, not assumed: `git merge-base --is-ancestor` confirms both `f2d26c8` (PR #68's exact head) and `da5e8fb` (PR #70's exact head) are real ancestors of PR #65's HEAD. Byte-for-byte diffs of every file this phase touched (`orchestration.py`, `pipeline.py`, `manifest.py`) between each owning branch's head and PR #65's HEAD are empty — the integration branch carries the exact, unmodified latest corrections from both owning branches, not a re-derived or partially-applied copy.

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

**`READY_FOR_INDEPENDENT_REAUDIT`**

All conditions this phase could itself close are now closed and evidenced, not merely claimed:
- All four P0 findings fixed, root-caused, and regression-tested (Sections 2, 4).
- Both P1 boundaries resolved by explicit, honest documentation and a correct-usage regression test, matching the directive's own permitted alternative (Section 3).
- Exact-head CI fully green on all three PRs: **PR #65 19/19, PR #68 9/9, PR #70 9/9** — independently observed via `gh pr checks` after the CI-closure fix in Section 5, not assumed.
- Full GENESIS-suite regression: **3,130 passed, 20 skipped, 0 unexpected failures** (Section 4), cross-checked against an independent unmodified-baseline run.
- Integration-branch ancestry independently verified byte-for-byte against both owning branches (Section 8b).
- Every apparent anomaly encountered along the way (6 pre-existing-looking test failures, 1 flaky test, 2 failed CI checks) was root-caused to a concrete, falsifiable conclusion before being either fixed or ruled out — none were asserted as "expected" or "unrelated" without evidence.

Remaining, explicitly out of this phase's power to close:
- PR #58 / Audit #017's self-reported remediation has never received an independent Antigravity retest (Section 5b) — a standing precondition for `main`, carried forward unchanged.
- The four items in Section 9 require Antigravity's own independent execution, not this session's.

Only the independent auditor may issue the successor qualification verdict; this report records complete engineering evidence and a self-assessed starting point for that re-audit, not a self-declared PASS.
