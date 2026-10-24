# Dataset provenance pipeline

This note records a local synthetic gate. It does not record a protected corpus, a training grant, or acquired tokens.

## What ran

`qualify_synthetic_records` in `orca/genesis/data/provenance_steps.py` applies the twenty steps named in the foundation programme to in-memory records. It reuses `normalize_record_text`, `deterministic_split`, the pipeline Jaccard near-duplicate threshold, `find_exact_matches`, `find_normalized_substring_matches`, `find_near_duplicates_across_splits`, and `sanitize_for_candidate`.

Command:

```
python3 -m pytest -q tests/test_synthetic_provenance_steps.py
```

Result on this branch: 9 passed. `docs/orneur/acceptance/acceptance_ledger.json` remained `[]\n` (sha256 `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570`).

## Local results

- A `synthetic://` record labeled `synthetic-fixture` / `local-test-only` can enter a synthetic manifest.
- That manifest sets `training_grant` false and `protected_corpus` false.
- `training_admitted` is false for every report.
- `public-web` is rejected as `public_web_not_cleared`.
- `MIT` is rejected as `license_metadata_not_a_training_grant`. A license string is not clearance.
- Email-shaped text and the documentation-shaped token `AKIAIOSFODNN7EXAMPLE` are rejected through the existing sanitizer.
- Exact duplicates, removal flags, excluded source ids, non-synthetic URIs, digest mismatches, and eval overlap are rejected.
- Code-domain records are listed in `code_separated` and are not hashed into the prose manifest.
- An injected fault publishes no manifest and lists the records discarded by the rollback.
- A caller-supplied publication mapping is ignored. `publication_rights` stays `BLOCKED`.
- A caller-supplied custodian key raises `ProvenanceError`. `independent_custody` stays `BLOCKED`. No key is written.
- Language and domain counts are measured. `quality_distribution_target` is `UNSET`. `balance_qualified` is false.
- Token accounting uses `whitespace-and-utf8-bytes-v1`. That is not a model tokenizer.

## Token requirement that was not acquired

`literature_token_requirement(1_000_000_000)` returns 20,000,000,000. The formula is the Hoffmann et al. 2022 compute-optimal rule of thumb, twenty tokens per parameter. `tokens_acquired` is 0. `selected` is false. The 1B figure is an illustration against an unselected tier, not an ORNEUR data plan.

## Still blocked

Independent custody, publication-rights review, real license grants, and a selected quality distribution are not done. The existing `process_corpus` path remains the filesystem writer for an authorized local shard experiment. This gate does not call it and does not download data.
