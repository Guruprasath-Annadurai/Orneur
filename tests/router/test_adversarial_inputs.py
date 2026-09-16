"""
Spec section 26: a dedicated adversarial/hostile test matrix. Malformed
values for every typed field must be rejected via a typed RouterError
(or a Phase-19 error from the reused trust seam) -- never a raw
TypeError/KeyError/AttributeError/ValueError escaping to the caller.
"""
from __future__ import annotations

import pytest

from orneur.intelligence.router import CognitiveFamily, CognitiveRequirementKind, CognitiveTaskProfile, errors as router_errors
from orneur.intelligence.router.limits import MAX_MATERIAL_ATOMS_PER_TASK, MAX_REQUIREMENTS_PER_TASK
from tests.router.conftest import build_known_affirmed_fixture, route_task_trusted


@pytest.fixture()
def fixture():
    return build_known_affirmed_fixture(atom_id="a1")


def test_non_string_task_id_rejected(fixture):
    compiled, overlay = fixture
    task = CognitiveTaskProfile(task_id=123)  # type: ignore[arg-type]
    with pytest.raises(router_errors.RouterError):
        route_task_trusted(task, overlay=overlay, artifact=compiled)


def test_requirements_not_a_container_rejected(fixture):
    compiled, overlay = fixture
    task = CognitiveTaskProfile(task_id="t", requirements="IMPLEMENTATION")  # type: ignore[arg-type]
    with pytest.raises(router_errors.RouterError):
        route_task_trusted(task, overlay=overlay, artifact=compiled)


def test_requirements_member_wrong_type_rejected(fixture):
    compiled, overlay = fixture
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({123}))  # type: ignore[arg-type]
    with pytest.raises(router_errors.InvalidObjectType):
        route_task_trusted(task, overlay=overlay, artifact=compiled)


def test_requirements_member_value_alike_string_rejected(fixture):
    """A bare string equal to an enum member's .value must never be
    accepted as if it were the genuine enum member (isinstance-only
    trust boundary, never membership-by-value)."""
    compiled, overlay = fixture
    task = CognitiveTaskProfile(task_id="t", requirements=frozenset({"IMPLEMENTATION"}))  # type: ignore[arg-type]
    with pytest.raises(router_errors.InvalidObjectType):
        route_task_trusted(task, overlay=overlay, artifact=compiled)


def test_too_many_requirements_rejected(fixture):
    compiled, overlay = fixture
    # Only 13 CognitiveRequirementKind members exist -- exceed the
    # limit by duplicating structurally invalid members is not
    # possible via a frozenset, so instead pass a raw tuple with
    # repeats beyond the limit to hit the length check pre-validation.
    oversized = tuple(CognitiveRequirementKind.IMPLEMENTATION for _ in range(MAX_REQUIREMENTS_PER_TASK + 1))
    task = CognitiveTaskProfile(task_id="t", requirements=oversized)  # type: ignore[arg-type]
    with pytest.raises(router_errors.PayloadLimitExceeded):
        route_task_trusted(task, overlay=overlay, artifact=compiled)


def test_material_atom_ids_not_a_sequence_rejected(fixture):
    compiled, overlay = fixture
    task = CognitiveTaskProfile(task_id="t", material_epistemic_atom_ids="a1")  # type: ignore[arg-type]
    with pytest.raises(router_errors.RouterError):
        route_task_trusted(task, overlay=overlay, artifact=compiled)


def test_material_atom_id_wrong_type_rejected(fixture):
    compiled, overlay = fixture
    task = CognitiveTaskProfile(task_id="t", material_epistemic_atom_ids=(123,))  # type: ignore[arg-type]
    with pytest.raises(router_errors.RouterError):
        route_task_trusted(task, overlay=overlay, artifact=compiled)


def test_too_many_material_atom_ids_rejected(fixture):
    compiled, overlay = fixture
    oversized = tuple(f"atom-{i}" for i in range(MAX_MATERIAL_ATOMS_PER_TASK + 1))
    task = CognitiveTaskProfile(task_id="t", material_epistemic_atom_ids=oversized)
    with pytest.raises(router_errors.PayloadLimitExceeded):
        route_task_trusted(task, overlay=overlay, artifact=compiled)


def test_preferred_family_wrong_type_rejected(fixture):
    compiled, overlay = fixture
    task = CognitiveTaskProfile(task_id="t", preferred_family="GENESIS")  # type: ignore[arg-type]
    with pytest.raises(router_errors.RouterError):
        route_task_trusted(task, overlay=overlay, artifact=compiled)


def test_metadata_non_mapping_root_rejected(fixture):
    compiled, overlay = fixture
    task = CognitiveTaskProfile(task_id="t", metadata="not-a-mapping")  # type: ignore[arg-type]
    with pytest.raises(router_errors.InvalidObjectType):
        route_task_trusted(task, overlay=overlay, artifact=compiled)


