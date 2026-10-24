# Adversarial test report

Command: `python3 -m pytest tests/test_rag_x_foundation.py`.

16 passed locally on Linux after the tests in this file were added. CI for this branch had not completed when this note was written.

Covered failures and the observed behavior:

| Case | Result |
|---|---|
| Foreign tenant, workspace, and principal | Not returned. |
| Revoked document | Not returned on the next call. |
| Instruction text inside a document | Scope unchanged. Hidden principal still excluded. |
| Email in the query | Absent from the kernel log. |
| Raw SQL | `unauthorized`. |
| Foreign row inside a visible table | Dropped. |
| Failing connector and foreign connector document | `partial`, with both reasons. |
| Fabricated claim string | `supported` is false. |
| Summary-only raptor hit | Claim not supported. |
| Evidence that contains the grant token | Action not authorized. |
| `model_identity=genesis` | `model_not_trained`, no evidence. |

Not tested here: poisoned neural embeddings, SSRF, prompt injection against a real generator, or a multi-process cache.
