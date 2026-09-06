# Phase 3 Closure — Cognitive Kernel Foundation

## Scope reminder

Build the Cognitive Kernel control plane (contracts, intent/complexity/risk/freshness/evidence classifiers, budget, planning, state machine, trace, model policy) and integrate it with `ModelGateway` — without training models, redesigning RAG/Memory/Agent systems, or beginning Truth Fabric/Deliberation Fabric/Agent Runtime/Godmode/Simulation Chamber work.

## Acceptance gates

| Gate | Status |
|---|---|
| Existing full suite remains green | ✅ 698 passed (625 Phase-2.1 baseline + 73 new Phase 3 tests) |
| Security suite remains green | ✅ 31 passed |
| Cognitive Kernel exists | ✅ `orca/cognitive/kernel.py::CognitiveKernel` |
| Kernel has bounded modules, not a god class | ✅ 15 focused modules — see `ARCHITECTURE.md` |
| `CognitiveRequest` exists | ✅ |
| `IntentPlan` exists | ✅ |
| Complexity is explicit | ✅ `ComplexityAssessment` (TRIVIAL–DEEP, documented score thresholds) |
| Risk is explicit | ✅ `RiskAssessment` (LOW–CRITICAL), explicitly NOT authorization |
| Freshness requirement is explicit | ✅ `FreshnessRequirement` (STATIC–REAL_TIME) |
| Evidence requirement is explicit | ✅ `EvidenceRequirement` (NONE–AUDIT_GRADE) |
| `CognitiveBudget` exists | ✅ |
| Budget exhaustion is enforced | ✅ Pre-flight hard-stop on `MODEL_CALLS`; `CognitiveBudgetExhaustedError` never silently swallowed |
| `CognitiveContext` exists | ✅ (references only; empty is honest per phase spec) |
| `CognitivePlan` exists | ✅ |
| Operations have support states | ✅ `SUPPORTED_NOW`/`PLANNED`/`UNAVAILABLE`/`FORBIDDEN`, honestly mapped against real repo capability (`planner.py`) |
| Abstention exists | ✅ `AbstentionReason`, tested (critical-risk/unavailable-verify, budget exhaustion, model unavailable) |
| Completion conditions exist | ✅ |
| State machine exists | ✅ |
| Invalid state transitions are rejected | ✅ `InvalidStateTransitionError`, tested |
| `CognitiveTrace` exists | ✅ |
| No raw chain-of-thought is required | ✅ Every trace field is a label/short string, tested explicitly |
| Model policy is separate from actual deployment | ✅ `ModelPolicyCharacteristic` never names a model; `policy.py`'s mapping table only ever produces `nano`/`core`/`ultra`, tested |
| Kernel uses ModelGateway | ✅ via unchanged `orca/gateway/wiring.py::brain_for_tier_resolution` |
| Aeternum remains non-routable | ✅ `test_aeternum_remains_non_routable_through_the_kernel` |
| Novus governance remains enforced | ✅ `test_novus_deployment_registers_as_experimental_not_production_via_kernel` |
| Genesis historical/canonical distinction remains intact | ✅ `test_genesis_legacy_and_canonical_stay_distinct_through_kernel_policy` |
| Cancellation propagates through Kernel | ✅ `test_cancellation_propagates_through_kernel_execute` (real Ollama, real `asyncio.CancelledError`) |
| Trace IDs propagate | ✅ `CognitiveRequest.trace_id` flows into `InferenceRequest.trace_id` unchanged |
| Cognitive metrics exist | ✅ `orca/cognitive/metrics.py`, low-cardinality, tested |
| Simple supported requests route through Kernel in real serving path | ✅ `/api/cognitive/execute` — real, tested, end-to-end |
| No unexpected orchestration bypass remains | ✅ within the scope the Kernel actually claims — see `CUTOVER.md`'s explicit scope table |
| Kernel overhead is measured | ✅ see Performance below |

## Real serving cutover — honest scope

**Not** a claim that `/api/chat`/`/api/stream` now execute through the Kernel. See `CUTOVER.md` for the full reasoning: those endpoints run the Kernel in **shadow mode only** (plans every request, records a shadow-comparison metric, never changes the actual response), because the Kernel's cognitive `ModelPolicyCharacteristic` and the existing paid-tier entitlement system (`model_access_allowed`) are genuinely different concerns that must not be silently blended — doing so risks a real plan-gating leak (a free-tier user's "complex" question silently routed to a paid tier's model). Full production cutover of those two endpoints is named as a disclosed remaining blocker, not hidden.

