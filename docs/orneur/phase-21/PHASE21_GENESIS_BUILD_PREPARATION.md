# PHASE 21B — Genesis 1 Build Preparation

Infrastructure/data/evaluation-readiness closure. **No canonical Genesis
checkpoint has been trained.** Genesis remains `NOT_TRAINED` /
`UNAVAILABLE` in the trusted Phase 20 router throughout and after this
closure (see `tests/test_genesis_not_trained_guard.py`).

## 1. Canonical identity (unchanged)

`Orneur Genesis`, generation 1, `family="genesis"`, role Builder /
Executor -- Executable Intelligence. Parameter starting class ~3B
(provisional, no permanent ceiling). Router: `CognitiveRole.
BUILDER_EXECUTOR`, `NOT_TRAINED`, `UNAVAILABLE`, unchanged by this
closure.

## 2. Base model qualification

See `GENESIS_BASE_MODEL_QUALIFICATION.md` for full detail, verified live
against authoritative HF sources (not memory) on 2026-09-16. Summary:

- Repo: `unsloth/Qwen2.5-3B-Instruct` (unchanged selection), a direct
  repack of `Qwen/Qwen2.5-3B-Instruct` -- no architectural modification.
- Pinned commit SHA (new this closure):
  `7548fff1f997f57b2e9e8ab1ec7be96949b00ed0`, recorded in
  `orca/registry/model_spec.py::MODEL_SPECS["genesis"].base_model_revision`
  / `.tokenizer_revision`, with a new fail-closed accessor
  `require_pinned_revision()` refusing to resolve an unpinned "latest".
- Architecture: Qwen2, 36 layers, hidden_size 2048, GQA (16 Q heads / 2
  KV heads), 3.09B nominal params (2.77B non-embedding), native context
  32,768 tokens (the repo's own `context_length=4096` field remains a
  training-time sequence-length choice, not the architectural ceiling).
- **License -- MATERIAL BLOCKER**: `qwen-research` (Qwen RESEARCH
  LICENSE AGREEMENT), **non-commercial use only**. Recorded in
  `model_spec.py` as `license_name="qwen-research"`,
  `license_commercial_use="RESTRICTED"`. This blocks a *commercial*
  Genesis release on this exact base, not research/internal training --
  see the qualification doc's "Options for the owner to consider"
  section. **Not resolved here; requires owner decision.**

## 3. Dataset architecture

Two dataset manifests now exist for Genesis, both real
`DatasetManifest` records under `~/.orca/registry/datasets/` with
checksums, dedup verification, and (v2) explicit train/eval leakage
checks:

