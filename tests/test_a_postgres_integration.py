"""Workstream A -- REAL PostgreSQL migration and concurrency tests (PostgreSQL 16 started locally by `pgserver`; skipped when it is not installed).

Each scenario runs in a fresh subprocess so `orca.auth.db` binds to PostgreSQL at import time exactly as in production.
Install: `pip install -e ".[pgtest]"`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

pgserver = pytest.importorskip("pgserver")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def pg(tmp_path_factory):
    d = tmp_path_factory.mktemp("pgdata")
    srv = pgserver.get_server(str(d), cleanup_mode="stop")
    yield srv
    srv.cleanup()


def _run(pg, scenario: str, tmp_path, fresh_db=True, role: str | None = None):
    base = pg.get_uri()
    name = "t_" + uuid.uuid4().hex[:10]
    if role:
        pg.psql(f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{role}') THEN CREATE ROLE {role} LOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$;")
        pg.psql(f"CREATE DATABASE {name} OWNER {role};")
        pg.psql(f"GRANT ALL ON SCHEMA public TO {role};") if False else None
    else:
        pg.psql(f"CREATE DATABASE {name};")
    uri = base.replace("/postgres?", f"/{name}?")
    if role:
        uri = uri.replace("postgres:@", f"{role}:@")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ORNEUR_", "ORCA_"))}
    env.update({"ORNEUR_DATABASE_URL": uri, "ORNEUR_HOME": str(tmp_path / "home"), "PYTHONPATH": str(ROOT)})
    p = subprocess.run([sys.executable, str(ROOT / "tests" / "_pg_scenarios.py"), scenario], env=env, capture_output=True, text=True, timeout=300, cwd=ROOT)
    assert p.stdout.strip(), p.stderr[-1500:]
    out = json.loads(p.stdout.strip().splitlines()[-1])
    assert out["ok"], out.get("error")
    return out["result"]


def test_fresh_schema_has_everything_and_init_is_idempotent(pg, tmp_path):
    r = _run(pg, "fresh_init", tmp_path)
    assert r["backend"] == "postgres" and r["has_tokens_valid_after"] and r["unique_session_index"]
    assert r["tables"] == ["idempotency_keys", "owner_bootstrap", "owner_bootstrap_tokens", "revoked_tokens", "session_storage_keys", "signup_counter", "usage_daily", "user_sessions", "user_settings", "users"]


def test_upgrade_from_the_pre_g006_schema_keeps_data_and_collapses_duplicate_owners(pg, tmp_path):
    r = _run(pg, "legacy_upgrade", tmp_path)
    assert r["dup_owner_after"] == ["legacy-owner"]                       # earliest claim wins
    assert r["session_rows"] == 2
    assert r["marker"] == {"owner_user_id": "legacy-owner", "method": "legacy_existing_owner"}
    assert r["roles"] == {"legacy-owner": "owner", "legacy-user": "member"}   # no role invented or changed
    assert r["tokens_valid_after_default"] == 0
    assert r["claim_dup_by_winner"] is True and r["claim_dup_by_loser"] is False
    assert r["old_login_lookup_ok"] is True
    assert r["force_rls_tables_after"] == 0                                 # the FORCE ROW LEVEL SECURITY of the old schema is migrated away


def test_concurrent_schema_initialisation_by_many_workers_does_not_fail(pg, tmp_path):
    assert _run(pg, "concurrent_init", tmp_path)["errors"] == []


def test_owner_bootstrap_has_exactly_one_winner_under_real_concurrency(pg, tmp_path):
    r = _run(pg, "bootstrap_races", tmp_path)
    assert r["wins_single_token"] == 1 and r["owners_after_single_token"] == 1 and r["singleton_rows"] == 1
    assert r["wins_many_tokens"] == 1 and r["owners_after_many"] == 1


def test_concurrent_signups_get_unique_contiguous_sequence_numbers_and_nobody_is_owner(pg, tmp_path):
    r = _run(pg, "signup_counter_and_no_owner", tmp_path)
    assert r["errors"] == [] and r["created"] == 24 and r["unique_seqs"] == 24 and r["contiguous"] and r["owners"] == 0


def test_session_claims_are_atomic_and_storage_prefix_collisions_fail_closed(pg, tmp_path):
    r = _run(pg, "claim_session_races", tmp_path)
    assert r["granted_count"] == 1 and r["rows"] == 1 and r["row_matches_winner"] and r["access_recheck"] is True
    assert r["prefix_first"] is True and r["prefix_second_other_user"] is False


def test_transactions_roll_back_and_the_password_epoch_is_a_float(pg, tmp_path):
    r = _run(pg, "rollback_and_password_epoch", tmp_path)
    assert r["rolled_back"] and r["tva_is_float"] and r["tva_recent"]


def test_connections_are_released_after_each_use(pg, tmp_path):
    assert _run(pg, "connections_are_released", tmp_path)["open_connections"] <= 5


def test_the_schema_works_for_a_non_superuser_table_owner_with_force_row_level_security(pg, tmp_path):
    """Managed PostgreSQL gives the application a NON-superuser owner role. FORCE ROW LEVEL SECURITY applies to table owners, so a policy set that requires a
    per-connection context would make every ordinary query return nothing. Ordinary flows must keep working."""
    r = _run(pg, "non_superuser_app_role", tmp_path, role="orneur_app")
    assert r["superuser"] is False and r["bypassrls"] is False
    assert r.get("created") is True, json.dumps(r)
    assert r["lookup"] is True and r["login"] is True, r


def test_squatter_replacement_has_one_winner_and_leaves_no_duplicate_account(pg, tmp_path):
    r = _run(pg, "replace_race", tmp_path)
    assert r["wins"] == 1 and r["owners"] == 1 and r["squatter_rows"] == 0 and r["rows_for_email"] == 1


def test_a_deployment_on_the_first_g021_schema_upgrades_in_place(pg, tmp_path):
    r = _run(pg, "upgrade_from_g021_v1_schema", tmp_path)
    assert r["flag"] == 1 and r["token_prefix"] == "orneur-owner-"


def test_workstream_b_stores_work_on_postgres_including_idempotency_races(pg, tmp_path):
    r = _run(pg, "workstream_b_stores", tmp_path)
    assert r["begin_states"].count("new") == 1 and r["begin_states"].count("in_progress") == 9          # exactly one winner of the key
    assert r["replay"] == ["done", {"ok": True}] and r["mismatch"] == "mismatch"
    assert r["revoked"] and r["old_gone"] and r["purged"] == 1
    assert r["retention"] == 45 and r["in_retention_list"] == [45]
    assert r["history"][0]["messages"] == 2 and r["history"][0]["ultra_runs"] == 1
    assert r["claimed"] and r["released"] and r["reclaimed_by_other"]                                     # a released id is free again
    assert r["epoch_advanced"]


def test_the_real_application_flow_runs_on_postgres_end_to_end(pg, tmp_path):
    """Signup, chat, usage metering, streaming, durable history, search, logout/revocation and owner bootstrap through the real FastAPI app on PostgreSQL 16
    (the model is the FakeOllama test double)."""
    r = _run(pg, "api_flow_on_postgres", tmp_path)
    assert r["backend"] == "postgres" and r["signup"] == 200 and r["role"] == "member"
    assert r["chat"] == 200, r["chat_body"]
    assert r["usage"]["messages"] == 1 and r["stream_done"] and r["messages_total"] == 4 and r["search_hits"] == 1
    assert r["me_before"] == 200 and r["logout"] == 200 and r["me_after"] == 401
    assert r["bootstrap"] == 200 and r["bootstrap_role"] == "owner"
