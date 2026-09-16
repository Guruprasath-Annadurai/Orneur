"""
Phase 21B guard (spec section 31): even with real Phase 21B build-
preparation infrastructure in place (base-model qualification,
reproducibility wiring, dataset builder), Genesis MUST remain
NOT_TRAINED / UNAVAILABLE in the trusted Phase 20 router until an actual
canonical checkpoint exists and is separately, evidence-gated promoted.
Training-run/checkpoint-record infrastructure existing and being
exercised by CPU-safe tests must never itself flip this truth.
"""
from __future__ import annotations

from orneur.intelligence.router import (
    CognitiveFamily,
    RuntimeAvailability,
    RuntimeLifecycleState,
    build_default_capability_registry,
)


def test_genesis_remains_not_trained_and_unavailable_in_default_registry():
    registry = build_default_capability_registry()
    genesis = next(e for e in registry if e.family is CognitiveFamily.GENESIS)
    assert genesis.lifecycle_state is RuntimeLifecycleState.NOT_TRAINED
    assert genesis.runtime_availability is RuntimeAvailability.UNAVAILABLE


def test_genesis_default_registry_entry_has_no_trained_checkpoint_reference():
    """The default registry is code-defined, not derived from any
    checkpoint/training-run record -- confirms no side channel could
    have silently promoted Genesis via CPU-safe provenance tests."""
    registry = build_default_capability_registry()
    genesis = next(e for e in registry if e.family is CognitiveFamily.GENESIS)
    # A trained-and-eligible entry would be EXPERIMENTAL/PROMOTABLE/
    # PRODUCTION + AVAILABLE, matching Novus's own default entry -- assert
    # Genesis is specifically NOT in that shape.
    assert genesis.lifecycle_state not in (
        RuntimeLifecycleState.EXPERIMENTAL, RuntimeLifecycleState.PROMOTABLE, RuntimeLifecycleState.PRODUCTION,
    )
    assert genesis.runtime_availability is not RuntimeAvailability.AVAILABLE
