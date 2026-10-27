# Acceptance gates

| Gate | State | Why |
|---|---|---|
| G1 Architecture inventory | PARTIAL | The reality baseline names the subsystems inspected. Duplicate Truth Fabric and `orca/rag_x` paths are explicit. Product integration is not inventoried end to end. |
| G2 RAG-38 | PARTIAL | Every RAG-01–RAG-38 and X1–X8 row has a class in `orca/rag_x/matrix.py`. Several rows are prototypes or backend-unavailable. |
| G3 Security | PARTIAL | In-memory tenant, workspace, principal, revocation, raw-SQL, and evidence-grant tests passed. That is not the whole production threat surface. |
| G4 Retrieval correctness | PARTIAL | The in-memory contracts in `tests/test_rag_x_foundation.py` passed. There is no production index. |
| G5 Claim verification | PARTIAL | Span containment and `KEY=value` conflicts are tested. This is not general factual verification. |
| G6 Reproducibility | PARTIAL | Synthetic tests are deterministic. Torch and GPU checks were not re-run. |
| G7 Data integrity | PARTIAL | Synthetic admission, rights, digest, and overlap checks passed. No real corpus was qualified. |
| G8 Evaluation integrity | PARTIAL | X2 items and the endpoint are frozen in `orca/rag_x/research.py`. The set has six items. |
| G9 Runtime integration | BLOCKED | PR #79 and PR #81 were not modified. No application request path was exercised. |
| G10 Independent audit | NOT STARTED | No independent reviewer has reported on this SHA. |
| G11 Formal acceptance | UNCHANGED | `pretraining=95 numerator=0`. |

Training remains NO-GO.
