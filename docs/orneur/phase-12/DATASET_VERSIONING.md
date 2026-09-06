# Phase 12 — Dataset Versioning & Approval

## Approval states (spec §25)

`DatasetApprovalState` (string constants on `DatasetManifest`, not an
`Enum`, so the existing `json.load(**dict)` round-trip is untouched):
`DRAFT → REVIEWED → APPROVED → FROZEN`, plus `RETIRED`.

`DatasetManifest.approve(approved_by)`:
- Sets `approval_state=APPROVED`, `approved_by`, `approved_at`.
- Raises `ValueError` if `approved_by` starts with `"model:"` — models
  cannot approve datasets (spec §69), same invariant as candidate review.

`DatasetManifest.freeze()`:
- Requires `approval_state == APPROVED` first; raises `ValueError`
  otherwise — **no automatic "candidate count reached threshold → train"**
  (spec §25's explicit prohibition). Tested:
  `test_candidate_approval_required_before_freeze`.
- Sets `frozen=True`, `frozen_at`, `approval_state=FROZEN`.

## Immutability (spec §51)

`DatasetManifest.save()` reads the EXISTING on-disk copy at this
`dataset_id`+`version` path (if any) and checks **that persisted copy's
own `frozen` field** — not this Python object's in-memory flag, and not
merely "does a file exist here." This distinction is load-bearing: a
naive "block if `self.frozen` and the path exists" check (the first
version written this phase) incorrectly rejected the very FIRST save of a
newly-frozen manifest whenever an earlier, not-yet-frozen save had
already created a file at that same path — a real bug caught by
`orca/learning/eval_harness.py`'s own `scenario_frozen_dataset_immutability`
failing on first run, fixed before commit.

Any change after a version is frozen requires a NEW version (`v2`, `v3`,
...) — this module never mutates a frozen file in place, enforced by
raising `DatasetFrozenError` on any attempted overwrite of a frozen
on-disk manifest.

## Checksums (spec §26)

`train_checksum`/`eval_checksum` (SHA-256, `sha256_of_file`) already
existed in Phase 1's `DatasetManifest`; Phase 12 adds `holdout_checksum`
for the protected holdout (see `DATASET_LINEAGE.md`).
`verify_against_files()` re-hashes and compares — unchanged from Phase 1.
