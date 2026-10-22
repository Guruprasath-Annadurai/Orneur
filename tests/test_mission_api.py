"""
Integration tests for orca/serve/mission_api.py -- the new C02 Mission
Execution REST surface over the existing, already-tested
`orca.mission` engine.

These tests exercise the actual FastAPI wiring (TestClient against the
real `app`), not the underlying mission_store/operation_store units in
isolation (those already have their own dedicated test suites). The
mission-DB connection itself is faked via `app.dependency_overrides`
on `orca.serve.mission_api._mission_conn` -- a lightweight in-memory
fake that implements just enough of the psycopg cursor/connection
protocol (`%s` placeholders, `cur.fetchone()`/`fetchall()` returning
dict-like rows, `conn.commit()`/`rollback()`) for mission_store and
operation_store's real, unmodified code to run against it. This tests
THIS FILE's own authorization/ownership/wiring logic for real, without
requiring a live Neon connection (covered separately and already by
the existing `tests/test_*_live_neon.py` suites).

Per the CTO directive's explicit "essential integration tests" list,
this file focuses on: unauthorized creation, cross-user/cross-tenant
access, self-approval rejection, approval denial, and duplicate
side-effect prevention (idempotency).
"""
from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from orca.auth import get_current_user
from orca.auth.store import User
from orca.mission import mission_store
from orca.mission.mission_store import CancellationEvidenceError
from orca.mission.state_machine import MissionState
from orca.serve import api as api_module
from orca.serve.mission_api import _mission_conn


def _user(uid: str) -> User:
    return User(id=uid, email=f"{uid}@example.com", name=uid, tier="pro", verified=True)


class _FakeCursor:
    def __init__(self, db):
        self._db = db
        self._result: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params: tuple = ()):
        sql_norm = " ".join(sql.split())
        if sql_norm.startswith("INSERT INTO missions"):
            cols = ["id", "workspace_id", "repository", "branch", "base_revision", "current_revision",
                    "mode", "autonomy_level", "state", "owner_user_id", "window_started_at",
                    "window_deadline_at", "created_at", "updated_at"]
            row = dict(zip(cols, params))
            row["cancellation_episode_id"] = None
            row["cancellation_episode_revision"] = None
            self._db["missions"][row["id"]] = row
            self._result = []
        elif sql_norm.startswith("SELECT * FROM missions WHERE id = %s"):
            row = self._db["missions"].get(params[0])
            self._result = [row] if row else []
        elif sql_norm.startswith("SELECT * FROM missions WHERE owner_user_id = %s"):
            rows = [r for r in self._db["missions"].values() if r["owner_user_id"] == params[0]]
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            self._result = rows
        elif sql_norm.startswith("UPDATE missions SET state = %s, cancellation_episode_id = %s, cancellation_episode_revision = %s"):
            # request_mission_cancellation(): params (new_state, episode_id, revision, updated_at, mission_id, expected_state)
            new_state, episode_id, revision, _updated_at, mission_id, expected_state = params
            row = self._db["missions"][mission_id]
            if row["state"] == expected_state:
                row["state"] = new_state
                row["cancellation_episode_id"] = episode_id
                row["cancellation_episode_revision"] = revision
                self._rowcount = 1
            else:
                self._rowcount = 0
            self._result = []
        elif sql_norm.startswith("UPDATE missions SET state = %s, cancellation_episode_id = %s"):
            # resolve_mission_cancellation(): params (new_state, new_episode_id, updated_at, mission_id, expected_state)
            new_state, new_episode_id, _updated_at, mission_id, expected_state = params
            row = self._db["missions"][mission_id]
            if row["state"] == expected_state:
                row["state"] = new_state
                row["cancellation_episode_id"] = new_episode_id
                self._rowcount = 1
            else:
                self._rowcount = 0
            self._result = []
        elif sql_norm.startswith("UPDATE missions SET state"):
            # params: (new_state, updated_at, mission_id, expected_current_state)
            new_state, _updated_at, mission_id, expected_state = params
            row = self._db["missions"][mission_id]
            if row["state"] == expected_state:
                row["state"] = new_state
                self._rowcount = 1
            else:
                self._rowcount = 0
            self._result = []
        elif sql_norm.startswith("SELECT state FROM missions WHERE id = %s FOR UPDATE"):
            row = self._db["missions"].get(params[0])
            self._result = [{"state": row["state"]}] if row else []
        elif sql_norm.startswith("INSERT INTO operations"):
            # NOTE: the real SQL's VALUES clause has a literal 'REQUESTED'
            # for `status` (not a %s placeholder), so `params` has only 7
            # entries for these 7 columns -- `status` is set explicitly
            # below, not from `params`.
            cols = ["id", "mission_id", "idempotency_key", "kind", "requested_at",
                    "parameters_fingerprint", "requested_by"]
            row = dict(zip(cols, params))
            row["status"] = "REQUESTED"
            row["authorized_at"] = None
            row["started_at"] = None
            row["result_ref"] = None
            existing_key = next((r for r in self._db["operations"].values() if r["idempotency_key"] == row["idempotency_key"]), None)
            if existing_key is not None:
                self._result = []
            else:
                self._db["operations"][row["id"]] = row
                self._result = [{"id": row["id"]}]
        elif (
            sql_norm.startswith("SELECT * FROM operations WHERE id = %s FOR UPDATE")
            or sql_norm.startswith("SELECT * FROM operations WHERE id = %s")
            or sql_norm.startswith("SELECT status FROM operations WHERE id = %s FOR UPDATE")
        ):
            row = self._db["operations"].get(params[0])
            self._result = [row] if row else []
        elif sql_norm.startswith("SELECT * FROM operations WHERE idempotency_key = %s"):
            row = next((r for r in self._db["operations"].values() if r["idempotency_key"] == params[0]), None)
            self._result = [row] if row else []
        elif sql_norm.startswith("UPDATE operations SET status='AUTHORIZED'"):
            now, op_id = params
            row = self._db["operations"][op_id]
            if row["status"] == "REQUESTED":
                row["status"] = "AUTHORIZED"
                row["authorized_at"] = now
                self._rowcount = 1
            else:
                self._rowcount = 0
            self._result = []
        elif sql_norm.startswith("UPDATE operations SET status=%s"):
            new_status, op_id = params[0], params[-1]
            row = self._db["operations"][op_id]
            row["status"] = new_status
            self._result = []
            self._rowcount = 1
        elif sql_norm.startswith("INSERT INTO authority_decisions") or sql_norm.startswith("INSERT INTO approvals"):
            self._result = []
        elif sql_norm.startswith("INSERT INTO mission_steps"):
            cols = ["id", "mission_id", "step_index", "description", "created_at"]
            row = dict(zip(cols, params))
            row["status"] = "PENDING"
            row["started_at"] = None
            row["completed_at"] = None
            self._db["mission_steps"][row["id"]] = row
            self._result = []
        elif sql_norm.startswith("SELECT * FROM mission_steps WHERE mission_id = %s"):
            rows = [r for r in self._db["mission_steps"].values() if r["mission_id"] == params[0]]
            rows.sort(key=lambda r: r["step_index"])
            self._result = rows
        else:
            raise AssertionError(f"FakeCursor: unhandled SQL: {sql_norm[:120]}")

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)

    @property
    def rowcount(self):
        return getattr(self, "_rowcount", len(self._result))


