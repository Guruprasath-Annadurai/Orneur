# Current Model Routing Architecture (Phase 7 §3 audit)

Required first action before any Model Society code is written. Classifies
every existing model-selection mechanism as CANONICAL / LEGACY / RULE_BASED /
DUPLICATED / UNMEASURED_ASSUMPTION / UNSAFE / DEAD / MISSING.

## `orca/cognitive/policy.py::select_model_policy()` / `characteristic_to_tier()`

**CANONICAL, RULE_BASED.** Deterministic mapping from
`(IntentPlan, ComplexityAssessment)` to a `ModelPolicyCharacteristic`
(FAST/BALANCED/DEEP/CODE/REASONING/VERIFICATION), then to a legacy tier
string (nano/core/ultra). Input signals: intent category, complexity level,
`requires_agents`/`requires_reasoning`/`requires_tools`. No cost/latency/
capability-evidence awareness — a characteristic always maps to the same
tier regardless of measured model quality, deployment health, or cost.
**Not superseded this phase** — Model Society's `RoleRequirement` machinery
is a parallel, richer path used specifically for Deliberation Fabric roles
(Court); `characteristic_to_tier` remains the path for ordinary Kernel
generation requests, which stay out of scope for Phase 7 per §45 ("do not
redesign Agent Runtime").

## `orca/serve/registry.py::resolve_tier_backend()` (not modified this phase, referenced)

**CANONICAL.** Resolves a tier string to an actually-installed Ollama model
or a statically-configured frontier backend, with the existing
ultra→core→nano step-down chain when a tier's model isn't installed.
Config-level sovereignty lock enforcement lives here. Untouched this phase.

## `orca/serve/routing.py::decide_route()` / `classify_query()`

**CANONICAL, RULE_BASED.** Per-query cost-aware escalation from a
self-hosted tier to a frontier backend, gated by four independent checks
(operator opt-in, sovereignty lock, backend credentials configured, and a
surface-pattern-matched query-complexity heuristic), plus a daily cap.
Input signals: raw query text (regex heuristics for time-sensitivity/
complexity), not the Cognitive Kernel's typed `ComplexityAssessment`.
**A different concern from cognitive routing** — this operates on the
legacy `/api/chat` fast path before the Cognitive Kernel is invoked at all,
and is not touched by Model Society this phase.

## `orca/gateway/gateway.py::ModelGateway.resolve_deployment()` / `.generate()` / `.stream()`

**CANONICAL.** The actual hard-filter + health enforcement layer:
`_worker_permits_routing()`, `_artifact_is_available()` (checkpoint
`ArtifactAvailability.LOCAL`), lifecycle/experimental-policy checks,
`CircuitBreaker.allow_request()`/`record_success()`/`record_failure()`.
This is the ONE place that currently enforces "deployment must be healthy
and routable" — and it does so correctly today. **Model Society does not
replace this layer or duplicate its authority** — Society decides WHICH
role → model_id/tier to request; ModelGateway remains the final,
authoritative hard-filter enforcement point underneath it (defense in
depth, not duplicated policy). Society's own hard filters in Phase 7
additionally consult the SAME registry/deployment/circuit-breaker state
so that a `RoutingDecision`'s rejection reasons are meaningful and
auditable at the Society layer too, not just discovered as a runtime
failure one layer down.

## `orca/registry/model_registry.py` / `orca/registry/model_spec.py` / `orca/registry/checkpoint.py`

**CANONICAL.** Real lifecycle state machine (EXPERIMENTAL → CANDIDATE →
PRODUCTION → RETIRED/REJECTED), real artifact-availability tracking
independent of lifecycle, real evaluation-gated promotion
(`ModelRegistry.promote()` refuses without a `PROMOTABLE`
`EvaluationReport`). **Model Society reuses this directly as its capability-
profile lifecycle source** — it does not introduce a second lifecycle
concept.

## `orca/cognitive/entitlement.py`

**CANONICAL.** Wraps the existing billing abstraction
(`orca.auth.store.model_access_allowed`) into `CapabilityClass`
(BASIC/STANDARD/ADVANCED). **Reused directly** as Model Society's
entitlement hard filter — not re-derived.

## `orca/deliberation/twin.py::EpistemicTwin.__init__(tier: str = "nano")`

**HARDCODED / UNSAFE for Phase-7 purposes.** Court's Constructor and
Falsifier both resolve to the literal string `"nano"` — no role-based
reasoning, no capability evidence, no lifecycle/entitlement/health check at
the Society layer (the call does still pass through
`orca.serve.registry.resolve_tier_backend` further down, so it is not
*unsafe* in the sense of bypassing the Gateway's own hard filters, but it
is unsafe in the sense the spec means: model identity is picked by a
literal string, not evidence-backed role routing). **This is the primary
migration target for §41-42.**

## `orca/truth/llm.py::gateway_json_call()`

**CANONICAL helper, RULE_BASED caller-supplied tier.** A single
Gateway-routed JSON-call helper reused across Truth Fabric's claim
extractor/verifier/query-rewrite calls and now Deliberation Fabric's Twin.
Callers pass a literal tier string (`"nano"`/`"core"`) directly — no Society
role concept involved. **Not migrated wholesale this phase** (spec §43:
"do not force every deterministic Truth operation through Model Society") —
kept as still-CANONICAL infrastructure; only Court's Constructor/Falsifier
calls migrate to Society routing in Phase 7 (§41).

## `orca/brain/agent.py::AgentLoop` model calls

**RULE_BASED, out of scope for redesign (spec §45/§71).** `AgentLoop`
resolves models via the pre-existing tier system directly, not Model
Society. Phase 7 does not touch `AgentLoop`'s internals; a
`TOOL_REASONER` role concept is *defined* in Model Society's role
vocabulary (§5) but is not wired into `AgentLoop` this phase — documented
honestly as a foundation-only role definition here, matching the same
"contract exists, not yet consumed everywhere" pattern Phase 6 used for
`WorldState`.

## `orca/variants/ultra.py::OrcaUltra` grade/self-heal model call

**RULE_BASED / DUPLICATED-reasoning-pattern (already flagged in Phase 6's
`CURRENT_REASONING_ARCHITECTURE.md`).** Not modified this phase — Ultra's
model selection is unchanged; Phase 6 already established Cognitive Court
supersedes its reasoning role, and Phase 7 does not expand that migration.

## `orca/gateway/circuit_breaker.py` / `orca/gateway/deployment.py`

**CANONICAL.** Real `CLOSED/OPEN/HALF_OPEN` breaker state and
`DeploymentHealth` (`STARTING/READY/DEGRADED/DRAINING/OFFLINE` — see
`deployment.py`). **Currently only consulted by `ModelGateway`, not by any
cognitive-layer routing decision** (`policy.py`, `twin.py`) — this is a
genuine **UNMEASURED_ASSUMPTION** in the pre-Phase-7 system: cognitive code
picks a tier/model_id assuming it will be servable, and only discovers
health/circuit problems when the Gateway call itself fails. Phase 7's
Society hard-filter layer closes this gap for Court-routed roles by
querying `list_deployments()`/`CircuitBreaker` state before selecting a
candidate, not just after.

## `orca/registry/evaluation_registry.py`

**CANONICAL.** Versioned `EvaluationReport` with an explicit `UNMEASURED`
sentinel already established (not zero, not passing). **Model Society's
capability-evidence requirement (§8-9) reuses this directly** as the
evidence-lineage source for capability claims — no second evaluation-record
format is introduced.

## Summary of what Phase 7 actually changes

Nothing enumerated above as CANONICAL is modified or duplicated. The only
HARDCODED/UNSAFE item found — `EpistemicTwin`'s literal `tier="nano"` — is
the one migration target, per spec §41-42. Everything else Model Society
needs (lifecycle, entitlement, health, circuit state, evaluation evidence)
already exists as real, tested infrastructure and is reused, not
reimplemented.
