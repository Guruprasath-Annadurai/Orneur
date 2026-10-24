"""Scenario labels do not invent capacity."""
from __future__ import annotations

from orca.pretrain_foundation.compute_scenarios import (
    FREE_TIER_OBSERVATIONS,
    PRICE,
    QUALIFICATION,
    SCENARIOS,
    frontier_pretraining_available,
    scenario,
)


def test_no_scenario_is_marked_frontier_pretraining():
    assert frontier_pretraining_available() is False
    for row in SCENARIOS:
        assert row["frontier_pretraining"] is False
        assert row["production_inference"] is False


def test_workstation_note_does_not_claim_frontier_capacity():
    row = scenario("single_workstation")
    assert "not globally competitive" in row["note"]
    assert "₹2.5 lakh" in row["note"]
    assert row["qualification"] == QUALIFICATION
    assert row["price"] == PRICE
    assert row["throughput_measured"] is False
    assert row["price"] != 0


def test_free_tier_notes_are_not_enrolled_capacity():
    assert FREE_TIER_OBSERVATIONS
    for row in FREE_TIER_OBSERVATIONS:
        assert row["enrolled_for_orneur"] is False
        assert row["qualification"] == "COMPUTE_NOT_QUALIFIED"
        assert row["price"] == "UNKNOWN"
        assert row["retrieved"] == "2026-10-24"
