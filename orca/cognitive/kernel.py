"""
Cognitive Kernel -- the control plane above inference (Phase 3 spec §1-2).

The Kernel does NOT call Ollama, query vector DBs, search the web, execute
shell tools, manage permissions, perform RAG, store long-term memory, or
run agent swarms. It coordinates: it converts a CognitiveRequest into a
CognitivePlan (plan()), and for the subset of plans it can genuinely
satisfy on its own -- a direct answer or a reasoning completion with no
tool/retrieval/memory/agent requirement -- executes them via ModelGateway
(execute()). Everything else remains, as instructed, the existing serving
stack's job (see docs/orneur/phase-3/CUTOVER.md): a plan requiring
RETRIEVE/USE_TOOL/RECALL_MEMORY/DELEGATE_AGENT is real and valid, but its
actual execution is the existing DocStore/AgentLoop/MemoryEngine path in
orca/serve/api.py, not a Kernel reimplementation of any of them.

This module is intentionally small: it is coordination glue over the
bounded modules (intent.py, complexity.py, risk.py, freshness.py,
evidence.py, policy.py, planner.py, budget.py, state_machine.py, trace.py)
-- not a god class (Phase 3 spec §2).
"""
from __future__ import annotations

import time

from orca.cognitive import metrics
from orca.cognitive.budget import CognitiveBudgetExhaustedError, DEFAULT_BUDGET, consume
from orca.cognitive.complexity import assess_complexity
from orca.cognitive.contracts import (
    AbstentionReason,
    BudgetDimension,
    CognitiveBudget,
    CognitiveRequest,
    CognitiveResult,
    CognitiveState,
    OperationSupportState,
    OperationType,
)
from orca.cognitive.entitlement import EntitlementPolicy
from orca.cognitive.errors import CognitiveExecutionFailedError, PlanInvalidError
from orca.cognitive.evidence import assess_evidence_requirement
from orca.cognitive.freshness import assess_freshness
from orca.cognitive.intent import compile_intent
from orca.cognitive.planner import build_plan, plan_abstention_reason
from orca.cognitive.policy import characteristic_to_tier, select_model_policy
from orca.cognitive.reconciliation import ReconciliationOutcome, reconcile_policy
from orca.cognitive.risk import assess_risk
from orca.cognitive.state_machine import CognitiveStateMachine
from orca.cognitive.trace import CognitiveTraceBuilder

# Operations Kernel.execute() can genuinely satisfy on its own in Phase 3
# -- see module docstring. Any plan requiring something outside this set
# is real (not an error), just not something THIS method executes.
_KERNEL_EXECUTABLE_OPS = {OperationType.ANSWER_DIRECTLY, OperationType.REASON, OperationType.RECALL_MEMORY}

# Since Phase 4: real via orca.truth.truth_fabric.TruthFabric, bounded,
# Gateway-routed. Handled by _answer_with_truth_fabric() below -- NOT by
# _answer_directly(), and NOT delegated to the existing serving stack, as
# long as the plan needs nothing ELSE (USE_TOOL/DELEGATE_AGENT) beyond
# these three operations.
_TRUTH_FABRIC_OPS = {OperationType.RETRIEVE, OperationType.SEARCH, OperationType.VERIFY}


