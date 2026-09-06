"""
EntitlementPolicy wraps the EXISTING orca/auth/store.py billing rules
(model_access_allowed/DAILY_LIMITS) rather than reimplementing them (Phase
3.1 spec §4). Reconciliation between Kernel-desired policy and entitlement
must be structurally incapable of granting more than the entitlement
ceiling (Phase 3.1 spec §5-7).
"""
from __future__ import annotations

from orca.auth.store import User
from orca.cognitive.contracts import ModelPolicy, ModelPolicyCharacteristic
from orca.cognitive.entitlement import CapabilityClass, class_rank, derive_entitlement_policy
from orca.cognitive.reconciliation import ReconciliationOutcome, reconcile_policy


def _user(tier: str, signup_seq: int | None = None) -> User:
    return User(id="u", email="u@x.com", name="U", tier=tier, verified=True, signup_seq=signup_seq)


def test_anonymous_gets_only_basic():
    policy = derive_entitlement_policy(None)
    assert policy.allowed_model_classes == {CapabilityClass.BASIC}
    assert not policy.deep_access


def test_free_tier_gets_only_basic():
    policy = derive_entitlement_policy(_user("free"))
    assert policy.allowed_model_classes == {CapabilityClass.BASIC}


def test_early_cohort_free_user_gets_standard_too():
    """Mirrors model_access_allowed's first-100-signup exception exactly
    -- this module must not reimplement or diverge from it."""
    policy = derive_entitlement_policy(_user("free", signup_seq=42))
    assert CapabilityClass.STANDARD in policy.allowed_model_classes
    assert CapabilityClass.ADVANCED not in policy.allowed_model_classes


def test_pro_tier_gets_everything():
    policy = derive_entitlement_policy(_user("pro"))
    assert policy.allowed_model_classes == {CapabilityClass.BASIC, CapabilityClass.STANDARD, CapabilityClass.ADVANCED}
    assert policy.deep_access
    assert policy.maximum_quality_class == CapabilityClass.ADVANCED


def test_enterprise_tier_gets_everything():
    policy = derive_entitlement_policy(_user("enterprise"))
    assert policy.deep_access


def test_quota_limit_reflects_tier():
    free_policy = derive_entitlement_policy(_user("free"))
    pro_policy = derive_entitlement_policy(_user("pro"))
    assert free_policy.message_quota_limit == 50
    assert pro_policy.message_quota_limit == -1
    assert not pro_policy.quota_exhausted()


def test_capability_class_rank_is_monotonic():
    assert class_rank(CapabilityClass.BASIC) < class_rank(CapabilityClass.STANDARD) < class_rank(CapabilityClass.ADVANCED)


# ── Reconciliation ───────────────────────────────────────────────────────

def test_granted_when_desired_within_entitlement():
    entitlement = derive_entitlement_policy(_user("pro"))
    policy = ModelPolicy(characteristic=ModelPolicyCharacteristic.DEEP, reasons=[])
    effective = reconcile_policy(policy, entitlement)
    assert effective.outcome == ReconciliationOutcome.GRANTED
    assert not effective.degraded
    assert effective.resolved_tier == "ultra"


def test_downgraded_never_exceeds_entitlement_ceiling():
    entitlement = derive_entitlement_policy(_user("free"))
    policy = ModelPolicy(characteristic=ModelPolicyCharacteristic.DEEP, reasons=[])
    effective = reconcile_policy(policy, entitlement)
    assert effective.outcome == ReconciliationOutcome.DOWNGRADED
    assert effective.degraded
    assert effective.resolved_tier == "nano"
    assert effective.user_notification_required


def test_reconciliation_never_grants_above_ceiling_property(monkeypatch):
    """Property-style check across every (characteristic, tier) combination
    -- the resolved class rank must never exceed the entitlement ceiling's
    rank, for any Kernel-desired characteristic."""
    from orca.cognitive.entitlement import tier_to_class
    for tier_str in ("free", "pro", "enterprise"):
        entitlement = derive_entitlement_policy(_user(tier_str))
        for characteristic in ModelPolicyCharacteristic:
            policy = ModelPolicy(characteristic=characteristic, reasons=[])
            effective = reconcile_policy(policy, entitlement)
            resolved_class = tier_to_class(effective.resolved_tier)
            assert class_rank(resolved_class) <= class_rank(entitlement.maximum_quality_class)


def test_explicit_tier_request_exceeding_entitlement_is_entitlement_required():
    entitlement = derive_entitlement_policy(_user("free"))
    policy = ModelPolicy(characteristic=ModelPolicyCharacteristic.FAST, reasons=[])
    effective = reconcile_policy(policy, entitlement, explicit_tier_request="ultra")
    assert effective.outcome == ReconciliationOutcome.ENTITLEMENT_REQUIRED
    assert effective.user_notification_required


def test_desired_below_ceiling_is_granted_not_upgraded():
    """A trivial FAST request from a pro user must not be force-upgraded
    to ultra just because they're entitled to it -- entitlement is a
    ceiling, not a floor."""
    entitlement = derive_entitlement_policy(_user("pro"))
    policy = ModelPolicy(characteristic=ModelPolicyCharacteristic.FAST, reasons=[])
    effective = reconcile_policy(policy, entitlement)
    assert effective.outcome == ReconciliationOutcome.GRANTED
    assert effective.resolved_tier == "nano"
