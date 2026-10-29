"""FOUNDATION-02 model-serving interface handoff (no live chatbot mutation)."""
from __future__ import annotations

import pytest

from orca.pretrain_foundation.serving_contract import (
    FORBIDDEN_QUALIFICATION,
    NativeServingIdentity,
    REQUIRED_SERVING_FIELDS,
    ServingContractError,
    assert_not_live_ui_injection,
    handoff_defaults,
    validate_serving_identity,
)


def test_required_serving_fields_are_stable():
    assert "model_family" in REQUIRED_SERVING_FIELDS
    assert "training_provenance_status" in REQUIRED_SERVING_FIELDS
    assert "cancellation_required" in REQUIRED_SERVING_FIELDS


def test_handoff_defaults_are_honest_for_all_families():
    defaults = handoff_defaults()
    assert set(defaults) == {"GENESIS", "NOVUS", "AETERNUM"}
    assert defaults["GENESIS"].qualification_status == "INTERFACE_ONLY"
    assert defaults["NOVUS"].served_model_identity is None
    assert defaults["AETERNUM"].safety_metadata["deployable"] is False
    for identity in defaults.values():
        validate_serving_identity(identity)


def test_refuses_frontier_qualification_for_untrained_family():
    with pytest.raises(ServingContractError):
        validate_serving_identity(
            NativeServingIdentity(
                model_family="GENESIS",
                model_revision="v0",
                training_provenance_status="INTERFACE_ONLY",
                served_model_identity=None,
                qualification_status="FRONTIER_QUALIFIED",
                third_party_disclosure=None,
                tokenizer_digest=None,
                context_window=2048,
                supported_operations=("refuse_unsupported",),
                streaming_compatible=False,
                cancellation_required=False,
                safety_metadata={},
            )
        )


@pytest.mark.parametrize("status", sorted(FORBIDDEN_QUALIFICATION))
def test_forbidden_qualification_statuses_are_rejected(status):
    with pytest.raises(ServingContractError):
        validate_serving_identity(
            NativeServingIdentity(
                model_family="NOVUS",
                model_revision=None,
                training_provenance_status="NOT_AVAILABLE",
                served_model_identity=None,
                qualification_status=status,
                third_party_disclosure=None,
                tokenizer_digest=None,
                context_window=None,
                supported_operations=("refuse_unsupported",),
                streaming_compatible=False,
                cancellation_required=False,
                safety_metadata={},
            )
        )


def test_streaming_requires_cancellation():
    with pytest.raises(ServingContractError, match="cancellation"):
        validate_serving_identity(
            NativeServingIdentity(
                model_family="GENESIS",
                model_revision=None,
                training_provenance_status="INTERFACE_ONLY",
                served_model_identity=None,
                qualification_status="INTERFACE_ONLY",
                third_party_disclosure="n/a",
                tokenizer_digest=None,
                context_window=1024,
                supported_operations=("stream", "refuse_unsupported"),
                streaming_compatible=True,
                cancellation_required=False,
                safety_metadata={},
            )
        )


def test_not_available_family_cannot_advertise_served_identity():
    with pytest.raises(ServingContractError, match="served_model_identity"):
        validate_serving_identity(
            NativeServingIdentity(
                model_family="AETERNUM",
                model_revision=None,
                training_provenance_status="NOT_AVAILABLE",
                served_model_identity="aeternum-fake-v1",
                qualification_status="NOT_QUALIFIED",
                third_party_disclosure=None,
                tokenizer_digest=None,
                context_window=None,
                supported_operations=("refuse_unsupported",),
                streaming_compatible=False,
                cancellation_required=False,
                safety_metadata={},
            )
        )


def test_ui_injection_phrases_are_refused():
    with pytest.raises(ServingContractError):
        assert_not_live_ui_injection("GENESIS is ready for customers")
    assert_not_live_ui_injection("Native families remain INTERFACE_ONLY / NOT_AVAILABLE")