class _FakeConn:
    def __init__(self, db):
        self._db = db

    def cursor(self):
        return _FakeCursor(self._db)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def shared_db():
    return {"missions": {}, "operations": {}, "mission_steps": {}}


@pytest.fixture
def client(shared_db):
    def _fake_conn_dep():
        conn = _FakeConn(shared_db)
        try:
            yield conn
        finally:
            conn.close()

    api_module.app.dependency_overrides[_mission_conn] = _fake_conn_dep
    try:
        yield TestClient(api_module.app, raise_server_exceptions=False)
    finally:
        api_module.app.dependency_overrides.pop(_mission_conn, None)
        api_module.app.dependency_overrides.pop(get_current_user, None)


def _as(client, user: User):
    api_module.app.dependency_overrides[get_current_user] = lambda: user
    return client


def test_unauthenticated_creation_is_rejected(client):
    """No auth override installed at all: must be rejected, never
    silently treated as anonymous/owner-less."""
    resp = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"})
    assert resp.status_code == 401


def test_authenticated_creation_binds_server_derived_owner(client):
    _as(client, _user("alice"))
    resp = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["owner_user_id"] == "alice"
    assert body["state"] == "DRAFT"


def test_cross_user_access_to_someone_elses_mission_is_404_not_403(client):
    """A mission that exists but belongs to another user must look
    IDENTICAL to one that doesn't exist at all -- never a 403 that
    would let a caller distinguish 'exists but not mine' from 'does
    not exist', which would leak other tenants' mission IDs."""
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]

    _as(client, _user("mallory"))
    resp = client.get(f"/v1/missions/{mission_id}")
    assert resp.status_code == 404

    resp_nonexistent = client.get("/v1/missions/does-not-exist")
    assert resp_nonexistent.status_code == 404
    # error_id is intentionally unique per request (correlation id);
    # the user-facing detail must be identical either way.
    assert resp.json()["detail"] == resp_nonexistent.json()["detail"] == "mission not found"


def test_cross_user_cannot_plan_or_cancel_someone_elses_mission(client):
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]

    _as(client, _user("mallory"))
    assert client.post(f"/v1/missions/{mission_id}/plan", json={"steps": ["do the thing"]}).status_code == 404
    assert client.post(f"/v1/missions/{mission_id}/cancel").status_code == 404


