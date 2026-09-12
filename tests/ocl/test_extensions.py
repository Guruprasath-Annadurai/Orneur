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
