# Foundation-X reality baseline

Inspection date: 23 October 2026, Asia/Calcutta. Local `main` was `20a8546` and was not fetched again in this session.

| PR | Head observed | Base | Role |
|---|---|---|---|
| #78 | `97582a94efcb93dda6c4e8a8c89e457f446a5af2` | `claude/genesis-native-learning-engine-phase1-2026-10-17` | GENESIS checkpoint remediation. Not modified. |
| #79 | `c4e3d6e0bf3dd1cb43d933e2f02d010250a67989` | `main` | C02 mission backend. Not modified. |
| #80 | `fc1eb1dd098377e8506485dbcd82d6ed148b52b3` after the progress-database commit; inspection started at `b5230a0960d4686b1e5982f20a79208dec365088` | `claude/genesis-audit077-p0-remediation-2026-10-21` | Cursor pre-training foundation. |
| #81 | `2be788df1fb0ded33c3bc5dc6379a0f6af37eb04` | `main` | Conversation shell. Not modified. |

Acceptance command in this session: `python3 scripts/acceptance/validate_register_graph.py --check` printed `pretraining=95 numerator=0 application=3 execution=2 post=1`.

## Classification

| Subsystem | Class | Evidence | Limitation |
|---|---|---|---|
| `orca/genesis/data/pipeline.py` progress database | QUALIFIED_ON_LINUX_CI at `fc1eb1d` | https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39840961482 (9/9 success) | Darwin `F_GETPATH` was not executed. That blocker remains. |
| `orca/pretrain_foundation/agents.py` task identity | IMPLEMENTED_UNQUALIFIED in this session | CI on `b5230a0` is https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39802379378 | That run does not include `fc1eb1d`. |
| `orca/truth/` | QUALIFIED_LOCALLY for the authorized-index hook and the non-smoke Truth suites listed below | `tests/test_truth_authorized_index.py` plus corrective, planner, citation, claims, fetch, and retrieval-mode tests | Live Ollama smoke stays deselected. Neural retrieval is not claimed. |
| `orca/connectors/federated_retrieval.py` | IMPLEMENTED_UNQUALIFIED | `federated_search` keeps `failed_connectors` and `skipped_unhealthy` | Not re-run here. `orca/rag_x` does not replace it. |
| `orca/memory/` | IMPLEMENTED_UNQUALIFIED | Retrieval, deletion, and firewall modules exist | Not re-run here. The new kernel's memory mode is a separate in-memory contract. |
| `orca/docs/` | QUALIFIED_LOCALLY for the authorized index and shared BM25 | `AuthorizedIndex` uses `chunk_text`, `bm25_scores`, and `reciprocal_rank_fusion` | `DocStore` Chroma/Ollama retrieval was not re-qualified as a neural backend. |
| `orca/cognitive/` | IMPLEMENTED_UNQUALIFIED | Kernel, budget, policy, and evidence modules exist | Not wired to `orca/rag_x` in this change. |
| `orca/evalinfra/` | IMPLEMENTED_UNQUALIFIED | Pre-registration, leakage, and paired-stats modules exist | The new X2 fixture is separate and synthetic. |
| `orca/genesis` training math | IMPLEMENTED_UNQUALIFIED for this session | Prior torch tests live in the training-math CI job | Not re-executed while writing this baseline. |
| `orca/rag_x` and `orca/foundation_x` | RESEARCH KERNEL plus fail-closed lifecycle | `tests/test_rag_x_foundation.py`. Previous head `81e4e31` CI: https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39843423059 | That run does not cover the integration commit. The kernel is not the canonical index. |
| Native GENESIS, NOVUS, AETERNUM weights | MISSING | Lifecycle refuses those model ids | No training authorization. |
| Audio and video retrieval | MISSING | `mode=audio` and `mode=video` return `backend_unavailable` | No encoder. |
| Product path through PR #79 and PR #81 | BLOCKED | Those branches were not edited | End-to-end application integration is not shown. |
| Independent audit | BLOCKED | No Antigravity report exists for this SHA | Author tests are not independent qualification. |

An older document that describes a subsystem is not counted as verified unless the source and a test in this session agree.
