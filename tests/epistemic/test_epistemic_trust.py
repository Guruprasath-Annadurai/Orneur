from __future__ import annotations

from orneur.intelligence.epistemic.enums import EpistemicResolutionTrustContext
from orneur.intelligence.epistemic.trust import (
    can_mint_structurally_unverifiable,
    is_qualified,
    is_valid_resolution_trust_context,
)


def test_bare_string_equal_to_member_value_is_not_a_valid_trust_context():
    assert is_valid_resolution_trust_context("TRUSTED_DETERMINISTIC_VERIFIER") is False
    assert is_valid_resolution_trust_context("TRUSTED_TOOL_RESOLVER") is False
    assert is_valid_resolution_trust_context("UNTRUSTED") is False


def test_genuine_enum_members_are_valid():
    for member in EpistemicResolutionTrustContext:
        assert is_valid_resolution_trust_context(member) is True


def test_none_and_other_types_are_not_valid_trust_contexts():
    assert is_valid_resolution_trust_context(None) is False
    assert is_valid_resolution_trust_context(1) is False
    assert is_valid_resolution_trust_context({}) is False


def test_only_trusted_tiers_are_qualified():
    assert is_qualified(EpistemicResolutionTrustContext.UNTRUSTED) is False
    assert is_qualified(EpistemicResolutionTrustContext.TRUSTED_TOOL_RESOLVER) is True
    assert is_qualified(EpistemicResolutionTrustContext.TRUSTED_DETERMINISTIC_VERIFIER) is True


def test_only_deterministic_verifier_can_mint_structurally_unverifiable():
    assert can_mint_structurally_unverifiable(EpistemicResolutionTrustContext.UNTRUSTED) is False
    assert can_mint_structurally_unverifiable(EpistemicResolutionTrustContext.TRUSTED_TOOL_RESOLVER) is False
    assert can_mint_structurally_unverifiable(EpistemicResolutionTrustContext.TRUSTED_DETERMINISTIC_VERIFIER) is True
