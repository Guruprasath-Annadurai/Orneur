# Model Society Architecture (Phase 7)

## Where Model Society sits

```
API -> CognitiveKernel -> memory recall -> Truth Fabric -> ReasoningCompiler
     -> Deliberation Fabric (if required) -> Cognitive Court
          -> Model Society routing (Constructor/Falsifier role requests)
               -> ModelGateway (hard health/circuit-breaker enforcement, unchanged)
     -> structured result
```

Model Society is a **new layer between Cognitive Court and ModelGateway**,
not a replacement for either. It decides WHICH checkpoint should serve a
named cognitive role (`orca/society/router.py`); `ModelGateway` remains the
final, authoritative enforcement point for deployment health, circuit
breaking, and lifecycle/experimental-policy gating (unchanged from before
this phase -- see `docs/orneur/phase-7/CURRENT_MODEL_ROUTING.md`).

## Package layout (`orca/society/`)

- `contracts.py` -- all typed dataclasses (spec §4): `CognitiveRole`,
  `ModelCapability(Profile)`, `RoleRequirement`, `RoutingRequest`,
  `RoutingCandidate`, `RoutingDecision`, `RoutingReason`, `RoutingOutcome`,
  `RoleAssignment`, `SocietyPlan`, `DisagreementSignal`,
  `EscalationDecision`, `RoutingTrace`.
- `lifecycle.py` -- lifecycle ranking, including the disclosed
  `LEGACY_PRODUCTION_SERVING` pseudo-state (see below).
- `profiles.py` -- real `ModelCapabilityProfile`s for Genesis-legacy and
  Novus, built from actual on-disk `EvaluationReport`/registry state; no
  profile exists for Aeternum or a canonical-future-Genesis-3B checkpoint,
  because neither has a trained checkpoint.
- `role_requirements.py` -- the 15 `CognitiveRole` declarations (spec §5)
  and their `RoleRequirement`s (spec §6).
- `router.py` -- `route()`: hard filters then evidence-weighted scoring
  (spec §11-16).
- `society_plan.py` -- `build_court_society_plan()`: Constructor/Falsifier
  role assignment for one Court invocation (spec §17-18).
- `disagreement.py` -- `compute_disagreement()` (spec §19-20).
- `escalation.py` -- `decide_escalation()` (spec §21-23).
- `budget_ledger.py` -- `SocietyBudgetLedger`: operationalizes Phase 6's
  Cognitive Budget Market policy into real per-purpose call caps
  (spec §24-27).
- `eval_harness.py` / `latency_bench.py` -- deterministic evaluation and
  performance measurement (spec §58-59, §63).

Deliberation Fabric additions living in `orca/deliberation/` (not
`orca/society/`, since they extend Phase 6 contracts directly):
`worldstate_ops.py`, `worldstate_build.py` (spec §28-30), `replanning.py`
(spec §31-33).

## A real, disclosed lifecycle nuance: `LEGACY_PRODUCTION_SERVING`

`ModelRegistry` records Genesis's legacy 7B checkpoint (`orca-nano-v7`) as
`RETIRED` -- correctly reflecting "not the canonical future 3B
architecture" (Phase 0's finding). But `orca-nano-v7` is, in fact, the
exact artifact that has served the `nano` tier in production for a long
time, through a SEPARATE, untouched authority
(`orca/serve/registry.py`'s tier resolution, which does not consult
`ModelRegistry` lifecycle at all). Hard-filtering Model Society routing
strictly on `ModelRegistry`'s formal `RETIRED` state would make Genesis
un-routable for every role, which both regresses real working behavior for
no safety benefit and contradicts the spec's own
`LEGACY_GENESIS_SELECTED_FOR_FAST_ROLE` routing-reason vocabulary (which
presumes legacy Genesis IS selectable).

`orca.society.lifecycle.LEGACY_PRODUCTION_SERVING` names this real,
in-between fact honestly: not a false claim of formal `PRODUCTION`
promotion, and not an incorrect claim of `RETIRED` non-routability.
`ModelCapabilityProfile`s use this pseudo-state for Genesis-legacy only --
Novus and any future canonical checkpoint use `ModelRegistry`'s real
lifecycle values unmodified.

## What Model Society does NOT touch this phase

Per spec §45/§71: `AgentLoop` (Agent Runtime) internals, Truth Fabric's
existing tier-based LLM calls (claim extractor/verifier/query-rewrite --
still literal tier strings, not migrated), `OrcaUltra`'s grade/self-heal
call. See `CURRENT_MODEL_ROUTING.md` for the full classification and
`TRUTH_FABRIC_INTEGRATION` notes in `PHASE_7_CLOSURE.md` for why.
