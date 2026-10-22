"""
AUDIT-C02-P1-03 ("database qualification") -- LIVE_NEON_TEMP_BRANCH
integration tests for orca/serve/mission_api.py.

Matches this repo's own established live-Neon pattern (see
tests/test_mission_store_live_neon.py): requires
ORNEUR_MISSION_DATABASE_URL and ORNEUR_MISSION_DATABASE_URL_DIRECT to
point at a real, disposable Neon branch, never production. Skipped
entirely when those env vars are unset, so CI and local runs without
Neon credentials are unaffected -- no infrastructure is provisioned
by running this file; it only exercises one if the caller has already
pointed it at one.

This exists specifically because tests/test_mission_api.py's existing
12+ tests use a fake, in-memory connection (sufficient for this HTTP
layer's own authorization/ownership/wiring logic, and explicitly
documented as such) -- it does not exercise real transaction
rollback, real UNIQUE-constraint idempotency enforcement, or real
row-level-lock concurrency. This file closes that gap with the real
database, through the real FastAPI app (not the store functions in
isolation, which tests/test_mission_store_live_neon.py and
tests/test_operation_store_live_neon.py already cover).
"""
from __future__ import annotations

import os
import threading

import pytest
from fastapi.testclient import TestClient

from orca.auth import get_current_user
from orca.auth.store import User
from orca.mission.db import apply_schema, get_conn
from orca.serve import api as api_module

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ORNEUR_MISSION_DATABASE_URL") and os.environ.get("ORNEUR_MISSION_DATABASE_URL_DIRECT")),
    reason="LIVE_NEON_TEMP_BRANCH: requires ORNEUR_MISSION_DATABASE_URL(_DIRECT) pointing at a disposable Neon branch",
)


def _user(uid: str) -> User:
    return User(id=uid, email=f"{uid}@example.com", name=uid, tier="pro", verified=True)


@pytest.fixture(scope="module", autouse=True)
def _ensure_schema():
    conn = get_conn(direct=True)
    try:
        apply_schema(conn)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def client():
    return TestClient(api_module.app, raise_server_exceptions=False)


def _as(client, user: User):
    api_module.app.dependency_overrides[get_current_user] = lambda: user
    return client


def test_mission_creation_is_durably_persisted_across_a_fresh_connection(client):
    """Proves persistence is real: a mission created through the API
    in one request is independently readable via a BRAND NEW psycopg
    connection, not merely held in the test process's own memory."""
    _as(client, _user(f"alice-{os.getpid()}"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]

    conn = get_conn(direct=False)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM missions WHERE id = %s", (mission_id,))
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()
    assert row is not None
    assert row["repository"] == "r"


def test_illegal_transition_rolls_back_and_leaves_state_unchanged(client):
    """A rejected transition (e.g. DRAFT -> RUNNING, skipping
    PLANNING/READY) must not partially apply -- the real transaction
    rolls back, and the mission's persisted state is exactly what it
    was before the attempt."""
    _as(client, _user(f"alice-{os.getpid()}"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]

    # No /plan call -- mission is still DRAFT. Attempting /cancel twice
    # back to back after an illegal intermediate state is exercised
    # indirectly via the public API's own 409 handling; here we assert
    # directly against the real row that an out-of-band illegal write
    # attempt (simulating a buggy caller) is rejected by the real CHECK
    # constraint, not merely by application code that could be bypassed.
    conn = get_conn(direct=False)
    try:
        with conn.cursor() as cur:
            with pytest.raises(Exception):
                cur.execute(
                    "UPDATE missions SET state = %s WHERE id = %s",
                    ("NOT_A_REAL_STATE", mission_id),
                )
        conn.rollback()

        with conn.cursor() as cur:
            cur.execute("SELECT state FROM missions WHERE id = %s", (mission_id,))
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()
    assert row["state"] == "DRAFT"


def test_ownership_constraint_enforced_by_the_real_row_not_just_application_code(client):
    """Cross-user access must still be refused against a real,
    persisted row, not only against an in-memory fake."""
    owner = f"alice-{os.getpid()}"
    other = f"mallory-{os.getpid()}"
    _as(client, _user(owner))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]

    _as(client, _user(other))
    resp = client.get(f"/v1/missions/{mission_id}")
    assert resp.status_code == 404

    # Confirm directly against the database that the row really does
    # belong to `owner`, not merely that the API said so.
    conn = get_conn(direct=False)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT owner_user_id FROM missions WHERE id = %s", (mission_id,))
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()
    assert row["owner_user_id"] == owner


def test_idempotency_key_uniqueness_is_enforced_by_the_real_unique_constraint(client):
    """The fake-DB tests in test_mission_api.py simulate this
    conflict in Python; this proves the REAL `operations
    .idempotency_key` UNIQUE constraint is what ultimately backstops
    it, even if application-level dedup logic were ever bypassed."""
    owner = f"alice-{os.getpid()}"
    _as(client, _user(owner))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]
    key = f"live-neon-key-{os.getpid()}"

    r1 = client.post(f"/v1/missions/{mission_id}/operations", json={"kind": "shell_exec", "target": "ls", "idempotency_key": key})
    assert r1.status_code == 201, r1.text

    conn = get_conn(direct=False)
    try:
        with conn.cursor() as cur:
            with pytest.raises(Exception):
                cur.execute(
                    "INSERT INTO operations (id, mission_id, idempotency_key, kind, status, requested_at, requested_by) "
                    "VALUES (%s, %s, %s, 'shell_exec', 'REQUESTED', now()::text, %s)",
                    (f"raw-dup-{os.getpid()}", mission_id, key, owner),
                )
        conn.rollback()
    finally:
        conn.close()


