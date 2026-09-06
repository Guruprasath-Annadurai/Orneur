"""
Phase 7.1 spec §5-6: Truth Fabric's `verify_answer()`/`assess_evidence()`
default (unoverridden) tier resolution now goes through Model Society
(CLAIM_EXTRACTOR/VERIFIER/QUERY_REWRITER roles) instead of a hardcoded
`"nano"` literal -- this is the LIVE production path, since
`CognitiveKernel` never overrides `tier` when calling `verify_answer()`.
Deterministic -- exercises `resolve_tier_for_role()` directly, no live
model call.
"""
from __future__ import annotations

from orca.society.contracts import CognitiveRole
from orca.society.router import resolve_tier_for_role


def test_default_resolution_uses_society_not_a_hardcoded_literal():
    tier, decision = resolve_tier_for_role(CognitiveRole.VERIFIER)
    assert decision.reasons and "EXCLUDED_BY_CALLER" not in decision.reasons[0]
    assert tier in ("nano", "core", "ultra")


def test_explicit_override_bypasses_society_for_legacy_compatibility():
    tier, decision = resolve_tier_for_role(CognitiveRole.VERIFIER, override_tier="core")
    assert tier == "core"
    assert "EXCLUDED_BY_CALLER" in decision.reasons[0]


def test_production_default_never_silently_promotes_experimental_novus():
    """Without allow_experimental=True (the Kernel's real default),
    resolve_tier_for_role must never resolve to Novus's tier even though
    Novus has real measured VERIFIER evidence -- lifecycle is a hard
    filter Society routing cannot override for a production call."""
    tier, decision = resolve_tier_for_role(CognitiveRole.VERIFIER, allow_experimental=False)
    assert tier != "core"  # "core" is Novus's tier; production must stay on Genesis-legacy ("nano")


def test_evaluation_opt_in_can_reach_novus_for_verifier():
    tier, decision = resolve_tier_for_role(CognitiveRole.VERIFIER, allow_experimental=True)
    assert tier == "core"
    assert decision.selected_model_id == "orneur-novus"


