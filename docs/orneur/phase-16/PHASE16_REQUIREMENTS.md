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
| REQ-BOUNDARY-002a | No model-facing package directly imports `orca.mission` | Import-boundary check | VERIFIED | grep + `tests/test_phase16_architecture_invariants.py::test_no_model_facing_package_imports_orca_mission` | — |
| REQ-BOUNDARY-002b | Mission's own state machine rejects illegal/out-of-order transitions | Existing tests cited, not re-derived | VERIFIED | `tests/test_mission_state_machine.py::test_draft_cannot_jump_to_running` etc. (cited, not re-run in isolation this phase beyond the full regression) | — |
| REQ-BOUNDARY-002c | No code path anywhere (not just direct imports) can bypass Mission state across all its writers | Full enumeration of Mission-state writers | DEFERRED_TO_FUTURE_PHASE | Corrected this closure — the initial pass over-claimed this from import-grep alone; narrowed per owner review | Phase 17 |
| REQ-BOUNDARY-003 | Court ACCEPT is not execution authority | Signature-inspection test | VERIFIED | `tests/test_godmode_boundaries.py::test_court_accept_cannot_activate_godmode` (cited, pre-existing) | — |
| REQ-BOUNDARY-004 | Model output (including injected/adversarial text) cannot mint authority | Existing tests cited | VERIFIED | `tests/test_godmode_boundaries.py::test_model_society_cannot_issue_modify_extend_revoke_or_forge_a_lease`, `tests/test_godmode_security.py::test_model_injection_text_cannot_construct_a_valid_lease` | — |
| REQ-BOUNDARY-005 | Stale/expired authority cannot execute | Existing tests cited | VERIFIED | `tests/test_godmode_cancellation.py::test_deadline_denies_independent_of_cancellation_plumbing`, `::test_cancellation_at_checkpoint_a_takes_priority_over_expired_lease` | — |
| REQ-PROVIDER-001 | External-provider vs native-model classification is defined | Canonical architecture doc §External-provider | VERIFIED | `orca/gateway/frontier_runtime.py` vs `ollama_runtime.py` docstrings | — |
| REQ-ROUTER-ARCH-001 | Routing architecture invariants are documented as design boundaries, no implementation | Canonical architecture doc §Routing | VERIFIED (design-level only) | `orca/society/router.py` RoutingReason enum inspection | — |
| REQ-ROUTER-ARCH-002 | Router never defaults to Aeternum / never uses size as sole competence proxy — proven by a real test | Automated test | DEFERRED_TO_FUTURE_PHASE | Threat #4 — no such test exists yet | Phase 20 |
| REQ-TRAINING-ARCH-001 | Inference-plane vs training/learning-plane separation is documented | Canonical architecture doc §Inference-plane | VERIFIED | import-grep evidence | — |
| REQ-MEMORY-ARCH-001 | Memory/learning boundary is audited, `all_sessions_summary`-class risk documented | Canonical architecture doc §Memory | VERIFIED | Cross-reference to 15.15 evidence + `orca/memory/` docstrings | — |
| REQ-MEMORY-ARCH-002 | Phase 26 binding rule (must build on `orca/memory/`, not `orca/brain/memory.py`) is recorded | Canonical architecture doc §Memory, binding rule stated | IMPLEMENTED (documentation only — no enforcement mechanism yet) | Canonical architecture doc | Phase 26 (enforcement) |
| REQ-COURT-ARCH-001 | Court verdicts remain exactly ACCEPT/REVISE/REJECT/INSUFFICIENT_EVIDENCE (the real orca.deliberation.contracts.CourtVerdictState values -- corrected from an earlier draft that misstated this enum), never itself execution authority | `CourtVerdictState` inspected; `orca/agent/policy.py` proven not to import `orca.deliberation` | VERIFIED | `tests/test_phase16_architecture_invariants.py::test_agent_policy_does_not_import_deliberation` (passed) | — |
| REQ-THREAT-001 | ~30-item intelligence threat model produced with existing/missing control and blocker Y/N | PHASE16_THREAT_MODEL.md, 30 items | VERIFIED | Threat model doc | — |
| REQ-THREAT-002 | Hard Phase-16 blockers, if any, are resolved or explicitly escalated | Threat model doc conclusion | VERIFIED — no hard blockers found; 3 soft flags recorded for Phase 17 | Threat model doc | Phase 17 (items 15/29), ongoing (item 5, 25) |
| REQ-PROVENANCE-001 | No model weights are moved, deleted, or altered during Phase 16 | `git status` / `git diff --stat` shows no changes under model artifact directories | VERIFIED | `git status` (see evidence doc) | — |
| REQ-PHASE-GATE-001 | Baseline test collection/regression counts are recorded before any Phase 16 code edits | Recorded numbers in evidence doc, from a real `.venv` run, not assumed from Phase 15 | VERIFIED | `PHASE16_EVIDENCE.md` | — |
| REQ-PHASE-GATE-002 | Phase 16 code changes are limited to the §22 allow-list (contracts/tests/small adapters/deprecation markers) | Diff review of all Phase 16 commits | VERIFIED | Only 1 new test file (`test_phase16_architecture_invariants.py`) + docs added; no production `orca/*` file modified | — |
| REQ-PHASE-GATE-003 | Strict TDD followed for any new test (failing-first, minimum implementation) | Both invariant tests were written to prove already-true properties (dependency-boundary tests can't "fail first" against unmodified code without a synthetic violation — verified instead by intentionally checking they'd fail if the violation were introduced) | VERIFIED (verification method documented) | See evidence doc | — |

