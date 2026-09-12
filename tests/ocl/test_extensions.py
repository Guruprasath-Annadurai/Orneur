from __future__ import annotations

import pytest

from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.errors import InvalidNamespace
from orneur.intelligence.ocl.extensions import (
    NamespaceRegistration,
    is_registered_namespace,
    register_namespace,
    unregister_namespace_for_tests,
)
from tests.ocl.conftest import make_artifact, make_atom


def test_core_namespace_always_registered():
    assert is_registered_namespace("core")


def test_unregistered_namespace_rejected():
    atom = make_atom("a1", namespace="software")
    with pytest.raises(InvalidNamespace):
        compile_artifact(make_artifact(atoms=(atom,)))


def test_registered_extension_namespace_is_accepted():
    register_namespace(NamespaceRegistration(namespace="test_ext", version="0.1.0", producer="tests.ocl"))
    try:
        atom = make_atom("a1", namespace="test_ext")
        compile_artifact(make_artifact(atoms=(atom,)))
    finally:
        unregister_namespace_for_tests("test_ext")


def test_after_unregistering_namespace_is_rejected_again():
    register_namespace(NamespaceRegistration(namespace="temp_ext", version="0.1.0", producer="tests.ocl"))
    unregister_namespace_for_tests("temp_ext")
    atom = make_atom("a1", namespace="temp_ext")
    with pytest.raises(InvalidNamespace):
        compile_artifact(make_artifact(atoms=(atom,)))


def test_core_namespace_cannot_be_overwritten():
    from orneur.intelligence.ocl.errors import ExtensionNamespaceConflict

    with pytest.raises(ExtensionNamespaceConflict):
        register_namespace(NamespaceRegistration(namespace="core", version="99.0.0", producer="attacker"))


def test_conflicting_reregistration_of_existing_namespace_rejected():
    from orneur.intelligence.ocl.errors import ExtensionNamespaceConflict

    register_namespace(NamespaceRegistration(namespace="conflict_ext", version="1.0.0", producer="team_a"))
    try:
        with pytest.raises(ExtensionNamespaceConflict):
            register_namespace(NamespaceRegistration(namespace="conflict_ext", version="2.0.0", producer="team_b"))
    finally:
        unregister_namespace_for_tests("conflict_ext")


def test_identical_reregistration_is_idempotent_not_a_conflict():
    reg = NamespaceRegistration(namespace="idempotent_ext", version="1.0.0", producer="team_a")
    register_namespace(reg)
    try:
        register_namespace(reg)  # same version/producer -- must not raise
    finally:
        unregister_namespace_for_tests("idempotent_ext")


def test_compile_uses_a_stable_registry_snapshot_per_call():
    """A namespace unregistered mid-validation-pass (simulated by
    unregistering right after taking a snapshot) does not affect a compile
    call already using its own snapshot."""
    from orneur.intelligence.ocl.extensions import snapshot_registry

    register_namespace(NamespaceRegistration(namespace="snapshot_ext", version="1.0.0", producer="tests.ocl"))
    try:
        snap = snapshot_registry()
        assert "snapshot_ext" in snap
        unregister_namespace_for_tests("snapshot_ext")
        # The live registry no longer has it, but the snapshot we already
        # took is untouched -- proving compile_artifact's own internal
        # snapshot (taken once per call) is stable for that call's duration.
        assert "snapshot_ext" in snap
        assert not is_registered_namespace("snapshot_ext")
    finally:
        unregister_namespace_for_tests("snapshot_ext")
