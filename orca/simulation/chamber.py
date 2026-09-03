"""
Simulation Chamber orchestrator (Phase 11 spec §2-3, §34-36, §43-46).
The canonical high-authority path (spec §2):

    AgentPlan -> ActionRequest -> Capability/Policy preliminary eligibility
    -> Simulation Requirement Policy -> Simulation Chamber -> SimulationResult
    -> Truth/Court/Risk review where applicable -> approval/lease resolution
    -> Capability Engine -> Policy Engine -> budget -> actual execution
    -> Observation -> WorldState reconciliation

`run_simulation()` NEVER authorizes anything -- it returns a
`SimulationResult`/`ExecutionGateDecision` that downstream Capability/
Policy/lease checks (unchanged, Phase 8/9/10) still gate on
independently. A Godmode `lease_id` given here is used ONLY for a
READ-ONLY compatibility check (`orca.godmode.resolution.resolve_lease()`,
never `resolve_and_consume_lease()`) -- simulation must never consume a
one-use lease merely for a non-executing preview (spec §47-48).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from orca.connectors.contracts import ConnectorIdentity, ConnectorInstance
from orca.simulation.connector_sim import simulate_connector_write
from orca.simulation.contracts import (
    PredictedEffect,
    SimulationAction,
    SimulationFailureReason,
    SimulationMode,
    SimulationRequest,
    SimulationResult,
    SimulationTrace,
    SimulationVerdict,
    StateFingerprint,
)
from orca.simulation.filesystem_sim import simulate_file_action
from orca.simulation.fingerprint import fingerprint_file, fingerprint_unavailable
from orca.simulation.integrity import apply_result_signature

MAX_SIMULATION_ACTIONS = 5    # spec §34: hard bound, no unbounded plan exploration
MAX_SIMULATION_BRANCHES = 2   # spec §35: success + expected-failure, never hundreds of futures


@dataclass
class ChamberDependencies:
    """Every dependency is optional and explicit -- the Chamber never
    guesses which domain to simulate from a tool name (spec §10's "do
    not infer simulation support solely from tool name")."""
    filesystem_root: Path | None = None
    connector_instance: ConnectorInstance | None = None
    connector_identity: ConnectorIdentity | None = None
    lease_id: str | None = None
    budget_ledger: object | None = None   # orca.society.budget_ledger.SocietyBudgetLedger, kept untyped here to avoid a hard import cycle
    kill_switch_check: object | None = None  # callable[[], bool], injected so this module never hard-imports orca.godmode.kill_switch unconditionally


def _reserve_budget(deps: ChamberDependencies) -> bool:
    if deps.budget_ledger is None:
        return True
    from orca.cognitive.errors import CognitiveBudgetExhaustedError
    try:
        deps.budget_ledger.reserve("simulation_operations", 1)
        return True
    except CognitiveBudgetExhaustedError:
        return False


def _check_lease_compatibility(request: SimulationRequest) -> tuple[bool, list[str]]:
    """Read-only lease check -- NEVER consumes a use (spec §47-48)."""
    if request.lease_id is None:
        return True, []
    from orca.godmode.contracts import CapabilityDomain
    from orca.godmode.resolution import resolve_lease
    decision = resolve_lease(
        request.lease_id, tenant_id=request.tenant_id, capability_domain=CapabilityDomain(request.capability_domain),
        capability=request.capability, resource_scope=request.action.resource_scope,
        operation_scope=request.action.operation_scope, arguments={},
    )
    if decision.state.value != "ALLOW":
        return False, [f"lease compatibility check failed (read-only, not consumed): {r}" for r in decision.reasons]
    return True, []


def run_simulation(request: SimulationRequest, deps: ChamberDependencies) -> tuple[SimulationResult, SimulationTrace]:
    trace = SimulationTrace(request_id=request.request_id)

    if deps.kill_switch_check is not None and deps.kill_switch_check():
        result = SimulationResult(request_id=request.request_id, verdict=SimulationVerdict.BLOCK, block_reasons=["kill switch is active"], failure_reason=SimulationFailureReason.POLICY_BLOCKED)
        return apply_result_signature(result), trace

    if not _reserve_budget(deps):
        result = SimulationResult(request_id=request.request_id, verdict=SimulationVerdict.INCONCLUSIVE, failure_reason=SimulationFailureReason.BUDGET_EXHAUSTED, warnings=["simulation budget exhausted"])
        return apply_result_signature(result), trace

    lease_ok, lease_reasons = _check_lease_compatibility(request)
    if not lease_ok:
        result = SimulationResult(request_id=request.request_id, verdict=SimulationVerdict.BLOCK, block_reasons=lease_reasons, failure_reason=SimulationFailureReason.POLICY_BLOCKED)
        return apply_result_signature(result), trace

    if deps.filesystem_root is not None and "operation" in request.action.arguments:
        trace.mode = SimulationMode.SANDBOX_EXECUTION
        trace.provider_id = "filesystem_sim"
        input_fp = fingerprint_file(deps.filesystem_root, request.action.arguments.get("path", ""))
        outcome = simulate_file_action(root=deps.filesystem_root, action=request.action)
        if outcome.blocked:
            result = SimulationResult(
                request_id=request.request_id, mode_used=SimulationMode.SANDBOX_EXECUTION, verdict=SimulationVerdict.BLOCK,
                block_reasons=[outcome.block_reason or "blocked"], assumptions=outcome.assumptions, input_fingerprints=[input_fp],
            )
            trace.verdict = result.verdict
            return apply_result_signature(result), trace
        warnings = []
        for effect in outcome.predicted_effects:
            if effect.reversibility.value == "IRREVERSIBLE":
                warnings.append(f"predicted effect on {effect.resource!r} is IRREVERSIBLE")
        verdict = SimulationVerdict.PASS_WITH_WARNINGS if warnings else SimulationVerdict.PASS
        result = SimulationResult(
            request_id=request.request_id, mode_used=SimulationMode.SANDBOX_EXECUTION, verdict=verdict,
            predicted_effects=outcome.predicted_effects, assumptions=outcome.assumptions, warnings=warnings,
            input_fingerprints=[input_fp],
        )
        trace.effect_ids = [e.effect_id for e in outcome.predicted_effects]
        trace.assumption_ids = [a.assumption_id for a in outcome.assumptions]
        trace.verdict = result.verdict
        return apply_result_signature(result), trace

    if deps.connector_instance is not None and deps.connector_identity is not None:
        trace.mode = SimulationMode.PROVIDER_PREVIEW
        trace.provider_id = "connector_sim"
        if deps.connector_instance.tenant_id != deps.connector_identity.tenant_id:
            result = SimulationResult(request_id=request.request_id, mode_used=SimulationMode.PROVIDER_PREVIEW, verdict=SimulationVerdict.BLOCK, block_reasons=["predicted tenant escape -- connector instance tenant does not match requesting identity tenant"])
            trace.verdict = result.verdict
            return apply_result_signature(result), trace

        outcome = simulate_connector_write(instance=deps.connector_instance, identity=deps.connector_identity, action=request.action)
        if not outcome.supported:
            result = SimulationResult(
                request_id=request.request_id, mode_used=SimulationMode.PROVIDER_PREVIEW, verdict=SimulationVerdict.INCONCLUSIVE,
                failure_reason=SimulationFailureReason.UNSUPPORTED, warnings=[outcome.unavailable_reason or "unsupported"],
            )
            trace.verdict = result.verdict
            return apply_result_signature(result), trace

        warnings = []
        if outcome.outcome_unknown_risk:
            warnings.append("OUTCOME_UNKNOWN_RISK: a commit-then-response-lost race exists for this write (no idempotency key)")
        verdict = SimulationVerdict.PASS_WITH_WARNINGS if warnings else SimulationVerdict.PASS
        result = SimulationResult(
            request_id=request.request_id, mode_used=SimulationMode.PROVIDER_PREVIEW, verdict=verdict,
            predicted_effects=outcome.predicted_effects, assumptions=outcome.assumptions, warnings=warnings,
        )
        trace.effect_ids = [e.effect_id for e in outcome.predicted_effects]
        trace.assumption_ids = [a.assumption_id for a in outcome.assumptions]
        trace.verdict = result.verdict
        return apply_result_signature(result), trace

    # No real simulation mechanism wired for this request -- STATIC_ANALYSIS
    # only (spec §12): no execution, no fabricated confidence.
    trace.mode = SimulationMode.STATIC_ANALYSIS
    trace.provider_id = "static_only"
    result = SimulationResult(
        request_id=request.request_id, mode_used=SimulationMode.STATIC_ANALYSIS, verdict=SimulationVerdict.INCONCLUSIVE,
        failure_reason=SimulationFailureReason.UNSUPPORTED,
        warnings=["no sandbox/dry-run/preview mechanism was wired for this action -- only static analysis was possible"],
    )
    trace.verdict = result.verdict
    return apply_result_signature(result), trace
