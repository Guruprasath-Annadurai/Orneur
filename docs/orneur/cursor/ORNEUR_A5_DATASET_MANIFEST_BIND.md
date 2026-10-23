# Increment 2 — A5 dataset-manifest identity bind

Engineering evidence for this increment. This document does not accept any requirement and does not alter `docs/orneur/acceptance/acceptance_ledger.json`.

## Change

`GenesisTrainingRun.validate()` refuses a bare `dataset_digest`. Identity is derived only after `dataset_manifest.verify_against_records(dataset_records)` succeeds. Isolated workers must supply non-empty `dataset_records` or they fail closed before serving.

`BoundDatasetRecords` is a duck-typed `DatasetManifestLike` for workers and tests that already hold concrete records. Production callers should pass a real `GenesisDatasetManifest`.

## API compatibility

- `validate(..., dataset_digest=..., dataset_manifest=..., dataset_records=...)` still accepts an optional digest, but only as a consistency check against the verified manifest digest.
- Callers that previously passed only `dataset_digest` now fail closed with `ValueError`.
- Isolated-worker `WorkerStartupConfig.dataset_records` defaults to `()` (fail-closed). Tests that start a worker must bind records.

No HTTP API surface is changed in this increment. Frontend files under `orca/serve/web/` are not modified.

## Security impact

- Closes a well-formed-digest-without-content bind at training validation.
- Isolated workers cannot mint a run identity from a digest string alone.
- Does not authorize native pretraining. Founder ledger remains empty (`[]`).
- Does not replace grant signature, shard-file rehash, or live revocation checks.

## Platform

Linux tests in this increment are the qualification surface. Native macOS / Apple Silicon qualification of PR #86 remains independent and is not claimed here.

## Limitations

- `BoundDatasetRecords` is not a substitute for Workstream A provenance objects outside tests and isolated-worker startup.
- This increment does not train GENESIS, NOVUS, or AETERNUM.
- This increment is not merge-authorized onto protected baselines.
