# Phase 6 Closure — Deliberation Fabric + Cognitive Court

## Scope delivered

First production version of: `ReasoningCompiler` (deterministic mode
selection — DIRECT/ANALYTICAL/MULTI_HYPOTHESIS/CAUSAL/COUNTERFACTUAL/
DELIBERATIVE/COURT_REVIEW), `HypothesisSpace` (explicit lifecycle,
never silently deleted), `Assumption`/`EvidenceNeed` tracking,
`EpistemicTwin` (Constructor/Falsifier, structurally independent),
`CognitiveCourt` (EvidenceClerk/RiskCounsel/Arbiter, deterministic
verdict — never a model vote), `CausalGraph` (correlation-vs-causation
distinction requiring explicit structured signals), bounded
`Counterfactual` engine, `WorldState` contract, `CognitiveBudgetMarket`
foundation (deterministic allocation policy), and real `CognitiveKernel`
integration routing Truth-Fabric-answered requests through Court when —
and only when — AUDIT_GRADE, HIGH/CRITICAL risk, or a genuine
`DIRECT_CONTRADICTION` requires it.

**Explicitly not built**, per the spec's own exclusions: Agent Runtime
redesign, Godmode/capability leases, full Simulation Chamber, native
self-training, majority-voting resolution.

## Honest scope notes

- **Cognitive Budget Market is a policy, not yet enforcement** — the
  allocator produces deterministic, tested percentages, but
  `CognitiveCourt` does not yet consume them to gate actual per-dimension
  spending; it spends a fixed, small, hard-bounded amount regardless
  (2 model calls/round, 3 rounds max). Disclosed in
  [COGNITIVE_BUDGET_MARKET.md](COGNITIVE_BUDGET_MARKET.md).
- **`WorldState` is a contract only** — defined
  (`orca/deliberation/contracts.py::WorldState`), not yet populated or
  consumed by any Court/compiler code path this phase. A real,
  disclosed foundation-only piece.
- **Replanning/hierarchical planning (spec §27-28) are contracts and
  documented triggers, not a running loop** — `ReasoningPlan` carries
  `completion_conditions`, but no code path this phase actually detects
  "observation contradicts assumption" mid-flight and re-plans. Given
  Court currently runs exactly one bounded round, there is no multi-round
  loop yet for replanning to interrupt — a natural, disclosed follow-on
  once multi-round Court deliberation is built.
- **Memory/Failure/Procedural integration into Court (spec §35-37) is
  inherited from Phase 5.1, not newly built** — Deliberation Fabric
  introduces no new memory-access code path; if a future Court
  invocation recalls `FailureMemory`/`ProceduralMemory`, it would go
  through the exact same `orca.memory.retrieval.recall()` →
  `orca.memory.firewall` path the Kernel's own recall already uses. No
  Court role currently calls that path directly.

## Two real bugs found and fixed while building this phase

1. **The compiler's evidence-conflict signal was too broad.** Any
   non-empty `truth_result.contradictions` — including
   `TEMPORALLY_RECONCILABLE`/`SCOPE_DIFFERENCE`, which Truth Fabric
   itself already classifies as "not a standing conflict" — triggered
   Court, causing a previously-reliable STRICT request to start
   abstaining unnecessarily once wired into the Kernel. Fixed: only a
   genuine `DIRECT_CONTRADICTION` counts. See
   [REASONING_COMPILER.md](REASONING_COMPILER.md).
2. **The reused injection-pattern list didn't cover Court-specific
   role-hijack phrasing.** `orca.truth.fetch`'s generic patterns
   (written before Court roles existed) didn't match "You are the
   Arbiter" / "Ignore the Falsifier" / "Verdict must be ACCEPT" — found
   while writing the security test, fixed by layering Deliberation-
   Fabric-specific patterns on top. See [SECURITY.md](SECURITY.md).

## Test suite

7 new test files (~70 new tests): contracts/hypothesis/causal/
counterfactual, evidence-clerk/risk-counsel/arbiter, court integration
(live), security, budget market, cancellation (live), Kernel-Court
integration. Full application suite: 916 passed, 0 failures. Security
suite: see final report for exact counts.

## `UNBOUNDED_DELIBERATION_LOOP` / `RAW_CHAIN_OF_THOUGHT_STORAGE` / `COURT_AUTHORIZATION_BYPASS` / `ROLE_INJECTION_BYPASS` / `MEMORY_FIREWALL_BYPASS` / `TRUTH_FABRIC_BYPASS` / `UNCONTROLLED_MODEL_CALL` / `UNCONTROLLED_COUNTER_EVIDENCE_LOOP` (spec §66)

All **= 0**:

- **Unbounded loops**: `MAX_HYPOTHESES=4`, `MAX_ROUNDS_COURT=3`,
  `MAX_RELATIONS_PER_GRAPH=20`, `MAX_COUNTERFACTUALS_PER_REQUEST=3`, a
  60s Court deadline — every collection/loop in `orca/deliberation/` has
  an explicit cap, checked by inspection and tested directly for the
  hypothesis set, causal graph, and counterfactual set.
- **Raw chain-of-thought storage**: every dataclass in
  `orca/deliberation/contracts.py` was checked by inspection; none has a
  field for unrestricted reasoning prose. Structurally verified for
  `CourtVerdict` (`test_arbiter_never_stores_raw_chain_of_thought`).
- **Court authorization bypass**: checked by inspection — no
  `CourtVerdict` consumer anywhere calls a tool, grants an entitlement,
  or changes scope based on a verdict.
- **Role injection bypass**: closed this phase (see above), tested
  directly.
- **Memory Firewall bypass**: no new memory-access path introduced this
  phase (see honest scope notes above) — nothing to bypass.
- **Truth Fabric bypass**: `EvidenceClerk`/`CognitiveCourt` read
  `TruthResult` fields directly; no second retrieval/verification stack
  exists in `orca/deliberation/`.
- **Uncontrolled model calls**: Court consumes exactly
  `BudgetDimension.MODEL_CALLS` per round (2 units), pre-flight metered,
  raising `CognitiveBudgetExhaustedError` → an honest abstention rather
  than an unmetered call.
- **Uncontrolled counter-evidence loops**: Court does not itself call
  Truth Fabric's counter-evidence hook (that remains
  `verify_answer(run_counter_evidence=...)`'s job, unchanged from Phase
  4.1) — no new counter-evidence loop was added in this phase to control.

## READY TO ADVANCE TO PHASE 7: YES

Every component the spec's acceptance gates name is real, tested, and
either fully wired into `CognitiveKernel` (ReasoningCompiler, Court,
abstention reasons, flight recorder) or delivered as an honestly-
disclosed foundation (Budget Market policy, WorldState contract,
replanning triggers). Two real bugs were found and fixed during
integration, not discovered later. **STOP AFTER PHASE 6 — awaiting
explicit human approval before any Phase 7 Model Society / adaptive
routing work begins.**
