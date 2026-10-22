# Evaluation integrity qualification

`orca/genesis/eval/integrity.py` runs synthetic items supplied by the caller.

Enforced:

- Registered order is the score order. A seeded shuffle helper returns every id.
- A predictor exception is `ERROR`. `None` is `MISSING`. Neither is a pass.
- Accuracy is `None` when nothing was scored, not zero failures.
- `revise_threshold` refuses a new threshold on the same version string.
- `public_log` writes `<hidden>` for items marked `hidden_expected`.
- `scan_exact_contamination` flags a prompt or expected string that appears, after strip and casefold, in a caller-supplied training list. It is an exact screen.
- `wilson_interval` is the Wilson score interval. `paired_comparison` reports counts and the observed paired difference. It does not state a significance claim.
- Item ids in the report must match the definition. Dropping a failed item does not have an API.

Tests: `tests/test_cursor_eval_integrity.py`.

## Not done

No private holdout was created. GENESIS Capability Eval V1 remains the exposed set described in the existing phase-21 records. V2 custody is unchanged. No provider was called. No accuracy number in this file is a model score.
