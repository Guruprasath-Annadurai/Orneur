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
from orca.cognitive.errors import CognitiveExecutionFailedError, PlanInvalidError
from orca.cognitive.evidence import assess_evidence_requirement
from orca.cognitive.freshness import assess_freshness
from orca.cognitive.intent import compile_intent
from orca.cognitive.planner import build_plan, plan_abstention_reason
from orca.cognitive.policy import characteristic_to_tier, select_model_policy
from orca.cognitive.risk import assess_risk
from orca.cognitive.state_machine import CognitiveStateMachine
from orca.cognitive.trace import CognitiveTraceBuilder

# Operations Kernel.execute() can genuinely satisfy on its own in Phase 3
# -- see module docstring. Any plan requiring something outside this set
# is real (not an error), just not something THIS method executes.
_KERNEL_EXECUTABLE_OPS = {OperationType.ANSWER_DIRECTLY, OperationType.REASON, OperationType.RECALL_MEMORY}


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

    async def execute(self, request: CognitiveRequest) -> CognitiveResult:
        """
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
        non_kernel_ops = [op for op in plan.operations if op.type not in _KERNEL_EXECUTABLE_OPS]

        sm.transition(CognitiveState.EXECUTING)
        trace_builder.record_transition(sm.history[-1])

        if non_kernel_ops:
            # Real, valid plan -- but satisfying RETRIEVE/USE_TOOL/
            # DELEGATE_AGENT is the existing serving stack's job in Phase
            # 3, not this method's (see module docstring / CUTOVER.md).
            # The plan itself is still useful output for the caller.
            sm.transition(CognitiveState.COMPLETED)
            trace_builder.record_transition(sm.history[-1])
            trace_builder.record_operation_outcome("deferred_to_existing_serving_stack")
            trace_builder.finalize(plan.budget)
            latency_ms = (time.monotonic() - start) * 1000
            metrics.record_total_latency(latency_ms)
            return CognitiveResult(
                request_id=request.request_id, trace_id=request.trace_id, status=CognitiveState.COMPLETED,
                plan_id=plan.plan_id, operations_executed=[], latency_ms=latency_ms,
                warnings=[f"plan requires {op.type.value} -- executed by the existing serving stack, not the Kernel" for op in non_kernel_ops],
            )

        warnings: list[str] = []
        try:
            # Hard-stop check BEFORE spending anything -- a model call is
            # about to happen, so MODEL_CALLS is enforced pre-flight.
            consume(plan.budget, BudgetDimension.MODEL_CALLS, 1)
            tier = characteristic_to_tier(plan.model_policy.characteristic)
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
            output=output_text, resolved_model=resolved_model, plan_id=plan.plan_id,
            operations_executed=[op.type for op in executable_ops], latency_ms=latency_ms,
            usage=usage, warnings=warnings,
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
