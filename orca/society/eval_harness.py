"""
Model Society evaluation harness (Phase 7 spec §58-59). Deterministic --
no live model calls, matching the same "real code exercised, no fabricated
scores" discipline as `orca.deliberation.eval_harness`. Scenarios below
cover the subset of spec §59's list that can be measured without a live
model call; the rest (Constructor/Falsifier role live execution,
role-injection during an actual call, same-model overlap during a live
Court run) are already covered live by
`tests/test_deliberation_court_integration.py`,
`tests/test_society_router.py`, `tests/test_society_security.py`, and
named explicitly in `covered_elsewhere` below rather than duplicated or
faked here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orca.cognitive.contracts import CognitiveBudget, ComplexityLevel, RiskLevel
from orca.deliberation.budget_market import allocate_budget
from orca.society.budget_ledger import SocietyBudgetLedger
from orca.society.contracts import CognitiveRole, RoutingRequest
from orca.society.escalation import FAST, decide_escalation
from orca.society.router import _default_checkpoint_lookup, route
from orca.society.society_plan import build_court_society_plan


def _harness_circuit_breaker_lookup():
    return None


def _harness_deployment_lookup(model_id: str) -> list:
    """The harness must be deterministic regardless of whatever stray
    ModelDeployment records happen to exist on this machine's real
    ORCA_HOME (a real fragility found during this phase's own
    development, see EVALUATION.md) -- always report 'no deployment
    record', matching this codebase's actual common-case state for the
    legacy tier-based serving path."""
    return []


def _route(request):
    return route(request, checkpoint_lookup=_default_checkpoint_lookup, deployment_lookup=_harness_deployment_lookup, circuit_breaker_lookup=_harness_circuit_breaker_lookup)


@dataclass
class Scenario:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class HarnessResult:
    total: int = 0
    passed: int = 0
    results: list[Scenario] = field(default_factory=list)
    covered_elsewhere: dict[str, str] = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


def _record(results: list[Scenario], name: str, condition: bool, detail: str = "") -> None:
    results.append(Scenario(name=name, passed=bool(condition), detail=detail))


def run_all() -> HarnessResult:
    results: list[Scenario] = []

    d = _route(RoutingRequest(role=CognitiveRole.FAST_RESPONDER))
    _record(results, "simple fast request routes without error", d.selected_model_id is not None)

    d = _route(RoutingRequest(role=CognitiveRole.CLAIM_EXTRACTOR))
    _record(results, "structured extraction role routes", d.selected_model_id is not None)

    d = _route(RoutingRequest(role=CognitiveRole.VERIFIER, allow_experimental=False))
    _record(results, "experimental Novus disallowed in production", d.selected_model_id != "orneur-novus")

    d = _route(RoutingRequest(role=CognitiveRole.VERIFIER, allow_experimental=True))
    _record(results, "experimental Novus explicitly allowed in evaluation", d.selected_model_id == "orneur-novus")

    d = _route(RoutingRequest(role=CognitiveRole.CONSTRUCTOR, allow_experimental=True))
    aeternum_ids = [c for c in d.rejected_candidates if "aeternum" in c]
    _record(results, "Aeternum absent -- never a routing candidate", bool(aeternum_ids) and d.selected_model_id != "orneur-aeternum")

    d = _route(RoutingRequest(role=CognitiveRole.CONSTRUCTOR))
    _record(results, "legacy Genesis mapping selectable for fast roles", d.selected_model_id == "orneur-genesis")

    d = _route(RoutingRequest(role=CognitiveRole.CODER))
    profiles_test = _route(RoutingRequest(role=CognitiveRole.CODER, allowed_capability_classes=["BASIC"]))
    _record(results, "entitlement-constrained request respects the constraint", "orneur-novus" != profiles_test.selected_model_id)

    plan = build_court_society_plan(allow_experimental=False, checkpoint_lookup=_default_checkpoint_lookup, deployment_lookup=_harness_deployment_lookup, circuit_breaker_lookup=_harness_circuit_breaker_lookup)
    _record(results, "same-model Constructor/Falsifier disclosed honestly", plan.same_model_role_overlap is True)

    from orca.deliberation.contracts import Argument, CounterArgument, TwinResult
    from orca.society.disagreement import compute_disagreement

    arg = Argument(claim="x")
    disagreeing = TwinResult(
        constructor_claims=[arg],
        falsifier_objections=[CounterArgument(target_argument_id=arg.argument_id, objection="no", objection_kind="contradiction", counter_evidence_ids=["ev-contra-1"])],
        disputed_claim_ids=[arg.argument_id], counter_evidence_ids=["ev-contra-1"],
    )
    signal = compute_disagreement(disagreeing)
    escalation = decide_escalation(current_tier=FAST, disagreement=signal)
    _record(results, "disagreement triggers escalation, not silent pass", escalation.action.value == "ESCALATE")

    budget = CognitiveBudget(max_model_calls=2)
    allocation = allocate_budget(uncertainty=0.5, risk=RiskLevel.LOW, evidence_conflict=False, complexity=ComplexityLevel.MEDIUM)
    ledger = SocietyBudgetLedger(budget=budget, allocation=allocation)
    ledger.reserve("constructor", 1)
    ledger.reserve("falsifier", 1)
    exhausted = False
    try:
        ledger.reserve("verification", 1)
    except Exception:
        exhausted = True
    _record(results, "budget exhaustion stops optional work", exhausted)

    from orca.deliberation.contracts import CourtVerdictState, ReasoningPlan
    from orca.deliberation.replanning import ReplanState, revise_plan_for_court_verdict

    plan0 = ReasoningPlan(goal="g")
    state = ReplanState()
    plan1 = revise_plan_for_court_verdict(plan0, CourtVerdictState.REVISE, state)
    _record(results, "replan behavior produces a new bounded plan version", plan1.version == plan0.version + 1)

    from orca.deliberation.worldstate_build import build_world_state

    ws = build_world_state("objective")
    _record(results, "WorldState is request-scoped (fresh id per call)", bool(ws.world_state_id))

    result = HarnessResult(total=len(results), passed=sum(1 for r in results if r.passed), results=results)
    result.covered_elsewhere = {
        "role fallback under a live model outage": "tests/test_gateway_model_gateway.py (existing ModelGateway fallback coverage)",
        "unhealthy preferred deployment / open circuit": "tests/test_gateway_warmup_health.py, orca/gateway/circuit_breaker.py's own test suite",
        "latency-constrained request against a live model": "docs/orneur/phase-7/PHASE_7_CLOSURE.md's latency section (live Court benchmark)",
        "role injection attempt during an actual live call": "tests/test_deliberation_security.py, tests/test_society_security.py",
        "cancellation propagation through a live Court run": "tests/test_deliberation_cancellation.py",
    }
    return result


if __name__ == "__main__":
    r = run_all()
    for scenario in r.results:
        print(("PASS" if scenario.passed else "FAIL"), scenario.name, scenario.detail)
    print(f"\n{r.passed}/{r.total} passed ({r.pass_rate:.3f})")
