# Deliberation Fabric — Architecture (Phase 6)

## Why not "think step by step"

A free-text chain-of-thought is unauditable, unfalsifiable, and cannot
be checked by anything other than another free-text pass. Deliberation
Fabric's central principle: reasoning happens over **structured
artifacts** — `Hypothesis`, `Argument`, `CounterArgument`,
`EvidenceNeed`, `Assumption`, `CausalRelation`, `Counterfactual`,
`CourtVerdict` — never a raw reasoning transcript. No component in this
phase stores a model's private chain-of-thought; every dataclass field
is a short, structured, auditable label (same discipline
`orca/cognitive/trace.py` already established for `CognitiveTrace`).

## The canonical flow (spec §40)

```
API
  → CognitiveKernel
      → memory recall (Phase 5, if IntentPlan needs it)
      → Truth Fabric assess_evidence() (Phase 4, if plan needs it)
          → ReasoningCompiler.compile_reasoning_plan()  -- pure, sub-millisecond
              → mode = DIRECT/ANALYTICAL: proceed straight to generation (fast path)
              → mode = COURT_REVIEW: CognitiveCourt.run() BEFORE generation
                  → EpistemicTwin (Constructor + Falsifier)
                  → EvidenceClerk (reports, doesn't decide)
                  → RiskCounsel (recommends, doesn't authorize)
                  → Arbiter (deterministic verdict)
              → ACCEPT/REVISE: proceed to ModelGateway generation
              → REJECT/INSUFFICIENT_EVIDENCE: abstain, never generate
      → ModelGateway
      → TruthFabric.verify_answer() (still runs independently, per Phase 4.1)
      → structured CognitiveResult
```

`compile_reasoning_plan()` runs for every Truth-Fabric-answered request,
but it is pure/synchronous/deterministic — sub-millisecond (measured:
0.007ms p50, see [EVALUATION.md](EVALUATION.md)). Only when it sets
`requires_court=True` does anything expensive happen. See
[REASONING_COMPILER.md](REASONING_COMPILER.md) for exactly which signals
set that flag.

## Where this sits relative to Truth Fabric and Memory Continuum

- **Truth Fabric remains the sole evidence authority** (spec §38).
  `CognitiveCourt` never retrieves, verifies, or fetches anything itself
  — it consumes a `TruthResult` the Kernel already computed via
  `TruthFabric.assess_evidence()`. `EvidenceClerk` reads that
  `TruthResult`'s own fields (contradictions, sources, evidence) rather
  than re-deriving anything.
- **Memory Continuum's Firewall is still the only path memory reaches
  Court through** (spec §35) — Deliberation Fabric introduces no new
  memory read path; if a future integration recalls `FailureMemory`/
  `ProceduralMemory` into a `CourtCase`, it goes through
  `orca.memory.retrieval.recall()` → `orca.memory.firewall` exactly like
  the Kernel's own `_recall_memory_and_enrich()` already does.
- **`CognitiveBudget` gains no new dimension this phase** — Court
  consumes `BudgetDimension.MODEL_CALLS` (2 units per round: Constructor
  + Falsifier), the same dimension every other Gateway-routed call
  already uses. The Cognitive Budget Market
  ([COGNITIVE_BUDGET_MARKET.md](COGNITIVE_BUDGET_MARKET.md)) is an
  *allocation policy* over these existing dimensions, not a new one.

## What Phase 6 explicitly does NOT touch

Per the spec's own scope boundaries (§60-62) and confirmed by the
Phase 6 audit
([CURRENT_REASONING_ARCHITECTURE.md](CURRENT_REASONING_ARCHITECTURE.md)):
`orca/brain/agent.py::AgentLoop` (tool-use execution, unchanged),
`orca/serve/routing.py` (backend cost routing, a different concern
entirely), `orca/variants/ultra.py::OrcaUltra`'s task decomposition/
parallel execution (kept — only its single-score "critic" step is
superseded for Court-eligible requests routed through the new Kernel
path). No Agent Runtime redesign, no Godmode, no Simulation Chamber.
