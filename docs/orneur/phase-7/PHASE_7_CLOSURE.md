# Phase 7 Closure — Model Society + Adaptive Cognitive Routing

## Scope delivered

First production version of: `orca/society/` (Model Society package) --
typed contracts (`CognitiveRole`, `ModelCapabilityProfile`,
`RoleRequirement`, `RoutingRequest/Candidate/Decision/Reason/Outcome`,
`SocietyPlan`, `DisagreementSignal`, `EscalationDecision`, `RoutingTrace`),
real evidence-backed capability profiles for Genesis-legacy and Novus
(Aeternum deliberately unprofiled -- no checkpoint exists), a
deterministic evidence-weighted adaptive router with explicit hard-filter/
soft-ranking phases, `SocietyPlan` construction for Court's
Constructor/Falsifier, structured disagreement (never majority vote),
a capability-requirement-based escalation/de-escalation engine, an
operational Cognitive Budget Market ledger (real reservation/release/
reallocation against the existing `CognitiveBudget`), typed WorldState
operations with mandatory provenance, a first bounded replan mechanism
with plan versioning, Court's Constructor/Falsifier now routed through
Model Society instead of a hardcoded `"nano"` literal, and a schema-
enforcement fix for the Phase 6 Falsifier `objection_kind` finding.

**Explicitly not built**, per the spec's own exclusions: Agent Runtime
redesign, Godmode, full Simulation Chamber, model training (Genesis/
Novus/Aeternum/router), Phase 8 Agentic Runtime expansion.

## Honest scope notes

- **Only Constructor/Falsifier are migrated to live Society routing.**
  Truth Fabric's claim extractor/verifier/query-rewrite, `AgentLoop`'s
  tool-reasoning calls, `OrcaUltra`'s grade/self-heal call, and Memory's
  selector/summarizer calls remain on their pre-existing literal-tier call
  sites -- per spec §43-45's own "do not force every operation through
  Model Society" / "do not redesign Agent Runtime." `RoleRequirement`s for
  all 13 other roles are declared and tested, not wired to a live call.
- **Cognitive Budget Market enforcement covers Court's constructor/
  falsifier reservations only.** `SocietyBudgetLedger` supports
  verification/counter_evidence/retrieval/optional_second_model/
  replanning purposes, and reallocation between them, but no production
  code path currently reserves against those other purposes -- only
  Court's two mandatory role calls are wired end-to-end.
- **Replanning is a real, tested mechanism, not yet wired into Kernel.**
  `revise_plan_for_court_verdict()` correctly produces a versioned,
  locally-revised plan on Court's `REVISE` verdict, bounded by
  `MAX_REPLANS=2` -- but no production code path calls it yet; Court still
  returns a single-round verdict exactly as in Phase 6. See
  `REPLANNING.md`.
- **WorldState is populated from TruthResult + HypothesisSet only.**
  Memory (WorkingMemory/SemanticMemory) is not yet a WorldState source --
  an honest, disclosed gap (spec §28 lists memory as one of several
  possible sources, not a requirement to use all of them immediately).
- **Deployment-health hard-filtering is best-effort.** No `ModelDeployment`
  records exist for the legacy tier-based Ollama serving path today, so
  this check is a documented no-op for the common case (see
  `CURRENT_MODEL_ROUTING.md`, `ADAPTIVE_ROUTER.md`).

## A real, disclosed environment finding (not a Model Society bug, but found because of it)

