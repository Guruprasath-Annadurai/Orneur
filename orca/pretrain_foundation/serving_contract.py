"""Product/model interface contract for native-family handoff (FOUNDATION-02).

This module documents and validates the *expected* serving identity
contract. It does not modify the live chatbot, inject GENESIS/NOVUS/
AETERNUM into the UI, or claim those families are trained or qualified.

Customer-facing serving remains under product ownership. This is an
exact-SHA interface handoff for CTO review.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from orca.genesis.model.family_registry import (
    FAMILIES,
    FORBIDDEN_STATUSES,
    HONEST_STATUSES,
    ModelFamilyContractError,
    default_registry,
)

# Fields a future native-model serve path must expose truthfully.
REQUIRED_SERVING_FIELDS = (
    "model_family",
    "model_revision",
    "training_provenance_status",
    "served_model_identity",
    "qualification_status",
    "third_party_disclosure",
    "tokenizer_digest",
    "context_window",
    "supported_operations",
    "streaming_compatible",
    "cancellation_required",
    "safety_metadata",
)

ALLOWED_QUALIFICATION = frozenset({
    "EXPERIMENTAL",
    "NOT_QUALIFIED",
    "INTERFACE_ONLY",
    "UNKNOWN",
})

FORBIDDEN_QUALIFICATION = frozenset({
    "PRODUCTION",
    "FRONTIER_QUALIFIED",
    "TRAINED",
    "AVAILABLE",
})

SUPPORTED_OPERATIONS = frozenset({
    "generate",
    "stream",
    "cancel",
    "refuse_unsupported",
})


class ServingContractError(Exception):
    """The proposed serving identity violates the native-family contract."""


@dataclass(frozen=True)
class NativeServingIdentity:
    model_family: str
    model_revision: str | None
    training_provenance_status: str
    served_model_identity: str | None
    qualification_status: str
    third_party_disclosure: str | None
    tokenizer_digest: str | None
    context_window: int | None
    supported_operations: tuple[str, ...]
    streaming_compatible: bool
    cancellation_required: bool
    safety_metadata: dict[str, Any]


def validate_serving_identity(identity: NativeServingIdentity) -> None:
    if identity.model_family not in FAMILIES:
        raise ServingContractError(f"unknown model family {identity.model_family!r}")
    if identity.training_provenance_status in FORBIDDEN_STATUSES:
        raise ServingContractError(
            f"training_provenance_status {identity.training_provenance_status!r} is refused"
        )
    if identity.training_provenance_status not in HONEST_STATUSES:
        raise ServingContractError(
            f"training_provenance_status {identity.training_provenance_status!r} is not honest"
        )
    if identity.qualification_status in FORBIDDEN_QUALIFICATION:
        raise ServingContractError(
            f"qualification_status {identity.qualification_status!r} is refused for untrained families"
        )
    if identity.qualification_status not in ALLOWED_QUALIFICATION:
        raise ServingContractError(
            f"qualification_status {identity.qualification_status!r} is not allowed"
        )
    if identity.context_window is not None and identity.context_window <= 0:
        raise ServingContractError("context_window must be positive when declared")
    unknown_ops = set(identity.supported_operations) - SUPPORTED_OPERATIONS
    if unknown_ops:
        raise ServingContractError(f"unsupported operations claimed: {sorted(unknown_ops)}")
    if "refuse_unsupported" not in identity.supported_operations:
        raise ServingContractError("supported_operations must include refuse_unsupported")
    if identity.streaming_compatible and not identity.cancellation_required:
        raise ServingContractError("streaming_compatible identities must require cancellation")
    # Registry honesty: serving cannot claim more than the family registry.
    registry = default_registry()
    family = registry[identity.model_family]
    if family.status in {"NOT_AVAILABLE", "UNSPECIFIED"} and identity.served_model_identity:
        raise ServingContractError(
            f"{identity.model_family} is {family.status}; cannot advertise a served_model_identity"
        )
    if family.status == "INTERFACE_ONLY" and identity.qualification_status not in {
        "INTERFACE_ONLY",
        "NOT_QUALIFIED",
        "EXPERIMENTAL",
        "UNKNOWN",
    }:
        raise ServingContractError(
            f"INTERFACE_ONLY family cannot claim qualification {identity.qualification_status!r}"
        )


def handoff_defaults() -> dict[str, NativeServingIdentity]:
    """Honest defaults for a future native serve path — not live UI wiring."""
    out: dict[str, NativeServingIdentity] = {}
    for family, record in default_registry().items():
        out[family] = NativeServingIdentity(
            model_family=family,
            model_revision=None,
            training_provenance_status=record.status,
            served_model_identity=None,
            qualification_status=(
                "INTERFACE_ONLY" if record.status == "INTERFACE_ONLY" else "NOT_QUALIFIED"
            ),
            third_party_disclosure=(
                "No native checkpoint is registered; do not present this family as trained."
            ),
            tokenizer_digest=record.tokenizer_digest,
            context_window=None,
            supported_operations=("refuse_unsupported",),
            streaming_compatible=False,
            cancellation_required=False,
            safety_metadata={"deployable": False, "reason": "native family not trained"},
        )
        validate_serving_identity(out[family])
    return out


def assert_not_live_ui_injection(source: str) -> None:
    """Refuse source that would market untrained families as live models."""
    banned = (
        "GENESIS is ready",
        "NOVUS is ready",
        "AETERNUM is ready",
        "frontier-qualified native",
        "trained ORNEUR model online",
    )
    lowered = source.lower()
    for phrase in banned:
        if phrase.lower() in lowered:
            raise ServingContractError(f"refused UI/marketing claim: {phrase!r}")


# Re-export for adversarial tests that mutate registry assumptions.
__all__ = [
    "ALLOWED_QUALIFICATION",
    "FORBIDDEN_QUALIFICATION",
    "NativeServingIdentity",
    "REQUIRED_SERVING_FIELDS",
    "ServingContractError",
    "SUPPORTED_OPERATIONS",
    "assert_not_live_ui_injection",
    "handoff_defaults",
    "validate_serving_identity",
    "ModelFamilyContractError",
]
