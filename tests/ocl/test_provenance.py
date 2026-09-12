from __future__ import annotations

import pytest

from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.enums import ProducerKind
from orneur.intelligence.ocl.errors import InvalidProvenance
from orneur.intelligence.ocl.provenance import ModelIdentityRef, Provenance
from tests.ocl.conftest import make_artifact


def test_native_model_with_valid_family_and_lifecycle_accepted():
    prov = Provenance(
        producer_kind=ProducerKind.NATIVE_MODEL, producer_id="genesis-1",
        model_identity=ModelIdentityRef(family="genesis", lifecycle_state="EXPERIMENTAL"),
    )
    compile_artifact(make_artifact(provenance=prov))


def test_native_model_without_model_identity_rejected():
    prov = Provenance(producer_kind=ProducerKind.NATIVE_MODEL, producer_id="genesis-1")
    with pytest.raises(InvalidProvenance):
        compile_artifact(make_artifact(provenance=prov))


def test_native_model_without_family_rejected():
    prov = Provenance(
        producer_kind=ProducerKind.NATIVE_MODEL, producer_id="genesis-1",
        model_identity=ModelIdentityRef(family=None),
    )
    with pytest.raises(InvalidProvenance):
        compile_artifact(make_artifact(provenance=prov))


def test_unknown_model_family_rejected():
    prov = Provenance(
        producer_kind=ProducerKind.NATIVE_MODEL, producer_id="x",
        model_identity=ModelIdentityRef(family="not-a-real-family"),
    )
    with pytest.raises(InvalidProvenance):
        compile_artifact(make_artifact(provenance=prov))


def test_unknown_lifecycle_state_rejected():
    prov = Provenance(
        producer_kind=ProducerKind.NATIVE_MODEL, producer_id="x",
        model_identity=ModelIdentityRef(family="genesis", lifecycle_state="NOT_A_REAL_STATE"),
    )
    with pytest.raises(InvalidProvenance):
        compile_artifact(make_artifact(provenance=prov))


def test_external_provider_cannot_claim_a_native_family():
    """An external frontier response must never be relabeled as native
    (Phase 16 §15) -- this is the exact structural guard for that rule."""
    prov = Provenance(
        producer_kind=ProducerKind.EXTERNAL_PROVIDER, producer_id="openai:gpt-4o",
        model_identity=ModelIdentityRef(family="genesis"),
    )
    with pytest.raises(InvalidProvenance):
        compile_artifact(make_artifact(provenance=prov))


def test_external_provider_with_provider_id_and_no_family_is_valid():
    prov = Provenance(
        producer_kind=ProducerKind.EXTERNAL_PROVIDER, producer_id="openai:gpt-4o",
        model_identity=ModelIdentityRef(family=None, provider_id="openai"),
    )
    compile_artifact(make_artifact(provenance=prov))


def test_deterministic_system_producer_needs_no_model_identity():
    prov = Provenance(producer_kind=ProducerKind.DETERMINISTIC_SYSTEM, producer_id="orca.mission.cognitive_court")
    compile_artifact(make_artifact(provenance=prov))
