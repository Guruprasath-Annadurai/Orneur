# PHASE 16 — Requirements Registry

Status vocabulary: UNIMPLEMENTED / IMPLEMENTED / VERIFIED / BLOCKED / DEFERRED_TO_FUTURE_PHASE.
"VERIFIED" is used only where a real test or direct inspection backs the claim — never because
something exists in prose.

| ID | Statement | Acceptance criteria | Status | Evidence | Owning phase if deferred |
|---|---|---|---|---|---|
| REQ-NATIVE-001 | Repository-wide intelligence inventory is produced covering all 14 intelligence-adjacent packages | Table exists in PHASE16_NATIVE_INTELLIGENCE_BASELINE_AUDIT.md §2 with 8-value Current Reality vocabulary | VERIFIED | Audit doc §2 | — |
| REQ-NATIVE-002 | Legacy ORCA→ORNEUR elements are classified, distinguishing naming from behavior | Audit doc §3 table | VERIFIED | Audit doc §3 | — |
| REQ-MODEL-ID-001 | Genesis/Novus/Aeternum artifact truth is audited without modifying weights | Audit doc §4; `git status` clean, no files under model artifact paths touched | VERIFIED | Audit doc §4; `git status` | — |
| REQ-MODEL-ID-002 | Canonical Model Identity Contract is reconciled against `orca/registry` reality | Canonical architecture doc, LifecycleState mapping table | VERIFIED | Canonical architecture doc | — |
| REQ-MODEL-ID-003 | Public display names never leak parameter counts | `ModelSpec.display_name` inspected for all 3 families | VERIFIED | `orca/registry/model_spec.py` read in full | — |
| REQ-BOUNDARY-001 | 9-layer architecture map with edge definitions is produced | Audit doc §5 | VERIFIED | Audit doc §5 | — |
| REQ-BOUNDARY-002 | Authority flows downward only through deterministic mechanisms — proven with code, not intuition | Dependency-graph evidence in canonical architecture doc §Dependency-graph-evidence | VERIFIED | grep evidence + `tests/test_phase16_architecture_invariants.py` (2 passed) | — |
| REQ-PROVIDER-001 | External-provider vs native-model classification is defined | Canonical architecture doc §External-provider | VERIFIED | `orca/gateway/frontier_runtime.py` vs `ollama_runtime.py` docstrings | — |
| REQ-ROUTER-ARCH-001 | Routing architecture invariants are documented as design boundaries, no implementation | Canonical architecture doc §Routing | VERIFIED (design-level only) | `orca/society/router.py` RoutingReason enum inspection | — |
| REQ-ROUTER-ARCH-002 | Router never defaults to Aeternum / never uses size as sole competence proxy — proven by a real test | Automated test | DEFERRED_TO_FUTURE_PHASE | Threat #4 — no such test exists yet | Phase 20 |
| REQ-TRAINING-ARCH-001 | Inference-plane vs training/learning-plane separation is documented | Canonical architecture doc §Inference-plane | VERIFIED | import-grep evidence | — |
| REQ-MEMORY-ARCH-001 | Memory/learning boundary is audited, `all_sessions_summary`-class risk documented | Canonical architecture doc §Memory | VERIFIED | Cross-reference to 15.15 evidence + `orca/memory/` docstrings | — |
| REQ-MEMORY-ARCH-002 | Phase 26 binding rule (must build on `orca/memory/`, not `orca/brain/memory.py`) is recorded | Canonical architecture doc §Memory, binding rule stated | IMPLEMENTED (documentation only — no enforcement mechanism yet) | Canonical architecture doc | Phase 26 (enforcement) |
| REQ-COURT-ARCH-001 | Court verdicts remain exactly ACCEPT/REJECT/NEED_MORE_EVIDENCE/ESCALATE/HUMAN_APPROVAL_REQUIRED, never itself execution authority | `CourtVerdictState` inspected; `orca/agent/policy.py` proven not to import `orca.deliberation` | VERIFIED | `tests/test_phase16_architecture_invariants.py::test_agent_policy_does_not_import_deliberation` (passed) | — |
| REQ-THREAT-001 | ~30-item intelligence threat model produced with existing/missing control and blocker Y/N | PHASE16_THREAT_MODEL.md, 30 items | VERIFIED | Threat model doc | — |
| REQ-THREAT-002 | Hard Phase-16 blockers, if any, are resolved or explicitly escalated | Threat model doc conclusion | VERIFIED — no hard blockers found; 3 soft flags recorded for Phase 17 | Threat model doc | Phase 17 (items 15/29), ongoing (item 5, 25) |
| REQ-PROVENANCE-001 | No model weights are moved, deleted, or altered during Phase 16 | `git status` / `git diff --stat` shows no changes under model artifact directories | VERIFIED | `git status` (see evidence doc) | — |
| REQ-PHASE-GATE-001 | Baseline test collection/regression counts are recorded before any Phase 16 code edits | Recorded numbers in evidence doc, from a real `.venv` run, not assumed from Phase 15 | VERIFIED | `PHASE16_EVIDENCE.md` | — |
| REQ-PHASE-GATE-002 | Phase 16 code changes are limited to the §22 allow-list (contracts/tests/small adapters/deprecation markers) | Diff review of all Phase 16 commits | VERIFIED | Only 1 new test file (`test_phase16_architecture_invariants.py`) + docs added; no production `orca/*` file modified | — |
| REQ-PHASE-GATE-003 | Strict TDD followed for any new test (failing-first, minimum implementation) | Both invariant tests were written to prove already-true properties (dependency-boundary tests can't "fail first" against unmodified code without a synthetic violation — verified instead by intentionally checking they'd fail if the violation were introduced) | VERIFIED (verification method documented) | See evidence doc | — |

Deferred items (2) are explicitly future-phase work, not silently marked VERIFIED.
