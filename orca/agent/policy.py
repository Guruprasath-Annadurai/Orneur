"""
Policy Engine (Phase 8 spec §12). The ONLY thing that may authorize
execution -- never a model, never Court ACCEPT, never Society routing,
never Memory (spec §2, §38). Fully deterministic; no model call, no
learned classifier.
"""
from __future__ import annotations

from orca.agent.contracts import (
    ActionRiskLevel,
    AgentGoal,
    Capability,
    CapabilityDecision,
    PolicyDecision,
    PolicyDecisionState,
    SideEffectClass,
    ToolSpec,
)

# Side-effect classes that always require explicit human approval,
# regardless of goal/capabilities -- spec §28/§40: never fake approval
# from a model, Court, memory, or retrieved content.
_ALWAYS_REQUIRE_APPROVAL = {SideEffectClass.DESTRUCTIVE}


def evaluate_policy(
    *,
    goal: AgentGoal,
    tool_spec: ToolSpec,
    capability_decision: CapabilityDecision,
    resolved_side_effect_class: SideEffectClass | None = None,
) -> PolicyDecision:
    """
    `resolved_side_effect_class`, when given, is the ACTUAL side-effect
    class the resolved tool operation turned out to be (spec §40's risk-
    escalation case: a plan expected READ_ONLY but the resolved operation
    is a write) -- checked in addition to, never instead of, the tool
    spec's own declared class. Defaults to `tool_spec.side_effect_class`
    when not given.
    """
    reasons: list[str] = []

    if not capability_decision.granted:
        reasons.append(f"capability check failed: {', '.join(m.value for m in capability_decision.missing)}")
        return PolicyDecision(state=PolicyDecisionState.DENY, reasons=reasons)

    effective_class = resolved_side_effect_class or tool_spec.side_effect_class

    if resolved_side_effect_class is not None and resolved_side_effect_class != tool_spec.side_effect_class:
        # Risk escalated at runtime (spec §40) -- never silently execute
        # under the OLD, lower-risk approval; re-evaluate against the
        # NEW, actual class from here on.
        reasons.append(
            f"resolved side-effect class ({resolved_side_effect_class.value}) differs from planned "
            f"({tool_spec.side_effect_class.value}) -- re-evaluating under the resolved class"
        )

    if effective_class in _ALWAYS_REQUIRE_APPROVAL:
        reasons.append(f"{effective_class.value} always requires human approval")
        return PolicyDecision(state=PolicyDecisionState.REQUIRE_APPROVAL, reasons=reasons)

    if effective_class not in goal.allowed_action_classes:
        reasons.append(f"goal does not permit {effective_class.value} actions (allowed: {sorted(c.value for c in goal.allowed_action_classes)})")
        if effective_class in (SideEffectClass.IRREVERSIBLE_WRITE, SideEffectClass.EXTERNAL_SIDE_EFFECT):
            return PolicyDecision(state=PolicyDecisionState.REQUIRE_APPROVAL, reasons=reasons)
        return PolicyDecision(state=PolicyDecisionState.DENY, reasons=reasons)

    if tool_spec.risk_class in (ActionRiskLevel.HIGH, ActionRiskLevel.CRITICAL) and goal.risk not in (ActionRiskLevel.HIGH, ActionRiskLevel.CRITICAL):
        reasons.append(f"tool risk_class={tool_spec.risk_class.value} exceeds goal's declared risk={goal.risk.value}")
        return PolicyDecision(state=PolicyDecisionState.REQUIRE_APPROVAL, reasons=reasons)

    reasons.append(f"{effective_class.value} permitted by goal, capability present, risk acceptable")
    return PolicyDecision(state=PolicyDecisionState.ALLOW, reasons=reasons)
