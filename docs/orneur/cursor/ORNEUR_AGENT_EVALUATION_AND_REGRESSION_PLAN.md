# Evaluation and regression

The measurement in this pass is `compare_equation_teams` in `orca/pretrain_foundation/team_benchmark.py`.

Fixed tasks: evidence span `2+2=4` with claim `2+2=4`, and the same span with claim `2+2=5`. Team sizes 1, 3, 5, and 10. Five trials. Handlers are pure, so the variance of the verdicts is 0. `model_inference` is false.

| Case | 1 handler | 3, 5, and 10 handlers |
|---|---|---|
| Supported equation | OBSERVED | OBSERVED. The larger team does not change the verdict. |
| Unsupported equation | OBSERVED, which leaves the false equation standing | REFUTED. Ten matches three and records more handler calls. |

A later regression gate may fail a change that makes the unsupported case stay OBSERVED or that lets the producer set VERIFIED. No public benchmark questions were added to a training set. No score against another vendor was computed.

Existing GENESIS eval integrity remains `orca/genesis/eval/integrity.py` and `tests/test_cursor_eval_integrity.py` on this parent branch. This agent comparison does not freeze that private evaluation.
