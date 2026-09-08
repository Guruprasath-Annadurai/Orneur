"""
Phase 15.4 -- UNIT tests for orca.mission.mission_store (no database
required). Live database behavior (CRUD, transactions, constraints,
concurrency) is covered separately in
tests/test_mission_store_live_neon.py (LIVE_NEON_TEMP_BRANCH).
"""
from __future__ import annotations

from orca.mission.mission_store import Checkpoint


def _row(**overrides) -> dict:
    base = {
        "id": "ckpt_1",
        "mission_id": "mis_1",
        "created_at": "2026-09-08T00:00:00Z",
        "mission_state": "PAUSED_USER",
        "current_step_id": "step_2",
        "completed_step_ids": "[\"step_0\", \"step_1\"]",
        "remaining_step_ids": "[\"step_2\"]",
        "repository": "github.com/example/repo",
        "branch": "main",
        "base_revision": "abc",
        "current_revision": "def",
        "diff_ref": None,
        "requirement_states": "{\"REQ-X-001\": \"IMPLEMENTED\"}",
        "test_states": "{}",
        "verification_states": "{}",
        "evidence_refs": "[]",
        "pending_approvals": "[]",
        "active_blocker": None,
        "resource_budget_state": None,
        "tool_outcomes": "[]",
        "environment_identity": None,
    }
    base.update(overrides)
    return base


def test_from_row_parses_json_columns():
    ckpt = Checkpoint.from_row(_row())
    assert ckpt.completed_step_ids == ("step_0", "step_1")
    assert ckpt.remaining_step_ids == ("step_2",)
    assert ckpt.requirement_states == {"REQ-X-001": "IMPLEMENTED"}


def test_from_row_leaves_genuinely_absent_fields_none():
    ckpt = Checkpoint.from_row(_row())
    assert ckpt.diff_ref is None
    assert ckpt.active_blocker is None
    assert ckpt.resource_budget_state is None
    assert ckpt.environment_identity is None


def test_from_row_parses_nested_resource_budget_state():
    ckpt = Checkpoint.from_row(_row(resource_budget_state="{\"tokens_used\": 1000}"))
    assert ckpt.resource_budget_state == {"tokens_used": 1000}


def test_from_row_parses_tool_outcomes_list_of_dicts():
    ckpt = Checkpoint.from_row(_row(tool_outcomes="[{\"tool\": \"pytest\", \"status\": \"ok\"}]"))
    assert ckpt.tool_outcomes == ({"tool": "pytest", "status": "ok"},)
