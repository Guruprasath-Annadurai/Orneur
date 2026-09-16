"""
Closure: freshness timezone safety. Reproduced defect: an
offset-aware overlay.assessed_at ('2026-01-01T00:00:00+00:00')
subtracted against an offset-naive evaluated_at
('2026-06-01T00:00:00') raised a raw Python TypeError ("can't subtract
offset-naive and offset-aware datetimes") that escaped the public
boundary. Fixed: floor.parse_aware_iso8601() rejects any naive
timestamp (no tzinfo) with a typed error before it ever reaches a
subtraction.
"""
from __future__ import annotations

import pytest

from orneur.intelligence.epistemic.enums import EpistemicPolarity
from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.contracts import IntegrityPolicy, IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import IntegrityStatus, PresentationTreatment
from orneur.intelligence.integrity.evaluator import assess_integrity
from orneur.intelligence.integrity.floor import is_overlay_stale
from tests.integrity.conftest import ASSESSED_AT, build_known_affirmed_fixture


def _proposal():
    return IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))


def test_aware_overlay_naive_evaluated_at_rejected_not_raw_typeerror():
    artifact, overlay = build_known_affirmed_fixture()
    assert overlay.assessed_at == ASSESSED_AT  # offset-aware, "+00:00"
    policy = IntegrityPolicy(max_overlay_age_seconds=60)
    try:
        assess_integrity(_proposal(), overlay=overlay, artifact=artifact, policy=policy, evaluated_at="2026-06-01T00:00:00")
        assert False, "expected an exception"
    except errors.IntegrityError:
        pass
    except TypeError as exc:
        pytest.fail(f"a raw TypeError escaped instead of a typed IntegrityError: {exc}")


def test_naive_overlay_assessed_at_rejected_directly_in_is_overlay_stale():
    """Direct unit test of the lower-level function against a
    hypothetical naive overlay timestamp, in case a malformed overlay
    ever reaches this path."""
    with pytest.raises(errors.IntegrityError):
        is_overlay_stale(
            overlay_assessed_at="2026-01-01T00:00:00",  # naive
            evaluated_at="2026-06-01T00:00:00+00:00",  # aware
            max_overlay_age_seconds=60,
        )


def test_two_aware_timestamps_different_offsets_same_instant_compare_correctly():
    """2026-01-01T01:00:00+01:00 and 2026-01-01T00:00:00+00:00 are the
    SAME instant -- age must be computed as zero, not as a spurious
    one-hour difference."""
    assert is_overlay_stale(
        overlay_assessed_at="2026-01-01T01:00:00+01:00",
        evaluated_at="2026-01-01T00:00:00+00:00",
        max_overlay_age_seconds=0,
    ) is False


def test_equivalent_offset_timestamps_produce_deterministic_staleness_result():
    # 30 minutes later in a different offset representation of the same
    # absolute time window.
    assert is_overlay_stale(
        overlay_assessed_at="2026-01-01T00:00:00+00:00",
        evaluated_at="2026-01-01T01:30:00+01:00",  # = 2026-01-01T00:30:00+00:00 -> 30 min later
        max_overlay_age_seconds=3600,
    ) is False
    assert is_overlay_stale(
        overlay_assessed_at="2026-01-01T00:00:00+00:00",
        evaluated_at="2026-01-01T03:30:00+03:00",  # = 2026-01-01T00:30:00+00:00 -> 30 min later
        max_overlay_age_seconds=60,
    ) is True


def test_malformed_offset_rejected():
    with pytest.raises(errors.IntegrityError):
        is_overlay_stale(
            overlay_assessed_at="2026-01-01T00:00:00+00:00",
            evaluated_at="not-a-real-timestamp",
            max_overlay_age_seconds=60,
        )


def test_z_suffix_is_accepted_as_aware():
    assert is_overlay_stale(
        overlay_assessed_at="2026-01-01T00:00:00Z",
        evaluated_at="2026-01-01T00:30:00Z",
        max_overlay_age_seconds=3600,
    ) is False


def test_evaluated_at_top_level_validation_rejects_naive_even_without_policy():
    """evaluated_at is validated as offset-aware unconditionally when
    supplied, independent of whether a freshness policy is even active
    -- a single, predictable rule rather than two-tier strictness."""
    artifact, overlay = build_known_affirmed_fixture()
    with pytest.raises(errors.IntegrityError):
        assess_integrity(_proposal(), overlay=overlay, artifact=artifact, evaluated_at="2026-06-01T00:00:00")


def test_aware_evaluated_at_without_policy_is_fine():
    artifact, overlay = build_known_affirmed_fixture()
    receipt = assess_integrity(_proposal(), overlay=overlay, artifact=artifact, evaluated_at="2026-06-01T00:00:00+00:00")
    assert receipt.integrity_status is IntegrityStatus.SATISFIED
    assert receipt.evaluated_at == "2026-06-01T00:00:00+00:00"