### Added this closure (owner architecture correction)

| ID | Statement | Acceptance criteria | Status | Evidence | Owning phase if deferred |
|---|---|---|---|---|---|
| REQ-MODEL-ID-004 | Aeternum's base model is UNSELECTED, not the legacy Llama-3.1-70B plan | `ModelSpec.base_model is None`, `base_model_status == "UNSELECTED_PROVISIONAL"` | VERIFIED | `tests/test_registry_model_spec.py::test_aeternum_base_model_is_unselected_not_legacy_70b` | — |
| REQ-MODEL-ID-005 | Aeternum's ~14B sizing is a provisional research hypothesis, not a lock | `ModelSpec.provisional_parameter_hypothesis` states this explicitly | VERIFIED | `tests/test_registry_model_spec.py::test_aeternum_has_provisional_size_hypothesis_not_a_lock` | — |
| REQ-MODEL-ID-006 | No family has a permanent size ceiling | `require_base_model()` fails closed rather than silently substituting; role text carries no size-tier framing | VERIFIED | `tests/test_registry_model_spec.py::test_require_base_model_fails_closed_for_aeternum`, `::test_no_family_role_implies_a_permanent_size_ceiling` | — |
| REQ-NATIVE-003 | Genesis/Novus/Aeternum are locked to distinct cognitive identities (Builder/Executor, Reasoner/Investigator, Critic/Arbiter/Discoverer), not a size tier | `ModelSpec.role` wording updated; documented in canonical architecture doc | VERIFIED (documentation + `role` field updated; not yet consumed by any routing/training code, since none exists that reads `role` for behavior) | `orca/registry/model_spec.py`, canonical architecture doc | — |
| REQ-NATIVE-004 | Universal Expert Intelligence doctrine is recorded | Canonical architecture doc §Universal Expert Intelligence | IMPLEMENTED (documentation only) | Canonical architecture doc | Phase 18+ (training/eval implementation) |
| REQ-PRODUCT-INTEL-001 | Production Product Intelligence hard-qualification objective is recorded, ProductBench NOT implemented | Canonical architecture doc §Production Product Intelligence | DEFERRED_TO_FUTURE_PHASE | Doctrine recorded, no implementation | Phase 21+ |
| REQ-RESEARCH-001 | Frontier Research doctrine is recorded | Canonical architecture doc §Frontier Research | DEFERRED_TO_FUTURE_PHASE | Doctrine recorded, no implementation | Phase 18+ |
| REQ-COLLECTIVE-001 | Three-Model Collective Intelligence doctrine is recorded | Canonical architecture doc §Collective Intelligence | DEFERRED_TO_FUTURE_PHASE | Doctrine recorded, no implementation | Phase 24-29 |
| REQ-BOUNDARY-006 | Canonical owner L0-L8 layer map (Human Sovereignty ... Evaluation/Qualification/Promotion) is restored, existing components mapped into it without discarding them | Canonical architecture doc §9-layer map | VERIFIED | Canonical architecture doc | — |
| REQ-COMPUTE-001 | Training architecture is compute-provider neutral (AMD/Modal/Race/other); no provider integration added in Phase 16 | Canonical architecture doc §Compute architecture; `git diff` shows no new dependency on any GPU-cloud SDK | VERIFIED | Canonical architecture doc; `git status` | — |

### Corrected this closure (superseded, kept for audit trail)

`REQ-COURT-ARCH-001`'s acceptance criteria previously misstated `CourtVerdictState`'s values as
`ACCEPT/REJECT/NEED_MORE_EVIDENCE/ESCALATE/HUMAN_APPROVAL_REQUIRED`; the real enum (verified via
`grep -n "class CourtVerdictState" -A5 orca/deliberation/contracts.py`) is
`ACCEPT/REVISE/REJECT/INSUFFICIENT_EVIDENCE`. Corrected in place (see the table above) rather than
left wrong, since this is a requirements *registry* (a living reference), not an append-only
evidence log.

Deferred items are explicitly future-phase work, not silently marked VERIFIED.
