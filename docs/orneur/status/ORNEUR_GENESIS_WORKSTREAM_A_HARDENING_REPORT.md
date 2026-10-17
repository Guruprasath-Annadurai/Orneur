# ORNEUR GENESIS Workstream A Hardening Report (A-07 through A-11)

Status date: 2026-10-17. Native-Authorization-Convergence directive,
"Workstream A: Production-Grade GENESIS Dataset Engineering and Training
Readiness."

## Exact ancestry and verified starting SHAs

Confirmed exact-match against the directive's stated starting position
before any work began:

| Branch | Head SHA | PR |
|---|---|---|
| `claude/genesis-workstream-f-grant-fields-2026-10-16` | `0942169` | #69 (draft) |
| `claude/genesis-mission2-native-authorization-2026-10-16` | `5874c88` → `eb40cc9` (NaN fix added this session) | #68 (draft) |
| `claude/genesis-cross-workstream-integration-2026-10-16` | `dd2f2ee` → `96e6456` (this session's work) | #65 (draft) |

New branches created this session:

| Branch | Base | Head SHA | PR |
|---|---|---|---|
| `claude/genesis-workstream-a-hardening-2026-10-16` | PR #63 (`a1fab6e`) | `90a5ebb` | #70 (draft) |

**All ancestor branches remain draft and unaccepted.** This report
covers only the Workstream A hardening (A-07 through A-11) and the
narrowly-bounded NaN/boolean-type-confusion fix the directive asked to
be addressed first; it does not re-open or re-litigate Missions 1/2's
already-reported findings.

## Preliminary: narrowly bounded Mission 2 correction (requested first)

Independently reproduced before fixing, per the directive's own
instruction: `GenesisTrainingRun.validate(requested_spend_usd=float("nan"))`
passed the prior `isinstance(..., (int, float))` and `< 0` checks (every
comparison against NaN is `False`), and would have ALSO silently passed
`authorize()`'s later `current.requested_spend_usd > grant.max_spend_usd`
limit check for the identical reason — a NaN spend request bypassed
spend-limit enforcement entirely. Separately, `gpu_requested` used
`bool(gpu_requested)`, so the **string** `"False"` (any non-empty string
is truthy) silently became `gpu_requested=True`, the opposite of caller
intent. Both fixed: `math.isfinite()` now rejects NaN/±inf for spend,
and `gpu_requested`/numeric fields explicitly reject `bool` as a stray
`int` subtype and non-`bool` values respectively. 86/86 tests passing.
Carried through PR #68 → PR #65. This did not reopen or touch any other
part of Mission 1/2's security-reviewed surface.

## A-07: Bounded-memory dataset processing

**Reproduced defect**: `process_corpus()` accumulated THREE
corpus-size-proportional structures entirely in memory — `seen_exact`
(a Python `set` growing by one entry per unique record in the WHOLE
corpus), `kept_records` (every kept record's full text), and
`shard_writers` (every kept record bucketed by shard+split, written to
disk only once at the very end). Peak memory scaled linearly with
corpus size, with no bound.

**Fix**: rewrote around a SQLite-backed durable store
(`_progress.sqlite3`, one per `output_dir`) holding the exact-dedup set,
every kept record's `(shard, split, text)` assignment, and progress —
queried via `SELECT ... WHERE exact_key = ?` (not loaded into Python
memory) and paged in bounded chunks when read back. The processing loop
holds only a `commit_batch_size`-bounded buffer (default 200 records)
plus the already-bounded near-duplicate sliding window (`NEAR_DUP_WINDOW
= 500`, unchanged, already compliant).

**Measured, not assumed**: `test_peak_memory_does_not_scale_with_corpus_size`
uses `tracemalloc` to process a 100-record and a 5,000-record synthetic
corpus (50x larger) and asserts peak traced memory grows to **less than
12.5x**, not 50x — confirmed passing. `test_commit_batch_bounds_the_in_memory_pending_buffer`
confirms the number of real SQLite commit/flush cycles matches
`ceil(kept / commit_batch_size)`, proving batching actually occurs.

## A-08: Correct interruption and resumption

**Reproduced defects**: (1) the final write loop called `os.replace()`
once per shard file, unconditionally — resuming into an existing
`output_dir` silently **destroyed** everything a prior run had already
committed; (2) a crash before that final write loop (i.e. during most of
a large corpus's processing time) produced **zero** durable output and
no resumable progress record.

**Fix**: shard files are now **append-only**, flushed from SQLite's own
durable `kept_records` table (never truncated/replaced). Crash recovery
works via a "safe byte offset" recorded **before** each write attempt
(not only after success) — a genuine bug in my own first draft, caught
by this module's own test suite: without recording the offset first,
the very first write to a given shard file had no prior safe offset to
truncate back to on recovery, producing a duplicate. Fixed by committing
the pre-write offset in its own transaction before attempting the file
write.

Tests: `test_a_resumed_run_produces_the_same_logical_corpus_as_an_uninterrupted_run`
(a "half the corpus, then resume with the full corpus" run produces an
identical final kept set, byte-for-byte identical shard files, to an
uninterrupted single-pass run); `test_resuming_does_not_overwrite_already_committed_shard_content`
(direct regression of the overwrite bug); `test_a_crash_mid_shard_flush_is_cleanly_recovered_on_the_next_call`
(simulates an `os.fsync` failure mid-flush and confirms the next call
recovers to exactly one correct line, not zero or two).

## A-09: Manifest integrity

**Reproduced defect**: `GenesisDatasetManifest.load()` deserialized
whatever `manifest_id` (and every other field) a JSON file claimed, with
**zero** recomputation. A hand-edited file with a substituted
`dataset_name` and an arbitrary `manifest_id` ("ffff...ffff") loaded
without any complaint.

**Fix**: `load()` is now the trusted boundary. It recomputes
`manifest_id` fresh from the file's own claimed binding fields
(`schema_version`, `dataset_name`, `version`, `origins`,
`source_content_digest`, `tokenizer_binding`) and raises
`ManifestTamperedError` on any mismatch, missing required field,
malformed JSON, or an unrecognized `schema_version`. Explicitly
documented (in the exception's own docstring, per the directive's own
caution) that this proves only **internal self-consistency** — it does
not, and cannot, independently authenticate who produced the file.

Tests cover: substituted field + unchanged id, substituted id alone,
missing required field, unrecognized schema version, malformed JSON,
and a negative control (genuine, untampered manifest still loads
cleanly).

## A-10: Actual training-artifact binding

**Added**: `compute_shard_digests(output_dir)` — real, streamed SHA-256
digests of the actual processed shard files on disk (never loading a
whole shard file into memory). This is the concrete artifact
`GenesisTrainingRun.validate()`'s `authorized_shard_digests` parameter
(Mission 2) should be bound to, not an arbitrary caller-chosen string.

**Integration with Workstream C's native preflight** (already built in
Mission 2's M2-03 fix, confirmed working here, not re-implemented):
`validate()` accepts a real `dataset_manifest` object (duck-typed
against `DatasetManifestLike`) plus the actual records, and re-verifies
them itself via `verify_against_records()` before deriving
`dataset_digest` from the VERIFIED object — so the end-to-end test
exercises this path directly rather than passing a bare digest string.

**Demonstrated directly** (`test_tampering_a_shard_after_manifest_binding_invalidates_the_training_identity`):
mint a real synthetic grant bound to a run's original shard digests,
then flip one byte in one shard file on disk. The SAME grant no longer
authorizes the (now-different) declared identity —
`NativePretrainingNotAuthorized: WRONG_AUTHORIZED_SHARDS`.

**Scope note**: tokenizer and transformation-code binding were already
real (tokenizer: `vocab_digest`, a real SHA-256 of the tokenizer's own
vocabulary bytes, already in `GenesisDatasetManifest`; transformation
code: `transformation_code_digest`, bound at the orchestration/grant
layer in Mission 2's M2-01 fix). A-10's actual gap was specifically the
missing shard-byte-level digest; that gap is what this fix closes.

## A-11: Fail-closed contamination controls

**Already solid at the module level** before this session's changes:
`ContaminationReport.is_fully_verified_clean(required_checks=...)`
already implemented the directive's own exact wording ("a dataset
cannot be marked clean merely because no scanner error was reported")
— a report with zero flags but an incomplete `checks_performed` set was
already correctly treated as NOT fully verified clean, confirmed by a
pre-existing test (`test_a_report_with_no_checks_performed_is_never_treated_as_clean`).

**Gap found and fixed**: no check existed for near-duplicate (not
merely exact-duplicate) content LEAKING across train/validation/test
split boundaries — `deterministic_split()` guarantees a given record
never appears in two splits, but says nothing about two DIFFERENT,
near-identical records landing in different splits. Added
`find_near_duplicates_across_splits()`, wired into
`run_contamination_checks()`/`ContaminationReport` alongside the
pre-existing exact-match, normalized-substring, and Genesis Eval V1
holdout-overlap checks.

Tests: a real leaking pair is flagged; within-split pairs are correctly
excluded (that's `process_corpus()`'s own concern); genuinely distinct
records produce no flags; and — directly matching the directive's own
wording — a report missing the cross-split check is confirmed NOT fully
verified clean even with zero flags from whatever checks did run.

## Mandatory end-to-end workflow (`tests/test_genesis_workstream_a_end_to_end.py`)

One complete, CPU-testable pipeline using real project modules and real
filesystem artifacts — no mocking of any critical integrity check:

```
raw synthetic corpus (60 unique + 1 exact duplicate + 1 corrupt record)
  -> process_corpus() [normalization, dedup, bounded incremental shards]
  -> a second call against the SAME output_dir [restart-recovery no-op proof]
  -> run_contamination_checks() [exact + normalized + cross-split, all required, all clean]
  -> GenesisDatasetManifest.build() -> .save() -> .load() [trusted-load re-verification]
  -> .verify_against_records() [re-derived digest matches]
  -> compute_shard_digests() [real shard-byte digests]
  -> GenesisTrainingRun.validate(dataset_manifest=..., dataset_records=..., authorized_shard_digests=real digests, ...)
  -> .request_authorization() -> .authorize(real synthetic NativePretrainingGrant)
  -> run.state == AUTHORIZED
  -> run.start() -> ExecutionAcceptanceIncompleteError (the real, empty founder-acceptance ledger denies it)
```

Confirms the pipeline genuinely prepares a dataset and reaches a real
`AUTHORIZED` orchestration state end to end, while native training
remains **exactly as unauthorized as every other test in this
codebase** — the only thing that changed is that the PREPARATION side
now does real, bounded-memory, crash-safe, independently-verified work,
not that any execution gate has loosened.

## Full regression evidence

Combined regression on the integration branch (`claude/genesis-cross-workstream-integration-2026-10-16`,
head `96e6456`):

```
583 passed in 85.36s
```

Covering: `test_genesis_scaling`, `test_genesis_checkpoint_integrity`,
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

CI on the exact pushed SHAs: pending at time of writing — PR #66 (an
unrelated, earlier branch in this same chain) is confirmed green
(9/9 checks); PRs #68/#69/#70/#65 will be reported once observed, not
assumed.

## Unresolved problems and explicit residuals

- **Crash-consistency within a single SQLite commit batch**: a crash
  mid-batch (before the batch's `COMMIT`) loses that batch's work
  entirely and redoes it from scratch on resume — by design, and
  bounded to at most `commit_batch_size` records, never silently
  duplicated or lost. This is the intended, documented trade-off, not a
  residual defect.
- **Near-duplicate detection remains O(n²) within a bounded window**
  (`NEAR_DUP_WINDOW = 500`), as already documented in the module's own
  docstring — a genuinely large corpus would need MinHash/LSH-based
  near-duplicate detection; that is a drop-in algorithmic upgrade to
  `process_corpus()`'s internals, not a change to its public contract,
  and was explicitly out of scope for this hardening pass.
- **A-09's trust boundary is explicitly internal-consistency-only**: a
  manifest whose `manifest_id` correctly matches its own binding fields
  still does not prove who produced it or that its content is
  independently trustworthy. That remains a separate, unaddressed
  concern (a signed provenance record, or a trusted registry entry) —
  consistent with the directive's own instruction not to conflate the
  two.
- **The real, committed founder-acceptance ledger and authority registry
  were not touched** — every positive-path test in this report uses
  fully isolated synthetic fixtures (`monkeypatch`), confirmed by a
  dedicated negative test
  (`test_full_workstream_a_pipeline_reaches_authorized_but_stays_no_go`'s
  own `run.start()` assertion, and `test_the_real_committed_record_is_not_authorized`
  in the pre-existing Workstream F test suite) that the real repo state
  still denies everything.
- **Legacy GENESIS/NOVUS recovery inventory**: a separate,
  genuinely-investigative body of work, reported independently in
  `ORNEUR_GENESIS_NOVUS_TRAINING_RECOVERY_INVENTORY.md`.

## Verdict

**`READY_FOR_INDEPENDENT_AUDIT`** for the Workstream A hardening (A-07
through A-11) and the preliminary NaN/boolean fix, specifically. All
branches remain draft and unmerged; this is not a self-declared
independent acceptance. Native training remains **NO-GO**: ₹0 spend, no
GPU provisioning, no founder key issuance, no fabricated acceptance
records.