def test_mission_list_is_owner_filtered(client):
    _as(client, _user("alice"))
    client.post("/v1/missions", json={"repository": "r1", "mode": "ASSIST", "autonomy_level": "L0"})
    _as(client, _user("bob"))
    client.post("/v1/missions", json={"repository": "r2", "mode": "ASSIST", "autonomy_level": "L0"})

    _as(client, _user("alice"))
    resp = client.get("/v1/missions")
    assert resp.status_code == 200
    repos = [m["repository"] for m in resp.json()["missions"]]
    assert repos == ["r1"]


def test_plan_transitions_draft_to_ready_and_persists_real_steps(client):
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]
    resp = client.post(f"/v1/missions/{mission_id}/plan", json={"steps": ["clone repo", "run tests", "open PR"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "READY"

    steps = client.get(f"/v1/missions/{mission_id}/steps").json()["steps"]
    assert [s["description"] for s in steps] == ["clone repo", "run tests", "open PR"]
    assert all(s["status"] == "PENDING" for s in steps)


def test_plan_with_no_steps_is_rejected_and_mission_stays_in_draft(client):
    """AUDIT-C02-P1-01: a mission must never reach READY with zero
    persisted plan content."""
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]

    resp = client.post(f"/v1/missions/{mission_id}/plan", json={"steps": []})
    assert resp.status_code == 422

    mission = client.get(f"/v1/missions/{mission_id}").json()
    assert mission["state"] == "DRAFT"


def test_cancel_from_draft_goes_directly_to_cancelled(client):
    """Nothing is running yet in DRAFT -- there's nothing to confirm
    terminated, so the direct path remains legitimate."""
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    resp = client.post(f"/v1/missions/{created['id']}/cancel")
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "CANCELLED"


_RECONCILIATION_TOKEN = "test-reconciliation-secret-do-not-use-in-prod"


@pytest.fixture(autouse=True)
def _reconciliation_token(monkeypatch):
    monkeypatch.setenv("ORNEUR_MISSION_RECONCILIATION_TOKEN", _RECONCILIATION_TOKEN)


def _reconciliation_headers(token: str = _RECONCILIATION_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _run_mission_to_running(client, shared_db, mission_id: str):
    conn = _FakeConn(shared_db)
    mission_store.transition_mission(conn, mission_id, MissionState.PLANNING)
    mission_store.create_mission_steps(conn, mission_id, ["step one"])
    mission_store.transition_mission(conn, mission_id, MissionState.READY)
    mission_store.transition_mission(conn, mission_id, MissionState.RUNNING)


def test_cancel_from_running_requests_cancellation_not_direct_cancel(client, shared_db):
    """AUDIT-C02-P0-03: a mission that might have a live worker
    process must never be reported CANCELLED on a single call --
    /cancel only moves it to CANCELLATION_REQUESTED."""
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]
    _run_mission_to_running(client, shared_db, mission_id)

    resp = client.post(f"/v1/missions/{mission_id}/cancel")
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "CANCELLATION_REQUESTED"
    assert resp.json()["cancellation_episode_id"]

    # Calling /cancel again while still CANCELLATION_REQUESTED must
    # not silently succeed either -- there is no CANCELLATION_REQUESTED
    # -> CANCELLATION_REQUESTED transition via the owner-facing /cancel
    # endpoint (only /confirm-cancelled, under the reconciliation
    # credential, may move it onward).
    resp2 = client.post(f"/v1/missions/{mission_id}/cancel")
    assert resp2.status_code == 409


def test_ordinary_authenticated_user_cannot_confirm_cancellation(client, shared_db):
    """AUDIT-C02-P0-03 follow-up correction: the mission's own owner,
    however authenticated, must NOT be able to confirm termination --
    only the separate reconciliation credential may."""
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]
    _run_mission_to_running(client, shared_db, mission_id)
    cancel_resp = client.post(f"/v1/missions/{mission_id}/cancel").json()
    episode_id = cancel_resp["cancellation_episode_id"]

    # No reconciliation header at all -- just the owner's own session.
    resp = client.post(
        f"/v1/missions/{mission_id}/confirm-cancelled",
        json={"cancellation_episode_id": episode_id, "cancellation_episode_revision": None, "outcome": "TERMINATED"},
    )
    assert resp.status_code == 401

    conn = _FakeConn(shared_db)
    assert mission_store.get_mission(conn, mission_id)["state"] == "CANCELLATION_REQUESTED"


def test_confirmation_with_no_reconciliation_token_configured_fails_closed(client, shared_db, monkeypatch):
    """If the operator has not configured a real reconciliation
    credential, confirmation must be entirely unavailable (503) --
    never silently permitted."""
    monkeypatch.delenv("ORNEUR_MISSION_RECONCILIATION_TOKEN", raising=False)
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]
    _run_mission_to_running(client, shared_db, mission_id)
    cancel_resp = client.post(f"/v1/missions/{mission_id}/cancel").json()
    episode_id = cancel_resp["cancellation_episode_id"]

    resp = client.post(
        f"/v1/missions/{mission_id}/confirm-cancelled",
        json={"cancellation_episode_id": episode_id, "cancellation_episode_revision": None, "outcome": "TERMINATED"},
        headers=_reconciliation_headers("anything"),
    )
    assert resp.status_code == 503


