"""
Tests for orca/auth/privacy.py — consent tracking, data export requests,
and the security breach log.

Real gap this closes: before this module existed, Orca had no structured
record of what a user consented to, no data-portability mechanism, and no
dedicated incident tracking table. These tests lock in the actual
behaviors that make those real (append-only audit trail, one-pending-
export-at-a-time, immutability of breach records), not just that the
functions run without raising.
"""
from __future__ import annotations

import pytest


def test_set_consent_creates_new_record(isolated_home):
    store = isolated_home
    import orca.auth.privacy as privacy

    user = store.create_user("a@test.com", "pw12345678")
    result = privacy.set_consent(user.id, "analytics", granted=True)

    assert result["granted"] is True
    consents = privacy.get_consents(user.id)
    assert consents["analytics"]["granted"] is True
    assert consents["analytics"]["granted_at"] is not None
    assert consents["analytics"]["revoked_at"] is None


def test_set_consent_rejects_unknown_purpose(isolated_home):
    store = isolated_home
    import orca.auth.privacy as privacy

    user = store.create_user("a@test.com", "pw12345678")
    with pytest.raises(ValueError):
        privacy.set_consent(user.id, "not_a_real_purpose", granted=True)


def test_set_consent_revoke_updates_existing_row_not_duplicate(isolated_home):
    """Real behavior being locked in: revoking consent must UPDATE the
    existing (user_id, purpose) row, not insert a second one — the UNIQUE
    constraint exists specifically to prevent a user having two
    contradictory 'current' consent states for the same purpose."""
    store = isolated_home
    import orca.auth.privacy as privacy

    user = store.create_user("a@test.com", "pw12345678")
    privacy.set_consent(user.id, "marketing_email", granted=True)
    privacy.set_consent(user.id, "marketing_email", granted=False)

    consents = privacy.get_consents(user.id)
    assert len(consents) == 1
    assert consents["marketing_email"]["granted"] is False
    assert consents["marketing_email"]["revoked_at"] is not None


def test_consent_audit_trail_records_every_change(isolated_home):
    """The actual evidence a legal request for 'prove what this user
    consented to and when' would need — not just current state."""
    store = isolated_home
    import orca.auth.privacy as privacy

    user = store.create_user("a@test.com", "pw12345678")
    privacy.set_consent(user.id, "training", granted=True)
    privacy.set_consent(user.id, "training", granted=False)
    privacy.set_consent(user.id, "training", granted=True)

    trail = privacy.get_consent_audit_trail(user.id)
    assert len(trail) == 3
    assert [t["action"] for t in trail] == ["granted", "revoked", "granted"]
    assert trail[0]["previous_state"] is None
    assert trail[1]["previous_state"] is True
    assert trail[2]["previous_state"] is False


def test_consent_audit_log_is_append_only(isolated_home):
    """Real DB-level enforcement, not just application convention — an
    UPDATE or DELETE against consent_audit_log must fail at the database
    layer even if application code tried to do it."""
    store = isolated_home
    import orca.auth.privacy as privacy
    from orca.auth.db import get_conn

    user = store.create_user("a@test.com", "pw12345678")
    privacy.set_consent(user.id, "analytics", granted=True)

    with get_conn() as conn:
        row = conn.execute("SELECT id FROM consent_audit_log WHERE user_id = ?", (user.id,)).fetchone()
        entry_id = row["id"]

    with pytest.raises(Exception):
        with get_conn() as conn:
            conn.execute("UPDATE consent_audit_log SET new_state = 0 WHERE id = ?", (entry_id,))

    with pytest.raises(Exception):
        with get_conn() as conn:
            conn.execute("DELETE FROM consent_audit_log WHERE id = ?", (entry_id,))


def test_init_default_consents_seeds_necessary_cookies(isolated_home):
    store = isolated_home
    import orca.auth.privacy as privacy

    user = store.create_user("a@test.com", "pw12345678")
    privacy.init_default_consents(user.id)

    consents = privacy.get_consents(user.id)
    assert consents["cookies_necessary"]["granted"] is True
    assert consents["cookies_necessary"]["source"] == "default"


def test_request_data_export_creates_pending_request(isolated_home):
    store = isolated_home
    import orca.auth.privacy as privacy

    user = store.create_user("a@test.com", "pw12345678")
    result = privacy.request_data_export(user.id)

    assert result["status"] == "pending"
    requests = privacy.get_export_requests(user.id)
    assert len(requests) == 1
    assert requests[0]["status"] == "pending"


def test_request_data_export_blocks_second_pending_request(isolated_home):
    """Real constraint: a user should not be able to queue unlimited
    concurrent export requests — one pending at a time."""
    store = isolated_home
    import orca.auth.privacy as privacy

    user = store.create_user("a@test.com", "pw12345678")
    privacy.request_data_export(user.id)

    with pytest.raises(ValueError):
        privacy.request_data_export(user.id)


