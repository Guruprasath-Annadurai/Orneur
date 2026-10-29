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
    "capability_state",
)

# Structured capability states — preferred over phrase denylists.
CAPABILITY_STATES = frozenset({
    "REFUSE_ONLY",          # may only refuse; no native generate/stream
    "THIRD_PARTY_PROXY",    # answers via disclosed third-party provider
    "QUALIFIED_NATIVE",     # reserved; requires evidence this module refuses today
})

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

# Live-serving operations that imply a runnable native model.
LIVE_SERVING_OPERATIONS = frozenset({"generate", "stream", "cancel"})

SUPPORTED_OPERATIONS = LIVE_SERVING_OPERATIONS | frozenset({"refuse_unsupported"})

# Registry statuses that are not live-serving native models.
UNTRAINED_REGISTRY_STATUSES = frozenset({
    "UNSPECIFIED",
    "INTERFACE_ONLY",
    "CONFIGURATION_ONLY",
    "EXPERIMENTAL_UNTRAINED",
    "NOT_AVAILABLE",
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
    capability_state: str = "REFUSE_ONLY"
    checkpoint_digest: str | None = None


def _truthy_deployable(meta: dict[str, Any]) -> bool:
    value = meta.get("deployable")
    return value is True or value == "true" or value == 1


def validate_serving_identity(identity: NativeServingIdentity) -> None:
    if identity.model_family not in FAMILIES:
        raise ServingContractError(f"unknown model family {identity.model_family!r}")
    if identity.capability_state not in CAPABILITY_STATES:
        raise ServingContractError(f"unknown capability_state {identity.capability_state!r}")
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

    ops = set(identity.supported_operations)
    unknown_ops = ops - SUPPORTED_OPERATIONS
    if unknown_ops:
        raise ServingContractError(f"unsupported operations claimed: {sorted(unknown_ops)}")
    if "refuse_unsupported" not in ops:
        raise ServingContractError("supported_operations must include refuse_unsupported")
    if identity.streaming_compatible and not identity.cancellation_required:
        raise ServingContractError("streaming_compatible identities must require cancellation")
    if identity.streaming_compatible and "stream" not in ops:
        raise ServingContractError("streaming_compatible requires stream in supported_operations")
    if "stream" in ops and not identity.streaming_compatible:
        raise ServingContractError("stream operation requires streaming_compatible=True")
    if "cancel" in ops and "stream" not in ops and "generate" not in ops:
        raise ServingContractError("cancel without generate/stream is inconsistent")

    registry = default_registry()
    family = registry[identity.model_family]
    if identity.training_provenance_status != family.status:
        raise ServingContractError(
            f"training_provenance_status {identity.training_provenance_status!r} disagrees with "
            f"registry status {family.status!r}"
        )

    untrained = family.status in UNTRAINED_REGISTRY_STATUSES
    live_ops = ops & LIVE_SERVING_OPERATIONS

    if untrained:
        if identity.capability_state == "QUALIFIED_NATIVE":
            raise ServingContractError(
                f"{identity.model_family} is {family.status}; QUALIFIED_NATIVE is refused"
            )
        if identity.capability_state == "THIRD_PARTY_PROXY":
            if not (identity.third_party_disclosure and identity.third_party_disclosure.strip()):
                raise ServingContractError(
                    "THIRD_PARTY_PROXY requires non-empty third_party_disclosure"
                )
            # Proxy may stream via third party, but must not advertise a native checkpoint.
            if identity.served_model_identity or identity.checkpoint_digest:
                raise ServingContractError(
                    "THIRD_PARTY_PROXY must not advertise native served_model_identity or checkpoint_digest"
                )
            if identity.model_revision:
                raise ServingContractError(
                    "THIRD_PARTY_PROXY must not advertise a native model_revision"
                )
        else:
            # REFUSE_ONLY (default for untrained native families)
            if identity.capability_state != "REFUSE_ONLY":
                raise ServingContractError(
                    f"untrained family requires REFUSE_ONLY or THIRD_PARTY_PROXY, not "
                    f"{identity.capability_state!r}"
                )
            if live_ops:
                raise ServingContractError(
                    f"{identity.model_family} is {family.status}; live operations "
                    f"{sorted(live_ops)} are refused without a qualified native checkpoint"
                )
            if identity.streaming_compatible:
                raise ServingContractError(
                    f"{identity.model_family} is {family.status}; streaming_compatible is refused"
                )
            if identity.served_model_identity:
                raise ServingContractError(
                    f"{identity.model_family} is {family.status}; cannot advertise served_model_identity"
                )
            if identity.checkpoint_digest:
                raise ServingContractError(
                    f"{identity.model_family} is {family.status}; cannot advertise checkpoint_digest"
                )
            if identity.model_revision:
                raise ServingContractError(
                    f"{identity.model_family} is {family.status}; cannot advertise model_revision"
                )
            if identity.tokenizer_digest:
                raise ServingContractError(
                    f"{identity.model_family} is {family.status}; tokenizer_digest requires bound evidence"
                )

        if _truthy_deployable(identity.safety_metadata):
            raise ServingContractError(
                f"{identity.model_family} is {family.status}; deployable readiness is refused"
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

    if identity.capability_state == "QUALIFIED_NATIVE":
        # Reserved path: this repository has no accepted native qualification evidence.
        raise ServingContractError(
            "QUALIFIED_NATIVE is refused until independent qualification evidence exists "
            "(FOUNDATION-02 does not grant it)"
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
                "No native checkpoint is registered. Customer answers today use disclosed "
                "third-party / experimental Ollama tags when product serving is enabled — "
                "not a trained GENESIS/NOVUS/AETERNUM checkpoint."
            ),
            tokenizer_digest=None,
            context_window=None,
            supported_operations=("refuse_unsupported",),
            streaming_compatible=False,
            cancellation_required=False,
            safety_metadata={"deployable": False, "reason": "native family not trained"},
            capability_state="REFUSE_ONLY",
            checkpoint_digest=None,
        )
        validate_serving_identity(out[family])
    return out


def assert_capability_matches_registry(identity: NativeServingIdentity) -> None:
    """Explicit structured check used by adversarial tests."""
    validate_serving_identity(identity)
    family = default_registry()[identity.model_family]
    if family.status in UNTRAINED_REGISTRY_STATUSES and identity.capability_state == "QUALIFIED_NATIVE":
        raise ServingContractError("registry truth forbids QUALIFIED_NATIVE")


# Re-export for adversarial tests that mutate registry assumptions.
__all__ = [
    "ALLOWED_QUALIFICATION",
    "CAPABILITY_STATES",
    "FORBIDDEN_QUALIFICATION",
    "LIVE_SERVING_OPERATIONS",
    "NativeServingIdentity",
    "REQUIRED_SERVING_FIELDS",
    "ServingContractError",
    "SUPPORTED_OPERATIONS",
    "UNTRAINED_REGISTRY_STATUSES",
    "assert_capability_matches_registry",
    "handoff_defaults",
    "validate_serving_identity",
    "ModelFamilyContractError",
]
