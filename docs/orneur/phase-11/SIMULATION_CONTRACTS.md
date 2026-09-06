# Phase 11 — Simulation Contracts

All in `orca/simulation/contracts.py`.

| Contract | Purpose |
|---|---|
| `Provenance` | `SIMULATION` \| `TOOL_OBSERVATION` \| `CONNECTOR_OBSERVATION` \| `TRUTH_EVIDENCE` \| `USER_INPUT` — structural distinction between predicted and real. |
| `SimulationMode` | `STATIC_ANALYSIS` \| `DRY_RUN` \| `SANDBOX_EXECUTION` \| `STATE_PROJECTION` \| `COUNTERFACTUAL` \| `SHADOW_EXECUTION` \| `PROVIDER_PREVIEW`. |
| `SimulationSupportLevel` | `SUPPORTED` \| `PARTIAL` \| `UNAVAILABLE`. |
| `ToolSimulationCapability` | Per-tool declared support (`supports_static_validation`/`supports_dry_run`/`supports_sandbox`/`supports_preview`/`supports_read_back_prediction`/`simulation_fidelity`). |
| `SimulationRequirement` | `NOT_REQUIRED` \| `OPTIONAL` \| `REQUIRED` \| `UNAVAILABLE_BUT_REVIEW_REQUIRED`. |
| `EffectType` | `CREATE`/`UPDATE`/`DELETE`/`SEND`/`MOVE`/`PERMISSION_CHANGE`/`STATE_TRANSITION`/`RESOURCE_CONSUMPTION`/`UNKNOWN_EFFECT`. |
| `Reversibility` | `REVERSIBLE`/`COMPENSATABLE`/`IRREVERSIBLE`/`UNKNOWN` — never assumed reversible merely because an inverse command exists. |
| `BlastRadius` | `SINGLE_OBJECT` through `PRODUCTION_SYSTEM`/`UNKNOWN`. |
| `EffectConfidence` | `HIGH` (deterministic mechanism) / `MEDIUM` / `LOW` (model-only) / `UNVERIFIABLE`. |
| `Assumption` | `assumption_id`, `description`, `source`, `verification_state`, `impact_if_false`. |
| `PredictedEffect` | `resource`, `effect_type`, `before_reference`/`predicted_after_reference` (hash/version, never full payload), `reversibility`, `blast_radius`, `confidence`, `assumption_ids`, `provenance`. |
| `CompensationPlan` | `original_effect_id`, `compensating_action_description`, `preconditions`, `limitations`, `required_capability`, `risk`, `confidence` — never a guaranteed rollback. |
| `SimulationConstraint` | `max_actions`, `max_branches`, `deadline_s`, `required_fidelity`. |
| `SimulationEnvironment` | Opaque sandbox/fake-provider handles — never a raw credential. |
| `SimulationAction` | Mirrors `AgentAction`'s shape (`tool_id`/`arguments`/`resource_scope`/`operation_scope`) deliberately. |
| `SimulationRequest` | The full typed request — action, tool/connector id, risk/side-effect class, tenant/principal, `lease_id`, explicit `capability`/`capability_domain` (see below), budget/deadline/fidelity. |
| `StateFingerprint` | `resource`, `kind` (`VERSION`/`ETAG`/`CONTENT_HASH`/`REVISION`/`MTIME`/`UNAVAILABLE`), `value`, `captured_at`. |
| `SimulationVerdict` | `PASS`/`PASS_WITH_WARNINGS`/`REVISE`/`BLOCK`/`INCONCLUSIVE`. |
| `SimulationFailureReason` | `UNSUPPORTED`/`FAILED`/`TIMEOUT`/`CANCELLED`/`BUDGET_EXHAUSTED`/`STALE_INPUT`/`POLICY_BLOCKED`. |
| `SimulationResult` | The signed, tamper-evident output — `predicted_effects`, `assumptions`, `compensation_plans`, `warnings`, `block_reasons`, `failure_reason`, `input_fingerprints`, `result_hash`. |
| `SimulationTrace` | Full lineage: mode, provider, effect/assumption IDs, branch count, budget summary, model/Truth/Memory/Court references, gate decision, staleness flag, `reality_diff_id`. |
| `ExecutionGateDecision` | `ALLOW_TO_PROCEED_TO_AUTHORIZATION`/`REQUIRE_REVIEW`/`REVISE_PLAN`/`BLOCK`. |
| `RealityDiffStatus` | `MATCHED`/`PARTIAL_MATCH`/`UNEXPECTED_EFFECT`/`MISSING_EXPECTED_EFFECT`/`OUTCOME_UNKNOWN`. |
| `RealityDiff` | Links `simulation_id`/`action_id`, predicted effect IDs, actual summary, differences, severity, `follow_up_required`. |
| `FailureCandidateRecord` | `simulation_failure_candidate` / `eval_candidate` only — never a direct Memory/training write. |

## A real bug this phase's own contract design caught

`SimulationRequest` originally had only `side_effect_class` (the
action's effect class, e.g. `"IRREVERSIBLE_WRITE"`) — the Chamber's
lease-compatibility check mistakenly compared THAT string against a
lease's `capability` field (e.g. `"FILE_WRITE"`), a category error
found while building the eval harness. Fixed by adding an explicit,
separate `capability: str` field, and — found again while building the
required end-to-end tests — an explicit `capability_domain: str = "FILE"`
field, since `CapabilityDomain` cannot be safely inferred from a tool
id's spelling (an `AGENT`-domain Capability lease and a `FILE`-domain
resource lease are both plausible for a `write_file`-shaped action, and
only the caller knows which applies).