def test_forged_reconciliation_credential_is_rejected(client, shared_db):
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]
    _run_mission_to_running(client, shared_db, mission_id)
    cancel_resp = client.post(f"/v1/missions/{mission_id}/cancel").json()
    episode_id = cancel_resp["cancellation_episode_id"]

    resp = client.post(
        f"/v1/missions/{mission_id}/confirm-cancelled",
        json={"cancellation_episode_id": episode_id, "cancellation_episode_revision": None, "outcome": "TERMINATED"},
        headers=_reconciliation_headers("wrong-secret-entirely"),
    )
    assert resp.status_code == 401

    conn = _FakeConn(shared_db)
    assert mission_store.get_mission(conn, mission_id)["state"] == "CANCELLATION_REQUESTED"


def test_forged_cancellation_episode_id_is_rejected(client, shared_db):
    """A valid reconciliation credential with a MADE-UP episode id
    must still be refused -- the credential alone is not evidence of
    which specific cancellation episode was actually resolved."""
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]
    _run_mission_to_running(client, shared_db, mission_id)
    client.post(f"/v1/missions/{mission_id}/cancel")

    resp = client.post(
        f"/v1/missions/{mission_id}/confirm-cancelled",
        json={"cancellation_episode_id": "completely-made-up", "cancellation_episode_revision": None, "outcome": "TERMINATED"},
        headers=_reconciliation_headers(),
    )
    assert resp.status_code == 409

    conn = _FakeConn(shared_db)
    assert mission_store.get_mission(conn, mission_id)["state"] == "CANCELLATION_REQUESTED"


