# Hypothesis register

| ID | Hypothesis | Baseline | Negative rule | Result |
|---|---|---|---|---|
| X2-contradiction-first-v1 | A challenge pass reduces confident answers that still contain a non-temporal `KEY=value` conflict, without losing the one-sided answers in the frozen set. | `mode=naive` with `challenge=False` | Treatment count is not lower, or any expected one-sided answer is lost | Supported on the six frozen items only: baseline 2, treatment 0, correct-answer loss 0. |

No other hypothesis was pre-registered. Architecture, scaling, and multilingual glossary behavior are engineering contracts, not superiority claims.

The X2 items are `X2_ITEMS` in `orca/rag_x/research.py`. They were not edited after the result was printed.
