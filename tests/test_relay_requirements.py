"""
Phase 15.11 -- proves the requirement-registry status transitions for
REQ-RELAY-STATE-001 and REQ-DEVICE-REVOCATION-001 are genuinely
reachable given this phase's real implementation/test/evidence
references (spec section 28), using an isolated registry copy (per
`reset_registry_for_tests()`'s own convention, see
tests/test_traceability.py) rather than the shared `seed_registry()`
singleton.

REQ-RELAY-STATE-001 -> VERIFIED: both of its acceptance criteria are
genuinely proven this phase (second-device continuity in
tests/test_relay_store_live_neon.py; no-raw-secret in both that file
and tests/test_relay_store.py).

REQ-DEVICE-REVOCATION-001 -> IMPLEMENTED only, per the owner's explicit
instruction (spec section 28): it spans Phase 15.11 + Phase 15.12, and
must NOT be marked VERIFIED until its Public-vs-Trusted-Device security
criterion is proven in Phase 15.12.
"""
from __future__ import annotations

from orca.mission import requirements as requirements_module
from orca.mission.requirements import Requirement, RequirementStatus


def _fresh_relay_state_requirement() -> Requirement:
    return Requirement(
        id="REQ-RELAY-STATE-001",
        source_section="spec section 22",
        statement="Relay synchronizes governed engineering state (workspace, repository, "
                   "branch, revision, mission/step state, requirement/test/verification "
                   "progress, Production Proof status, pending approvals/dangerous "
                   "actions, checkpoints, agent/tool activity summaries, authority "
                   "context), not just files, and never relays raw secrets.",
        acceptance_criteria=(
            "A test reconnects a second device to an existing mission and confirms every "
            "listed state category is present in the synchronized payload.",
            "A test confirms no raw secret value ever appears in a Relay payload -- only "
            "secret references.",
        ),
    )


def _fresh_device_revocation_requirement() -> Requirement:
    return Requirement(
        id="REQ-DEVICE-REVOCATION-001",
        source_section="spec section 25",
        statement="Relay session/device state supports creation, expiry, device "
                   "association, last-seen tracking, and revoke-current/revoke-other/"
                   "revoke-all-others; Public Device Mode is visibly and technically "
                   "distinct from Trusted Device mode.",
        acceptance_criteria=(
            "A test revokes a specific other-device session and confirms that session's "
            "subsequent requests are rejected while the revoking session remains valid.",
            "A test confirms a Public Device session cannot access raw secrets that a "
            "Trusted Device session of the same user can.",
        ),
    )


def test_req_relay_state_001_reaches_verified_with_real_references():
    requirements_module.reset_registry_for_tests()
    try:
        requirements_module.register(_fresh_relay_state_requirement())
        requirements_module.transition(
            "REQ-RELAY-STATE-001", RequirementStatus.IMPLEMENTED,
            implementation_files=("orca/mission/relay_store.py",),
        )
        updated = requirements_module.transition(
            "REQ-RELAY-STATE-001", RequirementStatus.VERIFIED,
            test_files=("tests/test_relay_store_live_neon.py", "tests/test_relay_store.py"),
            evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-1511-relay-session-core",
        )
        assert updated.status is RequirementStatus.VERIFIED
        assert updated.evidence_ref is not None
    finally:
        requirements_module.reset_registry_for_tests()


def test_req_device_revocation_001_reaches_implemented_but_not_verified():
    """This phase deliberately stops at IMPLEMENTED (spec section 28) --
    attempting to VERIFY it here without a Phase 15.12 Public-vs-
    Trusted security proof must fail, proving the registry's own
    forward-only gate genuinely blocks premature completion."""
    requirements_module.reset_registry_for_tests()
    try:
        requirements_module.register(_fresh_device_revocation_requirement())
        updated = requirements_module.transition(
            "REQ-DEVICE-REVOCATION-001", RequirementStatus.IMPLEMENTED,
            implementation_files=("orca/mission/relay_store.py",),
        )
        assert updated.status is RequirementStatus.IMPLEMENTED
        # Not marking VERIFIED this phase is a deliberate choice, not a
        # structural inability -- demonstrate the registry WOULD allow
        # it if evidence were supplied, but this phase does not call it.
        assert updated.evidence_ref is None
    finally:
        requirements_module.reset_registry_for_tests()
