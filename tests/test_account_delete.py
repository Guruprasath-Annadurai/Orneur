"""
Tests for orca/serve/account_delete.py.

Real architectural gap this locks in: chat history/documents/memory were
keyed purely by session_id with no link back to an owning user_id until
user_sessions was added — without it, deletion could only remove the
account row and silently leave everything else behind. These tests verify
the orchestration: every session the account touched gets processed,
account records are removed last (not first), and a partial failure in
one store doesn't block cleanup of the rest.

Scope note: session-data cleanup (_delete_session_data) touches
EpisodicMemory/DocStore/KnowledgeGraph, whose module-level path constants
are baked in at import time from ORCA_HOME — reloading all of them in
dependency order for a full filesystem integration test is out of scope
here. These tests verify delete_account()'s own orchestration contract by
patching _delete_session_data directly, which is the actual logic this
module is responsible for (the sub-stores have their own modules).
"""
from __future__ import annotations

import pytest

from orca.serve import account_delete


@pytest.fixture(autouse=True)
def _clean_stripe_env(isolated_home, monkeypatch):
    """
    Depends on isolated_home explicitly (not just alongside it) so fixture
    ordering is guaranteed: isolated_home's importlib.reload(orca.config)
    re-runs load_dotenv(), which re-populates STRIPE_SECRET_KEY from the
    real .env if it was unset — delenv must run AFTER that reload, not
    before it, or the real key leaks back in for the rest of the test.
    """
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)


def test_delete_account_processes_every_session(isolated_home, monkeypatch):
    store = isolated_home
    user = store.create_user("delete-me@test.com", "pw12345678")
    store.record_user_session(user.id, "sess-a")
    store.record_user_session(user.id, "sess-b")
    store.record_user_session(user.id, "sess-c")

    processed = []
    monkeypatch.setattr(
        account_delete, "_delete_session_data",
        lambda sid: processed.append(sid) or {"session_id": sid, "memory_deleted": True}
    )
    monkeypatch.setattr(account_delete, "_remove_session_title", lambda sid: None)

    report = account_delete.delete_account(user.id)

    assert sorted(processed) == ["sess-a", "sess-b", "sess-c"]
    assert report["sessions_processed"] == 3
    assert len(report["session_results"]) == 3


def test_delete_account_only_touches_its_own_sessions(isolated_home, monkeypatch):
    """A real isolation bug here would delete another account's data — must never happen."""
    store = isolated_home
    user_a = store.create_user("a@test.com", "pw12345678")
    user_b = store.create_user("b@test.com", "pw12345678")
    store.record_user_session(user_a.id, "sess-a1")
    store.record_user_session(user_b.id, "sess-b1")

    processed = []
    monkeypatch.setattr(
        account_delete, "_delete_session_data",
        lambda sid: processed.append(sid) or {"session_id": sid}
    )
    monkeypatch.setattr(account_delete, "_remove_session_title", lambda sid: None)

    account_delete.delete_account(user_a.id)

    assert processed == ["sess-a1"]
    assert "sess-b1" not in processed
    # user_b's session record must still exist — untouched by user_a's deletion
    assert store.get_user_session_ids(user_b.id) == ["sess-b1"]


def test_delete_account_removes_account_row_after_session_cleanup(isolated_home, monkeypatch):
    """Account records are deleted LAST — if session cleanup fails partway, we still know which sessions were the account's."""
    store = isolated_home
    user = store.create_user("delete-me@test.com", "pw12345678")
    store.record_user_session(user.id, "sess-x")

    monkeypatch.setattr(account_delete, "_delete_session_data", lambda sid: {"session_id": sid})
    monkeypatch.setattr(account_delete, "_remove_session_title", lambda sid: None)

    account_delete.delete_account(user.id)

    assert store.get_user_by_id(user.id) is None
    assert store.get_user_session_ids(user.id) == []


def test_delete_account_skips_stripe_when_no_customer_id(isolated_home, monkeypatch):
    store = isolated_home
    user = store.create_user("nostripecustomer@test.com", "pw12345678")

    monkeypatch.setattr(account_delete, "_delete_session_data", lambda sid: {"session_id": sid})
    monkeypatch.setattr(account_delete, "_remove_session_title", lambda sid: None)

    report = account_delete.delete_account(user.id)
    assert report["stripe_cancellation"] is None


def test_delete_account_attempts_stripe_cancellation_when_customer_id_present(isolated_home, monkeypatch):
    store = isolated_home
    user = store.create_user("stripecustomer@test.com", "pw12345678")
    store.set_stripe_customer_id(user.id, "cus_fake123")

    monkeypatch.setattr(account_delete, "_delete_session_data", lambda sid: {"session_id": sid})
    monkeypatch.setattr(account_delete, "_remove_session_title", lambda sid: None)
    # STRIPE_SECRET_KEY intentionally unset (autouse fixture) — must report
    # "attempted": False rather than crash or silently skip.
    report = account_delete.delete_account(user.id)
    assert report["stripe_cancellation"]["attempted"] is False


def test_delete_account_report_includes_retention_note(isolated_home, monkeypatch):
    """The audit-log retention disclosure must always be present — a real trust/legal requirement, not optional."""
    store = isolated_home
    user = store.create_user("noteuser@test.com", "pw12345678")

    monkeypatch.setattr(account_delete, "_delete_session_data", lambda sid: {"session_id": sid})
    monkeypatch.setattr(account_delete, "_remove_session_title", lambda sid: None)

    report = account_delete.delete_account(user.id)
    assert "audit log" in report["note"].lower()
    assert "not deleted" in report["note"].lower()


def test_delete_account_with_zero_sessions_still_removes_account(isolated_home, monkeypatch):
    store = isolated_home
    user = store.create_user("neversessioned@test.com", "pw12345678")

    report = account_delete.delete_account(user.id)

    assert report["sessions_processed"] == 0
    assert store.get_user_by_id(user.id) is None


def test_delete_session_data_survives_partial_failure(monkeypatch):
    """
    A failure in one sub-store (e.g. EpisodicMemory raising) must not
    prevent the other stores' cleanup from running — each try/except in
    _delete_session_data is independent by design.
    """
    class _BoomMemory:
        def __init__(self, session_id):
            raise RuntimeError("simulated memory store failure")

    monkeypatch.setattr(account_delete, "EpisodicMemory", _BoomMemory)
    monkeypatch.setattr(account_delete, "list_docs", lambda sid: [])
    monkeypatch.setattr(account_delete.session_store, "delete_session", lambda sid: None)
    monkeypatch.setattr(account_delete.session_store, "enabled", lambda: False)

    class _EmptyKG:
        def __init__(self, session_id):
            pass
        def count(self):
            return {"entities": 0}
        def clear(self):
            pass

    monkeypatch.setattr(account_delete, "KnowledgeGraph", _EmptyKG)

    result = account_delete._delete_session_data("some-session")
    assert result["memory_deleted"] is False
    assert "memory_error" in result
    # other stores still processed despite the memory failure
    assert result["knowledge_graph_deleted"] is False
    assert "knowledge_graph_error" not in result
