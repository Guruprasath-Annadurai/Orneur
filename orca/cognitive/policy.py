"""
Model policy resolution -- translates a cognitive ModelPolicyCharacteristic
into the EXISTING tier the pre-existing router (orca/serve/registry.py)
already knows how to resolve, rather than naming a model directly (Phase 3
spec §19). Deliberately does NOT hard-code "HIGH -> Aeternum": Aeternum
does not exist, and the existing step-down chain (ultra -> core -> nano,
untouched by this phase) already degrades gracefully when a tier's model
isn't installed. This module only picks a *starting* tier; actual
eligibility/availability is the registry's job, exactly as it is today for
every other caller.
"""
from __future__ import annotations

from orca.cognitive.contracts import ComplexityAssessment, ComplexityLevel, IntentCategory, IntentPlan, ModelPolicy, ModelPolicyCharacteristic

# Documented, deterministic mapping -- a policy decision in its own right,
# kept in one place so it's auditable rather than scattered.
_CHARACTERISTIC_TO_TIER: dict[ModelPolicyCharacteristic, str] = {
    ModelPolicyCharacteristic.FAST: "nano",
    ModelPolicyCharacteristic.BALANCED: "core",
    ModelPolicyCharacteristic.DEEP: "ultra",
    ModelPolicyCharacteristic.CODE: "core",
    ModelPolicyCharacteristic.REASONING: "ultra",
    ModelPolicyCharacteristic.VERIFICATION: "core",
}


def characteristic_to_tier(characteristic: ModelPolicyCharacteristic) -> str:
    """The one place a ModelPolicyCharacteristic becomes a tier name --
    orca/serve/registry.py's resolve_tier_backend/resolve_tier_model take
    it from here, unchanged."""
    return _CHARACTERISTIC_TO_TIER[characteristic]


def select_model_policy(intent: IntentPlan, complexity: ComplexityAssessment) -> ModelPolicy:
    """
    Deterministic selection from intent + complexity alone -- no risk
    input here, since model *capability* characteristics (fast/deep/code)
    are orthogonal to consequence risk (Phase 3 spec §37: risk is not
    authorization, and it's also not a model-selection signal on its own).
    """
    reasons: list[str] = []

    if intent.primary_intent == IntentCategory.CODING:
        reasons.append("primary_intent=CODING")
        return ModelPolicy(characteristic=ModelPolicyCharacteristic.CODE, reasons=reasons)

    if complexity.level in (ComplexityLevel.HIGH, ComplexityLevel.DEEP) or intent.requires_agents:
        reasons.append(f"complexity={complexity.level.value}" if complexity.level in (ComplexityLevel.HIGH, ComplexityLevel.DEEP) else "requires_agents")
        return ModelPolicy(characteristic=ModelPolicyCharacteristic.DEEP, reasons=reasons)

    if intent.requires_reasoning:
        reasons.append("requires_reasoning")
        return ModelPolicy(characteristic=ModelPolicyCharacteristic.REASONING, reasons=reasons)

    if complexity.level == ComplexityLevel.TRIVIAL and not intent.requires_tools:
        reasons.append("complexity=TRIVIAL, no tools required")
        return ModelPolicy(characteristic=ModelPolicyCharacteristic.FAST, reasons=reasons)

    reasons.append("default: no stronger signal than a normal balanced request")
    return ModelPolicy(characteristic=ModelPolicyCharacteristic.BALANCED, reasons=reasons)
