"""FOUNDATION-02 model-serving interface handoff (no live chatbot mutation)."""
from __future__ import annotations

import pytest

from orca.pretrain_foundation.serving_contract import (
    FORBIDDEN_QUALIFICATION,
    NativeServingIdentity,
    REQUIRED_SERVING_FIELDS,
    ServingContractError,
    assert_capability_matches_registry,
    handoff_defaults,
    validate_serving_identity,
)


def test_required_serving_fields_include_capability_state():
    assert "capability_state" in REQUIRED_SERVING_FIELDS
    assert "model_family" in REQUIRED_SERVING_FIELDS


def test_handoff_defaults_are_honest_for_all_families():
    defaults = handoff_defaults()
    assert set(defaults) == {"GENESIS", "NOVUS", "AETERNUM"}
    assert defaults["GENESIS"].qualification_status == "INTERFACE_ONLY"
    assert defaults["GENESIS"].capability_state == "REFUSE_ONLY"
    assert defaults["NOVUS"].served_model_identity is None
    assert defaults["AETERNUM"].safety_metadata["deployable"] is False
    for identity in defaults.values():
        validate_serving_identity(identity)
        assert identity.supported_operations == ("refuse_unsupported",)
        assert identity.checkpoint_digest is None


def test_refuses_frontier_qualification_for_untrained_family():
    with pytest.raises(ServingContractError):
        validate_serving_identity(
            NativeServingIdentity(
                model_family="GENESIS",
                model_revision=None,
                training_provenance_status="INTERFACE_ONLY",
                served_model_identity=None,
                qualification_status="FRONTIER_QUALIFIED",
                third_party_disclosure="n/a",
                tokenizer_digest=None,
                context_window=None,
                supported_operations=("refuse_unsupported",),
                streaming_compatible=False,
                cancellation_required=False,
                safety_metadata={"deployable": False},
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
                third_party_disclosure="n/a",
                tokenizer_digest=None,
                context_window=None,
                supported_operations=("refuse_unsupported",),
                streaming_compatible=False,
                cancellation_required=False,
                safety_metadata={"deployable": False},
            )
        )


def test_interface_only_cannot_claim_generate_or_deployable():
    """Failing-before fix: INTERFACE_ONLY accepted generate+deployable=True."""
    with pytest.raises(ServingContractError, match="live operations|deployable"):
        validate_serving_identity(
            NativeServingIdentity(
                model_family="GENESIS",
                model_revision=None,
                training_provenance_status="INTERFACE_ONLY",
                served_model_identity=None,
                qualification_status="INTERFACE_ONLY",
                third_party_disclosure="n/a",
                tokenizer_digest=None,
                context_window=2048,
                supported_operations=("generate", "stream", "cancel", "refuse_unsupported"),
                streaming_compatible=True,
                cancellation_required=True,
                safety_metadata={"deployable": True},
                capability_state="REFUSE_ONLY",
            )
        )


def test_interface_only_cannot_advertise_served_checkpoint_identity():
    """Failing-before fix: INTERFACE_ONLY accepted served_model_identity."""
    with pytest.raises(ServingContractError, match="served_model_identity|model_revision|checkpoint"):
        validate_serving_identity(
            NativeServingIdentity(
                model_family="GENESIS",
                model_revision="genesis-native-v0",
                training_provenance_status="INTERFACE_ONLY",
                served_model_identity="orca-genesis-native-v1",
                qualification_status="EXPERIMENTAL",
                third_party_disclosure="n/a",
                tokenizer_digest=None,
                context_window=None,
                supported_operations=("refuse_unsupported",),
                streaming_compatible=False,
                cancellation_required=False,
                safety_metadata={"deployable": False},
                capability_state="REFUSE_ONLY",
                checkpoint_digest="sha256:deadbeef",
            )
        )


