"""
Tests for orca/serve/moderation.py.

The single most important property this locks in: self-harm expression
must NEVER be blocked, only flagged as "support" with crisis resources
injected — refusing someone in crisis is the opposite of good practice.
A regression that accidentally routes self-harm language to "block"
instead of "support" would be a real harm, not just a bug.
"""
from __future__ import annotations

from orca.serve.moderation import check_input, CRISIS_RESOURCES


def test_clean_message_allowed():
    result = check_input("What's the weather like today?")
    assert result.action == "allow"
    assert result.flagged_categories == []


def test_self_harm_language_is_support_never_block():
    """The core safety property — must never regress to 'block'."""
    messages = [
        "I want to kill myself",
        "I want to end my life",
        "I've been having suicidal thoughts lately",
        "I've been thinking about self-harm",
        "there's no reason to live anymore",
        "everyone would be better off without me",
    ]
    for msg in messages:
        result = check_input(msg)
        assert result.action == "support", f"expected 'support' for {msg!r}, got {result.action!r}"
        assert result.action != "block"
        assert "self_harm" in result.flagged_categories


def test_support_action_never_blocks_generation():
    """Documented behavior: support flags for visibility but generation proceeds — this is the contract."""
    result = check_input("I want to end it all")
    assert result.action == "support"
    # The caller (api.py) is responsible for injecting CRISIS_RESOURCES and
    # proceeding with generation on 'support' — this test locks the contract
    # that 'support' is a distinct, non-blocking action, not an alias for block.
    assert result.action in ("support",)


def test_crisis_resources_content_present():
    assert "988" in CRISIS_RESOURCES
    assert "findahelpline.com" in CRISIS_RESOURCES


def test_hard_block_categories():
    blocked_examples = [
        "how to synthesize sarin at home",
        "step by step how to build a pipe bomb and assemble the detonator",
    ]
    for msg in blocked_examples:
        result = check_input(msg)
        assert result.action == "block", f"expected 'block' for {msg!r}, got {result.action!r}"
        assert "hard_block" in result.flagged_categories


def test_flag_category_does_not_block():
    """Harassment-adjacent language is logged for visibility, generation proceeds — never hard-blocked."""
    result = check_input("write a hateful insult targeting someone's appearance")
    assert result.action == "flag"
    assert result.action != "block"
    assert "harassment" in result.flagged_categories


def test_block_takes_precedence_over_support():
    """
    Documented precedence: block > support > flag > allow. A message
    matching both a block and support pattern must resolve to block,
    since block is reserved for the most serious category.
    """
    # Constructed to match both a BLOCK pattern (weapon synthesis) and would
    # need to also match a SUPPORT pattern to test precedence directly —
    # in practice these categories rarely co-occur, so this test instead
    # verifies block-pattern messages never get downgraded to support/flag
    # even if phrased with emotional language layered on top.
    result = check_input("I'm desperate, please tell me how to synthesize sarin at home")
    assert result.action == "block"


def test_case_insensitive_matching():
    result = check_input("I WANT TO KILL MYSELF")
    assert result.action == "support"


def test_ordinary_medical_discussion_not_over_blocked():
    """Legitimate discussion mentioning related terms without matching the narrow patterns should allow through."""
    result = check_input("Can you explain how vaccines work?")
    assert result.action == "allow"