`tests/test_gateway_artifact_cross_check.py`,
`test_gateway_compat_brain.py`, `test_gateway_model_gateway.py`, and
`test_gateway_warmup_health.py` write real `ModelDeployment` records
directly into this machine's actual `~/.orca` without isolating
`ORCA_HOME` -- a pre-existing test-hygiene gap, not introduced this phase.
This transiently caused Model Society's router to spuriously reject Novus
during this phase's own development. Fixed for Model Society's OWN tests
by making `route()`'s checkpoint/deployment lookups injectable (see
`ADAPTIVE_ROUTER.md`/`EVALUATION.md`); the underlying test file
non-isolation is flagged as a follow-on task, not fixed here (outside
Model Society's own code -- a background task has been filed for it).

## Real bug found and fixed during this phase

`ComplexityLevel.MODERATE` was used in `orca/deliberation/court.py`'s
first draft of the budget-allocation call -- the real enum has `MEDIUM`,
not `MODERATE`. Caught immediately by the live Court integration test
suite (`AttributeError: MODERATE`), fixed before any commit.

## Test suite

7 new test files (~68 new tests): `test_society_router.py`,
`test_society_plan_disagreement_escalation.py`, `test_society_security.py`,
`test_society_budget_ledger.py`, `test_society_eval_harness.py`,
`test_deliberation_worldstate_replanning.py`,
`test_twin_objection_kind_validation.py`, plus the existing
`test_deliberation_court_integration.py`/`test_kernel_court_integration.py`/
`test_deliberation_cancellation.py` (unchanged, now exercising the
Society-routed path and all still passing live).

Full application suite (fresh, clean run): **965 passed, 0 failures**,
309.79s. Security suite (14 files, including the two new deliberation/
society security test files): **154 passed, 0 failures**, 453.00s.

## `ROUTING_LIFECYCLE_BYPASS` / `ROUTING_ENTITLEMENT_BYPASS` / `ROUTING_BUDGET_BYPASS` / `FICTIONAL_MODEL_ROUTING` / `UNHEALTHY_DEPLOYMENT_ROUTING` / `UNVALIDATED_ROLE_OUTPUT` / `UNBOUNDED_ROLE_FANOUT` / `UNBOUNDED_REPLAN_LOOP` / `COURT_DIRECT_TIER_BYPASS` / `RAW_CHAIN_OF_THOUGHT_STORAGE` (spec §75)

All **= 0**:

- **Lifecycle bypass**: `route()` hard-filters `REJECTED`/`RETIRED` always,
  and `EXPERIMENTAL` unless `allow_experimental=True` -- checked directly
  (`test_novus_not_production_routable_without_explicit_opt_in`). No
  ranking score can override this (hard filter runs before scoring).
- **Entitlement bypass**: `_entitlement_ok()` is a hard filter, not a
  ranking dimension -- proven directly
  (`test_entitlement_hard_filter_cannot_be_overridden_by_score`).
- **Budget bypass**: `SocietyBudgetLedger.reserve()` raises
  `CognitiveBudgetExhaustedError` (the same exception every other Kernel
  budget dimension raises) rather than silently exceeding a cap; proven
  under an adversarial "spend unlimited model calls" framing directly
  (`test_unlimited_model_calls_request_is_still_hard_capped_by_the_ledger`).
- **Fictional model routing**: Aeternum is never a routing candidate
  (`AETERNUM_ABSENT` always present for it); no code path can select it.
- **Unhealthy deployment routing**: `_deployment_health_ok()` rejects any
  candidate with a present-but-unhealthy deployment record; checked
  directly by deliberately injecting an unhealthy fake deployment.
- **Unvalidated role outputs**: `_validate_objection_kind()` degrades any
  taxonomy value outside the declared seven to `UNVALIDATED`, never
  passed through raw.
- **Unbounded role fanout**: `SocietyPlan`'s only current fan-out is
  Constructor+Falsifier (2 roles), both budget-reserved before launch;
  `parallelizable_groups` is empty (Falsifier depends on Constructor's
  output) -- no unbounded concurrent role explosion exists in this phase.
- **Unbounded replan loop**: `MAX_REPLANS=2`, enforced by
  `ReplanBudgetExhaustedError` when exceeded.
- **Court direct-tier bypass**: `CognitiveCourt.run()` with no explicit
  `twin` argument ALWAYS routes through `build_court_society_plan()` --
  the old `EpistemicTwin(tier="nano")` hardcoded default remains only as
  the *fallback tier value* inside `EpistemicTwin.__init__` for callers
  that explicitly construct their own Twin (e.g. targeted unit tests), not
  as Court's own resolution path.
- **Raw chain-of-thought storage**: no dataclass in `orca/society/`
  carries an unrestricted reasoning-prose field; checked by inspection,
  matching Phase 6's discipline.

## READY TO ADVANCE TO PHASE 8: YES

Every component the spec's acceptance gates name is real, tested, and
either fully wired into `CognitiveCourt` (routing, budget ledger,
WorldState population, objection-kind validation) or delivered as an
honestly-disclosed foundation (replanning mechanism not yet
Kernel-wired, most non-Court roles declared but not live, WorldState not
yet memory-sourced). One real bug was found and fixed during
integration (a wrong enum name), one real pre-existing test-hygiene gap
in an unrelated test suite was found and filed as a follow-on task, not
papered over. **STOP AFTER PHASE 7 -- awaiting explicit human approval
before any Phase 8 Agentic Runtime / world/tool execution expansion
begins.**
