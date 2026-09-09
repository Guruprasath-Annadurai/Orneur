"""
Phase 15.10 -- Production Proof store tests that do not require a live
database connection: canonical payload round-trip via the store's own
(de)serialization helpers, and stale-proof detection (spec section
31), hardened by Phase 15.10.1's decision-context fingerprint. Durable
persistence itself (write/reload across a fresh connection, append-only
history, overall_status database integrity) is qualified against a
real disposable Neon branch in `tests/test_production_proof_live_neon.py`.
"""
from __future__ import annotations

import json

import pytest

from orca.mission.cognitive_court import CourtDecision, CourtRole, CourtVerdict, RiskLevel
from orca.mission.production_proof import (
    AntiGamingAnalysisEvidence,
    CATEGORY_BUILD,
    CATEGORY_SECURITY,
    CATEGORY_UNIT_TEST,
    ReleaseQualificationPolicy,
    compute_proof_hash,
    generate_production_proof,
    to_dict,
)
from orca.mission.production_proof_store import (
    ProductionProofStoreError,
    _SCHEMA_ALLOWED_STATUSES,
    _payload_to_proof,
    _row_to_proof,
    is_proof_stale,
)
from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import RequiredVerificationScope

_UNIT_TEST_SCOPE = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST"}))
_MINIMAL_POLICY = ReleaseQualificationPolicy(
    engineering_not_applicable={
        "integration_tests": "n/a", "e2e_tests": "n/a", "regression": "n/a", "authority": "n/a",
    },
)


def _rec(category, **overrides):
    defaults = dict(
        id=f"ver_{category}", mission_id="m1", requirement_id="REQ-X-1" if category == CATEGORY_UNIT_TEST else None,
        criterion_id=None, category=category, verification_method=category, verifier_id="TestVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision="rev1",
        evidence_refs=("x",),
    )
    defaults.update(overrides)
    return VerificationRecord(**defaults)


def _proof(**overrides):
    unit_rec = _rec(CATEGORY_UNIT_TEST)
    build_rec = _rec(CATEGORY_BUILD, id="ver_build")
    sec_rec = _rec(CATEGORY_SECURITY, id="ver_sec")
    decision = CourtDecision(
        decision_id="d1", mission_id="m1", revision="rev1", risk_level=RiskLevel.STANDARD,
        roles_invoked=(CourtRole.ARBITER,), findings_considered=(), verification_refs=(unit_rec.id,),
        reasoning_summary="ok", verdict=CourtVerdict.ACCEPT,
    )
    ag = AntiGamingAnalysisEvidence(
        analysis_id="ag1", mission_id="m1", baseline_revision="rev0", candidate_revision="rev1",
        detector_ids=("detect_x",),
    )
    kwargs = dict(
        mission_id="m1", revision="rev1", required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
        records_by_requirement={"REQ-X-1": (unit_rec,)}, court_decision=decision,
        anti_gaming_evidence=ag, build_records=(build_rec,), unit_test_records=(unit_rec,),
        unit_test_stats={"collected": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0},
        security_records=(sec_rec,), release_policy=_MINIMAL_POLICY,
    )
    kwargs.update(overrides)
    return generate_production_proof(**kwargs)


def test_payload_round_trip_without_db_preserves_hash():
    proof = _proof()
    h1 = compute_proof_hash(proof)
    payload = to_dict(proof)
    reloaded = _payload_to_proof(payload)
    h2 = compute_proof_hash(reloaded)
    assert h1 == h2
    assert proof == reloaded


def test_stale_proof_detected_on_revision_change():
    proof = _proof()
    assert is_proof_stale(proof, current_revision="rev1") is False
    assert is_proof_stale(proof, current_revision="rev2") is True


def test_stale_proof_detected_on_scope_change():
    proof = _proof()
    wider_scope = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST", "SECURITY_TEST"}))
    assert is_proof_stale(
        proof, current_revision="rev1", current_required_requirement_ids=("REQ-X-1",),
        current_required_scopes_by_requirement={"REQ-X-1": wider_scope},
    ) is True


def test_proof_not_stale_when_scope_unchanged():
    proof = _proof()
    assert is_proof_stale(
        proof, current_revision="rev1", current_required_requirement_ids=("REQ-X-1",),
        current_required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    ) is False


def test_stale_proof_cannot_be_reused_to_certify_new_revision():
    old_proof = _proof(revision="rev1")
    assert is_proof_stale(old_proof, current_revision="rev2") is True


def test_stale_proof_detects_new_required_requirement():
    proof = _proof()
    assert is_proof_stale(
        proof, current_revision="rev1", current_required_requirement_ids=("REQ-X-1", "REQ-Y-1"),
        current_required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE, "REQ-Y-1": _UNIT_TEST_SCOPE},
    ) is True


# ── Post-migration application-layer reconciliation ──────────────────

def test_schema_allowed_statuses_includes_not_engineering_ready():
    # The application-layer gate must agree with the MIGRATED
    # production schema (5 values), not the pre-migration 4-value set.
    from orca.mission.production_proof import NOT_ENGINEERING_READY
    assert NOT_ENGINEERING_READY in _SCHEMA_ALLOWED_STATUSES
    assert _SCHEMA_ALLOWED_STATUSES == frozenset({
        "NOT_ENGINEERING_READY", "ENGINEERING_READY", "SUBMISSION_READY", "RELEASE_CANDIDATE", "PUBLISHED",
    })


def test_blocked_proof_release_state_no_longer_rejected_by_application_gate():
    # A genuinely blocked proof's release_state must now pass the
    # application-layer guard in record_proof() -- the exact gap this
    # reconciliation closes (previously this value was outside
    # _CURRENT_SCHEMA_ALLOWED_STATUSES and record_proof() raised).
    blocked = _proof(build_records=())
    assert blocked.release_state == "NOT_ENGINEERING_READY"
    assert blocked.release_state in _SCHEMA_ALLOWED_STATUSES


def test_mismatch_between_sql_status_and_json_release_state_still_raises():
    # Retained per item 6: this defensive check must keep working even
    # though it should no longer be triggered by record_proof() itself
    # post-migration -- a row from any OTHER source with contradictory
    # state must still be refused, never silently accepted.
    proof = _proof()
    payload = to_dict(proof)
    tampered_row = {
        "id": proof.proof_id,
        "categories": json.dumps({**payload, "proof_hash": compute_proof_hash(proof)}),
        "overall_status": "PUBLISHED",  # deliberately disagrees with the payload's real release_state
    }
    with pytest.raises(ProductionProofStoreError):
        _row_to_proof(tampered_row)


def test_matching_sql_status_and_json_release_state_round_trips_cleanly():
    proof = _proof()
    payload = to_dict(proof)
    row = {
        "id": proof.proof_id,
        "categories": json.dumps({**payload, "proof_hash": compute_proof_hash(proof)}),
        "overall_status": proof.release_state,
    }
    reloaded, stored_hash = _row_to_proof(row)
    assert stored_hash == compute_proof_hash(proof)
    assert reloaded == proof
