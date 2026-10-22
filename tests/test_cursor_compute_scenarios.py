"""Scenario labels do not invent capacity."""
from __future__ import annotations

from orca.pretrain_foundation.compute_scenarios import SCENARIOS, frontier_pretraining_available, scenario


def test_no_scenario_is_marked_frontier_pretraining():
    assert frontier_pretraining_available() is False
    for row in SCENARIOS:
        assert row["frontier_pretraining"] is False
        assert row["production_inference"] is False


def test_workstation_note_does_not_claim_frontier_capacity():
    row = scenario("single_workstation")
    assert "not globally competitive" in row["note"]
    assert "₹2.5 lakh" in row["note"]