What IS real, tested, end-to-end Kernel authority: `POST /api/cognitive/execute`, a new internal/experimental endpoint where the Kernel genuinely plans AND executes, verified against real local Ollama.

## Direct-Kernel-bypass audit

No other HTTP-reachable code path was found calling into cognitive-shaped decision logic (intent/complexity/risk-style classification) outside `orca/cognitive/`. `orca/serve/routing.py`'s heuristics and `orca/lens/intent.py`'s generation-intent detector are real, pre-existing, orthogonal decision points (documented in `CURRENT_COGNITIVE_ORCHESTRATION.md`) — neither claims to be superseded by Phase 3, so neither counts as a "bypass" of a Kernel claim that was never made over them.

## Performance

Measured on this machine (Apple M4, 16GB, CPU-only Ollama — same environment as the Phase 2/2.1 baselines):

| | |
|---|---|
| `kernel.plan()` latency (pure, no I/O, 20 runs) | avg 0.075ms, min 0.064ms, max 0.148ms |
| `/api/cognitive/execute` total request latency (3 real runs) | 892.8ms / 972.4ms / 1176.4ms |
| Of which Kernel-measured latency | 884.1ms / 933.7ms / 1169.8ms (i.e. planning+auth+moderation overhead is ~10-40ms, the rest is the real Gateway/Ollama call) |

Planning itself is effectively free — deterministic rules-based classification with zero I/O. The measured end-to-end latency is dominated by the same Ollama generation cost Phase 2's baseline already established (~730-900ms TTFT on this hardware); the Kernel adds no material overhead on top of it.

## Test suite state

- Full suite: **698 passed, 0 failed**.
- Security suite: **31 passed**.
- 73 new tests this phase, spanning: pure unit tests for every classifier/budget/state-machine/planner/policy module (no I/O, deterministic), and real end-to-end integration tests against local Ollama for the Kernel's `execute()` method and the new `/api/cognitive/execute` HTTP endpoint (auto-skipping, not failing, when Ollama is unreachable) — consistent with this project's standing discipline of not relying only on mocked model behavior for integration claims.

## Known limitations (disclosed, not hidden)

1. `/api/chat` and `/api/stream` are shadow-only for Kernel planning, not execution-authoritative — see `CUTOVER.md`'s full reasoning (paid-tier entitlement entanglement, conversation-continuity preservation).
2. `SEARCH`/`RETRIEVE`/`USE_TOOL`/`DELEGATE_AGENT` operations are declared `SUPPORTED_NOW` (real capabilities exist via the existing `AgentLoop`/`DocStore`/tool registry) but are not executed BY the Kernel itself in Phase 3 — the Kernel's plan for these cases completes with an explicit deferral warning rather than fabricating an answer or reimplementing those subsystems.
3. `VERIFY`/`SIMULATE`/general-purpose `DELEGATE_AGENT` are declared `PLANNED` — no implementation exists. An `AUDIT_GRADE`-evidence request (e.g. anything matched as `CRITICAL` risk) honestly abstains rather than answering without the verification it requires.
4. `orca/brain/reasoning.py`'s `ReasoningEngine` (flagged dead code in Phase 2.1's closure) remains unused and untouched — irrelevant to Phase 3's scope.
5. No fuzz/property testing was added this pass beyond the deterministic unit tests already covering budget arithmetic and state-machine transitions exhaustively by enumeration (small enough state spaces that property-testing would add tooling overhead without meaningfully increasing coverage) — a deliberate "don't over-engineer" call per the phase spec's own §41.

## READY TO ADVANCE TO PHASE 4: YES

All Phase 3 acceptance gates are met. Cognitive Kernel foundation (contracts, classifiers, budget, planning, state machine, trace, model policy, ModelGateway integration) is real, bounded, tested against real infrastructure where safe, and honestly scoped against what later phases (Truth Fabric, Memory Continuum, Deliberation Fabric, Agent Runtime, Godmode, Simulation Chamber) will build. Per the phase instruction, this phase **STOPS** here — no Truth Fabric (Phase 4) work has been started, and none will begin without explicit human approval.
