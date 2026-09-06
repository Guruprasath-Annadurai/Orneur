# Cognitive Roles (Phase 7 spec §5-6)

Fifteen stable role concepts in `orca.society.contracts.CognitiveRole`:
`FAST_RESPONDER`, `INTENT_COMPILER`, `RETRIEVAL_PLANNER`, `QUERY_REWRITER`,
`CLAIM_EXTRACTOR`, `MEMORY_SELECTOR`, `CONSTRUCTOR`, `FALSIFIER`,
`VERIFIER`, `CODER`, `TOOL_REASONER`, `CAUSAL_REASONER`,
`COUNTERFACTUAL_REASONER`, `SUMMARIZER`, `ARBITRATION_SUPPORT`.

None of these names appear in any provider-specific logic (spec §5) --
`orca/society/router.py` never branches on a role name to pick a
provider; it only reads `RoleRequirement` fields.

## Which roles are actually wired to a live call this phase

| Role | Wired this phase? | Where |
|---|---|---|
| `CONSTRUCTOR` | Yes | `orca.deliberation.court.CognitiveCourt` |
| `FALSIFIER` | Yes | `orca.deliberation.court.CognitiveCourt` |
| all other 13 roles | Requirement declared only | `orca/society/role_requirements.py` |

Per spec §41 ("Court should request roles... through Society routing")
and §45 ("create a clean Society role boundary... where practical" without
redesigning Agent Runtime), only Constructor/Falsifier are migrated to a
live Society-routed call this phase. `VERIFIER`, `CLAIM_EXTRACTOR`,
`TOOL_REASONER`, etc. have real, tested `RoleRequirement` declarations and
are exercised in the deterministic evaluation harness
(`orca.society.eval_harness`) and router unit tests, but Truth Fabric's
claim extractor/verifier, `AgentLoop`'s tool-reasoning calls, and Memory's
selector/summarizer calls remain on their pre-existing tier-string call
sites -- an honest, disclosed scope boundary, not an oversight (see
`CURRENT_MODEL_ROUTING.md` and `PHASE_7_CLOSURE.md`'s
"TRUTH FABRIC INTEGRATION" / "MEMORY INTEGRATION" sections).

## Role requirements are declarative, never a model name

Every `RoleRequirement` (`orca/society/role_requirements.py`) declares
`min_lifecycle_rank`, `latency_sensitive`, `min_context_tokens`,
`requires_structured_output`, `requires_reasoning`,
`requires_verification`, `requires_tool_calling`, `requires_streaming`,
`cost_sensitive`, `risk_sensitive`, `evidence_sensitive` -- never a model
identifier. `orca.society.router.requirement_for(role)` is the only place
a role maps to these fields.
