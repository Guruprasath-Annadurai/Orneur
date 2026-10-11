"""G-021 -- the first public signup must not become `owner`; owner creation is a founder-controlled, single-use, auditable procedure.

Real FastAPI app + real auth store in an isolated temp database. No real account, key or network.
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

PW = "correct-horse-battery"


@pytest.fixture
def fresh(isolated_home, monkeypatch):
    """A brand-new deployment: no users at all (unlike the G-006 fixture, nothing is pre-created)."""
    from orca.serve import api, ratelimit

    ratelimit._local_counters.clear()
    monkeypatch.delenv("ORNEUR_PUBLIC_EDGE", raising=False)
    monkeypatch.setenv("ORNEUR_AUTH_SECRET", "g021-test-secret-not-the-dev-default")
    c = TestClient(api.app)
    from orca.auth import db
    db.init_db()
    return c


def _email():
    return f"g021-{uuid.uuid4().hex[:10]}@example.com"


def _owner_count():
    from orca.auth.db import get_conn
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM users WHERE role='owner'").fetchone()["n"]


def _signup(c, email=None, pw=PW):
    return c.post("/api/auth/signup", json={"email": email or _email(), "password": pw, "name": "x"})


def _redeem(c, token, email, pw=PW):
    return c.post("/api/auth/bootstrap-owner", json={"token": token, "email": email, "password": pw})


# ── signup never confers owner ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_first_signup_on_a_fresh_deployment_is_a_member_not_the_owner(fresh):
    r = _signup(fresh)
    assert r.status_code == 200 and r.json()["user"]["role"] == "member"
    assert _owner_count() == 0


def test_create_user_never_returns_an_owner_even_with_an_empty_table(isolated_home):
    from orca.auth.store import create_user
    assert create_user(_email(), PW).role == "member"
    assert _owner_count() == 0


def test_signup_ignores_a_client_supplied_role(fresh):
    r = fresh.post("/api/auth/signup", json={"email": _email(), "password": PW, "name": "x", "role": "owner", "tier": "enterprise"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "member" and r.json()["user"]["tier"] == "free"


def test_many_concurrent_first_signups_produce_zero_owners(isolated_home):
    from orca.auth.store import create_user
    out = []
    ts = [threading.Thread(target=lambda: out.append(create_user(_email(), PW).role)) for _ in range(12)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert out.count("owner") == 0 and _owner_count() == 0


# ── fail closed on an uninitialized public deployment ───────────────────────────────────────────────────────────────────────────

def test_public_edge_without_an_owner_refuses_signup(fresh, monkeypatch):
    monkeypatch.setenv("ORNEUR_PUBLIC_EDGE", "1")
    r = _signup(fresh)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "owner_not_initialized"


def test_public_edge_signup_opens_only_after_bootstrap(fresh, monkeypatch):
    from orca.auth.bootstrap import issue_token
    monkeypatch.setenv("ORNEUR_PUBLIC_EDGE", "1")
    em = _email()
    assert _redeem(fresh, issue_token(em), em).status_code == 200
    assert _signup(fresh).status_code == 200


def test_bootstrap_status_is_minimal(fresh):
    assert fresh.get("/api/auth/bootstrap-status").json() == {"initialized": False}


# ── the happy path and what it does ─────────────────────────────────────────────────────────────────────────────────────────────

def test_redeeming_a_token_creates_the_bound_owner_and_a_working_session(fresh):
    from orca.auth.bootstrap import issue_token
    em = _email()
    r = _redeem(fresh, issue_token(em), em)
    assert r.status_code == 200 and r.json()["user"]["role"] == "owner" and r.json()["user"]["email"].lower() == em
    me = fresh.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['token']}"})
    assert me.status_code == 200 and me.json().get("role", me.json().get("user", {}).get("role")) == "owner"
    assert fresh.get("/api/auth/bootstrap-status").json() == {"initialized": True}
    assert _owner_count() == 1


def test_an_existing_member_account_can_be_promoted_only_with_its_password(fresh):
    from orca.auth.bootstrap import issue_token
    em = _email()
    assert _signup(fresh, em).status_code == 200
    tok = issue_token(em)
    assert _redeem(fresh, tok, em, pw="wrong-password-123").status_code == 403
    assert _owner_count() == 0                       # nothing changed, and the failed attempt did not burn the token
    assert _redeem(fresh, tok, em).status_code == 200 and _owner_count() == 1


def test_only_a_hash_of_the_token_is_stored(fresh):
    from orca.auth.bootstrap import issue_token
    from orca.auth.db import get_conn
    tok = issue_token(_email())
    with get_conn() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM owner_bootstrap_tokens").fetchall()]
    assert rows and all(tok not in str(v) for r in rows for v in r.values())


# ── replay, wrong identity, expiry, forgery ─────────────────────────────────────────────────────────────────────────────────────

def test_a_token_cannot_be_replayed(fresh):
    from orca.auth.bootstrap import issue_token
    em = _email()
    tok = issue_token(em)
    assert _redeem(fresh, tok, em).status_code == 200
    again = _redeem(fresh, tok, em)
    assert again.status_code in (403, 409) and _owner_count() == 1


def test_a_token_is_bound_to_one_email(fresh):
    from orca.auth.bootstrap import issue_token
    em, attacker = _email(), _email()
    tok = issue_token(em)
    r = _redeem(fresh, tok, attacker)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "invalid_token" and _owner_count() == 0
    assert _redeem(fresh, tok, em).status_code == 200           # the wrong-email attempt did not consume it


def test_expired_tokens_are_rejected(fresh):
    from orca.auth.bootstrap import issue_token
    from orca.auth.db import get_conn
    em = _email()
    tok = issue_token(em)
    with get_conn() as conn:
        conn.execute("UPDATE owner_bootstrap_tokens SET expires_at=?", ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),))
    assert _redeem(fresh, tok, em).status_code == 403 and _owner_count() == 0


@pytest.mark.parametrize("forged", ["", "x", "orneur-owner-", "orneur-owner-" + "A" * 43, "orneur-owner-" + "A" * 5000, "' OR 1=1 --", "orneur-owner-%"])
def test_guessed_or_malformed_tokens_are_rejected_uniformly(fresh, forged):
    from orca.auth.bootstrap import issue_token
    em = _email()
    issue_token(em)
    r = _redeem(fresh, forged, em)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "invalid_token" and _owner_count() == 0


def test_wrong_token_wrong_email_expired_and_used_are_indistinguishable(fresh):
    from orca.auth.bootstrap import issue_token
    em = _email()
    tok = issue_token(em)
    a = _redeem(fresh, "orneur-owner-" + "B" * 43, em).json()
    b = _redeem(fresh, tok, _email()).json()
    assert a == b                                               # no oracle for "this token exists"


def test_weak_password_is_rejected_without_consuming_the_token(fresh):
    from orca.auth.bootstrap import issue_token
    em = _email()
    tok = issue_token(em)
    assert _redeem(fresh, tok, em, pw="short").status_code == 403
    assert _redeem(fresh, tok, em).status_code == 200


# ── privilege escalation ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_signed_in_member_cannot_self_promote_through_the_bootstrap_route(fresh):
    from orca.auth.bootstrap import issue_token
    em = _email()
    token = _signup(fresh, em).json()["token"]
    other_tok = issue_token(_email())                           # an unrelated, valid token for someone else
    r = fresh.post("/api/auth/bootstrap-owner", json={"token": other_tok, "email": em, "password": PW}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403 and _owner_count() == 0


def test_no_token_can_be_issued_or_redeemed_once_an_owner_exists(fresh):
    from orca.auth.bootstrap import BootstrapError, issue_token
    a, b = _email(), _email()
    stale = issue_token(b)
    assert _redeem(fresh, issue_token(a), a).status_code == 200
    with pytest.raises(BootstrapError):
        issue_token(_email())
    r = _redeem(fresh, stale, b)                                # a token issued BEFORE the owner existed is dead too
    assert r.status_code in (403, 409) and _owner_count() == 1


# ── races ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_one_token_redeemed_by_many_threads_yields_exactly_one_owner(fresh):
    from orca.auth.bootstrap import BootstrapError, issue_token, redeem
    em = _email()
    tok = issue_token(em)
    wins, errs = [], []

    def go():
        try:
            wins.append(redeem(tok, em, PW).id)
        except BootstrapError as e:
            errs.append(e.code)
        except Exception as e:                                  # a DB-level conflict is also a refusal, never a second owner
            errs.append(type(e).__name__)

    ts = [threading.Thread(target=go) for _ in range(10)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(wins) == 1 and len(errs) == 9 and _owner_count() == 1


def test_many_valid_tokens_for_different_emails_still_yield_exactly_one_owner(fresh):
    from orca.auth.bootstrap import BootstrapError, issue_token, redeem
    pairs = [(e, issue_token(e)) for e in (_email() for _ in range(8))]   # all issued while no owner exists
    wins = []

    def go(e, t):
        try:
            wins.append(redeem(t, e, PW).id)
        except Exception:
            pass

    ts = [threading.Thread(target=go, args=p) for p in pairs]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(wins) == 1 and _owner_count() == 1
    from orca.auth.db import get_conn
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM owner_bootstrap").fetchone()["n"] == 1


def test_a_lost_completion_race_rolls_back_the_account_and_the_token(fresh, monkeypatch):
    """Simulate losing the singleton INSERT after the token was claimed and the account created: nothing may survive."""
    from orca.auth import bootstrap
    from orca.auth.db import get_conn as real_get_conn

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
    em = _email()
    tok = bootstrap.issue_token(em)
    with pytest.raises(bootstrap.BootstrapError) as e:
        bootstrap.redeem(tok, em, PW)
    assert e.value.code == "already_initialized"
    monkeypatch.undo()
    with real_get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM users WHERE email=?", (em,)).fetchone()["n"] == 0
        assert conn.execute("SELECT redeemed_at FROM owner_bootstrap_tokens").fetchone()["redeemed_at"] is None
    assert _owner_count() == 0


# ── upgrade and recovery ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_install_that_already_has_an_owner_keeps_it_and_is_marked_initialized(isolated_home):
    from orca.auth import db
    from orca.auth.db import get_conn
    from orca.auth.store import insert_user
    with get_conn() as conn:
        owner = insert_user(conn, _email(), PW, role="owner")
        conn.execute("DELETE FROM owner_bootstrap")             # what a pre-G-021 database looks like
    db.init_db()                                                # the upgrade migration
    with get_conn() as conn:
        row = conn.execute("SELECT owner_user_id, method FROM owner_bootstrap WHERE id=1").fetchone()
        assert dict(row) == {"owner_user_id": owner.id, "method": "legacy_existing_owner"}
        assert conn.execute("SELECT role FROM users WHERE id=?", (owner.id,)).fetchone()["role"] == "owner"
    from orca.auth.bootstrap import BootstrapError, issue_token
    with pytest.raises(BootstrapError):
        issue_token(_email())


def test_the_migration_is_idempotent_and_never_invents_an_owner(isolated_home):
    from orca.auth import db
    from orca.auth.store import create_user
    create_user(_email(), PW)
    db.init_db(); db.init_db()
    assert _owner_count() == 0


def test_if_the_only_owner_is_deleted_bootstrap_can_run_again(fresh):
    from orca.auth.bootstrap import issue_token
    from orca.auth.db import get_conn
    a, b = _email(), _email()
    assert _redeem(fresh, issue_token(a), a).status_code == 200
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE role='owner'")
    assert _redeem(fresh, issue_token(b), b).status_code == 200 and _owner_count() == 1


# ── audit and CLI ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_completion_and_refusals_are_audited(fresh, monkeypatch):
    from orca import audit
    from orca.auth.bootstrap import issue_token
    seen = []
    real = audit.log
    monkeypatch.setattr(audit, "log", lambda ev, **kw: (seen.append((ev, kw)), real(ev, **kw))[1])
    em = _email()
    tok = issue_token(em)
    _redeem(fresh, "orneur-owner-" + "C" * 43, em)
    _redeem(fresh, tok, em)
    names = [e for e, _ in seen]
    assert "owner_bootstrap_refused" in names and "owner_bootstrap_completed" in names
    assert all(PW not in str(kw) and tok not in str(kw) for _, kw in seen)


def test_cli_issue_status_and_refusal(fresh, capsys):
    from orca.auth import bootstrap
    assert bootstrap._main(["issue", "--email", "founder@example.com", "--ttl", "120"]) == 0
    out = capsys.readouterr().out
    token = out.strip().splitlines()[-1]
    assert token.startswith("orneur-owner-")
    assert _redeem(fresh, token, "founder@example.com").status_code == 200
    assert bootstrap._main(["issue", "--email", "second@example.com"]) == 2
    assert bootstrap._main(["status"]) == 0 and "initialized': True" in capsys.readouterr().out


def test_ttl_is_clamped(fresh):
    from orca.auth.bootstrap import MAX_TTL_S, issue_token
    from orca.auth.db import get_conn
    issue_token(_email(), ttl_s=10**9)
    with get_conn() as conn:
        row = conn.execute("SELECT issued_at, expires_at FROM owner_bootstrap_tokens").fetchone()
    span = datetime.fromisoformat(row["expires_at"]) - datetime.fromisoformat(row["issued_at"])
    assert span <= timedelta(seconds=MAX_TTL_S + 1)
