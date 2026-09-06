# Policy Reconciliation

`orca/cognitive/entitlement.py` (EntitlementPolicy) + `orca/cognitive/reconciliation.py` (reconcile_policy). The explicit boundary between what the Cognitive Kernel WANTS (a cognitive quality judgment) and what the caller is COMMERCIALLY ENTITLED to use.

## `EntitlementPolicy` — wraps, never reimplements, existing billing rules

```python
class CapabilityClass(str, Enum):
    BASIC = "BASIC"        # today: nano / Genesis-equivalent
    STANDARD = "STANDARD"  # today: core / Novus-equivalent
    ADVANCED = "ADVANCED"  # today: ultra / Aeternum-equivalent
```

`derive_entitlement_policy(user, requested_tier)` calls the **existing**, unchanged `orca/auth/store.py::model_access_allowed()` once per capability class to build `allowed_model_classes` — it never re-derives free/pro/enterprise rules itself. `DAILY_LIMITS` (also existing, unchanged) supplies the quota ceiling. This is why `CapabilityClass` intentionally does NOT reuse the raw `"nano"/"core"/"ultra"` strings directly in comparisons — Phase 3.1 spec §7 explicitly forbids `if tier == "core": paid = True`-style coupling; callers reason about capability class, and only `tier_to_class()`/`class_to_tier()` (one small, auditable table) ever touch the legacy strings.

## `reconcile_policy` — the structural guarantee

```
resolved capability rank <= min(desired capability rank, entitlement ceiling rank)
```

This is not a convention the code happens to follow — it's mechanically true by construction: the function has exactly three branches (`ENTITLEMENT_REQUIRED`, `GRANTED`, `DOWNGRADED`), and none of them can produce a resolved class above the ceiling:

- **`GRANTED`** — the Kernel's desired capability is already within the entitlement ceiling. Resolved = desired. No degradation.
- **`DOWNGRADED`** (case A from the phase spec) — desired exceeds the ceiling. Resolved = the ceiling's own tier. This is the only branch that changes what the Kernel wanted, and it can only ever move DOWN.
- **`ENTITLEMENT_REQUIRED`** (case B) — used when a caller's own EXPLICIT tier selection (not the Kernel's judgment) exceeds their entitlement. In production wiring, this case is pre-empted by the existing `model_access_allowed()` 402 gate running before the Kernel is ever invoked (see `PRODUCTION_CUTOVER.md`) — it's exercised directly by `tests/test_cognitive_entitlement.py` to prove the contract itself is correct, independent of how production happens to wire it today.
- **`ABSTAINED`** (case C) — reserved for a future case where no permitted capability can safely approximate a plan at all. Never actually reached in Phase 3.1 (BASIC is always free per `model_access_allowed`'s own documented rule, so there's always a safe fallback) — the branch and its `AbstentionReason.POLICY_RESTRICTION` mapping exist and are tested (`kernel.py`'s `execute()` handles it), so a later phase that introduces a genuinely un-approximable case doesn't need to touch this contract.

Proven by property-style test (`test_reconciliation_never_grants_above_ceiling_property`): for every tier × every `ModelPolicyCharacteristic`, the resolved class never exceeds the entitlement ceiling.

## The user's own explicit tier selection is an ADDITIONAL ceiling

A pro user who explicitly picks the cheap "nano" tier for a conversation must not have some individual message silently answered via "ultra" just because the Kernel judged it complex and their overall plan permits ultra. `orca/serve/api.py::_run_cognitive_kernel` narrows the derived `EntitlementPolicy.maximum_quality_class` to `min(overall entitlement ceiling, requested tier's class)` before calling `kernel.execute()` — entitlement caps what's *possible*; the user's own selection caps what's *used* for this call. Tested: `test_entitlement_never_upgrades_kernel_choice`.

## Entitlement never influences the Kernel's own judgment

`CognitiveKernel.plan()` takes only a `CognitiveRequest` — it has no parameter for entitlement and never imports `orca.cognitive.entitlement`. Reconciliation happens strictly AFTER planning, inside `execute()`, as a separate, explicit step (`reconcile_policy(plan.model_policy, entitlement)`). This is what makes "cognitive quality policy and commercial entitlement policy are separate" (spec §1) true structurally, not just by convention — there is no code path by which entitlement data can leak into intent/complexity/risk/freshness/evidence classification.

## `EffectiveExecutionPolicy` — what gets recorded and returned

```python
EffectiveExecutionPolicy(
    desired_characteristic, desired_tier,      # what the Kernel wanted
    permitted_ceiling,                          # entitlement's ceiling
    resolved_tier, resolved_characteristic,     # what actually gets used
    degraded: bool, outcome: ReconciliationOutcome,
    reason: str, user_notification_required: bool,
)
```

Never hidden: `CognitiveResult.degraded`/`.degradation_reason`/`.user_notification_required` surface this to `orca/serve/api.py`'s response (both `/api/chat`'s JSON body and `/api/stream`'s `done` SSE event carry `degraded`/`degradation_reason`). `CognitiveTrace.entitlement_ceiling`/`.effective_capability`/`.reconciliation_outcome`/`.resolved_tier` carry it into observability (labels only, never raw prompts or user IDs).