def test_mark_export_complete_updates_status_and_path(isolated_home):
    store = isolated_home
    import orca.auth.privacy as privacy

    user = store.create_user("a@test.com", "pw12345678")
    result = privacy.request_data_export(user.id)
    privacy.mark_export_complete(result["id"], "/tmp/export.zip")

    requests = privacy.get_export_requests(user.id)
    assert requests[0]["status"] == "completed"
    assert requests[0]["file_path"] == "/tmp/export.zip"
    assert requests[0]["completed_at"] is not None


def test_mark_export_complete_allows_new_request_after_completion(isolated_home):
    """Once the pending request resolves (completed), the one-pending-
    request-at-a-time gate should allow a new request — this isn't a
    lifetime limit, just a concurrency guard."""
    store = isolated_home
    import orca.auth.privacy as privacy

    user = store.create_user("a@test.com", "pw12345678")
    first = privacy.request_data_export(user.id)
    privacy.mark_export_complete(first["id"], "/tmp/export1.zip")

    second = privacy.request_data_export(user.id)
    assert second["status"] == "pending"


def test_log_breach_rejects_unknown_type(isolated_home):
    _ = isolated_home
    import orca.auth.privacy as privacy

    with pytest.raises(ValueError):
        privacy.log_breach(
            title="test", description="test", breach_type="not_a_real_type", reported_by="tester",
        )


def test_log_breach_creates_open_incident(isolated_home):
    _ = isolated_home
    import orca.auth.privacy as privacy

    result = privacy.log_breach(
        title="Suspicious login pattern",
        description="Multiple failed logins from one IP range",
        breach_type="unauthorized_access",
        severity="high",
        affected_user_ids=["u1", "u2"],
        data_categories=["email"],
        reported_by="tester",
    )

    assert result["status"] == "open"
    breaches = privacy.list_breaches()
    assert len(breaches) == 1
    assert breaches[0]["affected_user_ids"] == ["u1", "u2"]
    assert breaches[0]["data_categories"] == ["email"]


def test_update_breach_status_to_contained_sets_timestamp(isolated_home):
    _ = isolated_home
    import orca.auth.privacy as privacy

    result = privacy.log_breach(
        title="test", description="test", breach_type="accidental", reported_by="tester",
    )
    privacy.update_breach_status(result["id"], "contained", remediation_steps="Rotated credentials")

    breaches = privacy.list_breaches()
    assert breaches[0]["status"] == "contained"
    assert breaches[0]["contained_at"] is not None
    assert breaches[0]["remediation_steps"] == "Rotated credentials"


def test_update_breach_status_rejects_invalid_status(isolated_home):
    _ = isolated_home
    import orca.auth.privacy as privacy

    result = privacy.log_breach(
        title="test", description="test", breach_type="accidental", reported_by="tester",
    )
    with pytest.raises(ValueError):
        privacy.update_breach_status(result["id"], "not_a_real_status")


def test_breach_log_delete_is_blocked_at_db_layer(isolated_home):
    """Real DB-level immutability — the historical fact an incident was
    opened must survive even a direct DELETE attempt."""
    _ = isolated_home
    import orca.auth.privacy as privacy
    from orca.auth.db import get_conn

    result = privacy.log_breach(
        title="test", description="test", breach_type="accidental", reported_by="tester",
    )

    with pytest.raises(Exception):
        with get_conn() as conn:
            conn.execute("DELETE FROM security_breach_log WHERE id = ?", (result["id"],))

    assert len(privacy.list_breaches()) == 1


def test_list_breaches_filters_by_status(isolated_home):
    _ = isolated_home
    import orca.auth.privacy as privacy

    open_result = privacy.log_breach(
        title="open one", description="test", breach_type="accidental", reported_by="tester",
    )
    closed_result = privacy.log_breach(
        title="closed one", description="test", breach_type="accidental", reported_by="tester",
    )
    privacy.update_breach_status(closed_result["id"], "closed")

    open_breaches = privacy.list_breaches(status="open")
    assert len(open_breaches) == 1
    assert open_breaches[0]["id"] == open_result["id"]


def test_mark_users_notified_sets_flag_and_timestamp(isolated_home):
    _ = isolated_home
    import orca.auth.privacy as privacy

    result = privacy.log_breach(
        title="test", description="test", breach_type="accidental", reported_by="tester",
    )
    privacy.mark_users_notified(result["id"])

    breaches = privacy.list_breaches()
    assert breaches[0]["users_notified"] == 1
    assert breaches[0]["users_notified_at"] is not None
