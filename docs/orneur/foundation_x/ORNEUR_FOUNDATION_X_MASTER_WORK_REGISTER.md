# Foundation-X master work register

Base for this branch: `fc1eb1dd098377e8506485dbcd82d6ed148b52b3` on `cursor/orneur-pretraining-foundation-p0-4e55`.

| ID | Priority | State | Test | Blocker | Next |
|---|---|---|---|---|---|
| P1 progress-database portability | P1 | QUALIFIED_LOCALLY | `tests/test_cursor_progress_db_portability.py` plus pipeline suites, 69 passed | CI for `fc1eb1d` not yet recorded. Darwin `F_GETPATH` not executed. | Independent review of PR #80. |
| FX-lifecycle | P1 | QUALIFIED_LOCALLY | `test_foundation_lifecycle_data_scaling_and_feedback` | Does not authorize training. | Independent review. |
| FX-data | P1 | QUALIFIED_LOCALLY | Same test, synthetic rights and digests | No real corpus. | Keep fixtures until a corpus is authorized. |
| FX-scaling | P2 | QUALIFIED_LOCALLY | Formula assertion in the same test | GPU checks listed and not run. | Run only with authorized hardware. |
| FX-feedback | P1 | QUALIFIED_LOCALLY | Self-approval and protected-path refusals | Cannot accept work by itself. | Human review remains required. |
| RAG-01–38 and X1–X8 | P0 | QUALIFIED_LOCALLY for the class each row names | `tests/test_rag_x_foundation.py`, 16 passed | Prototypes and unavailable backends stay non-production. CI not yet run. | Do not relabel rows without a new test. |
| X2 experiment | P1 | QUALIFIED_LOCALLY | Frozen six-item result 2 vs 0, loss 0 | Synthetic only. | Keep the item list frozen. |
| Truth Fabric, memory, docs, cognitive, evalinfra | P1 | IMPLEMENTED_UNQUALIFIED | Not re-run in this session | Existing suites were not executed here. | Re-run before calling them verified. |
| G9 application integration | P0 | BLOCKED | None | PR #79 and PR #81 were not edited. | A separate integration change. |
| G10 independent audit | P0 | NOT_STARTED | None | No independent report. | Antigravity or another reviewer. |
| G11 acceptance | P0 | UNCHANGED | `validate_register_graph.py --check` | Numerator remains 0. | Authorized reviewers only. |
| Native training | P0 | BLOCKED | Lifecycle refusal | Founder authorization is absent. | Do not train. |

Machine-readable copy of the same rows:

```json
[
  {"id": "P1", "status": "QUALIFIED_LOCALLY", "ci": "pending-fc1eb1d"},
  {"id": "RAG-X", "status": "QUALIFIED_LOCALLY", "ci": "pending-this-branch"},
  {"id": "G9", "status": "BLOCKED"},
  {"id": "G10", "status": "NOT_STARTED"},
  {"id": "G11", "status": "UNCHANGED", "numerator": 0, "denominator": 95},
  {"id": "TRAINING", "status": "BLOCKED"}
]
```