class CognitiveKernel:
    def __init__(self, gateway=None):
        """`gateway` is injectable for tests; defaults to the same shared
        ModelGateway singleton the rest of the live serving path uses
        (orca.gateway.wiring.get_shared_gateway) -- the Kernel never
        constructs its own runtime."""
        self._gateway_override = gateway

    def _gateway(self):
        if self._gateway_override is not None:
            return self._gateway_override
        from orca.gateway.wiring import get_shared_gateway
        return get_shared_gateway()

    def plan(self, request: CognitiveRequest):
        """Pure, deterministic, synchronous -- no I/O. Given the same
        CognitiveRequest, always produces the same CognitivePlan."""
        start = time.monotonic()
        intent = compile_intent(request.objective)
        complexity = assess_complexity(request.objective, intent)
        risk = assess_risk(request.objective, intent)
        freshness = assess_freshness(request.objective)
        evidence = assess_evidence_requirement(intent, risk)
        model_policy = select_model_policy(intent, complexity)
        budget = request.budget_constraints or CognitiveBudget(
            max_tokens=DEFAULT_BUDGET.max_tokens,
            max_latency_ms=DEFAULT_BUDGET.max_latency_ms,
            max_model_calls=DEFAULT_BUDGET.max_model_calls,
            max_retrieval_calls=DEFAULT_BUDGET.max_retrieval_calls,
            max_tool_calls=DEFAULT_BUDGET.max_tool_calls,
            max_agent_calls=DEFAULT_BUDGET.max_agent_calls,
            max_cost_usd=DEFAULT_BUDGET.max_cost_usd,
            max_reasoning_rounds=DEFAULT_BUDGET.max_reasoning_rounds,
        )

        plan = build_plan(
            request_id=request.request_id, trace_id=request.trace_id, objective=request.objective,
            intent=intent, complexity=complexity, risk=risk, freshness=freshness,
            evidence=evidence, model_policy=model_policy, budget=budget,
        )
        if not plan.operations:
            raise PlanInvalidError(internal_detail="plan produced zero operations")

        metrics.record_plan(
            intent=intent.primary_intent.value, complexity=complexity.level.value, risk=risk.level.value,
            model_policy=model_policy.characteristic.value, operations=[op.type.value for op in plan.operations],
            planning_latency_ms=(time.monotonic() - start) * 1000,
        )
        return plan

    async def execute(self, request: CognitiveRequest, entitlement: EntitlementPolicy | None = None, doc_store=None) -> CognitiveResult:
        """
        `doc_store`, when given (Phase 4), lets the Kernel route a plan
        needing RETRIEVE/SEARCH/VERIFY through orca.truth.truth_fabric's
        TruthFabric itself rather than deferring to the existing serving
        stack -- see _answer_with_truth_fabric(). Omitting it (or a plan
        that ALSO needs USE_TOOL/DELEGATE_AGENT) preserves exact Phase 3.1
        deferred behavior.

        `entitlement`, when given, makes this call entitlement-aware
        (Phase 3.1): the Kernel's own ModelPolicy is reconciled against it
        via orca/cognitive/reconciliation.py BEFORE any tier is resolved,
        for BOTH the direct-answer path and the deferred-to-existing-stack
        path (CognitiveResult.resolved_tier carries the reconciled tier
        either way, so callers like orca/serve/api.py use the SAME
        entitlement-capped tier regardless of which path actually executes
        the request). The Kernel's own cognitive judgment (plan(), model
        policy selection) never sees or is influenced by entitlement --
        only this reconciliation step is. Omitting `entitlement` entirely
        preserves exact Phase 3 behavior (e.g. /api/cognitive/execute,
        which has no session/commercial-tier concept).

        Cancellation: this is a plain `async def` awaiting ModelGateway
        directly -- a cancelled asyncio.Task propagates CancelledError
        through this call exactly like any other await, reaching the
        Gateway's own proven cancellation/permit-release path (Phase 2)
        without the Kernel swallowing or needing to special-case it
        (Phase 3 spec §38).
        """
        metrics.record_request()
        start = time.monotonic()
        sm = CognitiveStateMachine()
        trace_builder = CognitiveTraceBuilder(request.request_id, request.trace_id)

        sm.transition(CognitiveState.CLASSIFYING)
        try:
            plan = self.plan(request)
        except PlanInvalidError:
            sm.transition(CognitiveState.FAILED)
            trace_builder.record_transition(sm.history[-1])
            metrics.record_total_latency((time.monotonic() - start) * 1000)
            return CognitiveResult(request_id=request.request_id, trace_id=request.trace_id, status=CognitiveState.FAILED)

        trace_builder.record_transition(sm.history[-1])
        sm.transition(CognitiveState.PLANNED)
        trace_builder.record_plan(plan)
        trace_builder.record_transition(sm.history[-1])

        reason = plan_abstention_reason(plan)
        if reason is not None:
            sm.transition(CognitiveState.ABSTAINED)
            trace_builder.record_transition(sm.history[-1])
            trace_builder.record_abstention(reason)
            metrics.record_abstention(reason.value)
            if reason == AbstentionReason.BUDGET_EXHAUSTED:
                metrics.record_budget_exhaustion()
            trace_builder.finalize(plan.budget)
            latency_ms = (time.monotonic() - start) * 1000
            metrics.record_total_latency(latency_ms)
            return CognitiveResult(
                request_id=request.request_id, trace_id=request.trace_id, status=CognitiveState.ABSTAINED,
                plan_id=plan.plan_id, abstention_reason=reason, latency_ms=latency_ms,
            )

        executable_ops = [op for op in plan.operations if op.type in _KERNEL_EXECUTABLE_OPS and op.support_state == OperationSupportState.SUPPORTED_NOW]
        truth_fabric_ops = [op for op in plan.operations if op.type in _TRUTH_FABRIC_OPS and op.support_state == OperationSupportState.SUPPORTED_NOW]
        other_ops = [op for op in plan.operations if op.type not in _KERNEL_EXECUTABLE_OPS and op.type not in _TRUTH_FABRIC_OPS]
        # A plan needing USE_TOOL/DELEGATE_AGENT (in `other_ops`) ALONGSIDE
        # RETRIEVE/SEARCH/VERIFY still defers everything to the existing
        # stack unchanged (Truth Fabric doesn't run tools/agents). Absent
        # that, Truth Fabric runs even with doc_store=None -- it honestly
        # reports INSUFFICIENT evidence rather than needing a fallback
        # (verified in tests/test_truth_fabric_integration.py).
        use_truth_fabric = bool(truth_fabric_ops) and not other_ops
        non_kernel_ops = other_ops if use_truth_fabric else other_ops + truth_fabric_ops

        sm.transition(CognitiveState.EXECUTING)
        trace_builder.record_transition(sm.history[-1])

        # Entitlement/cognitive-policy reconciliation (Phase 3.1 spec §5-6)
        # -- applied BEFORE any tier is resolved, for both the
        # deferred-to-existing-stack path and the direct-answer path
        # below. Omitting `entitlement` preserves exact Phase 3 behavior.
        degraded = False
        degradation_reason: str | None = None
        notification_required = False
        resolved_tier = characteristic_to_tier(plan.model_policy.characteristic)
        if entitlement is not None:
            effective = reconcile_policy(plan.model_policy, entitlement)
            resolved_tier = effective.resolved_tier
            degraded = effective.degraded
            degradation_reason = effective.reason if effective.degraded else None
            notification_required = effective.user_notification_required
            trace_builder.record_reconciliation(effective)
            if effective.outcome == ReconciliationOutcome.ABSTAINED:
                sm.transition(CognitiveState.ABSTAINED)
                trace_builder.record_transition(sm.history[-1])
                trace_builder.record_abstention(AbstentionReason.POLICY_RESTRICTION)
                metrics.record_abstention(AbstentionReason.POLICY_RESTRICTION.value)
                trace_builder.finalize(plan.budget)
                latency_ms = (time.monotonic() - start) * 1000
                metrics.record_total_latency(latency_ms)
                return CognitiveResult(
                    request_id=request.request_id, trace_id=request.trace_id, status=CognitiveState.ABSTAINED,
                    plan_id=plan.plan_id, abstention_reason=AbstentionReason.POLICY_RESTRICTION, latency_ms=latency_ms,
                    degraded=True, degradation_reason=effective.reason, user_notification_required=True,
                )

        if use_truth_fabric:
            return await self._answer_with_truth_fabric(
                request, plan, resolved_tier, doc_store, sm, trace_builder, start,
                degraded, degradation_reason, notification_required,
            )

        if non_kernel_ops:
            # Real, valid plan -- but satisfying RETRIEVE/USE_TOOL/
            # DELEGATE_AGENT is the existing serving stack's job in Phase
            # 3, not this method's (see module docstring / CUTOVER.md).
            # The plan itself is still useful output for the caller;
            # resolved_tier carries the entitlement-reconciled tier the
            # caller's own execution (e.g. AgentLoop) should use.
            sm.transition(CognitiveState.COMPLETED)
            trace_builder.record_transition(sm.history[-1])
            trace_builder.record_operation_outcome("deferred_to_existing_serving_stack")
            trace_builder.finalize(plan.budget)
            latency_ms = (time.monotonic() - start) * 1000
            metrics.record_total_latency(latency_ms)
            return CognitiveResult(
                request_id=request.request_id, trace_id=request.trace_id, status=CognitiveState.COMPLETED,
                resolved_tier=resolved_tier, plan_id=plan.plan_id, operations_executed=[], latency_ms=latency_ms,
                warnings=[f"plan requires {op.type.value} -- executed by the existing serving stack, not the Kernel" for op in non_kernel_ops],
                degraded=degraded, degradation_reason=degradation_reason, user_notification_required=notification_required,
            )

        warnings: list[str] = list()
        try:
            # Hard-stop check BEFORE spending anything -- a model call is
            # about to happen, so MODEL_CALLS is enforced pre-flight.
            consume(plan.budget, BudgetDimension.MODEL_CALLS, 1)
            tier = resolved_tier
            output_text, resolved_model, usage = await self._answer_directly(request.objective, tier, request.trace_id)
            # TOKENS can only be known AFTER the call completes -- record
            # actual consumption for observability, but don't retroactively
            # fail an already-completed, already-useful response over it;
            # flag it instead so the caller/next request sees it.
            total_tokens = usage.get("total_tokens") or 0
            if total_tokens:
                try:
                    consume(plan.budget, BudgetDimension.TOKENS, total_tokens)
                except CognitiveBudgetExhaustedError:
                    plan.budget.consumed_tokens += total_tokens
                    warnings.append("token budget exceeded by this response -- recorded, not enforced retroactively")
        except CognitiveBudgetExhaustedError:
            sm.transition(CognitiveState.ABSTAINED)
            trace_builder.record_transition(sm.history[-1])
            trace_builder.record_abstention(AbstentionReason.BUDGET_EXHAUSTED)
            metrics.record_abstention(AbstentionReason.BUDGET_EXHAUSTED.value)
            metrics.record_budget_exhaustion()
            trace_builder.finalize(plan.budget)
            latency_ms = (time.monotonic() - start) * 1000
            metrics.record_total_latency(latency_ms)
            return CognitiveResult(
                request_id=request.request_id, trace_id=request.trace_id, status=CognitiveState.ABSTAINED,
                plan_id=plan.plan_id, abstention_reason=AbstentionReason.BUDGET_EXHAUSTED, latency_ms=latency_ms,
            )
        except Exception as e:
            from orca.gateway.errors import ModelNotRoutableError
            if isinstance(e, ModelNotRoutableError):
                sm.transition(CognitiveState.ABSTAINED)
                trace_builder.record_transition(sm.history[-1])
                trace_builder.record_abstention(AbstentionReason.MODEL_UNAVAILABLE)
                metrics.record_abstention(AbstentionReason.MODEL_UNAVAILABLE.value)
                trace_builder.finalize(plan.budget)
                latency_ms = (time.monotonic() - start) * 1000
                metrics.record_total_latency(latency_ms)
                return CognitiveResult(
                    request_id=request.request_id, trace_id=request.trace_id, status=CognitiveState.ABSTAINED,
                    plan_id=plan.plan_id, abstention_reason=AbstentionReason.MODEL_UNAVAILABLE, latency_ms=latency_ms,
                )
            sm.transition(CognitiveState.FAILED)
            trace_builder.record_transition(sm.history[-1])
            trace_builder.finalize(plan.budget)
            raise CognitiveExecutionFailedError(internal_detail=str(e)) from e

        metrics.record_model_resolution(resolved_model)
        trace_builder.record_model_resolved(resolved_model)
        trace_builder.record_operation_outcome("answered_directly")

        sm.transition(CognitiveState.COMPLETED)
        trace_builder.record_transition(sm.history[-1])
        trace_builder.finalize(plan.budget)

        latency_ms = (time.monotonic() - start) * 1000
        metrics.record_total_latency(latency_ms)
        return CognitiveResult(
            request_id=request.request_id, trace_id=request.trace_id, status=CognitiveState.COMPLETED,
            output=output_text, resolved_model=resolved_model, resolved_tier=resolved_tier, plan_id=plan.plan_id,
            operations_executed=[op.type for op in executable_ops], latency_ms=latency_ms,
            usage=usage, warnings=warnings,
            degraded=degraded, degradation_reason=degradation_reason, user_notification_required=notification_required,
        )

    async def _answer_directly(self, objective: str, tier: str, trace_id: str) -> tuple[str, str, dict]:
        """The one place the Kernel actually reaches ModelGateway --
        exactly the canonical path Phase 3 spec §27 requires (Kernel ->
        model policy -> ModelGateway -> deployment/runtime), reusing the
        EXISTING tier router (orca/serve/registry.py) and wiring bridge
        (orca/gateway/wiring.py) unchanged, per Phase 2.1's own cutover."""
        import uuid

        from orca.gateway.contracts import InferenceRequest
        from orca.gateway.wiring import brain_for_tier_resolution
        from orca.serve.registry import resolve_tier_backend

        resolution = resolve_tier_backend(tier)
        gateway_brain = brain_for_tier_resolution(resolution, gateway=self._gateway())
        inference_request = InferenceRequest(
            request_id=str(uuid.uuid4()), trace_id=trace_id,
            model_id=gateway_brain.model_id, model_version=gateway_brain.model_version,
            messages=[{"role": "user", "content": objective}], max_tokens=1024,
        )
        response = await self._gateway().generate(inference_request, allow_experimental=gateway_brain.allow_experimental)
        usage = {
            "prompt_tokens": response.prompt_tokens, "completion_tokens": response.completion_tokens,
            "total_tokens": (response.prompt_tokens or 0) + (response.completion_tokens or 0),
        }
        return response.output, response.resolved_version, usage

    async def _answer_with_truth_fabric(
        self, request: CognitiveRequest, plan, resolved_tier: str, doc_store, sm, trace_builder, start: float,
        degraded: bool, degradation_reason, notification_required: bool,
    ) -> CognitiveResult:
        """
        Phase 4: a plan needing only RETRIEVE/SEARCH/VERIFY (no
        USE_TOOL/DELEGATE_AGENT) is answered end-to-end through
        orca.truth.truth_fabric.TruthFabric -- assess evidence, answer via
        ModelGateway using the retrieved context, then verify the answer's
        own claims against that evidence. For AUDIT_GRADE evidence
        requirements specifically, a failed verification (insufficient/
        conflicted/low-authority evidence AFTER checking, not merely
        assumed) means an honest abstention (spec §36), never a fabricated
        "verified" answer.
        """
        from orca.gateway.errors import ModelNotRoutableError
        from orca.truth.contracts import CounterEvidenceStatus, EvidenceState, TruthRequest
        from orca.truth.errors import TruthBudgetExhaustedError, TruthError
        from orca.truth.truth_fabric import TruthFabric

        def _abstain(reason: AbstentionReason, plan_id: str) -> CognitiveResult:
            sm.transition(CognitiveState.ABSTAINED)
            trace_builder.record_transition(sm.history[-1])
            trace_builder.record_abstention(reason)
            metrics.record_abstention(reason.value)
            if reason == AbstentionReason.BUDGET_EXHAUSTED:
                metrics.record_budget_exhaustion()
            trace_builder.finalize(plan.budget)
            latency_ms = (time.monotonic() - start) * 1000
            metrics.record_total_latency(latency_ms)
            return CognitiveResult(
                request_id=request.request_id, trace_id=request.trace_id, status=CognitiveState.ABSTAINED,
                plan_id=plan_id, abstention_reason=reason, latency_ms=latency_ms,
            )

        truth_fabric = TruthFabric()
        truth_request = TruthRequest(
            objective=request.objective, evidence_requirement=plan.evidence_requirement.level,
            freshness_requirement=plan.freshness.level, trace_id=request.trace_id,
        )
        strict_or_higher = plan.evidence_requirement.level.value in ("STRICT", "AUDIT_GRADE")

        try:
            assessed = await truth_fabric.assess_evidence(
                truth_request, plan.intent, plan.complexity.level, doc_store=doc_store, budget=plan.budget,
            )
            if strict_or_higher and assessed.evidence_state in (EvidenceState.INSUFFICIENT, EvidenceState.CONFLICTED, EvidenceState.LOW_AUTHORITY):
                return _abstain(AbstentionReason.INSUFFICIENT_EVIDENCE, plan.plan_id)

            consume(plan.budget, BudgetDimension.MODEL_CALLS, 1)
            objective_with_context = (
                f"{request.objective}\n\n[Retrieved context]\n{assessed.context_block}" if assessed.context_block else request.objective
            )
            output_text, resolved_model, usage = await self._answer_directly(objective_with_context, resolved_tier, request.trace_id)

            is_audit_grade = plan.evidence_requirement.level.value == "AUDIT_GRADE"
            final = await truth_fabric.verify_answer(output_text, assessed, budget=plan.budget, run_counter_evidence=is_audit_grade)
            # Phase 4.1 spec §23: AUDIT_GRADE success requires ALL of --
            # EvidenceState=SUFFICIENT (itself already folding in citation
            # coverage >=0.8, no unresolved DIRECT_CONTRADICTION, required
            # source authority, and required freshness -- see
            # orca/truth/state.py::compute_evidence_state), PLUS a
            # counter-evidence attempt actually having been made (never
            # silently skipped for AUDIT_GRADE -- spec §17/§23).
            if is_audit_grade:
                counter_evidence_ran = final.counter_evidence is not None and final.counter_evidence.status == CounterEvidenceStatus.RAN
                if final.evidence_state != EvidenceState.SUFFICIENT or not counter_evidence_ran:
                    return _abstain(AbstentionReason.INSUFFICIENT_EVIDENCE, plan.plan_id)
        except CognitiveBudgetExhaustedError:
            return _abstain(AbstentionReason.BUDGET_EXHAUSTED, plan.plan_id)
        except TruthBudgetExhaustedError:
            return _abstain(AbstentionReason.BUDGET_EXHAUSTED, plan.plan_id)
        except ModelNotRoutableError:
            return _abstain(AbstentionReason.MODEL_UNAVAILABLE, plan.plan_id)
        except TruthError as e:
            sm.transition(CognitiveState.FAILED)
            trace_builder.record_transition(sm.history[-1])
            trace_builder.finalize(plan.budget)
            raise CognitiveExecutionFailedError(internal_detail=str(e)) from e

        metrics.record_model_resolution(resolved_model)
        trace_builder.record_model_resolved(resolved_model)
        trace_builder.record_operation_outcome(f"answered_via_truth_fabric:{final.evidence_state.value}")

        sm.transition(CognitiveState.COMPLETED)
        trace_builder.record_transition(sm.history[-1])
        trace_builder.finalize(plan.budget)

        latency_ms = (time.monotonic() - start) * 1000
        metrics.record_total_latency(latency_ms)
        return CognitiveResult(
            request_id=request.request_id, trace_id=request.trace_id, status=CognitiveState.COMPLETED,
            output=output_text, resolved_model=resolved_model, resolved_tier=resolved_tier, plan_id=plan.plan_id,
            operations_executed=[op.type for op in plan.operations if op.type in _TRUTH_FABRIC_OPS],
            latency_ms=latency_ms, usage=usage,
            evidence_state=final.evidence_state.value, citation_coverage=final.citation_coverage,
            degraded=degraded, degradation_reason=degradation_reason, user_notification_required=notification_required,
        )
