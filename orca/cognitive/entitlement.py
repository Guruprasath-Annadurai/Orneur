"""
Entitlement policy -- commercial/subscription constraint, kept explicitly
separate from Cognitive Kernel model policy (Phase 3.1 spec §1, §4-5, §7).

This module does NOT reimplement billing rules. It wraps the EXISTING,
already-tested billing abstraction (orca/auth/store.py's
model_access_allowed/DAILY_LIMITS) into a stable, capability-class-based
shape, so entitlement stays authoritative and deterministic while giving
the Kernel's reconciliation step (policy.py's reconcile_policy) something
typed to reconcile against. Auth/authorization logic in orca/auth/store.py
remains the single source of truth for what a user is allowed to buy --
this module never re-derives or second-guesses it.

No model-tier string coupling: CapabilityClass is a stable, three-level
ordering (BASIC < STANDARD < ADVANCED) that today happens to line up with
nano/core/ultra, but callers reason about capability CLASS, never the
legacy tier string directly -- so Genesis/Novus/Aeternum's roles evolving
does not require touching entitlement code (Phase 3.1 spec §7).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from orca.auth.store import DAILY_LIMITS, User, model_access_allowed


class CapabilityClass(str, Enum):
    BASIC = "BASIC"        # today: nano / Genesis-equivalent
    STANDARD = "STANDARD"  # today: core / Novus-equivalent
    ADVANCED = "ADVANCED"  # today: ultra / Aeternum-equivalent


# Ordering, most-restrictive-first -- the only place a CapabilityClass is
# compared numerically. Kept as one explicit table so the ordering is
# auditable, not scattered as ad-hoc comparisons.
_CLASS_RANK: dict[CapabilityClass, int] = {
    CapabilityClass.BASIC: 0,
    CapabilityClass.STANDARD: 1,
    CapabilityClass.ADVANCED: 2,
}

# The one place a legacy Orca tier string maps to a CapabilityClass --
# reused by both directions (tier -> class for checking entitlement, class
# -> tier for resolving what to actually request from the existing
# router). Kept intentionally symmetric with
# orca/cognitive/policy.py::characteristic_to_tier's own tier vocabulary.
_TIER_TO_CLASS: dict[str, CapabilityClass] = {
    "nano": CapabilityClass.BASIC,
    "core": CapabilityClass.STANDARD,
    "ultra": CapabilityClass.ADVANCED,
}
_CLASS_TO_TIER: dict[CapabilityClass, str] = {v: k for k, v in _TIER_TO_CLASS.items()}


def tier_to_class(tier: str) -> CapabilityClass:
    return _TIER_TO_CLASS.get(tier, CapabilityClass.STANDARD)


def class_to_tier(capability_class: CapabilityClass) -> str:
    return _CLASS_TO_TIER[capability_class]


def class_rank(capability_class: CapabilityClass) -> int:
    return _CLASS_RANK[capability_class]


@dataclass
class EntitlementPolicy:
    allowed_model_classes: set[CapabilityClass]
    allowed_modes: set[str] = field(default_factory=lambda: {"chat", "stream"})
    maximum_quality_class: CapabilityClass = CapabilityClass.BASIC
    agent_access: bool = True          # tool-use loop -- free for everyone today
    deep_access: bool = False          # ultra/multi-agent mode
    external_provider_access: bool = False  # frontier API backends
    message_quota_used: int | None = None
    message_quota_limit: int | None = None  # -1 = unlimited, None = not checked
    reasons: list[str] = field(default_factory=list)

    def permits(self, capability_class: CapabilityClass) -> bool:
        return capability_class in self.allowed_model_classes

    def quota_exhausted(self) -> bool:
        if self.message_quota_limit is None or self.message_quota_limit < 0:
            return False
        return (self.message_quota_used or 0) >= self.message_quota_limit


def derive_entitlement_policy(user: User | None, requested_tier: str | None = None) -> EntitlementPolicy:
    """
    Builds an EntitlementPolicy by calling the EXISTING, unchanged
    model_access_allowed() for each capability class -- never
    reimplementing the free/pro/enterprise rules. `requested_tier`, when
    given, is the caller's OWN explicit tier request (e.g. req.model_variant)
    -- its entitlement check result becomes `reasons`'s first entry so
    callers can still surface the exact existing upgrade message for an
    explicitly-denied request (see orca/serve/api.py's cutover: the
    existing model_access_allowed() 402 path is preserved unchanged, this
    function does not replace it).
    """
    allowed: set[CapabilityClass] = set()
    reasons: list[str] = []
    for tier, capability_class in _TIER_TO_CLASS.items():
        ok, reason = model_access_allowed(user, tier)
        if ok:
            allowed.add(capability_class)
        elif tier == (requested_tier or "").removeprefix("orca-"):
            reasons.append(reason)

    if not allowed:
        # nano is documented as "always free, no restriction, anonymous
        # included" in model_access_allowed itself -- allowed should never
        # actually be empty, but never silently grant nothing usable.
        allowed = {CapabilityClass.BASIC}

    maximum = max(allowed, key=class_rank)

    quota_used = quota_limit = None
    if user is not None:
        limits = DAILY_LIMITS.get(user.tier, DAILY_LIMITS["free"])
        quota_limit = limits.get("messages")

    return EntitlementPolicy(
        allowed_model_classes=allowed,
        maximum_quality_class=maximum,
        deep_access=CapabilityClass.ADVANCED in allowed,
        external_provider_access=CapabilityClass.STANDARD in allowed or CapabilityClass.ADVANCED in allowed,
        message_quota_used=quota_used,
        message_quota_limit=quota_limit,
        reasons=reasons,
    )
