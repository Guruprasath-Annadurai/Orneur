# Phase 12 — Dataset Lineage

## Lineage graph (spec §6, §24, §62)

`orca.learning.provenance.LineageGraph` — a plain adjacency-list
structure linking `FailureEvent -> CurriculumCandidate -> DatasetManifest
-> TrainingRun -> Checkpoint -> EvalRun -> PromotionDecision` (spec §62's
"Learning Flight Recorder"). `has_orphan(node_id)` returns `True` for any
non-`FailureEvent` node with zero `parent_refs` — spec §6's "no orphan
training sample without provenance," checked directly in
`test_lineage_graph_detects_orphan_non_root_node`.

`orca.learning.pipeline.run_pipeline()` populates this graph as it runs:
every input `FailureEvent` is added as a root node, and every produced
`CurriculumCandidate` is added with `parent_refs=[failure_id]`.

## DatasetManifest extensions (spec §21, §24)

`orca/registry/dataset_manifest.py::DatasetManifest` (Phase 1) gained,
additively:

- `candidate_ids: list[str]`, `failure_ids: list[str]` — sample → candidate
  → failure lineage (spec §24), stored directly on the frozen manifest.
- `approval_state`, `approved_by`, `approved_at`, `frozen`, `frozen_at` —
  see `DATASET_VERSIONING.md`.
- `split_group_keys: dict` — group-aware split safety (spec §22), see
  below.
- `holdout_checksum: str | None` — the protected holdout's checksum only;
  its content never lives in a training-visible manifest field (spec §23).
- `target_model_family`, `target_role`.

Every one of these fields has a default, so every dataset manifest ever
saved before Phase 12 still loads correctly
(`test_registry_lifecycle.py`/`test_registry_id_sanitization.py` — the
only two pre-existing call sites — both still pass unmodified).

## Split safety (spec §22)

`DatasetManifest.check_split_safety()` takes `split_group_keys` — a dict
of split name → list of **group keys** (e.g. a shared root `failure_id`
or dedupe-fingerprint family), not raw sample IDs — and returns a list of
violation descriptions if any group key appears in more than one split.
Candidates derived from the same root failure family are assigned the
SAME group key by convention, so a caller building `split_group_keys`
from real candidate data naturally keeps a family together.

## Protected holdout (spec §23, §67)

The holdout's own checksum is recorded on the manifest
(`holdout_checksum`), but `orca.learning.security.
assert_training_manifest_excludes_holdout(training_dataset_ids,
holdout_dataset_id)` is the actual enforcement point: it raises
`HoldoutExposureBlocked` if the holdout's `dataset_id` ever appears among
the IDs a training run's manifest references. This must be called by
every training-run preparation step before `TrainingRunManifest.save()`.
