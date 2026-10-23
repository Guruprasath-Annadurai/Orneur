# Quality and latency

No production corpus and no hosted model were available. The figures below are one Linux process and the synthetic fixtures in `tests/test_rag_x_foundation.py`.

Functional comparisons that the tests check:

- Naive term count and BM25 disagree on `["alpha alpha alpha", "alpha beta"]` for the query `alpha beta`.
- Hybrid fusion records both `method:hybrid-rrf` and an embedding id, and ranks the overlapping fixture first.
- A contextual prefix changes the winner for two chunks that share the same body.
- A supplied reranker can put the lower lexical item first.
- Code reference lookup returns a chunk whose text does not contain the query, while sparse mode returns nothing.

X2, pre-registered as `confident_despite_conflict` with negative rule `contradiction-first count >= baseline count OR correct-answer loss > 0`, on six frozen items: baseline 2, contradiction-first 0, correct-answer loss 0. The hypothesis is supported for that fixture only. It is not a general quality claim.

Q1 (`Q1-canonical-retrieval-v1`) is a fifteen-document, twelve-item set on the authorized index: seven one-sided, four conflicts, one missing-evidence. The negative rule is in `orca/truth/qualification.py`. One local run, with `model_backed` false and `dense_backend` `unavailable`: sparse one-sided hits 7, misses 0, basic confident conflicts 4, contradiction-first confident conflicts 0, citation `SUPPORTED` 0, citation `PARTIALLY_SUPPORTED` 7, abstentions 4, failures 0. Wall time for that run was about 9.7 ms and traced peak allocation was 92324 bytes. Those two resource figures are one observation. The test locks the counts, not the timing. This is not a service benchmark and not a neural evaluation.

Latency, measured earlier on the in-memory research kernel: 100 sparse queries over 20 short documents. p50 0.199 ms, p95 0.262 ms, max 0.364 ms. This is not a vector-database measurement and it is not a user-facing service latency.

Recall, nDCG, and cost against an external model were not measured. T1 and T2 were not run.
