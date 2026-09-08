"""
Phase 15.2 -- orca.mission.db connection-config tests.

These test the FAIL-CLOSED config-error path only (no live database
needed) -- get_conn() must never silently fall back to a wrong
connection type when the required env var is missing. Live connection
behavior (actually applying the schema, exercising CHECK/FK/UNIQUE
constraints) was verified directly against real Neon infrastructure
-- see docs/orneur/phase-15/PHASE15_EVIDENCE.md's Phase 15.2 checkpoint.
"""
from __future__ import annotations

import pytest

from orca.mission.db import MissionDatabaseConfigError, get_conn


def test_pooled_connection_requires_env_var(monkeypatch):
    monkeypatch.delenv("ORNEUR_MISSION_DATABASE_URL", raising=False)
    monkeypatch.delenv("ORCA_MISSION_DATABASE_URL", raising=False)
    with pytest.raises(MissionDatabaseConfigError):
        get_conn(direct=False)


def test_direct_connection_requires_env_var(monkeypatch):
    monkeypatch.delenv("ORNEUR_MISSION_DATABASE_URL_DIRECT", raising=False)
    monkeypatch.delenv("ORCA_MISSION_DATABASE_URL_DIRECT", raising=False)
    with pytest.raises(MissionDatabaseConfigError):
        get_conn(direct=True)


def test_direct_connection_does_not_fall_back_to_pooled_url(monkeypatch):
    """A missing direct/unpooled URL must never silently reuse the
    pooled URL for schema/admin operations (spec section 9) -- even
    when the pooled URL IS configured."""
    monkeypatch.setenv("ORNEUR_MISSION_DATABASE_URL", "postgresql://pooled-should-not-be-used")
    monkeypatch.delenv("ORNEUR_MISSION_DATABASE_URL_DIRECT", raising=False)
    monkeypatch.delenv("ORCA_MISSION_DATABASE_URL_DIRECT", raising=False)
    with pytest.raises(MissionDatabaseConfigError):
        get_conn(direct=True)
