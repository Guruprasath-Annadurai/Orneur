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
            self._db["missions"][row["id"]] = row
            self._result = []
        elif sql_norm.startswith("SELECT * FROM missions WHERE id = %s"):
            row = self._db["missions"].get(params[0])
            self._result = [row] if row else []
        elif sql_norm.startswith("SELECT * FROM missions WHERE owner_user_id = %s"):
            rows = [r for r in self._db["missions"].values() if r["owner_user_id"] == params[0]]
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            self._result = rows
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
    return {"missions": {}, "operations": {}}


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
    assert client.post(f"/v1/missions/{mission_id}/plan").status_code == 404
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


def test_plan_transitions_draft_to_ready(client):
    _as(client, _user("alice"))
    created = client.post("/v1/missions", json={"repository": "r", "mode": "ASSIST", "autonomy_level": "L0"}).json()
    resp = client.post(f"/v1/missions/{created['id']}/plan")
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "READY"


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