def test_stale_cancellation_episode_id_is_rejected_after_still_running_retry(client, shared_db):
    """STILL_RUNNING retires the old episode and mints a fresh one --
    the OLD episode id must no longer work, even with a genuinely
    valid credential."""
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]
    _run_mission_to_running(client, shared_db, mission_id)
    stale_episode_id = client.post(f"/v1/missions/{mission_id}/cancel").json()["cancellation_episode_id"]

    still_running_resp = client.post(
        f"/v1/missions/{mission_id}/confirm-cancelled",
        json={"cancellation_episode_id": stale_episode_id, "cancellation_episode_revision": None, "outcome": "STILL_RUNNING"},
        headers=_reconciliation_headers(),
    )
    assert still_running_resp.status_code == 200, still_running_resp.text
    assert still_running_resp.json()["state"] == "CANCELLATION_REQUESTED"
    fresh_episode_id = still_running_resp.json()["cancellation_episode_id"]
    assert fresh_episode_id != stale_episode_id

    # Replaying the STALE episode id must fail, even though the
    # mission is (again) legitimately CANCELLATION_REQUESTED.
    stale_replay_resp = client.post(
        f"/v1/missions/{mission_id}/confirm-cancelled",
        json={"cancellation_episode_id": stale_episode_id, "cancellation_episode_revision": None, "outcome": "TERMINATED"},
        headers=_reconciliation_headers(),
    )
    assert stale_replay_resp.status_code == 409

    # The FRESH episode id correctly works.
    resp = client.post(
        f"/v1/missions/{mission_id}/confirm-cancelled",
        json={"cancellation_episode_id": fresh_episode_id, "cancellation_episode_revision": None, "outcome": "TERMINATED"},
        headers=_reconciliation_headers(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "CANCELLED"


# AUDIT-B79-B-P0-02: cancellation_episode_revision is captured at
# request_mission_cancellation() time but was never enforced by
# resolve_mission_cancellation() -- a confirmation only had to present
# the right episode_id, never the right revision. These tests exercise
# orca.mission.mission_store directly (not through the HTTP layer,
# which has no way to set current_revision on a mission at all today)
# since that's the only way to put a mission into the state where this
# check is actually observable: a non-None current_revision.
def test_confirmation_with_a_stale_revision_is_rejected_even_with_the_correct_episode_id(shared_db):
    from orca.mission import mission_store

    conn = _FakeConn(shared_db)
    mission = mission_store.create_mission(
        conn, id="mis-rev-1", repository="r", mode="ASSIST", autonomy_level="L0",
        owner_user_id="alice", current_revision="rev-A",
    )
    mission_store.transition_mission(conn, mission["id"], MissionState.PLANNING)
    mission_store.create_mission_steps(conn, mission["id"], ["step one"])
    mission_store.transition_mission(conn, mission["id"], MissionState.READY)
    mission_store.transition_mission(conn, mission["id"], MissionState.RUNNING)
    requested = mission_store.request_mission_cancellation(conn, mission["id"])
    episode_id = requested["cancellation_episode_id"]
    assert requested["cancellation_episode_revision"] == "rev-A"

    # Correct episode_id, but a DIFFERENT (stale/forged) revision claim.
    with pytest.raises(CancellationEvidenceError):
        mission_store.resolve_mission_cancellation(
            conn, mission["id"],
            cancellation_episode_id=episode_id,
            expected_cancellation_episode_revision="rev-B-not-the-real-one",
            outcome="TERMINATED",
        )
    # Nothing changed.
    assert mission_store.get_mission(conn, mission["id"])["state"] == "CANCELLATION_REQUESTED"

    # The CORRECT revision (matching what was actually pinned) succeeds.
    resolved = mission_store.resolve_mission_cancellation(
        conn, mission["id"],
        cancellation_episode_id=episode_id,
        expected_cancellation_episode_revision="rev-A",
        outcome="TERMINATED",
    )
    assert resolved["state"] == "CANCELLED"


def test_still_running_retry_pins_a_fresh_revision_for_the_new_episode(shared_db):
    """A STILL_RUNNING retry must bind confirmations to the revision
    current AT THE MOMENT the new episode opens -- not silently reuse
    the old episode's pinned revision, and not leave it unenforced."""
    from orca.mission import mission_store

    conn = _FakeConn(shared_db)
    mission = mission_store.create_mission(
        conn, id="mis-rev-2", repository="r", mode="ASSIST", autonomy_level="L0",
        owner_user_id="alice", current_revision="rev-A",
    )
    mission_store.transition_mission(conn, mission["id"], MissionState.PLANNING)
    mission_store.create_mission_steps(conn, mission["id"], ["step one"])
    mission_store.transition_mission(conn, mission["id"], MissionState.READY)
    mission_store.transition_mission(conn, mission["id"], MissionState.RUNNING)
    requested = mission_store.request_mission_cancellation(conn, mission["id"])
    old_episode_id = requested["cancellation_episode_id"]

    still_running = mission_store.resolve_mission_cancellation(
        conn, mission["id"],
        cancellation_episode_id=old_episode_id,
        expected_cancellation_episode_revision="rev-A",
        outcome="STILL_RUNNING",
    )
    new_episode_id = still_running["cancellation_episode_id"]
    assert new_episode_id != old_episode_id
    assert still_running["cancellation_episode_revision"] == "rev-A"

    # A confirmation against the NEW episode with the OLD episode's id
    # is still correctly rejected (pre-existing behavior, reconfirmed).
    with pytest.raises(CancellationEvidenceError):
        mission_store.resolve_mission_cancellation(
            conn, mission["id"],
            cancellation_episode_id=old_episode_id,
            expected_cancellation_episode_revision="rev-A",
            outcome="TERMINATED",
        )

    # The new episode, with its own correctly pinned revision, resolves.
    resolved = mission_store.resolve_mission_cancellation(
        conn, mission["id"],
        cancellation_episode_id=new_episode_id,
        expected_cancellation_episode_revision="rev-A",
        outcome="TERMINATED",
    )
    assert resolved["state"] == "CANCELLED"


def test_terminated_worker_outcome_confirms_cancelled(client, shared_db):
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]
    _run_mission_to_running(client, shared_db, mission_id)
    episode_id = client.post(f"/v1/missions/{mission_id}/cancel").json()["cancellation_episode_id"]

    resp = client.post(
        f"/v1/missions/{mission_id}/confirm-cancelled",
        json={"cancellation_episode_id": episode_id, "cancellation_episode_revision": None, "outcome": "TERMINATED"},
        headers=_reconciliation_headers(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "CANCELLED"


def test_unresolved_outcome_is_distinct_from_both_cancelled_and_failed(client, shared_db):
    """AUDIT-C02-P0-03 follow-up correction: 'reconciliation could not
    determine the worker's fate' must never be silently folded into
    either CANCELLED (misreporting a possibly-still-running worker as
    safely stopped) or FAILED (misrepresenting an unresolved
    cancellation as a confirmed execution failure)."""
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]
    _run_mission_to_running(client, shared_db, mission_id)
    episode_id = client.post(f"/v1/missions/{mission_id}/cancel").json()["cancellation_episode_id"]

    resp = client.post(
        f"/v1/missions/{mission_id}/confirm-cancelled",
        json={"cancellation_episode_id": episode_id, "cancellation_episode_revision": None, "outcome": "UNRESOLVED"},
        headers=_reconciliation_headers(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "CANCELLATION_UNRESOLVED"


def test_reconciliation_interruption_then_retry_eventually_confirms(client, shared_db):
    """A second reconciliation attempt, after an earlier one came back
    UNRESOLVED (e.g. the reconciliation process itself was
    interrupted), can still resolve the SAME episode to a real
    outcome -- UNRESOLVED is not a dead end."""
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]
    _run_mission_to_running(client, shared_db, mission_id)
    episode_id = client.post(f"/v1/missions/{mission_id}/cancel").json()["cancellation_episode_id"]

    first = client.post(
        f"/v1/missions/{mission_id}/confirm-cancelled",
        json={"cancellation_episode_id": episode_id, "cancellation_episode_revision": None, "outcome": "UNRESOLVED"},
        headers=_reconciliation_headers(),
    )
    assert first.json()["state"] == "CANCELLATION_UNRESOLVED"

    second = client.post(
        f"/v1/missions/{mission_id}/confirm-cancelled",
        json={"cancellation_episode_id": episode_id, "cancellation_episode_revision": None, "outcome": "TERMINATED"},
        headers=_reconciliation_headers(),
    )
    assert second.status_code == 200, second.text
    assert second.json()["state"] == "CANCELLED"


def test_double_cancellation_confirmation_is_rejected(client, shared_db):
    """Once CANCELLED, the episode is cleared -- a second confirmation
    attempt (replaying the same episode id, or any id) must not
    succeed again."""
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]
    _run_mission_to_running(client, shared_db, mission_id)
    episode_id = client.post(f"/v1/missions/{mission_id}/cancel").json()["cancellation_episode_id"]

    first = client.post(
        f"/v1/missions/{mission_id}/confirm-cancelled",
        json={"cancellation_episode_id": episode_id, "cancellation_episode_revision": None, "outcome": "TERMINATED"},
        headers=_reconciliation_headers(),
    )
    assert first.json()["state"] == "CANCELLED"

    second = client.post(
        f"/v1/missions/{mission_id}/confirm-cancelled",
        json={"cancellation_episode_id": episode_id, "cancellation_episode_revision": None, "outcome": "TERMINATED"},
        headers=_reconciliation_headers(),
    )
    assert second.status_code == 409


def test_operation_request_requires_mission_ownership(client):
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()

    _as(client, _user("mallory"))
    resp = client.post(
        f"/v1/missions/{created['id']}/operations",
        json={"kind": "shell_exec", "target": "rm -rf /", "idempotency_key": "k1"},
    )
    assert resp.status_code == 404


def test_duplicate_idempotency_key_returns_existing_operation_not_a_new_one(client):
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]

    payload = {"kind": "shell_exec", "target": "ls", "idempotency_key": "same-key"}
    r1 = client.post(f"/v1/missions/{mission_id}/operations", json=payload)
    r2 = client.post(f"/v1/missions/{mission_id}/operations", json=payload)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["operation"]["id"] == r2.json()["operation"]["id"]
    assert r1.json()["created"] is True
    assert r2.json()["created"] is False


def test_different_parameters_under_same_idempotency_key_is_rejected(client):
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]

    client.post(f"/v1/missions/{mission_id}/operations", json={"kind": "shell_exec", "target": "ls", "idempotency_key": "k"})
    resp = client.post(f"/v1/missions/{mission_id}/operations", json={"kind": "shell_exec", "target": "rm -rf /", "idempotency_key": "k"})
    assert resp.status_code == 409


