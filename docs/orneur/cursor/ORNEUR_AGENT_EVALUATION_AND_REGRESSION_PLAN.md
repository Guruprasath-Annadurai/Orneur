# Evaluation and regression

The measurement in this pass is `compare_equation_teams` in `orca/pretrain_foundation/team_benchmark.py`.

Fixed tasks: evidence span `2+2=4` with claim `2+2=4`, and the same span with claim `2+2=5`. Team sizes 1, 2, 3, 5, and 10. Size 16 was not run because only 12 distinct handlers exist. Five trials. Handlers are pure, so the variance of the verdicts is 0. `model_inference` is false.

| Case | 1 handler | 3, 5, and 10 handlers |
|---|---|---|
| Supported equation | OBSERVED | OBSERVED. The larger team does not change the verdict. |
| Unsupported equation | OBSERVED, which leaves the false equation standing | REFUTED at size 2. Three, five, and ten match two and record more handler calls. |

A later regression gate may fail a change that makes the unsupported case stay OBSERVED or that lets the producer set VERIFIED. No public benchmark questions were added to a training set. No score against another vendor was computed.

Existing GENESIS eval integrity remains `orca/genesis/eval/integrity.py` and `tests/test_cursor_eval_integrity.py` on this parent branch. This agent comparison does not freeze that private evaluation.
