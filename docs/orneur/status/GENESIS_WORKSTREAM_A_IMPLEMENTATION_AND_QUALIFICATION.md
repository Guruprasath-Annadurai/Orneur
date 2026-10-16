# GENESIS Foundation Sprint 2 — Workstream A: Reproducible Native Pretraining Data Foundation

Status date: 2026-10-16. Branch: `claude/genesis-workstream-a-2026-10-16`,
branched from **PR #55's exact head, `88ac6da8450f7751e002aa243053c541d5eae4e5`**
(GENESIS Foundation Sprint 1) -- **not** from PR #58 or PR #61. Workstream A
needs only Sprint 1's tokenizer/model contracts
(`orca.genesis.tokenizer.framework`, `orca.genesis.model.config`), and
deliberately does not inherit PR #58's or PR #61's own unresolved
independent-review status, per explicit instruction. No native training, no
GPU use, no spend, no merges, no frozen-governance changes occurred.

## Branch ancestry

```
main (20a8546) -- PR #51
  -> PR #55 Sprint 1 (88ac6da) <- THIS BRANCH's parent
       -> PR #58 Sprint 2 Workstreams B/D/E + Mission 1A (3a27245)
            -> PR #61 Workstream C (330f1b8 -> ff9175f, under independent review)
  -> claude/genesis-workstream-a-2026-10-16 (this branch, sibling of PR #58/#61, not a descendant)
```

Workstream A's own commits add four new modules under `orca/genesis/data/`
plus their test suites and one `tests/conftest.py` isolation fix -- nothing
under `orca/genesis/training/` or `orca/genesis/model/` was touched, and
`checkpoint_integrity.py`/`eval_adapter.py`/`orchestration.py` (PR #58/#61's
own additions) do not exist on this branch at all.

## Reused, qualified implementations (not duplicated)

- `orca.registry.dataset_manifest.sha256_of_file` -- file hashing.
- `orca.config._mkdir_owner_only` -- the established owner-only (0700)
  directory-creation discipline every registry in this codebase already uses.
- `orca.genesis.model.config.ARCHITECTURE_VERSION` -- architecture identity.
- `orca.eval.genesis_contamination.normalize_text`/`word_ngrams`/`jaccard` --
  the same near-duplicate algorithm the Genesis Capability Eval V1 corpus's
  own contamination control already uses, applied here to raw pretraining
  records instead of eval-corpus items.
- `orca.eval.genesis_contamination.screen_training_texts` -- reused directly
  (not reimplemented) for benchmark-overlap screening.
- `orca.eval.genesis_corpus.CORPUS_DIR`/`FINGERPRINT_FILE` -- the exact,
  already-committed, non-text fingerprint file `orca.eval.genesis_prereg`
  and `tests/test_genesis_eval_v1.py` already read the same way.
- `orca.learning.sanitize.sanitize_for_candidate` -- PII/secret screening,
  the same DLP path `orca.learning.pipeline`'s curriculum pipeline uses.
- `orca.genesis.tokenizer.framework.GenesisTokenizer`/`per_language_fertility_report`/
  `code_switching_fertility` (Sprint 1) -- fertility and round-trip
  measurement, not reimplemented.
- The atomic-write discipline (`tempfile.mkstemp` + `fsync` + `os.replace`)
  established in Sprint 1's `save_training_state` -- reimplemented as a
  small local helper in `pipeline.py` (not imported, since
  `checkpoint_integrity.py`/`primitives.py`'s private helper live on a
  different branch this one deliberately does not inherit), but following
  the identical, already-reviewed pattern.

The existing `orca.registry.DatasetManifest` (single train/eval-file,
LoRA-fine-tune shape) was deliberately **not** extended or subclassed --
GENESIS native pretraining's shape (many shards, no LoRA concept,
tokenizer-digest binding) is different enough that forcing it into that
schema would blur two genuinely different contracts. `orca.genesis.data.manifest.GenesisDatasetManifest`
is a sibling, not a duplicate; both coexist.

## Mission A1 — Dataset provenance and trust

