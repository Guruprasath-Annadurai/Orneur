"""
Phase 15.10 -- Production Proof store tests that do not require a live
database connection: canonical payload round-trip via the store's own
(de)serialization helpers, and stale-proof detection (spec section
31). Durable persistence itself (write/reload across a fresh
connection, append-only history) is qualified against a real
disposable Neon branch in `tests/test_production_proof_live_neon.py`,
matching every other Phase 15 durable-store test file's split.
"""
from __future__ import annotations

from orca.mission.cognitive_court import CourtDecision, CourtRole, CourtVerdict, RiskLevel
from orca.mission.production_proof import compute_proof_hash, generate_production_proof, to_dict
from orca.mission.production_proof_store import _payload_to_proof, is_proof_stale
from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import RequiredVerificationScope

_UNIT_TEST_SCOPE = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST"}))


def _rec(**overrides):
    defaults = dict(
        id="v1", mission_id="m1", requirement_id="REQ-X-1", criterion_id=None, category="UNIT_TEST",
        verification_method="UNIT_TEST", verifier_id="UnitTestVerifier", started_at="2026-01-01T00:00:00Z",
        outcome=VerificationOutcome.PASS, revision="rev1", evidence_refs=("x",),
    )
    defaults.update(overrides)
    return VerificationRecord(**defaults)


def _proof(**overrides):
    record = _rec()
    decision = CourtDecision(
        decision_id="d1", mission_id="m1", revision="rev1", risk_level=RiskLevel.STANDARD,
        roles_invoked=(CourtRole.ARBITER,), findings_considered=(), verification_refs=(record.id,),
        reasoning_summary="ok", verdict=CourtVerdict.ACCEPT,
    )
    kwargs = dict(
        mission_id="m1", revision="rev1", required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
        records_by_requirement={"REQ-X-1": (record,)}, court_decision=decision,
        anti_gaming_analysis_performed=True, build_records=(record,), unit_test_records=(record,),
        unit_test_stats={"collected": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0},
        security_records=(record,),
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
        proof, current_revision="rev1",
        current_required_scopes_by_requirement={"REQ-X-1": wider_scope},
    ) is True


def test_proof_not_stale_when_scope_unchanged():
    proof = _proof()
    assert is_proof_stale(
        proof, current_revision="rev1",
        current_required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    ) is False


def test_stale_proof_cannot_be_reused_to_certify_new_revision():
    # A caller checking whether an OLD proof can certify a NEW revision
    # must see it as stale -- this is the exact "proof for revision A
    # cannot certify revision B" invariant (spec section 31).
    old_proof = _proof(revision="rev1")
    assert is_proof_stale(old_proof, current_revision="rev2") is True
