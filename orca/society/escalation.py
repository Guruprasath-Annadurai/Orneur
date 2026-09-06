"""
Escalation engine (Phase 7 spec §21-23). Escalation/de-escalation resolve
to a CAPABILITY REQUIREMENT ("DEEP_REASONING", "BALANCED_VERIFICATION"),
never a hardcoded future model name (spec §22) -- if no eligible model
satisfies the requirement, the caller must abstain/degrade honestly, never
fabricate Aeternum.
"""
from __future__ import annotations

from orca.cognitive.contracts import RiskLevel
from orca.society.contracts import DisagreementSignal, EscalationAction, EscalationDecision

# Named capability tiers a decision resolves TO -- consumed by
# orca.society.router's RoleRequirement machinery via the caller, never a
# model_id or checkpoint_id.
FAST = "FAST"
BALANCED = "BALANCED"
BALANCED_VERIFICATION = "BALANCED_VERIFICATION"
DEEP_REASONING = "DEEP_REASONING"

_ESCALATION_ORDER = [FAST, BALANCED, BALANCED_VERIFICATION, DEEP_REASONING]


def decide_escalation(
    *,
    current_tier: str,
    disagreement: DisagreementSignal | None = None,
    risk_level: RiskLevel = RiskLevel.LOW,
    critical_contradiction: bool = False,
    falsifier_objection_unresolved: bool = False,
    calibration_inadequate: bool = False,
    role_model_unavailable: bool = False,
    evidence_insufficient: bool = False,
) -> EscalationDecision:
    """
    Escalates on real structured signals only -- never "the answer is
    long" (spec §21's explicit non-example). Each signal is independent
    and auditable via `reasons`.
    """
    reasons: list[str] = []

    if role_model_unavailable:
        reasons.append("required role model unavailable")
        return EscalationDecision(action=EscalationAction.ABSTAIN_NO_CAPABLE_MODEL, reasons=reasons)

    should_escalate = False
    if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
        reasons.append(f"risk={risk_level.value}")
        should_escalate = True
    if critical_contradiction:
        reasons.append("critical contradiction")
        should_escalate = True
    if falsifier_objection_unresolved:
        reasons.append("unresolved falsifier objection")
        should_escalate = True
    if calibration_inadequate:
        reasons.append("model calibration/confidence inadequate")
        should_escalate = True
    if evidence_insufficient:
        reasons.append("evidence insufficient")
        should_escalate = True
    if disagreement is not None and disagreement.severity in ("MODERATE", "HIGH"):
        reasons.append(f"disagreement severity={disagreement.severity}")
        should_escalate = True

    if should_escalate:
        idx = _ESCALATION_ORDER.index(current_tier) if current_tier in _ESCALATION_ORDER else 0
        target = _ESCALATION_ORDER[min(idx + 1, len(_ESCALATION_ORDER) - 1)]
        return EscalationDecision(action=EscalationAction.ESCALATE, target_requirement=target, reasons=reasons)

    # De-escalation (spec §23): only when there is genuinely no signal
    # requiring extra capability -- never "just in case" downgrading of an
    # already-minimal tier.
    if current_tier != FAST and risk_level == RiskLevel.LOW and (disagreement is None or not disagreement.has_meaningful_disagreement):
        reasons.append("no risk/disagreement/evidence signal requires current tier -- cheaper sufficient candidate preferred")
        idx = _ESCALATION_ORDER.index(current_tier) if current_tier in _ESCALATION_ORDER else 0
        target = _ESCALATION_ORDER[max(idx - 1, 0)]
        return EscalationDecision(action=EscalationAction.DE_ESCALATE, target_requirement=target, reasons=reasons)

    reasons.append("no escalation or de-escalation signal")
    return EscalationDecision(action=EscalationAction.NONE, target_requirement=current_tier, reasons=reasons)