def test_self_approval_is_rejected(client):
    """The requester cannot also be the approver -- enforced by the
    existing orca.mission.operation_store.authorize_operation(), never
    bypassed by this HTTP layer."""
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]
    op = client.post(
        f"/v1/missions/{mission_id}/operations",
        json={"kind": "shell_exec", "target": "ls", "idempotency_key": "k"},
    ).json()["operation"]

    # alice both requested AND is attempting to approve her own operation.
    resp = client.post(
        f"/v1/missions/{mission_id}/operations/{op['id']}/approve",
        json={"reason": "looks fine to me"},
    )
    assert resp.status_code == 403


def test_distinct_principal_approval_journey_reaches_a_real_allow_decision(client, shared_db):
    """AUDIT-C02-P1-02 ("real approval path"): demonstrates that
    orca.mission.operation_store's underlying engine genuinely
    supports a legitimate operation-request-to-approval journey
    between two DISTINCT, real principals, reaching an actual ALLOW
    decision from the real orca.godmode authority engine (NOT
    mocked/faked) -- not merely that self-approval is rejected.

    UPDATE (AUDIT-B79-B-P0-01): this test's original docstring noted
    that the HTTP API (mission_api.py) had no way to designate a
    distinct approver, so this test called operation_store directly to
    prove the underlying mechanism worked while that HTTP-level gap
    stayed open. That gap is now closed -- CreateMissionRequest.
    workspace_id lets a mission's creator designate a second real
    principal who can reach /approve and /deny, checked by
    _get_tenant_mission_or_404(). See
    test_distinct_principal_approval_journey_reaches_a_real_allow_decision_via_http
    below for the same journey exercised through the real HTTP routes,
    not just the domain engine directly. This test is kept as-is: it
    still independently verifies the domain engine's own behavior in
    isolation from the HTTP layer, which remains a legitimate, distinct
    thing to test."""
    from orca.mission import operation_store

    conn = _FakeConn(shared_db)
    op, created = operation_store.request_operation(
        conn, id="op-distinct-1", idempotency_key="distinct-key", kind="shell_exec",
        requested_by="alice", mission_id="mission-distinct-1", target="ls", parameters=None,
    )
    assert created is True
    assert op["status"] == "REQUESTED"

    # A genuinely different principal (bob) approves alice's request.
    authorized_op, allowed = operation_store.authorize_operation(
        conn, op["id"], tenant_id="tenant-distinct-1", approved_by="bob", reason="qualification journey",
    )
    assert allowed is True, "a distinct, legitimate approver must be able to reach a real ALLOW decision"
    assert authorized_op["status"] == "AUTHORIZED"

    # Self-authorization remains independently, structurally rejected
    # by the SAME function -- not weakened to make the above work.
    op2, _ = operation_store.request_operation(
        conn, id="op-distinct-2", idempotency_key="distinct-key-2", kind="shell_exec",
        requested_by="alice", mission_id="mission-distinct-1", target="ls", parameters=None,
    )
    with pytest.raises(operation_store.SelfAuthorizationError):
        operation_store.authorize_operation(
            conn, op2["id"], tenant_id="tenant-distinct-1", approved_by="alice", reason="trying to self-approve",
        )


