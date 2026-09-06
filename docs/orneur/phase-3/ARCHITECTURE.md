# Phase 3 Architecture — Cognitive Kernel

## What this phase builds, and what it doesn't

The Cognitive Kernel is the control plane above inference. It converts a `CognitiveRequest` into structured cognitive state (intent, complexity, risk, freshness, evidence requirement, budget) and a bounded `CognitivePlan`. It is the foundation later phases build on:

| Future system | Phase 3 relationship |
|---|---|
| Truth Fabric | `EvidenceRequirement`/`VERIFY` operation contracts exist; no verification is implemented. `AUDIT_GRADE` evidence honestly abstains today. |
| Memory Continuum | `CognitiveContext.memory_refs` exists as a reference list; the Kernel never writes/reads memory itself — the existing `MemoryEngine` still does that. |
| Deliberation Fabric | `VERIFY`/`SIMULATE` operations are declared `PLANNED`, not implemented. |
| Agent Runtime | `DELEGATE_AGENT` is declared `PLANNED`. `OrcaUltra` remains a separate, narrower, user-selected entry point — not a Kernel-invokable operation. |
| Godmode | Risk classification is explicitly NOT authorization (see §37 of the phase spec). No capability is granted or denied here. |
| Simulation Chamber | `SIMULATE` is declared `PLANNED`. Nothing runs. |

Phase 3 does **not** train models, redesign RAG/Memory/Agent systems, or touch Cognitive Kernel Phase-4-and-beyond capabilities (Evidence Graph, Deep Search, Epistemic Twin, Cognitive Court, Agent Mesh, FDE).

## Module layout

```
orca/cognitive/
  contracts.py     -- all typed dataclasses/enums (pure data, no behavior)
  errors.py        -- CognitiveErrorCode taxonomy, normalized separately from InferenceError
  budget.py         -- CognitiveBudget validation/consumption/hard-stop enforcement
  intent.py         -- IntentCompiler (deterministic, rules-first)
  freshness.py      -- FreshnessRequirement classification
  complexity.py     -- ComplexityAssessment (reuses orca/serve/routing.py's QueryComplexity)
  risk.py           -- RiskAssessment (cognitive consequence, NOT authorization)
  evidence.py       -- EvidenceRequirement classification
  policy.py         -- ModelPolicyCharacteristic -> tier (never -> a model name)
  decomposition.py  -- bounded, deterministic sub-objective splitting
  planner.py        -- builds CognitivePlan; operation support states; abstention
  state_machine.py  -- CognitiveState transition validation
  trace.py          -- CognitiveTraceBuilder (Flight Recorder)
  metrics.py        -- low-cardinality cognitive observability
  kernel.py         -- CognitiveKernel: plan()/execute() -- the one public interface
  wiring.py         -- process-wide CognitiveKernel singleton (mirrors gateway/wiring.py)
```

No module is a god class. `kernel.py` is ~250 lines of coordination glue; every actual decision (what intent, how complex, how risky, what model policy, what plan) lives in its own named module, each independently unit-testable and independently replaceable (e.g. by a future Genesis-powered intent compiler, without `kernel.py` changing).

## Data flow (Phase 3 scope)

```
CognitiveRequest
  -> intent.compile_intent()          -> IntentPlan
  -> complexity.assess_complexity()   -> ComplexityAssessment
  -> risk.assess_risk()               -> RiskAssessment
  -> freshness.assess_freshness()     -> FreshnessRequirement
  -> evidence.assess_evidence_requirement() -> EvidenceRequirement
  -> policy.select_model_policy()     -> ModelPolicy
  -> planner.build_plan()             -> CognitivePlan (operations + support states + completion conditions)
  -> planner.plan_abstention_reason() -> AbstentionReason | None
       if abstain -> CognitiveResult(status=ABSTAINED, ...)
       else if plan needs only {ANSWER_DIRECTLY, REASON, RECALL_MEMORY}:
         -> policy.characteristic_to_tier() -> orca/serve/registry.py::resolve_tier_backend() [UNCHANGED]
         -> orca/gateway/wiring.py::brain_for_tier_resolution() [UNCHANGED, Phase 2.1]
         -> ModelGateway.generate() [UNCHANGED, Phase 2]
         -> CognitiveResult(status=COMPLETED, output=...)
       else:
         -> CognitiveResult(status=COMPLETED, output=None, warnings=[...])
            (plan is real; execution of RETRIEVE/USE_TOOL/DELEGATE_AGENT/SEARCH
             remains the existing serving stack's job -- see CUTOVER.md)
```

The Kernel never calls Ollama, a vector DB, the web, a shell tool, or long-term memory directly — every one of those, when actually needed, is either the existing `orca/gateway/wiring.py` bridge (for model calls) or explicitly deferred to the existing `AgentLoop`/`DocStore`/`MemoryEngine` stack (for everything else).

## Reused, not duplicated

- `orca/serve/routing.py`'s `classify_query()` (complex-reasoning/time-sensitive regex heuristics) is reused inside `complexity.py` rather than reimplemented — see `CURRENT_COGNITIVE_ORCHESTRATION.md`'s explicit note on this decision.
- `orca/serve/registry.py`'s `resolve_tier_backend()` (tier -> concrete model, with its existing step-down chain and data-sovereignty lock) is the only thing that ever turns a `ModelPolicyCharacteristic` into an actual deployment. Phase 3 adds zero new model-resolution logic.
- `orca/gateway/wiring.py`'s `brain_for_tier_resolution()` (Phase 2.1) is the only thing that ever registers a deployment or talks to `ModelGateway`. Phase 3 adds zero new Gateway-integration code beyond calling this exact function.
