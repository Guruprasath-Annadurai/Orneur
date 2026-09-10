"""
Phase 15.11.1 -- proves the CANONICAL requirement registry
(`orca.mission.requirements_seed.seed_registry()`) actually reflects
Relay's real status, not merely that an isolated test-only Requirement
copy could be transitioned (the exact gap this closure fixes -- see
PHASE15_EVIDENCE.md's "PHASE 15.11.1" checkpoint, item 1/13).

`_seed()` forces `requirements_seed._SEEDED = False` before calling
`seed_registry()`, matching the established pattern in
tests/test_mission_requirements.py::TestSeedDataQuality -- this is
necessary because `_SEEDED` is a module-level singleton flag that
survives `reset_registry_for_tests()` (which only clears the registry
dict, not the flag), so a bare `seed_registry()` call after another
test has already seeded once would silently no-op into an empty
registry.
"""
from __future__ import annotations

from orca.mission import requirements as requirements_module
from orca.mission import requirements_seed
from orca.mission.requirements import RequirementStatus


def _seed_canonical_registry() -> None:
    requirements_module.reset_registry_for_tests()
    requirements_seed._SEEDED = False
    requirements_seed.seed_registry()


def test_canonical_req_relay_state_001_is_verified_with_real_references():
    _seed_canonical_registry()
    try:
        req = requirements_module.get("REQ-RELAY-STATE-001")
        assert req.status is RequirementStatus.VERIFIED
        assert "orca/mission/relay_store.py" in req.implementation_files
        assert "tests/test_relay_store_live_neon.py" in req.test_files
        assert req.evidence_ref is not None and req.evidence_ref.strip() != ""
    finally:
        requirements_module.reset_registry_for_tests()


def test_canonical_req_device_revocation_001_acceptance_wording_does_not_permit_raw_secret_relay():
    """15.11.2 wording correction: the old acceptance criterion ("a
    Public Device session cannot access raw secrets that a Trusted
    Device session ... can") could be misread as implying Trusted
    Device mode is PERMITTED to relay raw secrets. It is not -- raw
    secret values are never relayed in ANY mode. The corrected wording
    must describe a capability/surface distinction, not imply raw
    secrets are ever exposed."""
    _seed_canonical_registry()
    try:
        req = requirements_module.get("REQ-DEVICE-REVOCATION-001")
        criteria_text = " ".join(req.acceptance_criteria)
        assert "raw secret values remain absent from Relay payloads in BOTH modes" in criteria_text
        assert "cannot access raw secrets that a Trusted Device session" not in criteria_text
    finally:
        requirements_module.reset_registry_for_tests()


def test_canonical_req_device_revocation_001_is_now_verified_in_phase_15_12():
    """Phase 15.12 closes the second acceptance criterion (Public
    Device's real, tested capability/surface restriction relative to
    Trusted Device, with raw secrets absent in BOTH) -- this
    requirement advances from IMPLEMENTED (15.11.1) to VERIFIED here."""
    _seed_canonical_registry()
    try:
        req = requirements_module.get("REQ-DEVICE-REVOCATION-001")
        assert req.status is RequirementStatus.VERIFIED
        assert "orca/mission/relay_security.py" in req.implementation_files
        assert "tests/test_relay_security_live_neon.py" in req.test_files
        assert req.evidence_ref is not None and req.evidence_ref.strip() != ""
    finally:
        requirements_module.reset_registry_for_tests()


def test_canonical_req_relay_reauth_001_is_verified():
    _seed_canonical_registry()
    try:
        req = requirements_module.get("REQ-RELAY-REAUTH-001")
        assert req.status is RequirementStatus.VERIFIED
        assert "orca/mission/relay_security.py" in req.implementation_files
        assert req.evidence_ref is not None and req.evidence_ref.strip() != ""
    finally:
        requirements_module.reset_registry_for_tests()


def test_canonical_req_relay_mobilereview_001_is_verified():
    _seed_canonical_registry()
    try:
        req = requirements_module.get("REQ-RELAY-MOBILEREVIEW-001")
        assert req.status is RequirementStatus.VERIFIED
        assert "orca/mission/relay_security.py" in req.implementation_files
        assert req.evidence_ref is not None and req.evidence_ref.strip() != ""
    finally:
        requirements_module.reset_registry_for_tests()


def test_canonical_req_reconnect_truth_001_is_verified_in_phase_15_13():
    """Phase 15.13: VERIFIED only after a real live-Neon proof of the
    exact acceptance criterion (canonical lost-successful-response
    reconnect, exactly-once executor preserved) -- not merely because
    Phase 15.5 idempotency already existed."""
    _seed_canonical_registry()
    try:
        req = requirements_module.get("REQ-RECONNECT-TRUTH-001")
        assert req.status is RequirementStatus.VERIFIED
        assert "orca/mission/relay_reconnect.py" in req.implementation_files
        assert "tests/test_relay_reconnect_live_neon.py" in req.test_files
        assert req.evidence_ref is not None and req.evidence_ref.strip() != ""
    finally:
        requirements_module.reset_registry_for_tests()


def test_canonical_req_relay_stalemutation_001_is_verified_in_phase_15_13():
    _seed_canonical_registry()
    try:
        req = requirements_module.get("REQ-RELAY-STALEMUTATION-001")
        assert req.status is RequirementStatus.VERIFIED
        assert "orca/mission/relay_reconnect.py" in req.implementation_files
        assert req.evidence_ref is not None and req.evidence_ref.strip() != ""
    finally:
        requirements_module.reset_registry_for_tests()


def test_seed_registry_transition_is_forward_only_and_would_reject_premature_verify():
    """Structural guarantee, not merely a policy choice: even if
    someone tried to skip straight to `transition(..., VERIFIED)` on
    the still-UNIMPLEMENTED REQ-RECONNECT-TRUTH-001 today, the
    registry's own gate rejects it -- VERIFIED is not reachable by
    assertion alone, and not reachable by skipping IMPLEMENTED either
    (orca.mission.requirements' own documented invariant)."""
    _seed_canonical_registry()
    try:
        from orca.mission.requirements import RequirementError
        import pytest
        with pytest.raises(RequirementError):
            requirements_module.transition("REQ-RECONNECT-TRUTH-001", RequirementStatus.VERIFIED)
    finally:
        requirements_module.reset_registry_for_tests()
