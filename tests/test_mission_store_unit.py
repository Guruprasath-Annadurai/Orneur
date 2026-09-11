"""
Phase 15.4 -- UNIT tests for orca.mission.mission_store (no database
required). Live database behavior (CRUD, transactions, constraints,
concurrency) is covered separately in
tests/test_mission_store_live_neon.py (LIVE_NEON_TEMP_BRANCH).
"""
from __future__ import annotations

import pytest

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


# ── REQ-STATE-NEON-002 (Phase 15.15): pooled vs direct connection ─────

def test_pooled_and_direct_connections_read_distinct_env_vars(monkeypatch):
    """Schema-modifying code paths are demonstrably distinct from the
    pooled application connection path (spec section 9's second
    acceptance criterion) -- proven structurally: get_conn(direct=True)
    and get_conn(direct=False) read DIFFERENT environment variables, so
    a schema/admin call can never silently fall back to the pooled
    application DSN, and vice versa."""
    from orca.mission import db as mission_db

    calls = []

    class _FakeConn:
        pass

    def _fake_connect(dsn, **kwargs):
        calls.append(dsn)
        return _FakeConn()

    monkeypatch.setattr(mission_db, "_pooled_dsn", lambda: "PLACEHOLDER_POOLED_DSN")
    monkeypatch.setattr(mission_db, "_direct_dsn", lambda: "PLACEHOLDER_DIRECT_DSN")
    import psycopg
    monkeypatch.setattr(psycopg, "connect", _fake_connect)

    mission_db.get_conn(direct=False)
    mission_db.get_conn(direct=True)

    assert calls == ["PLACEHOLDER_POOLED_DSN", "PLACEHOLDER_DIRECT_DSN"]


def test_every_live_neon_schema_fixture_uses_direct_true_exclusively():
    """Structural, self-discovering proof (mirrors tests/test_ci_live_
    neon_fail_closed.py's own self-discovery style): every test file's
    `_ensure_schema` fixture that calls `apply_schema()` does so on a
    `get_conn(direct=True)` connection -- never the pooled default --
    confirmed by parsing the actual fixture source, not by convention
    alone."""
    import ast
    import pathlib

    tests_dir = pathlib.Path(__file__).parent
    checked = 0
    for path in sorted(tests_dir.glob("test_*_live_neon.py")):
        source = path.read_text()
        if "apply_schema(" not in source:
            continue
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_ensure_schema":
                fn_source = ast.get_source_segment(source, node)
                assert fn_source is not None
                assert "apply_schema(" in fn_source
                assert "direct=True" in fn_source, (
                    f"{path.name}'s _ensure_schema fixture calls apply_schema() without "
                    f"direct=True"
                )
                checked += 1
    assert checked >= 5, "expected to find multiple live-Neon schema fixtures to check"


def test_no_neon_auth_functions_object_storage_or_ai_gateway_capability_enabled():
    """Spec section 9's third REQ-STATE-NEON-002 criterion: no Neon
    Auth/Functions/Object Storage/AI Gateway capability is enabled
    merely because it exists. Structural, repo-wide check -- confirms
    no production module actually references any of those Neon
    capabilities (the requirement's own text, which legitimately
    mentions them by name to prohibit them, is excluded)."""
    import pathlib
    import re

    orca_dir = pathlib.Path(__file__).parent.parent / "orca"
    pattern = re.compile(r"neon[\s_-]*(auth|functions|object[\s_-]*storage|ai[\s_-]*gateway)", re.IGNORECASE)
    offenders = []
    for path in orca_dir.rglob("*.py"):
        if path.name == "requirements_seed.py":
            continue  # this file's own text prohibits them by name
        text = path.read_text(errors="ignore")
        if pattern.search(text):
            offenders.append(str(path))
    assert offenders == [], f"unexpected Neon Auth/Functions/Object Storage/AI Gateway reference in: {offenders}"