def test_approval_denial_marks_operation_cancelled(client):
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]
    op = client.post(
        f"/v1/missions/{mission_id}/operations",
        json={"kind": "shell_exec", "target": "ls", "idempotency_key": "k"},
    ).json()["operation"]

    resp = client.post(f"/v1/missions/{mission_id}/operations/{op['id']}/deny")
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"


def test_idempotency_key_collision_across_missions_is_rejected_not_silently_returned(client):
    """AUDIT-C02-P0-01: operations.idempotency_key is globally unique
    (not scoped per-mission) in the existing schema. The SAME key with
    matching kind/target/parameters, reused under a DIFFERENT mission,
    must never be silently treated as "your mission's successful
    retry" -- it must be reported as a conflict."""
    _as(client, _user("alice"))
    mission_a = client.post("/v1/missions", json={"repository": "r1", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_b = client.post("/v1/missions", json={"repository": "r2", "mode": "ASSIST", "autonomy_level": "L0"}).json()

    payload = {"kind": "shell_exec", "target": "ls", "idempotency_key": "shared-key-across-missions"}
    r1 = client.post(f"/v1/missions/{mission_a['id']}/operations", json=payload)
    assert r1.status_code == 201, r1.text
    op_a = r1.json()["operation"]
    assert op_a["mission_id"] == mission_a["id"]

    r2 = client.post(f"/v1/missions/{mission_b['id']}/operations", json=payload)
    assert r2.status_code == 409, r2.text
    assert "different mission" in r2.json()["detail"]


def test_cannot_approve_operation_belonging_to_a_different_mission(client):
    """AUDIT-C02-P0-02: approving at
    /v1/missions/{mission_id}/operations/{operation_id}/approve must
    verify operation_id actually belongs to mission_id, not merely
    that the caller owns mission_id. Otherwise an operation_id learned
    from elsewhere could be approved/denied through an unrelated
    mission's URL."""
    _as(client, _user("alice"))
    mission_a = client.post("/v1/missions", json={"repository": "r1", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_b = client.post("/v1/missions", json={"repository": "r2", "mode": "ASSIST", "autonomy_level": "L0"}).json()

    op_a = client.post(
        f"/v1/missions/{mission_a['id']}/operations",
        json={"kind": "shell_exec", "target": "ls", "idempotency_key": "k-a"},
    ).json()["operation"]

    # Attempt to approve mission A's operation through mission B's URL.
    resp = client.post(
        f"/v1/missions/{mission_b['id']}/operations/{op_a['id']}/approve",
        json={"reason": "approving via the wrong mission"},
    )
    assert resp.status_code == 404

    # Same cross-mission mismatch on the deny path (already correct,
    # verified here as a regression guard).
    resp2 = client.post(f"/v1/missions/{mission_b['id']}/operations/{op_a['id']}/deny")
    assert resp2.status_code == 404


def test_cannot_deny_an_already_denied_operation(client):
    """A terminal (CANCELLED) operation cannot be acted on again --
    the existing operation state machine's own transition guard."""
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    mission_id = created["id"]
    op = client.post(
        f"/v1/missions/{mission_id}/operations",
        json={"kind": "shell_exec", "target": "ls", "idempotency_key": "k"},
    ).json()["operation"]

    client.post(f"/v1/missions/{mission_id}/operations/{op['id']}/deny")
    resp = client.post(f"/v1/missions/{mission_id}/operations/{op['id']}/deny")
    assert resp.status_code == 409


# AUDIT-B79-B-P0-01: approve/deny no longer gate on mission ownership
# alone -- a mission can designate a second real principal
# (workspace_id) who can reach the same decision point as the owner.
def _patch_real_user(monkeypatch, uid: str) -> None:
    import orca.auth.store as auth_store

    monkeypatch.setattr(auth_store, "get_user_by_id", lambda u: _user(uid) if u == uid else None)


def test_workspace_id_must_name_a_different_existing_user(client, monkeypatch):
    _as(client, _user("alice"))

    # Self-reference is rejected -- the owner already has access to
    # their own mission; naming themselves as the "second" principal
    # is meaningless and almost certainly a caller mistake.
    resp = client.post(
        "/v1/missions",
        json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0", "workspace_id": "alice"},
    )
    assert resp.status_code == 400

    # A workspace_id that doesn't name any real user is rejected, not
    # silently accepted into an unreachable tenant.
    resp2 = client.post(
        "/v1/missions",
        json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0", "workspace_id": "nobody-by-this-id"},
    )
    assert resp2.status_code == 400


def test_distinct_principal_approval_journey_reaches_a_real_allow_decision_via_http(client, monkeypatch):
    """The actual HTTP-level fix for AUDIT-B79-B-P0-01: alice creates a
    mission naming bob as its workspace_id (a real, existing, different
    user), alice requests an operation, and BOB -- not alice -- reaches
    /approve through the real route and gets a real ALLOW decision from
    the unmodified orca.godmode authority engine. No test-only bypass
    of the HTTP layer, unlike the domain-engine-only test above."""
    _patch_real_user(monkeypatch, "bob")
    _as(client, _user("alice"))
    created = client.post(
        "/v1/missions",
        json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0", "workspace_id": "bob"},
    ).json()
    mission_id = created["id"]
    assert created["workspace_id"] == "bob"

    op = client.post(
        f"/v1/missions/{mission_id}/operations",
        json={"kind": "shell_exec", "target": "ls", "idempotency_key": "two-principal-k"},
    ).json()["operation"]

    _as(client, _user("bob"))
    resp = client.post(
        f"/v1/missions/{mission_id}/operations/{op['id']}/approve",
        json={"reason": "bob reviewed and approves"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["allowed"] is True, "a genuinely designated, distinct approver must reach a real ALLOW"
    assert body["operation"]["status"] == "AUTHORIZED"


def test_an_unrelated_stranger_is_still_denied_even_with_workspace_id_in_play(client, monkeypatch):
    """Designating bob as the tenant must not open the mission up to
    EVERYONE -- mallory, who is neither the owner nor the designated
    workspace principal, must still get 404 on both approve and deny."""
    _patch_real_user(monkeypatch, "bob")
    _as(client, _user("alice"))
    created = client.post(
        "/v1/missions",
        json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0", "workspace_id": "bob"},
    ).json()
    mission_id = created["id"]
    op = client.post(
        f"/v1/missions/{mission_id}/operations",
        json={"kind": "shell_exec", "target": "ls", "idempotency_key": "stranger-k"},
    ).json()["operation"]

    _as(client, _user("mallory"))
    resp = client.post(
        f"/v1/missions/{mission_id}/operations/{op['id']}/approve",
        json={"reason": "mallory tries anyway"},
    )
    assert resp.status_code == 404
    resp2 = client.post(f"/v1/missions/{mission_id}/operations/{op['id']}/deny")
    assert resp2.status_code == 404


def test_self_authorization_is_still_rejected_even_when_owner_is_also_the_workspace_principal_scenario(client, monkeypatch):
    """The workspace_id relaxation must never weaken the hard
    self-authorization guard -- alice (the requester) still cannot
    approve her own operation, even on a mission that has a
    workspace_id configured."""
    _patch_real_user(monkeypatch, "bob")
    _as(client, _user("alice"))
    created = client.post(
        "/v1/missions",
        json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0", "workspace_id": "bob"},
    ).json()
    mission_id = created["id"]
    op = client.post(
        f"/v1/missions/{mission_id}/operations",
        json={"kind": "shell_exec", "target": "ls", "idempotency_key": "self-auth-k"},
    ).json()["operation"]

    resp = client.post(
        f"/v1/missions/{mission_id}/operations/{op['id']}/approve",
        json={"reason": "alice tries to approve her own request"},
    )
    assert resp.status_code == 403


def test_designated_workspace_principal_can_also_deny(client, monkeypatch):
    _patch_real_user(monkeypatch, "bob")
    _as(client, _user("alice"))
    created = client.post(
        "/v1/missions",
        json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0", "workspace_id": "bob"},
    ).json()
    mission_id = created["id"]
    op = client.post(
        f"/v1/missions/{mission_id}/operations",
        json={"kind": "shell_exec", "target": "ls", "idempotency_key": "deny-k"},
    ).json()["operation"]

    _as(client, _user("bob"))
    resp = client.post(f"/v1/missions/{mission_id}/operations/{op['id']}/deny")
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"
