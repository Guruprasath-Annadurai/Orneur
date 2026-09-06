"""
Tests for orca/auth/org_store.py — enterprise/team management.

Covers: lazy org creation, seat limit enforcement (the real constraint
since there's no separate seat-billing product), invite/accept lifecycle,
duplicate-invite rejection, role validation, and member removal.
"""
from __future__ import annotations

import pytest


def test_get_or_create_org_is_idempotent(isolated_home):
    from orca.auth import org_store
    owner = isolated_home.create_user("owner@test.com", "pw12345678")
    org_id_1 = org_store.get_or_create_org(owner.id, "Owner")
    org_id_2 = org_store.get_or_create_org(owner.id, "Owner")
    assert org_id_1 == org_id_2


def test_seat_usage_starts_at_one_for_owner_only(isolated_home):
    from orca.auth import org_store
    owner = isolated_home.create_user("owner@test.com", "pw12345678")
    org_id = org_store.get_or_create_org(owner.id)
    usage = org_store.get_seat_usage(org_id, "free")
    assert usage == {"used": 1, "limit": 1}


def test_invite_member_success(isolated_home):
    from orca.auth import org_store
    owner = isolated_home.create_user("owner@test.com", "pw12345678")
    org_id = org_store.get_or_create_org(owner.id)
    result = org_store.invite_member(org_id, "pro", "invitee@test.com", role="member")
    assert result["email"] == "invitee@test.com"
    assert result["role"] == "member"
    assert result["invite_token"]

    members = org_store.list_members(org_id)
    assert len(members) == 1
    assert members[0]["status"] == "invited"
    assert members[0]["invited_email"] == "invitee@test.com"


def test_invite_rejects_when_seat_limit_reached(isolated_home):
    from orca.auth import org_store
    owner = isolated_home.create_user("owner@test.com", "pw12345678")
    org_id = org_store.get_or_create_org(owner.id)
    # free tier: limit=1, owner already counts as 1 — any invite should fail
    with pytest.raises(ValueError, match="Seat limit reached"):
        org_store.invite_member(org_id, "free", "invitee@test.com")


def test_invite_rejects_duplicate_pending_invite(isolated_home):
    from orca.auth import org_store
    owner = isolated_home.create_user("owner@test.com", "pw12345678")
    org_id = org_store.get_or_create_org(owner.id)
    org_store.invite_member(org_id, "pro", "invitee@test.com")
    with pytest.raises(ValueError, match="already a member or has a pending invite"):
        org_store.invite_member(org_id, "pro", "invitee@test.com")


def test_invite_rejects_invalid_role(isolated_home):
    from orca.auth import org_store
    owner = isolated_home.create_user("owner@test.com", "pw12345678")
    org_id = org_store.get_or_create_org(owner.id)
    with pytest.raises(ValueError, match="Invalid role"):
        org_store.invite_member(org_id, "pro", "invitee@test.com", role="owner")


def test_accept_invite_links_real_user_and_consumes_token(isolated_home):
    from orca.auth import org_store
    owner = isolated_home.create_user("owner@test.com", "pw12345678")
    org_id = org_store.get_or_create_org(owner.id)
    invite = org_store.invite_member(org_id, "pro", "invitee@test.com")

    invitee = isolated_home.create_user("invitee@test.com", "pw12345678")
    result = org_store.accept_invite(invite["invite_token"], invitee.id)
    assert result["org_id"] == org_id
    assert result["role"] == "member"

    members = org_store.list_members(org_id)
    assert members[0]["status"] == "active"
    assert members[0]["user_id"] == invitee.id
    assert members[0]["joined_at"] is not None

    # token is single-use — a replay must fail
    with pytest.raises(ValueError, match="Invalid or already-used"):
        org_store.accept_invite(invite["invite_token"], invitee.id)


def test_accept_invite_rejects_unknown_token(isolated_home):
    from orca.auth import org_store
    with pytest.raises(ValueError, match="Invalid or already-used"):
        org_store.accept_invite("not-a-real-token", "some-user-id")


def test_set_member_role_updates_role(isolated_home):
    from orca.auth import org_store
    owner = isolated_home.create_user("owner@test.com", "pw12345678")
    org_id = org_store.get_or_create_org(owner.id)
    invite = org_store.invite_member(org_id, "pro", "invitee@test.com")
    org_store.set_member_role(org_id, invite["member_id"], "admin")
    members = org_store.list_members(org_id)
    assert members[0]["role"] == "admin"


def test_set_member_role_rejects_invalid_role(isolated_home):
    from orca.auth import org_store
    owner = isolated_home.create_user("owner@test.com", "pw12345678")
    org_id = org_store.get_or_create_org(owner.id)
    invite = org_store.invite_member(org_id, "pro", "invitee@test.com")
    with pytest.raises(ValueError, match="Invalid role"):
        org_store.set_member_role(org_id, invite["member_id"], "superadmin")


def test_remove_member_deletes_row_and_frees_seat(isolated_home):
    from orca.auth import org_store
    owner = isolated_home.create_user("owner@test.com", "pw12345678")
    org_id = org_store.get_or_create_org(owner.id)
    invite = org_store.invite_member(org_id, "pro", "invitee@test.com")
    org_store.remove_member(org_id, invite["member_id"])
    assert org_store.list_members(org_id) == []
    # seat freed — can invite again under a tight limit
    usage = org_store.get_seat_usage(org_id, "free")
    assert usage["used"] == 1  # just the owner


def test_get_org_for_owner_none_before_first_invite(isolated_home):
    from orca.auth import org_store
    owner = isolated_home.create_user("owner@test.com", "pw12345678")
    assert org_store.get_org_for_owner(owner.id) is None
    org_store.get_or_create_org(owner.id, "Owner")
    assert org_store.get_org_for_owner(owner.id) is not None