`orca/genesis/data/manifest.py`: `GenesisDatasetManifest.build()` is the
ONLY constructor. It computes a real, order-independent SHA-256 content
digest from the actual normalized records (never accepts a caller-supplied
digest string -- Mission A5's explicit requirement), and raises
`ProvenanceRejected` for: no origins, a missing license, missing usage
restrictions, empty records, or a non-hex/malformed tokenizer vocab digest.
`manifest_id` is content-addressed (a canonical hash over every binding
field: schema version, dataset name/version, origins, content digest,
tokenizer binding) -- two manifests with identical binding fields always
produce the identical id; any change to a binding field changes it.
Covers: origin/identity, source license/usage restrictions, versioning +
source checksums, deterministic normalization (`normalize_record_text` --
NFC + whitespace collapse, documented as deterministic and idempotent),
transformation lineage (`TransformationStep` list), tokenizer version +
digest binding (`TokenizerBinding`), immutable manifest identity, and
explicit rejection of missing/unverifiable provenance.

Tests: `tests/test_genesis_data_manifest.py`, **17/17 passing** --
content-addressing (order-independence, change-sensitivity), every
rejection case, save/load round-trip, owner-only (0600) file permissions,
and forged-file-content detection (an edited manifest's own recomputed id
no longer matches its stored id).

## Mission A2 — Streaming dataset pipeline

`orca/genesis/data/pipeline.py`: `process_corpus()` runs the full stage
sequence -- `stream_records()` (a generator, never materializing the whole
file in memory) -> corrupt-record rejection (malformed JSON, non-dict
records, missing/empty `text` field, each counted and sampled, never
raised past the function) -> `normalize_record_text` -> exact-duplicate
rejection (SHA-256 of normalized text) -> bounded-window (500 records)
near-duplicate rejection (word 5-gram Jaccaard >= 0.85) -> optional
caller-supplied quality filter -> optional PII/secret screening
(`sanitize_for_candidate`) -> deterministic shard + train/validation/test
split assignment (both pure functions of record content, never of
position) -> atomic, owner-only (0600) shard file writes. `resume_from_line`
and `ProcessingReport.resume_offset` give restart safety: a caller can
resume from exactly where a prior run left off, verified by directly
confirming a mid-stream resume yields exactly the remaining records.

Tests: `tests/test_genesis_data_pipeline.py`, **27/27 passing** -- corrupt
records (3 kinds), exact + near duplicates, genuinely-distinct records kept,
interrupted/resumed processing, deterministic shard/split (including a
byte-identical-output reproducibility test across two full independent
runs), quality filtering, PII/secret rejection (and explicit opt-out),
atomic-write permissions, a simulated crash during shard write leaving no
partial `.tmp-` file behind, 4 concurrent threads processing the same input
against separate output directories without corrupting each other or
diverging in kept-record count, a streaming-not-list-materializing check,
a bounded (not unbounded) near-duplicate window across 2000 distinct
records, and untrusted-path handling (nonexistent file, a directory passed
as a file).

## Mission A3 — Benchmark contamination controls

`orca/genesis/data/contamination.py`: `run_contamination_checks()` runs
exact-match and normalized-substring-match checks against an explicitly
supplied protected-text set, and/or a holdout-overlap check against the
Genesis Capability Eval V1 corpus's own n-gram fingerprints. **Protected
content is never accessed without authorization**: this module reads only
the pre-committed `holdout_fingerprints.json` (n-gram hashes, never raw
text) via the exact same pattern `orca.eval.genesis_prereg` already uses --
confirmed by a structural test parsing this module's own AST to verify it
never imports `orca.eval.genesis_harness.open_split` (the one sanctioned,
purpose-gated way to read raw HOLDOUT text) or `genesis_corpus.load_split`
directly. `ContaminationReport.is_fully_verified_clean(required_checks=...)`
is the honest gate Mission A3 explicitly demands: a report is never treated
as clean merely because no scanner error was reported -- it must both have
zero flags AND have actually run every check the caller requires.

Tests: `tests/test_genesis_data_contamination.py`, **11/11 passing**.

## Mission A4 — Multilingual preparation

`orca/genesis/data/multilingual.py`: integrates Sprint 1's existing
`per_language_fertility_report`/`code_switching_fertility`/`round_trip_check`
(not reimplemented) with two new measurements this framework didn't yet
expose -- `check_byte_fallback()` (verifies a genuinely unseen Unicode
character, chosen specifically for having no linguistic significance,
still round-trips correctly via SentencePiece's `byte_fallback=True`) and
sequence-length expansion (mean tokens-per-character, a second efficiency
signal complementing fertility's tokens-per-word). `REPRESENTATIVE_FIXTURES`
covers English plus three Indian languages spanning distinct scripts
(Hindi/Devanagari, Tamil, Telugu) with short, hand-authored, mundane,
rights-cleared sentences -- no external corpus. The module's own docstring
and a dedicated structural test both make explicit: this measures
**tokenizer behavior only**, never reasoning, fluency, or translation
quality.

Tests: `tests/test_genesis_data_multilingual.py`, **9/9 passing**, run
against a real SentencePiece tokenizer trained from the fixture texts
themselves (vocab_size=600) -- every number in the report is a real,
reproducible measurement, not an estimate.

## Mission A5 — Model and authorization integration contracts

`GenesisDatasetManifest`'s `manifest_id` and `source_content_digest` ARE
real SHA-256 cryptographic content digests, computed in `build()` from the
actual normalized record bytes -- never a caller-supplied arbitrary string
(`ProvenanceRejected` is raised for a malformed/non-hex tokenizer digest;
the dataset content digest is never accepted as input at all, only
computed). This is exactly the verifiable dataset identity Mission A5
requires, ready to eventually bind to GENESIS training authorization.

**The integration gap, documented for Workstream F rather than worked
around**: `orca.genesis.training.orchestration.GenesisTrainingRun.validate(
dataset_digest: str)` (PR #61, independently under review) currently
accepts ANY caller-supplied 64-hex-character string with zero verification
that it corresponds to real, provenance-checked data -- it has no concept
of a `GenesisDatasetManifest` at all. Workstream A does **not** modify
`orchestration.py` (an independently-reviewed branch this workstream must
not touch, per explicit instruction). The integration requirement for
Workstream F: `validate()` (or a successor to it) should require a real
`GenesisDatasetManifest` (or its independently re-verified
`source_content_digest`, via `verify_against_records()`) rather than any
bare string -- closing the same class of gap C-01's workload-binding fix
closed for the authorization-grant side, on the dataset-identity side.
Training orchestration remains fully disabled; no authorization grant was
issued and no parameter update occurred anywhere in this workstream.

## Mission A6 — Independent qualification

Adversarial coverage across all four modules, by category from the
directive's own list:

| Required adversarial case | Covered by |
|---|---|
| Dataset tampering | `test_verify_against_records_detects_content_tampering`, `test_loaded_manifest_detects_forged_file_content` |
| Forged manifests | `test_loaded_manifest_detects_forged_file_content` (recomputed id vs. stored id mismatch) |
| Changed tokenizer identity | `test_manifest_id_changes_if_tokenizer_binding_changes`, `test_rejects_a_non_hex_vocab_digest` |
| Nondeterministic sharding | `test_deterministic_shard_is_a_pure_function_of_content`, `test_reprocessing_the_same_input_produces_identical_shard_file_contents` |
| Train/evaluation leakage | `test_deterministic_split_is_reproducible_and_disjoint` (content-pure split assignment; contamination module's holdout-overlap check) |
| Interrupted processing | `test_interrupted_processing_can_resume_from_the_reported_offset`, `test_no_partial_shard_file_is_left_behind_on_a_simulated_write_failure` |
| Repeated records | `test_exact_duplicates_are_rejected`, `test_whitespace_and_case_variant_duplicates_are_caught_via_normalization` |
| Invalid license/provenance fields | `test_rejects_an_origin_with_no_license`, `test_rejects_an_origin_with_no_usage_restrictions_stated`, `test_rejects_empty_origins` |
| Untrusted input paths | `test_nonexistent_input_path_raises_a_clear_error`, `test_a_directory_passed_as_input_path_raises_rather_than_silently_producing_nothing` |
| Concurrent writers | `test_concurrent_pipeline_runs_against_separate_output_dirs_do_not_corrupt_each_other` (4 real threads) |
| Excessive memory consumption | `test_streaming_reader_does_not_load_the_whole_file_into_memory`, `test_near_duplicate_window_is_bounded_not_unbounded` |

## A real test-isolation gap found and fixed along the way

`GenesisDatasetManifest.save()`/`.load()` use a module-level
`GENESIS_DATASET_MANIFEST_DIR` constant derived from `ORCA_HOME`, following
the exact same pattern every other registry module in this codebase uses
(`DATASET_MANIFEST_DIR`, `CHECKPOINT_DIR`, etc.) -- and this codebase
already has an established, autouse `tests/conftest.py` fixture
(`_isolate_gateway_registry_dirs`) that redirects every one of those
constants to a per-test tmp directory, specifically because a prior
regression let a test write into a developer's real `~/.orca/registry/`.
This new constant was not yet in that list. Added
`genesis_dataset_manifest_dir_tmp` and the corresponding
`monkeypatch.setattr` to `tests/conftest.py`'s existing fixture -- confirmed
via a full re-run of unrelated registry test files
(`test_registry_lifecycle.py`, `test_registry_id_sanitization.py`,
`test_training_provenance.py`, 129 tests) that this change caused no
regressions elsewhere.

## Regression evidence

Full local run (`/Users/ag/orca/.venv`, Python 3.11.15, torch 2.13.0,
sentencepiece 0.2.2):

```
tests/test_genesis_data_manifest.py ......................... 17 passed
tests/test_genesis_data_pipeline.py ....................... 27 passed
tests/test_genesis_data_contamination.py ................. 11 passed
tests/test_genesis_data_multilingual.py .................... 9 passed
tests/test_genesis_model_architecture.py, test_genesis_training_primitives.py,
tests/test_genesis_tokenizer.py, test_genesis_eval_v1.py,
tests/test_training_authorization_gate.py (all pre-existing, unmodified) ... all passing

== 314 passed in 76.16s ==
```

Plus a separate confirmation run of `test_registry_lifecycle.py`,
`test_registry_id_sanitization.py`, `test_training_provenance.py` (129
tests) to validate the `conftest.py` change in isolation.

CI on this exact commit: will be reported once pushed and observed, per
this session's standing practice of never asserting unobserved CI results.

## Findings preserved for Antigravity (review targets, not demonstrated exploits)

Per the founder's explicit instruction, the following are flagged as
**investigation targets for the independent reviewer of PR #61**, not
claims that they are already confirmed exploits:

1. Whether mutable `RunIdentity` (in `orca.genesis.training.orchestration`)
   permits changing the dataset or model identity after initial
   authorization.
2. Whether absence or failure of a live revocation hook can permit a
   transition that should be blocked.
3. Whether synthetic LoRA-shaped grants can ever be confused with genuine
   GENESIS-native authorization.
4. Whether reported execution steps (`ExecutionEvent`,
   classification=`REPORTED_EXECUTION_PROGRESS`) can be mistaken for
   verified optimizer progress by a downstream consumer that does not read
   the `classification` field.

This workstream does not attempt to resolve any of these -- they belong to
PR #61, which remains under independent review.

## Known limitations (not claimed as solved)

- Near-duplicate detection is O(n^2) within a bounded 500-record window --
  a real multi-GB corpus would need MinHash/LSH-based detection, a drop-in
  algorithmic replacement, not a contract change.
- `check_byte_fallback()` tests one unseen character; it does not attempt
  to enumerate every possible OOV case.
- The dataset-to-authorization integration gap (Mission A5) is documented,
  not closed -- see the Workstream F integration requirement above.
- Tokenizer fixtures in `multilingual.py` are deliberately short and mundane
  (3 sentences per language); this is sufficient to exercise the mechanism
  honestly, not a claim of comprehensive linguistic coverage.

## Verdict

**`READY_FOR_INDEPENDENT_AUDIT`** for Workstream A as implemented and
tested above (Missions A1-A6 complete). No native training, no GPU
provisioning, no spend, no merges, no frozen-governance changes occurred.
Workstream F (founder authorization/dataset/model/tokenizer identity
binding, execution evidence, revocation, acceptance criteria) has not yet
been started -- it is the explicit next step, on its own isolated branch,
per the founder's own sequencing instruction.
