"""Workstream A -- owner bootstrap: recovery from a pre-registered ("squatted") founder e-mail, without ever weakening the fail-closed default.

Gap found while self-auditing G-021 (the text of Audit #009 was not available to this session; see docs/orneur/status/AUDIT_009_STATUS.md): on a
non-public install anybody can register the founder's e-mail address BEFORE the founder redeems the bootstrap token. The founder then cannot redeem
(correct: promotion needs that account's password) and had no operator path to recover. `issue --replace-unverified` is that path.
"""
from __future__ import annotations

import threading
import uuid

import pytest
from fastapi.testclient import TestClient

PW = "correct-horse-battery"
ATTACKER_PW = "attacker-password-123"


@pytest.fixture
def fresh(isolated_home, monkeypatch):
    from orca.serve import api, ratelimit
    ratelimit._local_counters.clear()
    monkeypatch.delenv("ORNEUR_PUBLIC_EDGE", raising=False)
    monkeypatch.setenv("ORNEUR_AUTH_SECRET", "g021-test-secret-not-the-dev-default")
    from orca.auth import db, secret
    secret._reset_cache_for_tests()
    db.init_db()
    return TestClient(api.app)


def _email():
    return f"squat-{uuid.uuid4().hex[:10]}@example.com"


def _squat(c, email):
    r = c.post("/api/auth/signup", json={"email": email, "password": ATTACKER_PW, "name": "attacker"})
    assert r.status_code == 200
    return r.json()["token"], r.json()["user"]["id"]


def _redeem(c, token, email, pw=PW):
    return c.post("/api/auth/bootstrap-owner", json={"token": token, "email": email, "password": pw})


def _owner_count():
    from orca.auth.db import get_conn
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM users WHERE role='owner'").fetchone()["n"]


def test_without_the_flag_a_squatted_email_cannot_be_taken_over(fresh):
    from orca.auth.bootstrap import issue_token
    em = _email()
    _squat(fresh, em)
    tok = issue_token(em)
    r = _redeem(fresh, tok, em)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "invalid_token" and _owner_count() == 0
    r2 = _redeem(fresh, tok, em, pw=ATTACKER_PW)                         # only the account holder's password promotes it
    assert r2.status_code == 200 and _owner_count() == 1


def test_the_operator_flag_replaces_an_unverified_squatter_and_signs_it_out(fresh):
    from orca.auth.bootstrap import issue_token
    from orca.auth.store import authenticate
    em = _email()
    squat_token, squat_id = _squat(fresh, em)
    tok = issue_token(em, replace_existing_unverified=True)
    r = _redeem(fresh, tok, em)
    assert r.status_code == 200 and r.json()["user"]["role"] == "owner" and r.json()["user"]["id"] != squat_id
    assert authenticate(em, ATTACKER_PW) is None and authenticate(em, PW) is not None
    assert fresh.get("/api/auth/me", headers={"Authorization": f"Bearer {squat_token}"}).status_code == 401      # the squatter's session is dead
    from orca.auth.db import get_conn
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM users WHERE id=?", (squat_id,)).fetchone()["n"] == 0
    assert _owner_count() == 1


def test_a_verified_account_is_never_replaced_even_with_the_flag(fresh):
    from orca.auth.bootstrap import issue_token
    from orca.auth.db import get_conn
    em = _email()
    _, uid = _squat(fresh, em)
    with get_conn() as conn:
        conn.execute("UPDATE users SET verified=1 WHERE id=?", (uid,))
    tok = issue_token(em, replace_existing_unverified=True)
    r = _redeem(fresh, tok, em)
    assert r.status_code == 403 and _owner_count() == 0
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM users WHERE id=?", (uid,)).fetchone()["n"] == 1
    assert _redeem(fresh, tok, em, pw=ATTACKER_PW).status_code == 200      # ...but the holder of the password can still be promoted


def test_the_flag_cannot_replace_a_different_users_account(fresh):
    from orca.auth.bootstrap import issue_token
    em, other = _email(), _email()
    _squat(fresh, other)
    tok = issue_token(em, replace_existing_unverified=True)
    assert _redeem(fresh, tok, other).status_code == 403                   # the token is bound to ONE e-mail
    assert _owner_count() == 0


def test_replacement_races_have_exactly_one_winner(fresh):
    from orca.auth.bootstrap import BootstrapError, issue_token, redeem
    em = _email()
    _squat(fresh, em)
    tok = issue_token(em, replace_existing_unverified=True)
    wins = []

    def go():
        try:
            wins.append(redeem(tok, em, PW).id)
        except (BootstrapError, Exception):
            pass

    ts = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(wins) == 1 and _owner_count() == 1


def test_a_failed_replacement_leaves_the_squatter_untouched(fresh, monkeypatch):
    """Atomicity: if completion fails after the old account was deleted inside the transaction, the deletion is rolled back."""
    from orca.auth import bootstrap
    from orca.auth.db import get_conn as real_get_conn
    em = _email()
    _, squat_id = _squat(fresh, em)
    tok = bootstrap.issue_token(em, replace_existing_unverified=True)

    class Lost:
        def fetchone(self):
            return None

    class Proxy:
        def __init__(self, conn):
            self._c = conn

        def __enter__(self):
            self._c.__enter__()
            return self

        def __exit__(self, *a):
            return self._c.__exit__(*a)

        def execute(self, sql, params=()):
            if sql.lstrip().startswith("INSERT INTO owner_bootstrap ("):
                return Lost()
            return self._c.execute(sql, params)

    monkeypatch.setattr(bootstrap, "get_conn", lambda: Proxy(real_get_conn()))
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.redeem(tok, em, PW)
    monkeypatch.undo()
    with real_get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM users WHERE id=?", (squat_id,)).fetchone()["n"] == 1
    assert _owner_count() == 0


def test_the_cli_exposes_the_flag_and_warns(fresh, capsys):
    from orca.auth import bootstrap
    assert bootstrap._main(["issue", "--email", "founder@example.com", "--replace-unverified"]) == 0
    out = capsys.readouterr().out
    assert "replace" in out.lower() and out.strip().splitlines()[-1].startswith("orneur-owner-")


def test_the_flag_is_stored_not_inferred_from_the_request(fresh):
    """The redeem request cannot ask for replacement: only the operator-issued token row can."""
    from orca.auth.bootstrap import issue_token
    em = _email()
    _squat(fresh, em)
    tok = issue_token(em)                                                  # no flag
    r = fresh.post("/api/auth/bootstrap-owner", json={"token": tok, "email": em, "password": PW, "replace_existing_unverified": True})
    assert r.status_code == 403 and _owner_count() == 0