def test_metadata_non_finite_float_rejected(fixture):
    compiled, overlay = fixture
    task = CognitiveTaskProfile(task_id="t", metadata={"x": float("nan")})
    with pytest.raises(router_errors.InvalidStructuredValue):
        route_task_trusted(task, overlay=overlay, artifact=compiled)


def test_metadata_top_level_scalar_via_call_kw_rejected(fixture):
    compiled, overlay = fixture
    from orneur.intelligence.router.evaluator import route_task
    from tests.router.conftest import TRUSTED_PHASE18_RUNTIME
    from orneur.intelligence.epistemic import canonical as epistemic_canonical

    task = CognitiveTaskProfile(task_id="t")
    with pytest.raises(router_errors.InvalidObjectType):
        route_task(
            task, overlay=overlay, artifact=compiled,
            overlay_trust_context=TRUSTED_PHASE18_RUNTIME,
            expected_overlay_digest=epistemic_canonical.digest(overlay),
            metadata="not-a-mapping",  # type: ignore[arg-type]
        )


def test_capability_registry_entry_wrong_type_rejected(fixture):
    # A malformed registry is rejected by validate_registry() INSIDE
    # verify_trusted_registry() strictly before any digest comparison
    # (registry_digest() itself assumes a validated registry and is not
    # a public trust-boundary function) -- called directly here rather
    # than via route_task_trusted, whose convenience wrapper eagerly
    # computes registry_digest() on the raw input for its own expected-
    # digest bookkeeping and would raise a raw AttributeError itself.
    from orneur.intelligence.router.evaluator import route_task
    from tests.router.conftest import TRUSTED_PHASE18_RUNTIME, TRUSTED_ROUTER_CONFIGURATION
    from orneur.intelligence.epistemic import canonical as epistemic_canonical

    compiled, overlay = fixture
    task = CognitiveTaskProfile(task_id="t")
    with pytest.raises(router_errors.RouterError):
        route_task(
            task, overlay=overlay, artifact=compiled,
            overlay_trust_context=TRUSTED_PHASE18_RUNTIME, expected_overlay_digest=epistemic_canonical.digest(overlay),
            capability_registry=("not-a-profile",),  # type: ignore[arg-type]
            capability_registry_trust_context=TRUSTED_ROUTER_CONFIGURATION, expected_registry_digest="irrelevant-fails-before-digest-check",
        )


def test_capability_registry_not_a_sequence_rejected(fixture):
    from orneur.intelligence.router.evaluator import route_task
    from tests.router.conftest import TRUSTED_PHASE18_RUNTIME, TRUSTED_ROUTER_CONFIGURATION
    from orneur.intelligence.epistemic import canonical as epistemic_canonical

    compiled, overlay = fixture
    task = CognitiveTaskProfile(task_id="t")
    with pytest.raises(router_errors.RouterError):
        route_task(
            task, overlay=overlay, artifact=compiled,
            overlay_trust_context=TRUSTED_PHASE18_RUNTIME, expected_overlay_digest=epistemic_canonical.digest(overlay),
            capability_registry="not-a-sequence",  # type: ignore[arg-type]
            capability_registry_trust_context=TRUSTED_ROUTER_CONFIGURATION, expected_registry_digest="irrelevant-fails-before-digest-check",
        )


def test_decision_id_wrong_type_rejected(fixture):
    compiled, overlay = fixture
    task = CognitiveTaskProfile(task_id="t")
    with pytest.raises(router_errors.RouterError):
        route_task_trusted(task, overlay=overlay, artifact=compiled, decision_id=12345)  # type: ignore[arg-type]


def test_task_wrong_type_rejected(fixture):
    compiled, overlay = fixture
    with pytest.raises(router_errors.RouterError):
        route_task_trusted("not-a-task", overlay=overlay, artifact=compiled)  # type: ignore[arg-type]


def test_overlay_wrong_type_rejected(fixture):
    compiled, overlay = fixture
    from orneur.intelligence.router.evaluator import route_task
    from tests.router.conftest import TRUSTED_PHASE18_RUNTIME

    task = CognitiveTaskProfile(task_id="t")
    with pytest.raises(router_errors.RouterError):
        route_task(
            task, overlay="not-an-overlay", artifact=compiled,  # type: ignore[arg-type]
            overlay_trust_context=TRUSTED_PHASE18_RUNTIME, expected_overlay_digest="x",
        )


def test_artifact_wrong_type_rejected(fixture):
    compiled, overlay = fixture
    from orneur.intelligence.router.evaluator import route_task
    from tests.router.conftest import TRUSTED_PHASE18_RUNTIME

    task = CognitiveTaskProfile(task_id="t")
    with pytest.raises(router_errors.RouterError):
        route_task(
            task, overlay=overlay, artifact="not-an-artifact",  # type: ignore[arg-type]
            overlay_trust_context=TRUSTED_PHASE18_RUNTIME, expected_overlay_digest="x",
        )
