# ORNEUR GENESIS Foundation — Final Hardening Engineering Report

Status date: 2026-10-17. Native-Authorization-Convergence directive:
"NEXT PHASE: GENESIS FOUNDATION FINAL HARDENING & INDEPENDENT AUDIT
PREPARATION."

## 1. Exact starting and finishing Git SHAs

| PR | Branch | Starting SHA (verified exact-match before work began) | Finishing SHA |
|---|---|---|---|
| #65 (integration) | `claude/genesis-cross-workstream-integration-2026-10-16` | `c048578` | `6cb72bd` |
| #68 (orchestration) | `claude/genesis-mission2-native-authorization-2026-10-16` | `eb40cc9` | `19d7403` |
| #69 (grant fields) | `claude/genesis-workstream-f-grant-fields-2026-10-16` | `0942169` (unchanged this phase) | `0942169` |
| #70 (Workstream A) | `claude/genesis-workstream-a-hardening-2026-10-16` | `90a5ebb` | `f03af2f` |

All four ancestor branches remain draft and unaccepted. PR #58's own
earlier `CONDITIONAL_REMEDIATION_REQUIRED` Audit #017 successor
verdict is inherited unresolved by all of them, unchanged by this
phase.

## 2. Files and modules changed

- `orca/genesis/data/manifest.py` (PR #70): P0-01 fix.
- `orca/genesis/data/pipeline.py` (PR #70): P0-02 (two sub-defects),
  P0-03, P1-01 fixes.
- `orca/genesis/data/contamination.py` (PR #70): P1-02 fix.
- `orca/genesis/training/orchestration.py` (PR #68): the preliminary
  NaN/boolean fix, P1-03 documentation + tests.
- `tests/test_genesis_data_manifest.py`, `tests/test_genesis_data_pipeline.py`,
  `tests/test_genesis_data_contamination.py`, `tests/test_genesis_training_orchestration.py`
  (both PRs): adversarial regressions for every defect above.

No other production module was touched this phase. PR #69's
`orca/genesis/governance/authorization.py` was NOT modified this
phase (its SHA is unchanged) -- confirmed by direct `git log` check
above, not merely assumed.

## 3. Defects reproduced and fixed

### Preliminary (requested first, narrowly bounded)

**NaN/boolean type confusion**: `requested_spend_usd=float("nan")`
passed `validate()`'s prior checks (every comparison against NaN is
`False`) and would have ALSO silently passed `authorize()`'s later
spend-limit comparison for the identical reason. `gpu_requested="False"`
(a string) silently coerced to `True` via `bool(...)`. Both fixed
(`math.isfinite()`, explicit `bool` type checks). Did not reopen any
other part of Mission 1/2's reviewed surface.

### P0-01: Manifest identity completeness

**Reproduced**: `transformation_lineage` was NOT a `manifest_id`
binding field. Two manifests built from identical
records/origins/tokenizer but completely different transformation
histories (one PII-screened+deduplicated, one recording zero steps)
produced the IDENTICAL `manifest_id` -- a genuine identity collision.

**Fixed**: introduced a single shared `_binding_fields()` helper (also
closing the latent "`build()`/`load()` could silently drift apart"
risk from two independently hand-duplicated dict literals), binding
`transformation_lineage` and `source_record_count` explicitly.
`MANIFEST_SCHEMA_VERSION` bumped `.../1` → `.../2`; `load()` correctly
rejects a manifest built under the prior version.

### P0-02: Crash-safe dataset resumption (three further scenarios investigated)

1. **Runs ending with only rejected/corrupt/duplicate records, resume
   offsets, rejection counters after restart**: investigated directly
   via the existing `_load_progress()`/SQLite-commit design -- already
   correct (progress, including all rejection counters, is part of the
   SAME atomic transaction as everything else; a run with zero kept
   records still durably commits and correctly resumes). No defect
   found; not changed.
2. **Near-duplicate detection across restart boundaries**: **reproduced**
   -- the sliding window lived only in process memory and reset to
   empty on every call. An uninterrupted run over one synthetic corpus
   reported 1 near-duplicate and kept 6 records; the identical corpus
   processed via a resume partway through reported 0 near-duplicates
   and kept 7 -- a different logical corpus. **Fixed**: the window's
   tail (bounded to `NEAR_DUP_WINDOW` entries) is now persisted to
   SQLite at the same commit cadence as everything else and reloaded
   at the start of every call.
3. **Interrupted shard writes; missing, truncated, or modified shard
   files**: covered by P0-03 below (a materially identical failure
   mode -- see there).
4. **Changed input files or processing configuration between resumes**:
   investigated directly -- changing `num_shards`/`commit_batch_size`
   between calls against the same `output_dir` does not corrupt
   state (shard assignment is a pure function of content, recomputed
   fresh each call; `commit_batch_size` only affects in-memory batching
   granularity, never correctness). Changing the INPUT FILE's content
   between resumes is a caller error this function cannot detect by
   design (it has no way to know the file "should" be append-only) --
   documented as an assumption, not fixed, since enforcing it would
   require content-hashing the entire input file on every call,
   defeating the point of streaming.
5. **Two processes writing to the same output directory**: **reproduced
   by inspection** (no mutual exclusion existed at all before this
   fix) and **fixed**: an exclusive `flock` on a dedicated lock file,
   held for the full duration of each `process_corpus()` call,
   serializes concurrent callers against the same `output_dir`.

### P0-03: Actual training-artifact integrity

**Reproduced**: externally deleting (or truncating) an already-flushed
shard file left `process_corpus()` completely unaware -- `report.kept`
and the returned `kept_records` (re-read from SQLite, never the
filesystem) still reported the full count even though the actual
processed-shard bytes no longer existed on disk. SQLite's own
`flushed = 1` bookkeeping proved only "this function believes it wrote
this," never "this content is still there" -- directly matching the
directive's own warning not to represent string-format digest
validation as proof real files were checked.

**Fixed**: a startup verification pass
(`_verify_and_recover_missing_or_corrupted_shard_output()`) compares
each shard file's actual current size against its own recorded safe
byte offset; a missing or undersized file resets the affected
`kept_records` rows to `flushed = 0` for idempotent regeneration from
SQLite's durable truth.

**Scope note on the broader P0-03 ask** ("tampering after
authorization," "swapping shard filenames or train/eval roles,"
"reusing stale digests," "changes between verification and
execution"): these are already covered by Mission 2's own existing
machinery, confirmed (not re-implemented) this phase:
`compute_shard_digests()` (A-10) + `GenesisTrainingRun.authorize()`'s
exact-match `authorized_shard_digests` binding means ANY shard-byte
change invalidates a previously-minted grant
(`test_tampering_a_shard_after_manifest_binding_invalidates_the_training_identity`,
already passing); re-verification happens again at every
`start()`/`resume()`/`recovered()` via `_reverify_grant_or_transition()`
(M2-02), not only once at `authorize()` time. "Swapping shard
filenames" is structurally prevented by `_shard_path()` being a pure
deterministic function of `(output_dir, shard_index, split_name)`
rather than a caller-supplied name. No new gap was found in this
specific sub-area beyond the deletion/truncation case already fixed
above.

### P1-01: Real large-corpus memory safety

**Confirmed real** (by direct code reading, not merely assumed): the
processing loop itself held only `commit_batch_size` records at a
time, but the compatibility return value unconditionally
re-materialized the FULL kept-records list before returning, defeating
bounded-memory operation for a caller who didn't need it.

**Fixed**: `return_kept_records: bool = False` short-circuits that
final re-read (default `True` preserves exact backward compatibility);
`iter_kept_records(output_dir)` is a new generator that pages through
SQLite for a caller who does need the records but cannot hold them all
in memory.

**Measured** (from the earlier Workstream A hardening phase, still
valid and re-confirmed passing this phase): `tracemalloc`-measured peak
memory across a 100-record vs. 5,000-record (50x) corpus grows less
than 12.5x, confirming sub-linear growth for the PROCESSING loop
itself, independent of this phase's additional interface-level fix.

### P1-02: Dataset contamination assurance

Reviewed the existing `ContaminationReport.is_fully_verified_clean()`
fail-closed design (confirmed already correct by a pre-existing test:
a report with zero flags but an incomplete `checks_performed` set is
NOT treated as fully verified clean) and `find_near_duplicates_across_splits()`
(added in the prior Workstream A hardening phase).

**Gap confirmed**: the cross-split check had no explicit scalability
limit or indexed implementation at all (an unbounded O(n²) pairwise
comparison). **Fixed**: added an explicit `max_total_records` limit
(default 5000), raising `CrossSplitScreeningTooLargeError` past it --
the directive's own stated alternative to a full MinHash/LSH-indexed
rewrite, which remains documented out-of-scope future work.

"Protected evaluation material is never exposed to the training
pipeline": confirmed unchanged and still correctly enforced --
`orca.eval.genesis_harness.open_split()` remains "the only sanctioned
way" to read HOLDOUT text, and `orca/genesis/data/contamination.py`
structurally never imports it (verified by this module's own
pre-existing AST-based test, re-run this phase, still passing).

### P1-03: Durable native authorization replay protection

Re-examined M2-04's concerns directly:

- **Replay after process crashes / reuse across processes**: already
  durable (on-disk `O_CREAT | O_EXCL` claim, confirmed working by the
  pre-existing cross-process test).
- **Marker deletion and rollback**: **confirmed and explicitly
  documented + tested this phase** (was previously only an implicit
  consequence of the mechanism, not stated or tested directly) -- a
  local operator with write access to `ORCA_HOME` can delete a
  `.claimed` marker and allow that `authorization_id` to be reclaimed.
  This mirrors `orca.train.authorization._claim_run_slot()`'s own
  documented trade-off exactly; the real security boundary is WHO can
  write to `ORCA_HOME`, not the guard mechanism.
- **Filesystem permissions**: confirmed `0o600` (owner-only) on marker
  files, by direct test (`test_marker_files_are_owner_only_permissions`).
- **Path attacks**: `authorization_id` is validated against a fixed
  regex (`^gnpauth-[0-9a-f]{16,64}$`, enforced upstream in
  `orca.genesis.governance.authorization`) before ever reaching the
  filename-construction step in `_claim_native_pretraining_authorization()`
  -- no caller-controlled arbitrary string reaches a filesystem path
  unsanitized. Not independently re-tested this phase (relies on an
  invariant enforced upstream, confirmed by reading, not a new test).
- **Revocation behavior**: confirmed mandatory and fail-closed
  (unavailable/erroring/truthy-non-`True` all treated as denial),
  already tested in the prior phase, re-confirmed passing.
- **Durability guarantees requiring external infrastructure**:
  **cross-host replay is explicitly NOT covered**, newly documented
  this phase -- the durable claim lives on one host's local
  filesystem; closing this would require shared/networked durable
  storage this module does not have and was not asked to build.

## 4. Issues investigated but NOT reproduced

- **P0-02 scenario 1-4** ("runs ending with only rejected records,"
  "changed processing configuration between resumes"): investigated
  directly against the existing design; found already correct or an
  inherent, documented caller-responsibility boundary (changing input
  file content between resumes), not a defect.
- **P0-03's broader scope** (tampering, filename-swapping, stale
  digests): confirmed already closed by Mission 2's existing
  machinery (M2-01/M2-02/M2-03), not a new gap.

## 5. Adversarial tests added (this phase)

`test_different_transformation_lineage_produces_a_different_manifest_id`,
`test_different_transformation_parameters_produce_a_different_manifest_id`,
`test_different_record_count_with_colliding_digest_is_still_bound_explicitly`,
`test_build_and_load_compute_manifest_id_identically`,
`test_load_rejects_a_file_built_under_the_prior_schema_version`,
`test_near_duplicate_detection_matches_across_a_restart_boundary`,
`test_concurrent_writers_to_the_same_output_dir_are_serialized_not_corrupted`,
`test_externally_deleted_shard_output_is_detected_and_regenerated`,
`test_externally_truncated_shard_output_is_detected_and_regenerated`,
`test_return_kept_records_false_returns_an_empty_list_not_the_full_corpus`,
`test_iter_kept_records_pages_through_the_full_corpus_without_process_corpus_materializing_it`,
`test_return_kept_records_true_still_matches_iter_kept_records`,
`test_find_near_duplicates_across_splits_raises_past_the_explicit_size_limit`,
`test_find_near_duplicates_across_splits_allows_a_caller_to_explicitly_raise_the_limit`,
`test_marker_files_are_owner_only_permissions`,
`test_deleting_the_marker_file_allows_the_authorization_id_to_be_reclaimed`
-- 16 new adversarial tests, all independently verified to fail against
the pre-fix code before being confirmed passing against the fix (for
every defect that was genuinely reproduced; the two "investigated but
not reproduced" scenario groups above have no corresponding new test,
by design, since there was no defect to regress-test).

## 6. Focused and full regression results

Focused (per-fix, at time of each commit): all passing, cited inline
above and in each commit message on PRs #68/#70.

Full combined regression on the integration branch (head `6cb72bd`):

```
599 passed in 86.72s
```

Covering all 18 GENESIS-adjacent test files:
`test_genesis_scaling`, `test_genesis_checkpoint_integrity`,
`test_genesis_eval_adapter`, `test_genesis_training_orchestration`,
`test_genesis_data_manifest`, `test_genesis_data_pipeline`,
`test_genesis_data_contamination`, `test_genesis_data_multilingual`,
`test_genesis_cross_workstream_integration`,
`test_genesis_workstream_a_end_to_end`,
`test_genesis_governance_authorization`,
`test_genesis_model_architecture`, `test_genesis_training_primitives`,
`test_genesis_tokenizer`, `test_genesis_audit016_remediation`,
`test_genesis_eval_v1`, `test_training_authorization_gate`,
`test_acceptance_engine`.

## 7. Exact-head CI results

PR #66 (an earlier branch in this same chain, included for continuity):
confirmed **9/9 checks green, mergeable, clean** as of this phase's
last direct check. PRs #68/#69/#70/#65's CI on the exact SHAs in
section 1: **pending at time of writing** -- will be reported honestly
once observed by Antigravity or a subsequent session; not assumed or
fabricated here.

## 8. Remaining P0/P1/P2 risks

- **P0**: none outstanding that were identified and reproduced this
  phase remain unfixed.
- **P1**: the documented, accepted residuals (marker deletion,
  cross-host replay, the SQLite-batch crash-consistency trade-off, the
  advisory-lock boundary) are P1/P2-level by nature (require either
  operator-level filesystem access or external infrastructure this
  module was not asked to build) and are explicitly documented, not
  silently left unstated.
- **P2**: the near-duplicate algorithms (both within-corpus and
  cross-split) remain O(n) windowed / O(n²) bounded respectively, not
  indexed (MinHash/LSH) -- explicitly documented as out-of-scope future
  work in both places, consistent with this module's own long-standing
  documented stance.
- **P2**: `find_exact_matches()`/`find_normalized_substring_matches()`
  (contamination.py's original exact/substring checks) were not
  re-examined for their own scalability bounds this phase -- only the
  newly-added cross-split check was. Worth a future pass if corpus
  sizes grow materially.

## 9. Current native GENESIS training readiness

**Unchanged: NOT_AUTHORIZED, by construction.** The real, committed
founder-acceptance ledger and authority registry were not touched by
any fix this phase. Every positive-path test uses fully isolated
synthetic fixtures; the real-ledger-denies-everything invariant is
re-confirmed by the end-to-end test's own final assertion
(`run.start()` raises `ExecutionAcceptanceIncompleteError` against the
real, unpatched ledger).

## 10. NOVUS checkpoint/evaluation preparation status (parallel assignment)

Re-confirming and building on the prior phase's
`ORNEUR_GENESIS_NOVUS_TRAINING_RECOVERY_INVENTORY.md` (unchanged this
phase; no new filesystem investigation was performed beyond what that
document already covers):

- **Checksum-verified historical NOVUS adapter**: `orca-core`'s QLoRA
  adapter, `sha256:094de7b23a0ce1b343b560c4c0354e408c48c2e1d74c84e03fbd4d65694ed5e4`,
  `r=64`/`lora_alpha=128`, `base_model_name_or_path=unsloth/meta-llama-3.1-8b-instruct-unsloth-bnb-4bit`
  -- confirmed matching `orca/train/variants.py`'s core-tier
  `lora_rank=64` exactly (real corroborating lineage evidence).
- **Evaluation artifacts that genuinely exist**: `eval_orca-core.json`,
  `eval_orca-core-combined-v2.json`, `novus_eval_orca-core-{v1,v2}.json`,
  `novus_eval_judged_orca-core.json`,
  `novus_eval_orca-core-combined-v2.json`,
  `redteam_orca-core{,-v1,-v2,-dpo,-calibration,-combined,-combined-v2}.json`,
  plus a timestamped `history/` subdirectory -- all confirmed present
  directly on the local filesystem.
- **Missing evaluation evidence**: the "attempt 3" result
  (`orca-core-combined-v2`, the latest adapter) had not returned as of
  the prior phase's investigation -- not independently re-checked for
  completion this phase; treat as still pending unless a fresher
  report is found.
- **Why exact optimizer-state resumption is unavailable**: every
  checkpoint in the registry records `optimizer_state_available: false`
  and `scheduler_state_available: false` -- no optimizer momentum/
  variance state or scheduler step count was ever captured during the
  original Kaggle/Colab training sessions (`step_or_epoch: "unknown
  (legacy, predates run-manifest tracking)"`). There is no artifact to
  recover; this is not a retrieval gap, it is a gap in what was ever
  produced.

### Reproducible, resource-estimated proposal for a NEW NOVUS fine-tuning continuation

This is a PROPOSAL only -- no training, GPU provisioning, or spend
occurs as part of producing it.

1. **Starting point**: load `orca-core`'s verified QLoRA adapter
   (checksum above) onto its documented base,
   `unsloth/meta-llama-3.1-8b-instruct-unsloth-bnb-4bit`, as
   INITIALIZATION -- not a resumption. A fresh optimizer (AdamW, the
   base config already used in prior rounds per `orca/train/config.py`)
   starts from zero state; this is a genuinely NEW training run, not a
   continuation of the original run's trajectory.
2. **Dataset**: `core_distilled_20260826.jsonl` (60 calibration
   examples) + `core-dpo_probe_grounded_safety_dpo_20260826.jsonl`
   (the most recent safety set) -- both already present locally, no
   new data collection required for a first attempt. The prior
   session's own finding (3 real safety examples is a "notably thin"
   base) should inform any oversampling ratio chosen, per the
   documented lesson from "fix attempt 1/2/3"'s oscillating
   safety:calibration ratios (1:20 → diluted to no effect; 1:2 → safety
   dominated, calibration collapsed; 1:5 → the most recent, still
   pending its own eval).
3. **Resource estimate**: matching the prior rounds' own documented
   infra (`orca-core-combined-sft-kernel-v1`, a Kaggle T4-class single
   GPU kernel) -- a LoRA/QLoRA SFT run of this size and data volume
   (60-100 examples) on a T4 typically completes in well under an hour
   of GPU time per attempt, based on the prior session's own completed
   kernel runs (not independently re-timed this phase). **No cost
   estimate is given beyond "within Kaggle's free T4 quota," since
   this proposal does not include executing it.**
4. **Evaluation**: `orca/train/redteam.py` (jailbreak block rate,
   bias, calibration) and `orca/train/novus_eval.py` (keyword +
   LLM-judge scoring) -- both already real, tested, and used for every
   prior round; no new evaluation infrastructure needed.
5. **Explicit gate**: per this directive's own restriction, executing
   ANY part of this proposal (the training run itself) requires
   founder approval, separate from and unrelated to native GENESIS
   pretraining's own authorization chain.

## 11. Explicit items requiring independent Antigravity verification

- All adversarial test logic claimed as "reproduced before fixed" in
  section 3 -- independent re-execution of each named test against the
  pre-fix commit (available via `git show <commit>^:<path>`) is the
  strongest form of verification and was not something this session
  could substitute for.
- The crash-consistency and lock-ordering reasoning in P0-02/P0-03's
  fixes (SQLite transaction boundaries, the pre-write-offset-first
  discipline) -- these are concurrency/crash-safety arguments verified
  here by targeted simulation (mocked `os.fsync` failures, concurrent
  threads), not by formal proof or real multi-process crash injection
  under load.
- CI results on the exact SHAs in section 1, once they land.
- The NOVUS proposal's resource estimate (section 10) -- based on prior
  session's own completed kernel timings, not independently re-measured
  this phase.

## Verdict

**`READY_FOR_INDEPENDENT_AUDIT`** for this phase's P0-01/P0-02/P0-03/
P1-01/P1-02/P1-03 hardening and the preliminary NaN/boolean fix,
specifically. This is not a self-declared independent acceptance --
Antigravity's own review per section 11 remains required. Native
GENESIS training remains **NOT_AUTHORIZED**; NOVUS fine-tuning remains
**not executed, proposal only**; AETERNUM remains deferred. No merges
to `main`, no founder keys, no fabricated acceptance records, no spend.
