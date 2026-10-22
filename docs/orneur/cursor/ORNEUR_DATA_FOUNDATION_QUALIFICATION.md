# Data foundation qualification

No external dataset was downloaded. No protected corpus was generated.

## Pipeline admission

`iter_classified_records` / `process_corpus` in `orca/genesis/data/pipeline.py`:

- Invalid UTF-8 is a counted corrupt record. It does not raise.
- A symlink at the input path raises `CorpusBoundaryError`.
- `allowed_root`, when passed, requires the resolved path to stay inside that root.
- `require_license=True` rejects a record with an empty `license` or `usage_restrictions`. The default remains False so existing shard fixtures keep working. A license string is metadata, not a training grant.
- `max_record_bytes`, when passed, stops buffering a line once the cap is hit and counts one rejection.

Tests: `tests/test_cursor_pipeline_admission.py`. Existing `tests/test_genesis_data_pipeline.py` passed after the change.

## Keyed derived cache

`LoaderConfig.cache_integrity_key` is optional.

- Omitted: previous unkeyed truncated SHA-256 behavior, and the same cache id. Coordinated rewrite of store plus manifest remains the residual the loader docstring already stated.
- Set: at least 32 bytes, same floor as checkpoint HMAC keys. The cache id includes a SHA-256 fingerprint of the key, not the key. Block digests are HMAC-SHA256. The manifest HMAC covers the store hash and the digest-sidecar hash. A bad tag raises `BlockStoreTamperedError` instead of rebuilding. An unkeyed loader refuses a manifest marked `hmac-sha256`.

The module does not mint a key and does not read one from the tree.

Tests: `tests/test_cursor_keyed_cache.py`. Existing `tests/test_genesis_data_loader.py` passed (unkeyed path).

## Still true from the base

Exact and near-duplicate rejection, cross-split contamination checks, manifest license rejection at manifest build, and shard digest checks were already implemented and were not weakened.
