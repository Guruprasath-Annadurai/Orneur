# Quality and latency

No production corpus and no hosted model were available. The figures below are one Linux process and the synthetic fixtures in `tests/test_rag_x_foundation.py`.

Functional comparisons that the tests check:

- Naive term count and BM25 disagree on `["alpha alpha alpha", "alpha beta"]` for the query `alpha beta`.
- Hybrid fusion records both `method:hybrid-rrf` and an embedding id, and ranks the overlapping fixture first.
- A contextual prefix changes the winner for two chunks that share the same body.
- A supplied reranker can put the lower lexical item first.
- Code reference lookup returns a chunk whose text does not contain the query, while sparse mode returns nothing.

X2, pre-registered as `confident_despite_conflict` with negative rule `contradiction-first count >= baseline count OR correct-answer loss > 0`, on six frozen items: baseline 2, contradiction-first 0, correct-answer loss 0. The hypothesis is supported for that fixture only. It is not a general quality claim.

Latency, measured in this session on the in-memory kernel: 100 sparse queries over 20 short documents. p50 0.199 ms, p95 0.262 ms, max 0.364 ms. This is not a vector-database measurement and it is not a user-facing service latency.

Recall, nDCG, and cost against an external model were not measured. T1 and T2 were not run.
