"""
Model policy resolution: cognitive characteristics stay separate from
actual model names/tiers (Phase 3 spec §19-20). No HIGH -> Aeternum
hard-coding; characteristic_to_tier only names a starting TIER, which the
existing registry (unchanged) resolves for real eligibility/availability.
"""
from __future__ import annotations

from orca.cognitive.complexity import assess_complexity
from orca.cognitive.contracts import ComplexityLevel, ModelPolicyCharacteristic
from orca.cognitive.intent import compile_intent
from orca.cognitive.policy import characteristic_to_tier, select_model_policy


def test_characteristic_to_tier_never_names_a_model_directly():
    for characteristic in ModelPolicyCharacteristic:
        tier = characteristic_to_tier(characteristic)
        assert tier in ("nano", "core", "ultra")


def test_coding_intent_selects_code_policy():
    msg = "Write a function to reverse a linked list in Python."
    intent = compile_intent(msg)
    complexity = assess_complexity(msg, intent)
    policy = select_model_policy(intent, complexity)
    assert policy.characteristic == ModelPolicyCharacteristic.CODE


def test_trivial_greeting_selects_fast_policy():
    msg = "hi"
    intent = compile_intent(msg)
    complexity = assess_complexity(msg, intent)
    policy = select_model_policy(intent, complexity)
    assert policy.characteristic == ModelPolicyCharacteristic.FAST


def test_deep_complexity_selects_deep_policy():
    msg = "Orchestrate this multi-step task: compare and analyze the trade-offs, comprehensive, in depth."
    intent = compile_intent(msg)
    complexity = assess_complexity(msg, intent)
    assert complexity.level in (ComplexityLevel.HIGH, ComplexityLevel.DEEP)
    policy = select_model_policy(intent, complexity)
    assert policy.characteristic == ModelPolicyCharacteristic.DEEP


def test_policy_selection_never_hard_codes_a_model_family_mapping():
    """Regression guard: model policy must stay a cognitive characteristic
    -> TIER mapping only (checked structurally above); the module's actual
    _CHARACTERISTIC_TO_TIER table must map to tier names, never family
    identifiers like 'orneur-aeternum'/'orneur-novus'/'orneur-genesis'."""
    from orca.cognitive.policy import _CHARACTERISTIC_TO_TIER
    for tier in _CHARACTERISTIC_TO_TIER.values():
        assert tier in ("nano", "core", "ultra")
        assert "orneur-" not in tier
