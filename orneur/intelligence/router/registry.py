"""
The Phase 20 TRUSTED capability registry. Registry truth comes from
trusted configuration/code ONLY -- never from an untrusted request
payload. `CognitiveTaskProfile`/its `.metadata` are never read to build
or override a registry entry.

Canonical model truth (see docs/PHASE20_INTELLIGENCE_ROUTER.md's
"Model-family truth", citing `orca.registry.model_spec` -- not
imported, this package never imports orca.*):

  GENESIS: canonical starting-point hypothesis ~3B, NOT trained ->
      RuntimeLifecycleState.NOT_TRAINED, RuntimeAvailability.UNAVAILABLE.
  NOVUS: real ~8B Llama fine-tuned experimental checkpoint exists,
      inference works, lifecycle EXPERIMENTAL, not production/promoted ->
      RuntimeLifecycleState.EXPERIMENTAL, RuntimeAvailability.AVAILABLE.
  AETERNUM: no trained checkpoint, base model unselected, ~14B is only a
      provisional V1 exploration target ->
      RuntimeLifecycleState.NOT_TRAINED, RuntimeAvailability.UNAVAILABLE.

This honestly means the DEFAULT registry currently has only ONE
routing-eligible family (Novus). That is not a bug -- Phase 20 must
represent model availability truthfully, per its own doctrine (section
10). Tests exercising other behavioral classes (e.g. a Genesis-eligible
routine-implementation route) supply a custom registry, exactly as
Phase 18/19 tests use synthetic fixtures rather than only production
data.
"""
from __future__ import annotations

import hashlib
import json

from orneur.intelligence.router import errors
from orneur.intelligence.router.contracts import IntelligenceCapabilityProfile
from orneur.intelligence.router.enums import (
    CognitiveFamily,
    CognitiveRequirementKind,
    CognitiveRole,
    RuntimeAvailability,
    RuntimeLifecycleState,
)
from orneur.intelligence.router.limits import MAX_REGISTRY_ENTRIES
from orneur.intelligence.router.typecheck import require_enum_member, require_instance, require_sequence_container

#: Only these lifecycle states are ever routing-eligible. NOT_TRAINED
#: and RETIRED can never become eligible merely because a request asks
#: for that family -- see errors.py's LIFECYCLE_INELIGIBLE reason code.
ELIGIBLE_LIFECYCLE_STATES: frozenset[RuntimeLifecycleState] = frozenset({
    RuntimeLifecycleState.EXPERIMENTAL,
    RuntimeLifecycleState.PROMOTABLE,
    RuntimeLifecycleState.PRODUCTION,
})


def build_default_capability_registry() -> tuple[IntelligenceCapabilityProfile, ...]:
    """The trusted default registry, reflecting current canonical model
    truth exactly (see module docstring)."""
    return (
        IntelligenceCapabilityProfile(
            family=CognitiveFamily.GENESIS,
            role=CognitiveRole.BUILDER_EXECUTOR,
            supported_requirements=frozenset({
                CognitiveRequirementKind.IMPLEMENTATION,
                CognitiveRequirementKind.EXECUTION_PLANNING,
                CognitiveRequirementKind.VERIFICATION,
            }),
            lifecycle_state=RuntimeLifecycleState.NOT_TRAINED,
            runtime_availability=RuntimeAvailability.UNAVAILABLE,
        ),
        IntelligenceCapabilityProfile(
            family=CognitiveFamily.NOVUS,
            role=CognitiveRole.REASONER_INVESTIGATOR,
            supported_requirements=frozenset({
                CognitiveRequirementKind.INVESTIGATION,
                CognitiveRequirementKind.CAUSAL_REASONING,
                CognitiveRequirementKind.UNCERTAINTY_RESOLUTION,
                CognitiveRequirementKind.CONTRADICTION_RESOLUTION,
                CognitiveRequirementKind.EVIDENCE_SYNTHESIS,
                CognitiveRequirementKind.ARCHITECTURE,
            }),
            lifecycle_state=RuntimeLifecycleState.EXPERIMENTAL,
            runtime_availability=RuntimeAvailability.AVAILABLE,
        ),
        IntelligenceCapabilityProfile(
            family=CognitiveFamily.AETERNUM,
            role=CognitiveRole.CRITIC_ARBITER_DISCOVERER,
            supported_requirements=frozenset({
                CognitiveRequirementKind.ADVERSARIAL_REVIEW,
                CognitiveRequirementKind.SECURITY_SENSITIVE_REASONING,
                CognitiveRequirementKind.DISCOVERY_EXPLORATION,
            }),
            lifecycle_state=RuntimeLifecycleState.NOT_TRAINED,
            runtime_availability=RuntimeAvailability.UNAVAILABLE,
        ),
    )


def validate_registry(entries: object) -> tuple[IntelligenceCapabilityProfile, ...]:
    """Fail-closed structural validation. Rejects malformed entries,
    duplicate families, and non-genuine enum members -- never a raw
    exception for adversarial registry input."""
    entries = require_sequence_container(entries, where="capability_registry")
    if len(entries) > MAX_REGISTRY_ENTRIES:
        raise errors.PayloadLimitExceeded("capability_registry exceeds MAX_REGISTRY_ENTRIES")

    seen_families: set[CognitiveFamily] = set()
    validated: list[IntelligenceCapabilityProfile] = []
    for entry in entries:
        require_instance(entry, IntelligenceCapabilityProfile, where="capability_registry[]")
        require_enum_member(entry.family, CognitiveFamily, where="IntelligenceCapabilityProfile.family")
        require_enum_member(entry.role, CognitiveRole, where="IntelligenceCapabilityProfile.role")
        require_enum_member(entry.lifecycle_state, RuntimeLifecycleState, where="IntelligenceCapabilityProfile.lifecycle_state")
        require_enum_member(entry.runtime_availability, RuntimeAvailability, where="IntelligenceCapabilityProfile.runtime_availability")

        supported = entry.supported_requirements
        if not isinstance(supported, (frozenset, set)):
            raise errors.InvalidCapabilityRegistry(
                f"IntelligenceCapabilityProfile.supported_requirements must be a frozenset/set, "
                f"got {type(supported).__name__}"
            )
        for member in supported:
            if not isinstance(member, CognitiveRequirementKind):
                raise errors.InvalidCapabilityRegistry(
                    f"IntelligenceCapabilityProfile.supported_requirements contains a non-"
                    f"CognitiveRequirementKind member: {type(member).__name__}"
                )

        if entry.family in seen_families:
            raise errors.DuplicateRegistryFamily(f"duplicate registry entry for family: {entry.family.value}")
        seen_families.add(entry.family)
        validated.append(entry)

    return tuple(sorted(validated, key=lambda e: e.family.value))


def is_eligible(entry: IntelligenceCapabilityProfile) -> bool:
    return (
        entry.runtime_availability is RuntimeAvailability.AVAILABLE
        and entry.lifecycle_state in ELIGIBLE_LIFECYCLE_STATES
    )


def registry_digest(entries: tuple[IntelligenceCapabilityProfile, ...]) -> str:
    """Deterministic digest of the validated, canonically-sorted
    registry -- included in every RoutingDecision so a decision can be
    audited against the exact registry state that produced it."""
    payload = [
        {
            "family": e.family.value,
            "role": e.role.value,
            "supported_requirements": sorted(r.value for r in e.supported_requirements),
            "lifecycle_state": e.lifecycle_state.value,
            "runtime_availability": e.runtime_availability.value,
        }
        for e in sorted(entries, key=lambda e: e.family.value)
    ]
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
