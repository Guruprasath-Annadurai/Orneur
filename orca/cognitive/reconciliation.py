"""
Policy reconciliation -- the explicit boundary between what the Cognitive
Kernel WANTS (ModelPolicy, a cognitive quality judgment) and what the
caller is COMMERCIALLY ENTITLED to use (EntitlementPolicy). Neither system
may silently bypass the other (Phase 3.1 spec §1).

The critical invariant, enforced structurally rather than by convention:
reconcile_policy() can only ever return a resolved capability class whose
rank is <= min(desired_class_rank, entitlement_ceiling_rank). It is
mechanically impossible for this function to grant more than the caller's
entitlement ceiling, regardless of what the Kernel requested -- there is
no code path here that ever raises the resolved class above that ceiling.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from orca.cognitive.contracts import ModelPolicy, ModelPolicyCharacteristic
from orca.cognitive.entitlement import CapabilityClass, EntitlementPolicy, class_rank, class_to_tier, tier_to_class
from orca.cognitive.policy import characteristic_to_tier


class ReconciliationOutcome(str, Enum):
    GRANTED = "GRANTED"                          # desired capability was within entitlement -- no degradation
    DOWNGRADED = "DOWNGRADED"                     # case A: best permitted policy selected
    ENTITLEMENT_REQUIRED = "ENTITLEMENT_REQUIRED"  # case B: caller's own explicit request exceeds entitlement
    ABSTAINED = "ABSTAINED"                       # case C: no permitted capability can safely approximate the plan


@dataclass
class EffectiveExecutionPolicy:
    desired_characteristic: ModelPolicyCharacteristic
    desired_tier: str
    permitted_ceiling: CapabilityClass
    resolved_tier: str
    resolved_characteristic: ModelPolicyCharacteristic
    degraded: bool
    outcome: ReconciliationOutcome
    reason: str
    user_notification_required: bool = field(default=False)


# The tier a resolved CapabilityClass maps back to also needs a
# representative ModelPolicyCharacteristic for observability/trace
# purposes -- BALANCED is the documented "no stronger signal" default
# characteristic (see policy.py), reused here rather than inventing a
# second mapping table.
_CLASS_TO_CHARACTERISTIC: dict[CapabilityClass, ModelPolicyCharacteristic] = {
    CapabilityClass.BASIC: ModelPolicyCharacteristic.FAST,
    CapabilityClass.STANDARD: ModelPolicyCharacteristic.BALANCED,
    CapabilityClass.ADVANCED: ModelPolicyCharacteristic.DEEP,
}


def reconcile_policy(
    model_policy: ModelPolicy,
    entitlement: EntitlementPolicy,
    explicit_tier_request: str | None = None,
) -> EffectiveExecutionPolicy:
    """
    `explicit_tier_request` is the caller's OWN tier selection (e.g.
    req.model_variant), if any -- distinct from what the Kernel's
    cognitive judgment wants. Phase 3.1's own entitlement gate
    (orca/serve/api.py, unchanged, calling model_access_allowed directly)
    already rejects an explicit request that exceeds entitlement with the
    existing 402/upgrade-message behavior BEFORE this function is ever
    called -- so by the time reconcile_policy() runs, an explicit request
    has already cleared entitlement. This function's ENTITLEMENT_REQUIRED
    outcome exists for direct/unit-tested use of the reconciliation
    contract itself (Phase 3.1 spec §6's outcome B), not because the real
    HTTP path routes through it a second time for the same check.
    """
    desired_tier = characteristic_to_tier(model_policy.characteristic)
    desired_class = tier_to_class(desired_tier)
    ceiling = entitlement.maximum_quality_class

    if explicit_tier_request:
        requested_class = tier_to_class(explicit_tier_request.removeprefix("orca-"))
        if not entitlement.permits(requested_class):
            return EffectiveExecutionPolicy(
                desired_characteristic=model_policy.characteristic, desired_tier=desired_tier,
                permitted_ceiling=ceiling, resolved_tier=explicit_tier_request, resolved_characteristic=model_policy.characteristic,
                degraded=True, outcome=ReconciliationOutcome.ENTITLEMENT_REQUIRED,
                reason=f"explicit tier '{explicit_tier_request}' exceeds entitlement ceiling '{ceiling.value}'",
                user_notification_required=True,
            )

    if entitlement.permits(desired_class):
        return EffectiveExecutionPolicy(
            desired_characteristic=model_policy.characteristic, desired_tier=desired_tier,
            permitted_ceiling=ceiling, resolved_tier=desired_tier, resolved_characteristic=model_policy.characteristic,
            degraded=False, outcome=ReconciliationOutcome.GRANTED,
            reason="desired cognitive policy is within entitlement",
        )

    # Desired capability exceeds what this caller is entitled to -- select
    # the best PERMITTED policy (case A). Never raises resolved rank above
    # the ceiling; structurally the only branch left once the "permits"
    # check above fails.
    resolved_tier = class_to_tier(ceiling)
    return EffectiveExecutionPolicy(
        desired_characteristic=model_policy.characteristic, desired_tier=desired_tier,
        permitted_ceiling=ceiling, resolved_tier=resolved_tier, resolved_characteristic=_CLASS_TO_CHARACTERISTIC[ceiling],
        degraded=True, outcome=ReconciliationOutcome.DOWNGRADED,
        reason=f"desired '{model_policy.characteristic.value}' (tier '{desired_tier}') exceeds entitlement ceiling "
               f"'{ceiling.value}' (tier '{resolved_tier}') -- downgraded to the highest permitted policy",
        user_notification_required=True,
    )