| Dataset | Records | Domains | Status |
|---|---|---|---|
| `orneur-genesis-combined-safety-calibration-v1` (Phase 0.5) | 37 | safety-refusal, calibration/premise-correction | Never used for training; small, template-limited (29% near-duplicate pairs) |
| `orneur-genesis-v2` (this closure) | 19 | requirement interpretation, implementation planning, debugging/root-cause, test creation, security-aware implementation, evidence-aware completion, authority-boundary, tool-use planning, consequence awareness, uncertainty handling | Never used for training; hand-authored this session, genuinely diverse across 11 domains, ChatML-formatted (correct for Qwen2.5, unlike v1's Llama-3 formatting) |

**Token accounting** (whitespace-token proxy, matching the established
convention in `docs/orneur/phase-0/GENESIS_DATASET_BASELINE.md` -- the
real Qwen BPE tokenizer was not downloaded, per this closure's own
"do not download multi-GB weights" restriction and, more specifically,
per Phase 21B.1's explicit instruction to use a clearly-labeled estimate
rather than a forbidden download; a real tokenizer-exact count is a
Phase 21C preflight step, not required here):

| Split | Records | Whitespace-tokens (min/p50/max/total) |
|---|---|---|
| v1 train | 34 | 149 / 336 / 525 / 11,685 |
| v1 eval | 3 | 107 / 246 / 248 / 601 |
| v2 train | 16 | 119 / 160 / 230 / 2,665 |
| v2 eval | 3 | 145 / 169 / 218 / 532 |
| **Combined** | **56** | **~15,483 whitespace-tokens total** |

Real BPE token count is typically somewhat higher than the whitespace
proxy for English text (subword splitting) -- this total should be read
as a conservative lower-bound estimate, not an exact figure.

Combined: **56 records total across both manifests.** Honest
assessment: **this is not adequate for a production SFT run.** A
meaningful first training experiment likely needs low-thousands of
records minimum, with real coverage depth per domain (2-3 examples per
domain is a seed, not a corpus) and, ideally, executable verification
for the code-adjacent categories (test creation, debugging) rather than
illustrative-only responses. Per this closure's own "do not manufacture
scale" instruction, **no attempt was made to pad this via templated
generation** -- the honest current dataset requirement is: **substantial
expansion needed before Phase 21C**, not a blocker to *preparing* for
Phase 21C.

Builder: `scripts/build_genesis_v2_dataset.py` -- deterministic (seed
42), schema-validated, fail-closed on malformed records, missing
fields, empty strings, and duplicate `(domain, prompt)` pairs (see
`tests/test_genesis_v2_dataset_builder.py`, 10 tests). Source seed file
is untracked local data (`~/.orca/training/raw/genesis_v2_seed_20260916.jsonl`,
matching the existing `~/.orca/` convention), hand-authored this
session -- clean, single-author provenance, no scraped/proprietary
content.

## 4. Training configuration

`orca/train/config.py::TrainingConfig.preset("nano")`, resolved from
`MODEL_SPECS["genesis"]` (unchanged): QLoRA rank 32, alpha 64, dropout
0.05, target modules `[q,k,v,o,gate,up,down]_proj`, `max_seq_length=4096`,
batch size 4, gradient accumulation 4 (effective batch 16), 3 epochs,
lr `2e-4`, cosine schedule, 5% warmup, seed 42, bf16. These remain the
starting hypothesis, not finalized/justified against real data yet
(Phase 21C's own runbook step "baseline eval" is the point at which
these would actually get tuned against evidence).

## 5. Reproducibility closure (this closure's primary infrastructure work)

**Before**: `orca.registry.training_run.TrainingRunManifest` existed as
a complete, well-designed contract, but no real training entry point
ever called it -- `~/.orca/registry/training_runs/` was empty despite
real historical training having occurred (Phase 21A audit finding).

**After**: `orca/registry/provenance.py` (new) wires
`TrainingConfig -> TrainingRunManifest -> CheckpointRecord ->
ModelRegistry`:

- `start_training_run()` validates identity (`validate_training_identity()`,
  the existing Phase 16 fail-closed guard) and persists a manifest
  **before** any model/dependency loading.
- `orca/train/finetune.py::train()` now calls this at its very first
  line, wraps the real GPU pipeline (`_train_impl`, extracted from the
  original `train()` body) in try/except, and calls
  `complete_training_run()` (registers a real `CheckpointRecord` at
  `EXPERIMENTAL` lifecycle **only** -- never auto-`PROMOTABLE`/
  `PRODUCTION`) on success or `fail_training_run()` on any exception.
- Verified end to end, on CPU, with **zero mocking**: this environment
  genuinely has no unsloth/trl/datasets/peft/bitsandbytes installed, so
  calling `train()` genuinely raises `ImportError` -- proving the real
  manifest-created / marked-failed wiring against a real failure, not a
  simulated one (`tests/test_training_provenance.py::
  test_finetune_train_wrapper_marks_manifest_failed_on_missing_dependencies`).
- 8 tests total in `tests/test_training_provenance.py`: manifest
  creation/persistence, fail-closed identity validation (both bypass
  classes from Phase 16), successful-completion checkpoint registration
  at EXPERIMENTAL-only, and the failure path never creating a
  checkpoint.

**Test-hermeticity fix (found live during this closure)**: the Phase
21A audit discovered real test-run pollution in the developer's actual
`~/.orca/registry/` (fake evaluation records, a stray redteam file) --
root cause: `tests/conftest.py`'s existing autouse isolation fixture
covered `DEPLOYMENT_DIR`/`LEASE_DIR`/`DOCS_DIR` but never the model/
dataset/checkpoint/training-run registries, the exact same unisolated-
module-constant class of bug that fixture's own docstring already
warns about for other stores. Fixed this closure by extending the same
fixture to isolate `CHECKPOINT_DIR`, `DATASET_MANIFEST_DIR`,
`EVALUATION_REGISTRY_DIR`, `REGISTRY_STATE_PATH`, and
`TRAINING_RUN_DIR` -- confirmed live (re-ran the affected tests, checked
`~/.orca/registry/` file timestamps before/after: no new pollution).

## 6. Checkpoint contract

`orca/registry/checkpoint.py::CheckpointRecord` (pre-existing, unchanged)
already enforces the required separation: `validation_state` defaults
`UNVALIDATED`, `availability` defaults `MISSING` (never assumed present),
`is_loadable()`/`is_routable()` require an explicitly-verified `LOCAL`
artifact. `ModelRegistry.register()` always registers at `EXPERIMENTAL`;
only `ModelRegistry.promote()` can reach `PRODUCTION`, and it refuses
without a passing `pass_fail_status == "PROMOTABLE"` evaluation report.
**No canonical checkpoint was created this closure** -- confirmed by
`tests/test_training_provenance.py`'s own assertions and by this
closure's live `train()` invocation genuinely raising before any
checkpoint step.

## 7. Evaluation suite

**Honest status: NOT substantially expanded this closure.**
`orca/train/genesis_eval.py` (pre-existing, real, keyword-coverage
scoring, 30 prompts covering business/coding/Hindi-English) remains the
only executable Genesis evaluation. The 12-category suite this closure's
spec requested (coding, debugging, architecture, product-building,
tool-planning, uncertainty, fabricated-completion resistance, security,
authority-boundary, broad professional reasoning, each with real
task counts and held-out status) was **not built** in this closure --
scoped out given the size of everything else in this closure, and
reported honestly here rather than claimed. This is the single largest
remaining gap before Phase 21C readiness; see &sect;9 Blocking Gaps.

The Genesis v2 dataset's `evidence_aware_completion` and
`authority_boundary` domains (6 records combined) are training examples,
not evaluation tasks -- they teach the target behavior but do not score
it. Building a genuine held-out evaluation set for these two categories
specifically (distinct examples from the training set, per
`test_build_produces_no_train_eval_leakage`'s already-enforced split)
is a concrete, scoped next step.

## 8. CPU-safe pipeline verification

`tests/test_training_provenance.py`'s
`test_finetune_train_wrapper_marks_manifest_failed_on_missing_dependencies`
is the CPU-safe orchestration proof requested by this closure's spec
section 29 -- it exercises the REAL `orca.train.finetune.train()`
entrypoint (not a parallel test-only path), proving: config resolution
-> identity validation -> manifest creation -> (real, unmocked) failure
-> manifest marked failed -> no checkpoint created. This is
infrastructure verification, not model training -- no model weights,
GPU, or network access were touched.

## 8.5. Phase 21B.1 closure (material blockers fixed)

An independent audit found Phase 21B's provenance wiring recorded
revisions/dataset IDs without actually enforcing them. Fixed:

- **Revision enforcement**: `orca/registry/provenance.py::
  resolve_pinned_revisions()` now runs before manifest creation, fails
  closed for any canonical family without a pinned revision, and its
  result is passed through to `orca/train/finetune.py::
  _load_base_model_and_tokenizer()`, which forwards it as `revision=`
  to Unsloth's real `FastLanguageModel.from_pretrained()` (verified
  live against Unsloth's own current source that this parameter exists
  and is honored). `tests/test_training_provenance.py` mocks the loader
  call itself (via `sys.modules` injection, no unsloth import needed)
  and asserts the exact pinned revision is received.
- **Dataset binding**: `verify_dataset_binding()` rejects an empty
  `dataset_manifest_ids` for any canonical (family-set) training
  request (closing "empty list as normal successful state"), and when
  exactly one dataset manifest is declared, cryptographically
  re-hashes the actual `cfg.train_file`/`cfg.eval_file` bytes and
  compares against that manifest's recorded checksums -- a tampered or
  wrong file is rejected before any model loading. Multi-manifest
  combined-file verification remains existence-only (documented
  limitation, not silently glossed over -- see the function's own
  docstring).
- **Checkpoint identity**: `hash_artifact_directory()` replaces "hash
  the first merged-model file" with a deterministic, sorted, multi-file
  manifest digest covering every file (config, tokenizer, every weight
  shard) under the checkpoint directory -- changing ANY file changes
  the checkpoint's identity, verified by dedicated mutation tests.
- **`TrainingRunManifest` expansion**: now directly carries
  `base_model_revision`, `tokenizer_revision`, `dataset_content_digests`,
  and `compute_provider` (all additive, backward compatible).

26 tests in `tests/test_training_provenance.py` (was 8) cover all of the
above, including the exact adversarial cases named by the audit
(tampered dataset file, missing declared file, missing dataset
manifest, unpinned revision for a canonical family, checkpoint digest
mutation sensitivity for shards/config/missing-files, filesystem-order
independence).

## 8.6. Phase 21B.2 closure (training-input & checkpoint trust boundary)

An independent audit found Phase 21B.1's dataset binding had a
default-path bypass: `verify_dataset_binding()` only cryptographically
verified files when `cfg.train_file`/`cfg.eval_file` were explicitly
set, so the common default-path case (`cfg.train_file=""`, resolved
later by `_train_impl()`'s own separate path formula) was accepted with
`dataset_content_digests={}` -- reproduced live before fixing. Also
found: multi-manifest dataset declarations were existence-only (never
verifying the actual combined bytes), a TOCTOU window between
verification and actual training consumption, and checkpoint
registration proved digest identity but never structural completeness.
Fixed:

- **Single source of truth for training inputs**:
  `orca/train/config.py::resolve_training_data_inputs()` -- both
  `verify_dataset_binding()` and `_train_impl()` now call this exact
  function; no independent path-formula reconstruction anywhere else.
- **Fail-closed on unverified canonical inputs**: canonical training
  with a declared dataset manifest now ALWAYS resolves and
  cryptographically verifies the real consumed files -- an empty
  `dataset_content_digests` is no longer a reachable state for
  canonical training.
- **`DatasetBundleManifest`** (`orca/registry/dataset_bundle.py`):
  when more than one source dataset manifest is declared, a bundle
  manifest binding the exact combined train/eval byte digests (plus
  full source lineage) is now required -- existence-only multi-manifest
  provenance is rejected.
- **TOCTOU closure**: `create_run_snapshot()`/`verify_run_snapshot()`
  copy verified source files into a run-scoped snapshot directory,
  re-hash them, and re-verify AGAIN immediately before
  `_train_impl()`'s `load_dataset()` call -- the trainer only ever
  reads the snapshot, never the original mutable source path.
- **Explicit split digests**: `TrainingRunManifest.dataset_split_digests`
  uses unambiguous `"train"`/`"validation"`/`"held_out"` keys (never a
  generic dataset-id key), with `dataset_snapshot_paths` kept as
  clearly-separate operational metadata, never treated as cryptographic
  identity.
- **Checkpoint structural validation**:
  `orca/registry/checkpoint.py::validate_checkpoint_artifact()` runs
  BEFORE `hash_artifact_directory()` in `complete_training_run()` --
  requires `config.json` (parseable), a tokenizer artifact, and either
  a single weight file or a shard index whose every referenced shard
  exists and is a safe bare filename (path traversal / absolute-path
  escape rejected). A structurally incomplete artifact is never
  registered, no matter how cleanly it hashes.
- **Hostile-self-review finding, fixed same closure**: `RESERVED_
  NATIVE_MODEL_NAMES` covered only legacy Ollama aliases (e.g.
  `"orca-nano"`), not each family's own canonical `model_id`
  (`"orneur-genesis"`) -- a generic (`family=None`) config could set
  `model_name="orneur-genesis"` directly and, via
  `complete_training_run()`'s family-from-model_id lookup, register an
  arbitrary experimental checkpoint under the real `genesis` family in
  `ModelRegistry`. Reproduced live, fixed by including each
  `spec.model_id` in the reserved-names set.

`tests/test_training_provenance.py`: 26 -> 50+ tests, covering every
adversarial case above plus the impersonation finding.

## 8.7. Phase 21B.2.1 closure (final provenance & checkpoint trust seams)

A further independent audit found that Phase 21B.2's own closure left
four seams open. Fixed:

- **Bundle not wired through the real entrypoint**: `start_training_run()`
  accepted `dataset_bundle_id`, but `orca.train.finetune.train()` -- the
  real public training path -- had no parameter to forward one, so a
  multi-manifest canonical run could never actually reach the
  `DatasetBundleManifest` path except via a direct (test-only) call to
  `start_training_run()`. `train()` now accepts and forwards
  `dataset_bundle_id`; no alternative or hidden path exists.
- **Bundle source lineage not enforced**: `verify_dataset_binding()`
  checked only that a bundle's source-manifest ID *set* matched the
  declared `dataset_manifest_ids` -- never that each source
  `DatasetManifest`'s CURRENT content checksums still matched the
  `SourceManifestLineage` checksums the bundle recorded at build time. A
  source manifest could be replaced or mutated under the same ID without
  invalidating the bundle's lineage claim. `_verify_bundle_source_lineage()`
  (`orca/registry/provenance.py`) now re-verifies every lineage entry's
  checksums against the live source manifest, and rejects duplicate or
  malformed lineage entries.
- **Checkpoint identity/integrity algorithm mismatch**:
  `hash_artifact_directory()` (registration-time identity) lived only in
  `orca.registry.provenance`, while `CheckpointRecord.verify_integrity()`
  (`orca.registry.checkpoint`) still called `sha256_of_file()` on what
  is, for every merged checkpoint this project produces, a DIRECTORY --
  registration and post-registration reverification disagreed about the
  very algorithm used to prove integrity. `hash_artifact_directory()` now
  lives in `orca.registry.checkpoint` (the dependency layer both modules
  already depend on) and is imported, never redefined, by
  `orca.registry.provenance` -- there is exactly one canonical
  directory-checkpoint digest algorithm. `verify_integrity()` now
  branches explicitly on `path.is_dir()` (never guesses from a filename),
  preserving `sha256_of_file()` for legacy single-file checkpoints.
- **Symlink escape**: `validate_checkpoint_artifact()`'s shard-index
  checks already resolved paths and rejected escapes, but non-index
  files (`config.json`, tokenizer artifacts, an unsharded weight file)
  were still accepted via `Path.is_file()`, which follows symlinks. Both
  `validate_checkpoint_artifact()` and `hash_artifact_directory()` now
  apply one fail-closed policy: ANY symlink anywhere in a canonical
  checkpoint artifact directory is rejected outright, so the validator
  and the hasher can never disagree about which bytes are trusted.

`tests/test_training_provenance.py`: 52 -> 71 tests.

## 9. Blocking gaps (honest, evidence-based)

1. **License**: Genesis's selected base is non-commercial-only
   (`qwen-research`). Blocks commercial release, not research training.
   Requires owner decision (see qualification doc).
2. **Dataset scale**: 56 total records across two manifests is a seed,
   not a training-ready corpus. Needs substantial, genuinely diverse
   expansion (not templated padding) before a real SFT run would be
   expected to produce a meaningfully capable checkpoint.
3. **Evaluation suite breadth**: only keyword-coverage business/coding/
   Hindi-English eval exists; no coding-execution, product-building,
   safety/authority, or fabricated-completion-resistance evaluation
   suite exists yet, canonical or otherwise.
4. **No CPU dry run of an actual tiny overfit** (spec section 30's Step
   C) has been performed -- deliberately not attempted this closure
   since it requires the real base model weights, which were
   deliberately not downloaded (multi-GB download forbidden this
   closure).

## 10. Phase-21C proposed resource envelope

See `PHASE21C_GENESIS_TRAINING_RUNBOOK.md`'s resource section for the
full breakdown. Summary: single consumer/prosumer or cloud T4/A10-class
GPU, ~10GB VRAM (QLoRA rank-32 3B), duration highly dependent on final
dataset size (not yet determined). **No resource was activated or
estimated with fabricated pricing.**
