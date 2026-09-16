"""Section 23/33-K: freshness is explicit-policy only, never a wall-clock
default or a universal age heuristic."""
from __future__ import annotations

import pytest

from orneur.intelligence.epistemic.enums import EpistemicPolarity
from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.contracts import IntegrityPolicy, IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import IntegrityStatus, IntegrityViolationReason, PresentationTreatment
from tests.integrity.conftest import assess_integrity_trusted as assess_integrity, ASSESSED_AT, build_known_affirmed_fixture


def _proposal():
    return IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))


def test_no_freshness_policy_means_not_evaluated_not_fresh():
    """Absence of a freshness policy must not silently claim freshness --
    it means the check simply never ran (no STALE_EPISTEMIC_OVERLAY
    violation either way, and no implicit pass/fail claim about age)."""
    artifact, overlay = build_known_affirmed_fixture()
    receipt = assess_integrity(_proposal(), overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED
    assert not any(v.reason is IntegrityViolationReason.STALE_EPISTEMIC_OVERLAY for v in receipt.violations)


def test_configured_stale_overlay_is_blocked():
    artifact, overlay = build_known_affirmed_fixture()
    assert overlay.assessed_at == ASSESSED_AT  # 2026-01-01T00:00:00+00:00
    policy = IntegrityPolicy(max_overlay_age_seconds=60)  # 1 minute
    receipt = assess_integrity(
        _proposal(), overlay=overlay, artifact=artifact, policy=policy,
        evaluated_at="2026-06-01T00:00:00+00:00",  # far past the 60s window
    )
    assert receipt.integrity_status is IntegrityStatus.BLOCKED
    assert any(v.reason is IntegrityViolationReason.STALE_EPISTEMIC_OVERLAY for v in receipt.violations)


def test_configured_fresh_overlay_within_window_passes():
    artifact, overlay = build_known_affirmed_fixture()
    policy = IntegrityPolicy(max_overlay_age_seconds=3600)
    receipt = assess_integrity(
        _proposal(), overlay=overlay, artifact=artifact, policy=policy,
        evaluated_at="2026-01-01T00:30:00+00:00",  # 30 minutes later, within 1 hour window
    )
    assert receipt.integrity_status is IntegrityStatus.SATISFIED


def test_max_age_without_evaluated_at_fails_closed():
    artifact, overlay = build_known_affirmed_fixture()
    policy = IntegrityPolicy(max_overlay_age_seconds=60)
    with pytest.raises(errors.InvalidFreshnessConfiguration):
        assess_integrity(_proposal(), overlay=overlay, artifact=artifact, policy=policy)  # no evaluated_at


def test_determinism_with_explicit_evaluation_time_no_clock_dependency():
    artifact, overlay = build_known_affirmed_fixture()
    policy = IntegrityPolicy(max_overlay_age_seconds=3600)
    r1 = assess_integrity(_proposal(), overlay=overlay, artifact=artifact, policy=policy, evaluated_at="2026-01-01T00:30:00+00:00", receipt_id="fixed")
    r2 = assess_integrity(_proposal(), overlay=overlay, artifact=artifact, policy=policy, evaluated_at="2026-01-01T00:30:00+00:00", receipt_id="fixed")
    from orneur.intelligence.integrity.canonical import digest

    assert digest(r1) == digest(r2)


def test_negative_max_overlay_age_seconds_rejected():
    artifact, overlay = build_known_affirmed_fixture()
    policy = IntegrityPolicy(max_overlay_age_seconds=-1)
    with pytest.raises(errors.InvalidFreshnessConfiguration):
        assess_integrity(_proposal(), overlay=overlay, artifact=artifact, policy=policy, evaluated_at="2026-01-01T00:30:00+00:00")


def test_bool_max_overlay_age_seconds_rejected():
    """bool masquerading as int must be rejected -- isinstance(True, int)
    is True in Python, so this needs an explicit guard."""
    artifact, overlay = build_known_affirmed_fixture()
    policy = IntegrityPolicy(max_overlay_age_seconds=True)  # type: ignore[arg-type]
    with pytest.raises(errors.InvalidFreshnessConfiguration):
        assess_integrity(_proposal(), overlay=overlay, artifact=artifact, policy=policy, evaluated_at="2026-01-01T00:30:00+00:00")
