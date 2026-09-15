from __future__ import annotations

import pytest

from orneur.intelligence.epistemic.enums import (
    EpistemicPolarity,
    EpistemicResolutionTrustContext,
    EpistemicState,
    EvidenceResolutionStatus,
    EvidenceStance,
    RelationEffect,
    VerificationFeasibility,
    get_relation_semantics,
)
from orneur.intelligence.ocl.enums import RelationKind


def test_epistemic_state_has_exactly_the_six_required_members():
    assert {member.value for member in EpistemicState} == {
        "KNOWN", "INFERRED", "UNCERTAIN", "DISPUTED", "UNKNOWN", "UNVERIFIABLE",
    }


def test_epistemic_state_unknown_string_fails_closed():
    with pytest.raises(ValueError):
        EpistemicState("LIKELY")
    with pytest.raises(ValueError):
        EpistemicState("MAYBE")
    with pytest.raises(ValueError):
        EpistemicState("OTHER")


def test_epistemic_polarity_has_exactly_four_members():
    assert {member.value for member in EpistemicPolarity} == {"AFFIRMED", "REFUTED", "MIXED", "UNRESOLVED"}


def test_unspecified_relation_kinds_default_to_none_effect():
    specified = {RelationKind.SUPPORTS, RelationKind.CONTRADICTS, RelationKind.DERIVED_FROM, RelationKind.FALSIFIES}
    for kind in RelationKind:
        if kind not in specified:
            assert get_relation_semantics(kind).effect is RelationEffect.NONE, (
                f"{kind} unexpectedly has non-NONE epistemic effect"
            )


def test_causes_and_correlates_with_are_explicitly_none():
    assert get_relation_semantics(RelationKind.CAUSES).effect is RelationEffect.NONE
    assert get_relation_semantics(RelationKind.CORRELATES_WITH).effect is RelationEffect.NONE


def test_evidence_resolution_status_and_stance_closed_vocabularies():
    assert {m.value for m in EvidenceResolutionStatus} == {"VERIFIED", "UNVERIFIED", "STALE", "UNAVAILABLE", "INVALID"}
    assert {m.value for m in EvidenceStance} == {"SUPPORTS", "REFUTES", "INCONCLUSIVE"}


def test_resolution_trust_context_closed_vocabulary():
    assert {m.value for m in EpistemicResolutionTrustContext} == {
        "UNTRUSTED", "TRUSTED_TOOL_RESOLVER", "TRUSTED_DETERMINISTIC_VERIFIER",
    }


def test_verification_feasibility_closed_vocabulary():
    assert {m.value for m in VerificationFeasibility} == {
        "AVAILABLE", "PENDING", "TEMPORARILY_UNAVAILABLE", "STRUCTURALLY_UNVERIFIABLE",
    }
