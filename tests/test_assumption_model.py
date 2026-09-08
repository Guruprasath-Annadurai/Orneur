"""Phase 15.7 -- Assumption/Fact test matrix (spec section 20)."""
from __future__ import annotations

import pytest

from orca.mission.assumption_model import (
    FactError,
    FactState,
    contest,
    get_fact,
    record_fact,
    reset_registry_for_tests,
    verify,
)
from orca.mission.provenance import SourceProvenance


@pytest.fixture(autouse=True)
def _clean():
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


def test_unverified_assumption_creation():
    f = record_fact(id="f1", statement="Users pay via Stripe", state=FactState.UNVERIFIED,
                     provenance=SourceProvenance.INFERRED_ASSUMPTION)
    assert f.state is FactState.UNVERIFIED


def test_unknown_fact_creation():
    f = record_fact(id="f1", statement="Target country is unknown", state=FactState.UNKNOWN,
                     provenance=SourceProvenance.INFERRED_ASSUMPTION)
    assert f.state is FactState.UNKNOWN


def test_verified_without_evidence_rejected():
    with pytest.raises(FactError):
        record_fact(id="f1", statement="x", state=FactState.VERIFIED,
                    provenance=SourceProvenance.OWNER_EXPLICIT)


def test_verified_with_evidence_accepted_via_verify():
    record_fact(id="f1", statement="x", state=FactState.UNVERIFIED, provenance=SourceProvenance.OWNER_EXPLICIT)
    verified = verify("f1", evidence_ref="docs/spec.md#section-3")
    assert verified.state is FactState.VERIFIED
    assert verified.evidence_ref == "docs/spec.md#section-3"


def test_verify_requires_nonempty_evidence():
    record_fact(id="f1", statement="x", state=FactState.UNVERIFIED, provenance=SourceProvenance.OWNER_EXPLICIT)
    with pytest.raises(FactError):
        verify("f1", evidence_ref="")


def test_contested_preserved_not_silently_resolved():
    record_fact(id="f1", statement="Users pay via Stripe", state=FactState.UNVERIFIED,
                provenance=SourceProvenance.INFERRED_ASSUMPTION)
    contested = contest("f1", competing_statement="Users pay via PayPal, per owner clarification")
    assert contested.state is FactState.CONTESTED
    assert contested.statement == "Users pay via Stripe"  # original NOT overwritten
    assert "Users pay via PayPal, per owner clarification" in contested.competing_statements


def test_cannot_construct_contested_without_competing_statement():
    with pytest.raises(FactError):
        record_fact(id="f1", statement="x", state=FactState.CONTESTED,
                    provenance=SourceProvenance.INFERRED_ASSUMPTION)


def test_model_suggested_assumption_cannot_self_promote():
    # An INFERRED_ASSUMPTION fact cannot be constructed as VERIFIED --
    # the only path to VERIFIED is verify(), which requires the
    # CALLER to supply real evidence.
    with pytest.raises(FactError):
        record_fact(id="f1", statement="x", state=FactState.VERIFIED,
                    provenance=SourceProvenance.INFERRED_ASSUMPTION)


def test_explicit_owner_fact_distinguishable_from_inferred():
    owner_fact = record_fact(id="f1", statement="Country: US", state=FactState.UNVERIFIED,
                             provenance=SourceProvenance.OWNER_EXPLICIT)
    inferred_fact = record_fact(id="f2", statement="Payment provider unknown", state=FactState.UNKNOWN,
                                provenance=SourceProvenance.INFERRED_ASSUMPTION)
    assert owner_fact.provenance != inferred_fact.provenance
    assert owner_fact.provenance is SourceProvenance.OWNER_EXPLICIT
    assert inferred_fact.provenance is SourceProvenance.INFERRED_ASSUMPTION


def test_cannot_register_duplicate_fact_id():
    record_fact(id="f1", statement="x", state=FactState.UNKNOWN, provenance=SourceProvenance.INFERRED_ASSUMPTION)
    with pytest.raises(FactError):
        record_fact(id="f1", statement="y", state=FactState.UNKNOWN, provenance=SourceProvenance.INFERRED_ASSUMPTION)


def test_get_fact_missing_raises():
    with pytest.raises(FactError):
        get_fact("nonexistent")