def test_not_available_cannot_claim_generate():
    """Failing-before fix: NOT_AVAILABLE accepted generate."""
    with pytest.raises(ServingContractError, match="live operations"):
        validate_serving_identity(
            NativeServingIdentity(
                model_family="NOVUS",
                model_revision=None,
                training_provenance_status="NOT_AVAILABLE",
                served_model_identity=None,
                qualification_status="NOT_QUALIFIED",
                third_party_disclosure="n/a",
                tokenizer_digest=None,
                context_window=None,
                supported_operations=("generate", "refuse_unsupported"),
                streaming_compatible=False,
                cancellation_required=False,
                safety_metadata={"deployable": False},
                capability_state="REFUSE_ONLY",
            )
        )


def test_qualified_native_capability_is_refused_without_evidence():
    with pytest.raises(ServingContractError, match="QUALIFIED_NATIVE"):
        validate_serving_identity(
            NativeServingIdentity(
                model_family="GENESIS",
                model_revision=None,
                training_provenance_status="INTERFACE_ONLY",
                served_model_identity=None,
                qualification_status="INTERFACE_ONLY",
                third_party_disclosure="n/a",
                tokenizer_digest=None,
                context_window=None,
                supported_operations=("refuse_unsupported",),
                streaming_compatible=False,
                cancellation_required=False,
                safety_metadata={"deployable": False},
                capability_state="QUALIFIED_NATIVE",
            )
        )


def test_third_party_proxy_requires_disclosure_and_forbids_native_checkpoint():
    with pytest.raises(ServingContractError, match="third_party_disclosure"):
        validate_serving_identity(
            NativeServingIdentity(
                model_family="AETERNUM",
                model_revision=None,
                training_provenance_status="NOT_AVAILABLE",
                served_model_identity=None,
                qualification_status="NOT_QUALIFIED",
                third_party_disclosure="",
                tokenizer_digest=None,
                context_window=None,
                supported_operations=("stream", "cancel", "refuse_unsupported"),
                streaming_compatible=True,
                cancellation_required=True,
                safety_metadata={"deployable": False},
                capability_state="THIRD_PARTY_PROXY",
            )
        )
    with pytest.raises(ServingContractError, match="native"):
        validate_serving_identity(
            NativeServingIdentity(
                model_family="AETERNUM",
                model_revision=None,
                training_provenance_status="NOT_AVAILABLE",
                served_model_identity="aeternum-fake",
                qualification_status="NOT_QUALIFIED",
                third_party_disclosure="Answers via disclosed Ollama tag only.",
                tokenizer_digest=None,
                context_window=None,
                supported_operations=("stream", "cancel", "refuse_unsupported"),
                streaming_compatible=True,
                cancellation_required=True,
                safety_metadata={"deployable": False},
                capability_state="THIRD_PARTY_PROXY",
            )
        )


def test_third_party_proxy_with_disclosure_is_allowed_without_native_identity():
    validate_serving_identity(
        NativeServingIdentity(
            model_family="NOVUS",
            model_revision=None,
            training_provenance_status="NOT_AVAILABLE",
            served_model_identity=None,
            qualification_status="NOT_QUALIFIED",
            third_party_disclosure="Experimental Ollama tag; not a trained NOVUS checkpoint.",
            tokenizer_digest=None,
            context_window=None,
            supported_operations=("stream", "cancel", "refuse_unsupported"),
            streaming_compatible=True,
            cancellation_required=True,
            safety_metadata={"deployable": False},
            capability_state="THIRD_PARTY_PROXY",
        )
    )


def test_provenance_must_match_registry_status():
    with pytest.raises(ServingContractError, match="disagrees with registry"):
        validate_serving_identity(
            NativeServingIdentity(
                model_family="GENESIS",
                model_revision=None,
                training_provenance_status="NOT_AVAILABLE",  # registry says INTERFACE_ONLY
                served_model_identity=None,
                qualification_status="NOT_QUALIFIED",
                third_party_disclosure="n/a",
                tokenizer_digest=None,
                context_window=None,
                supported_operations=("refuse_unsupported",),
                streaming_compatible=False,
                cancellation_required=False,
                safety_metadata={"deployable": False},
            )
        )


def test_assert_capability_matches_registry():
    identity = handoff_defaults()["GENESIS"]
    assert_capability_matches_registry(identity)
