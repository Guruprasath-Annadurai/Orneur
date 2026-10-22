# Foundation-X master work register

Base for this branch: `fc1eb1dd098377e8506485dbcd82d6ed148b52b3` on `cursor/orneur-pretraining-foundation-p0-4e55`.

| ID | Priority | State | Test | Blocker | Next |
|---|---|---|---|---|---|
| P1 progress-database portability | P1 | QUALIFIED_ON_LINUX_CI | Run 39840961482 for `fc1eb1d`, 9/9 success | Darwin `F_GETPATH` not executed. | Keep that blocker visible. |
| FX-lifecycle | P1 | QUALIFIED_LOCALLY | Forged grant string now fail-closed | A real grant still does not authorize training. Success path is unreachable without the gate. | Independent review. |
| FX-data | P1 | QUALIFIED_LOCALLY | Same test, synthetic rights and digests | No real corpus. | Keep fixtures until a corpus is authorized. |
| FX-scaling | P2 | QUALIFIED_LOCALLY | Formula assertion in the same test | GPU checks listed and not run. | Run only with authorized hardware. |
| FX-feedback | P1 | QUALIFIED_LOCALLY | Self-approval and protected-path refusals | Cannot accept work by itself. | Human review remains required. |
| RAG-01–38 and X1–X8 | P0 | RESEARCH KERNEL | `tests/test_rag_x_foundation.py` | Classes are not production certification. Canonical sparse path is separate. | Do not relabel rows without a new test. |
| Canonical authorized index | P0 | QUALIFIED_LOCALLY | `tests/test_truth_authorized_index.py` | No production neural encoder. CI for this commit not yet recorded. | Wait for exact-head CI. |
| X2 and Q1 | P1 | QUALIFIED_LOCALLY | X2 is 2 vs 0 on six items. Q1 is 7/7 sparse hits and 0 contradiction-first conflicts on twelve items | Synthetic and lexical only. `model_backed` is false. | Keep both item lists frozen. |
| Truth Fabric non-smoke suites | P1 | QUALIFIED_LOCALLY | Corrective, planner, citation, fetch, retrieval-mode, connector, and tenant tests passed with the access hook | Live Ollama smoke was deselected. | Do not treat that as neural retrieval. |
| G9 application integration | P0 | BLOCKED | None | PR #79 and PR #81 were not edited. | A separate integration change. |
| G10 independent audit | P0 | NOT_STARTED | None | No independent report. | Antigravity or another reviewer. |
| G11 acceptance | P0 | UNCHANGED | `validate_register_graph.py --check` | Numerator remains 0. | Authorized reviewers only. |
| Native training | P0 | BLOCKED | Lifecycle refusal | Founder authorization is absent. | Do not train. |

Machine-readable copy of the same rows:

```json
[
  {"id": "P1", "status": "QUALIFIED_ON_LINUX_CI", "ci": "https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39840961482", "darwin_f_getpath": "not_executed"},
  {"id": "RAG-X", "status": "RESEARCH_KERNEL", "previous_head_ci": "https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39843423059"},
  {"id": "AUTHORIZED_INDEX", "status": "QUALIFIED_LOCALLY", "ci": "pending-integration-commit"},
  {"id": "G9", "status": "BLOCKED"},
  {"id": "G10", "status": "NOT_STARTED"},
  {"id": "G11", "status": "UNCHANGED", "numerator": 0, "denominator": 95},
  {"id": "TRAINING", "status": "BLOCKED"}
]
```
