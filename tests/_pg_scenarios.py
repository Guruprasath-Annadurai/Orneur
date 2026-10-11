"""PostgreSQL scenario runner (Workstream A). Executed as a SUBPROCESS by tests/test_a_postgres_integration.py so that `orca.auth.db` binds to PostgreSQL at
import time exactly as in production (ORNEUR_DATABASE_URL set before import). Prints one JSON object on the last stdout line.

    ORNEUR_DATABASE_URL=... ORNEUR_HOME=... python tests/_pg_scenarios.py <scenario>
"""
from __future__ import annotations

import json
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _email():
    return f"pg-{uuid.uuid4().hex[:10]}@example.com"


def s_fresh_init():
    from orca.auth import db
    db.init_db()
    db.init_db()                                              # idempotent
    with db.get_conn() as c:
        tables = {r["table_name"] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'").fetchall()}
        cols = {r["column_name"] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='users'").fetchall()}
        idx = {r["indexname"] for r in c.execute("SELECT indexname FROM pg_indexes WHERE tablename='user_sessions'").fetchall()}
    return {"backend": db.BACKEND, "tables": sorted(tables & {"users", "user_sessions", "session_storage_keys", "owner_bootstrap", "owner_bootstrap_tokens", "signup_counter", "usage_daily"}),
            "has_tokens_valid_after": "tokens_valid_after" in cols, "unique_session_index": "ux_user_sessions_session" in idx}


def s_legacy_upgrade():
    """Start from the verbatim pre-G-006 schema with real legacy data, then run the new init_db()."""
    import psycopg
    from orca.config import orneur_env
    sql = (ROOT / "tests" / "fixtures" / "legacy_auth_schema_pre_g006_postgres.sql").read_text()
    schema, rls = sql.split("-- ==RLS==")
    conn = psycopg.connect(orneur_env("DATABASE_URL"), autocommit=True)
    cur = conn.cursor()
    for stmt in filter(None, (s.strip() for s in schema.split(";"))):
        cur.execute(stmt)
    cur.execute(rls)
    now = "2026-01-01T00:00:00+00:00"
    cur.execute("INSERT INTO users (id,email,name,password_hash,tier,role,created_at,signup_seq) VALUES ('legacy-owner','o@example.com','o','h','free','owner',%s,1)", (now,))
    cur.execute("INSERT INTO users (id,email,name,password_hash,tier,role,created_at,signup_seq) VALUES ('legacy-user','u@example.com','u','h','free','member',%s,2)", (now,))
    # two owners for one session: the pre-G-006 race outcome the migration must collapse to the EARLIEST claim
    cur.execute("INSERT INTO user_sessions (user_id, session_id, created_at) VALUES ('legacy-owner','dup-session','2026-01-01T00:00:01+00:00')")
    cur.execute("INSERT INTO user_sessions (user_id, session_id, created_at) VALUES ('legacy-user','dup-session','2026-01-01T00:00:09+00:00')")
    cur.execute("INSERT INTO user_sessions (user_id, session_id, created_at) VALUES ('legacy-user','solo-session',%s)", (now,))
    conn.close()
    from orca.auth import db
    db.init_db()
    with db.get_conn() as c:
        owners = [r["user_id"] for r in c.execute("SELECT user_id FROM user_sessions WHERE session_id='dup-session'").fetchall()]
        total = c.execute("SELECT COUNT(*) AS n FROM user_sessions").fetchone()["n"]
        marker = c.execute("SELECT owner_user_id, method FROM owner_bootstrap WHERE id=1").fetchone()
        roles = {r["id"]: r["role"] for r in c.execute("SELECT id, role FROM users").fetchall()}
        tva = c.execute("SELECT tokens_valid_after FROM users WHERE id='legacy-user'").fetchone()["tokens_valid_after"]
        forced = c.execute("SELECT COUNT(*) AS n FROM pg_class WHERE relforcerowsecurity AND relnamespace = 'public'::regnamespace").fetchone()["n"]
    from orca.auth.store import claim_session, get_user_by_email
    return {"dup_owner_after": owners, "session_rows": total, "marker": dict(marker) if marker else None, "roles": roles, "tokens_valid_after_default": tva,
            "claim_dup_by_loser": claim_session("dup-session", "legacy-user"), "claim_dup_by_winner": claim_session("dup-session", "legacy-owner"),
            "old_login_lookup_ok": get_user_by_email("u@example.com") is not None, "force_rls_tables_after": forced}


def s_concurrent_init():
    """Several processes/threads initialise the schema at the same time (a replica rollout): none may fail."""
    from orca.auth import db
    errs = []

    def go():
        try:
            db.init_db()
        except Exception as e:
            errs.append(f"{type(e).__name__}: {e}")

    ts = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    return {"errors": errs}


def s_bootstrap_races():
    from orca.auth import bootstrap, db
    db.init_db()
    # (a) one token, many redeemers
    em = _email()
    tok = bootstrap.issue_token(em)
    wins, other = [], []

    def go():
        try:
            wins.append(bootstrap.redeem(tok, em, "correct-horse-battery").id)
        except Exception as e:
            other.append(type(e).__name__ + ":" + getattr(e, "code", ""))

    ts = [threading.Thread(target=go) for _ in range(10)]
    [t.start() for t in ts]; [t.join() for t in ts]
    with db.get_conn() as c:
        owners_a = c.execute("SELECT COUNT(*) AS n FROM users WHERE role='owner'").fetchone()["n"]
        singleton_a = c.execute("SELECT COUNT(*) AS n FROM owner_bootstrap").fetchone()["n"]
    # (b) reset, many tokens for many emails
    with db.get_conn() as c:
        c.execute("DELETE FROM users WHERE role='owner'")
    pairs = [(e, bootstrap.issue_token(e)) for e in (_email() for _ in range(8))]
    wins_b = []

    def go2(e, t):
        try:
            wins_b.append(bootstrap.redeem(t, e, "correct-horse-battery").id)
        except Exception:
            pass

    ts = [threading.Thread(target=go2, args=p) for p in pairs]
    [t.start() for t in ts]; [t.join() for t in ts]
    with db.get_conn() as c:
        owners_b = c.execute("SELECT COUNT(*) AS n FROM users WHERE role='owner'").fetchone()["n"]
    return {"wins_single_token": len(wins), "owners_after_single_token": owners_a, "singleton_rows": singleton_a, "wins_many_tokens": len(wins_b), "owners_after_many": owners_b}


def s_signup_counter_and_no_owner():
    from orca.auth import db
    from orca.auth.store import create_user
    db.init_db()
    out, errs = [], []

    def go():
        try:
            u = create_user(_email(), "correct-horse-battery")
            out.append((u.signup_seq, u.role))
        except Exception as e:
            errs.append(repr(e))

    ts = [threading.Thread(target=go) for _ in range(24)]
    [t.start() for t in ts]; [t.join() for t in ts]
    seqs = sorted(s for s, _ in out)
    return {"created": len(out), "errors": errs, "unique_seqs": len(set(seqs)), "contiguous": seqs == list(range(seqs[0], seqs[0] + len(seqs))) if seqs else False, "owners": sum(1 for _, r in out if r == "owner")}


def s_claim_session_races():
    from orca.auth import db
    from orca.auth.store import check_session_access, claim_session, create_user
    db.init_db()
    users = [create_user(_email(), "correct-horse-battery").id for _ in range(12)]
    sid = "race-session-" + uuid.uuid4().hex[:8]
    results = []

    def go(u):
        results.append((u, claim_session(sid, u)))

    ts = [threading.Thread(target=go, args=(u,)) for u in users]
    [t.start() for t in ts]; [t.join() for t in ts]
    granted = [u for u, ok in results if ok]
    with db.get_conn() as c:
        rows = c.execute("SELECT user_id FROM user_sessions WHERE session_id=?", (sid,)).fetchall()
    # storage-prefix collision: the 8-char prefix of a different id must be refused for another user
    a = "abcd1234-first-" + uuid.uuid4().hex[:6]
    b = "abcd1234-second-" + uuid.uuid4().hex[:6]
    first = claim_session(a, users[0])
    second = claim_session(b, users[1])
    return {"granted_count": len(granted), "rows": len(rows), "row_matches_winner": bool(rows) and rows[0]["user_id"] == granted[0] if granted else False,
            "prefix_first": first, "prefix_second_other_user": second, "access_recheck": check_session_access(sid, granted[0]) if granted else None}


def s_rollback_and_password_epoch():
    from orca.auth import db
    from orca.auth.store import create_user, get_user_by_email, update_password
    db.init_db()
    em = _email()
    try:
        with db.get_conn() as c:
            c.execute("INSERT INTO users (id,email,name,password_hash,tier,role,created_at) VALUES (?,?,?,?,?,?,?)",
                      ("rb-" + uuid.uuid4().hex[:6], em, "x", "h", "free", "member", "now"))
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass
    rolled_back = get_user_by_email(em) is None
    u = create_user(_email(), "correct-horse-battery")
    before = time.time()
    update_password(u.id, "another-correct-horse")
    with db.get_conn() as c:
        tva = c.execute("SELECT tokens_valid_after FROM users WHERE id=?", (u.id,)).fetchone()["tokens_valid_after"]
    return {"rolled_back": rolled_back, "tva_is_float": isinstance(tva, float), "tva_recent": before - 1 <= tva <= time.time() + 1}


def s_connections_are_released():
    """Open/close many logical connections: the server must not accumulate them (the adapter used to leak one per call)."""
    from orca.auth import db
    db.init_db()
    for _ in range(150):
        with db.get_conn() as c:
            c.execute("SELECT 1").fetchone()
    with db.get_conn() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM pg_stat_activity WHERE datname = current_database()").fetchone()["n"]
    return {"open_connections": n}


def s_non_superuser_app_role():
    """The app role in managed Postgres is typically the table OWNER but NOT a superuser and without BYPASSRLS. The schema enables FORCE ROW LEVEL SECURITY:
    every ordinary flow must still work (the documented intent is that policies only bite for connections that opted in via set_user_context)."""
    from orca.auth import db
    from orca.auth.store import authenticate, create_user, get_user_by_email
    db.init_db()
    with db.get_conn() as c:
        who = c.execute("SELECT current_user AS u, (SELECT rolsuper FROM pg_roles WHERE rolname=current_user) AS su, "
                        "(SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user) AS bypass").fetchone()
    out = {"role": who["u"], "superuser": who["su"], "bypassrls": who["bypass"]}
    em = _email()
    try:
        u = create_user(em, "correct-horse-battery")
        out["created"] = True
        out["lookup"] = get_user_by_email(em) is not None
        out["login"] = authenticate(em, "correct-horse-battery") is not None
    except Exception as e:
        out["created"] = False
        out["error"] = f"{type(e).__name__}: {str(e)[:160]}"
    return out


def s_replace_race():
    from orca.auth import bootstrap, db
    from orca.auth.store import create_user
    db.init_db()
    em = _email()
    squat = create_user(em, "attacker-password-123")
    tok = bootstrap.issue_token(em, replace_existing_unverified=True)
    wins = []

    def go():
        try:
            wins.append(bootstrap.redeem(tok, em, "correct-horse-battery").id)
        except Exception:
            pass

    ts = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    with db.get_conn() as c:
        owners = c.execute("SELECT COUNT(*) AS n FROM users WHERE role='owner'").fetchone()["n"]
        squat_left = c.execute("SELECT COUNT(*) AS n FROM users WHERE id=?", (squat.id,)).fetchone()["n"]
        users_for_email = c.execute("SELECT COUNT(*) AS n FROM users WHERE email=?", (em,)).fetchone()["n"]
    return {"wins": len(wins), "owners": owners, "squatter_rows": squat_left, "rows_for_email": users_for_email}


def s_upgrade_from_g021_v1_schema():
    """A deployment that already ran the first G-021 migration (no replace_existing column) must upgrade in place."""
    import psycopg
    from orca.auth import db
    from orca.config import orneur_env
    db.init_db()
    conn = psycopg.connect(orneur_env("DATABASE_URL"), autocommit=True)
    conn.cursor().execute("ALTER TABLE owner_bootstrap_tokens DROP COLUMN replace_existing")
    conn.close()
    db.init_db()
    from orca.auth import bootstrap
    tok = bootstrap.issue_token(_email(), replace_existing_unverified=True)
    with db.get_conn() as c:
        flag = c.execute("SELECT replace_existing FROM owner_bootstrap_tokens").fetchone()["replace_existing"]
    return {"flag": flag, "token_prefix": tok[:13]}


SCENARIOS = {k[2:]: v for k, v in globals().items() if k.startswith("s_")}

if __name__ == "__main__":
    name = sys.argv[1]
    try:
        print(json.dumps({"ok": True, "result": SCENARIOS[name]()}, default=str))
    except Exception:
        print(json.dumps({"ok": False, "error": traceback.format_exc()[-1500:]}))
