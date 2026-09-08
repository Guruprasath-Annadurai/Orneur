"""
Phase 15.7 -- LIVE_NEON_TEMP_BRANCH: proves a compiled Product
Contract genuinely associates with a REAL, durable Mission via the
existing Phase 15 mission system (spec section 14) -- not a second,
parallel mission representation. The Product Contract/Fact/
AcceptanceCriterion layers themselves stay in-process this phase
(disclosed in the module docstrings and the evidence checkpoint,
spec section 18), but the mission they link to is the real durable
one, proven here by creating it, closing the connection, and
reloading it through a brand-new connection.

Skipped when ORNEUR_MISSION_DATABASE_URL(_DIRECT) are unset, matching
every other Phase 15 live-Neon test file.
"""
from __future__ import annotations

import os
import uuid

import pytest

from orca.mission import acceptance_criteria as ac_module
from orca.mission import assumption_model, product_contract, requirements as requirements_module
from orca.mission.db import apply_schema, get_conn
from orca.mission.idea_compiler import CompiledRequirement, compile_idea
from orca.mission.mission_store import create_mission, get_mission

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ORNEUR_MISSION_DATABASE_URL") and os.environ.get("ORNEUR_MISSION_DATABASE_URL_DIRECT")),
    reason="LIVE_NEON_TEMP_BRANCH: requires ORNEUR_MISSION_DATABASE_URL(_DIRECT) pointing at a disposable Neon branch",
)


@pytest.fixture(scope="module", autouse=True)
def _ensure_schema():
    conn = get_conn(direct=True)
    try:
        apply_schema(conn)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _clean():
    requirements_module.reset_registry_for_tests()
    product_contract.reset_registry_for_tests()
    assumption_model.reset_registry_for_tests()
    ac_module.reset_registry_for_tests()
    yield
    requirements_module.reset_registry_for_tests()
    product_contract.reset_registry_for_tests()
    assumption_model.reset_registry_for_tests()
    ac_module.reset_registry_for_tests()


def _mission_id() -> str:
    return f"mis_{uuid.uuid4().hex[:12]}"


def test_compiled_contract_links_to_a_real_durable_mission():
    conn_a = get_conn(direct=False)
    mission_id = _mission_id()
    try:
        real_mission = create_mission(
            conn_a, id=mission_id, repository="org/repo", mode="BUILD",
            autonomy_level="L1", owner_user_id="user_alice",
        )
        assert real_mission["id"] == mission_id
    finally:
        conn_a.close()  # simulated process boundary -- next reload uses a FRESH connection

    result = compile_idea(
        contract_id=f"contract-{mission_id}", product_name="TaskManager",
        raw_idea="Build a multi-tenant task-management web app for organization admins.",
        mission_id=mission_id,
        explicit_requirements=(
            CompiledRequirement(area="FUNC", statement="Admins can create teams within their organization.",
                                 acceptance_criteria=("A test creates a team and confirms it is listed.",)),
        ),
    )
    assert result.contract.mission_id == mission_id

    conn_b = get_conn(direct=False)
    try:
        reloaded_mission = get_mission(conn_b, mission_id)
        assert reloaded_mission is not None
        assert reloaded_mission["id"] == result.contract.mission_id
    finally:
        conn_b.close()

    for fid in result.fact_ids:
        fact = assumption_model.get_fact(fid)
        assert fact.mission_id == mission_id