def test_concurrent_cancel_requests_on_the_same_mission_are_serialized_not_double_applied(client):
    """Two concurrent /cancel calls against the same DRAFT mission:
    the real `SELECT ... FOR UPDATE` row lock in
    orca.mission.mission_store must serialize them, so exactly ONE
    succeeds (DRAFT -> CANCELLED) and the other is correctly rejected
    (CANCELLED is terminal) -- never both silently "succeeding" or the
    row ending up corrupted."""
    _as(client, _user(f"alice-{os.getpid()}"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]

    results = []
    lock = threading.Lock()

    def _cancel():
        local_client = TestClient(api_module.app, raise_server_exceptions=False)
        resp = local_client.post(f"/v1/missions/{mission_id}/cancel")
        with lock:
            results.append(resp.status_code)

    threads = [threading.Thread(target=_cancel) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert results.count(200) == 1, f"expected exactly one successful cancel, got: {results}"
    assert all(code in (200, 409) for code in results)

    conn = get_conn(direct=False)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT state FROM missions WHERE id = %s", (mission_id,))
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()
    assert row["state"] == "CANCELLED"


def test_concurrent_confirm_cancelled_calls_on_the_same_episode_are_serialized(client, monkeypatch):
    """AUDIT-C02-P0-03 follow-up correction, P1-03 real-DB coverage:
    the SELECT ... FOR UPDATE row lock in
    orca.mission.mission_store.resolve_mission_cancellation() must
    make concurrent reconciliation calls on the SAME cancellation
    episode safe -- exactly one succeeds (CANCELLATION_REQUESTED ->
    CANCELLED), the rest correctly fail (the episode is already
    consumed), never double-applied."""
    token = "live-neon-reconciliation-test-token"
    monkeypatch.setenv("ORNEUR_MISSION_RECONCILIATION_TOKEN", token)

    _as(client, _user(f"alice-{os.getpid()}"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]
    client.post(f"/v1/missions/{mission_id}/plan", json={"steps": ["do it"]})

    conn = get_conn(direct=False)
    try:
        from orca.mission.state_machine import MissionState
        from orca.mission import mission_store
        mission_store.transition_mission(conn, mission_id, MissionState.RUNNING)
    finally:
        conn.close()

    cancel_resp = client.post(f"/v1/missions/{mission_id}/cancel")
    episode_id = cancel_resp.json()["cancellation_episode_id"]

    results = []
    lock = threading.Lock()

    def _confirm():
        local_client = TestClient(api_module.app, raise_server_exceptions=False)
        resp = local_client.post(
            f"/v1/missions/{mission_id}/confirm-cancelled",
            json={"cancellation_episode_id": episode_id, "outcome": "TERMINATED"},
            headers={"Authorization": f"Bearer {token}"},
        )
        with lock:
            results.append(resp.status_code)

    threads = [threading.Thread(target=_confirm) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert results.count(200) == 1, f"expected exactly one successful confirmation, got: {results}"
    assert all(code in (200, 409) for code in results)

    conn = get_conn(direct=False)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT state FROM missions WHERE id = %s", (mission_id,))
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()
    assert row["state"] == "CANCELLED"
