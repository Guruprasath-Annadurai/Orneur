"""B06/B09: pins are owner metadata. A share is an expiring grant.

The grantee reads through the share id. The session message route stays closed.
"""
from __future__ import annotations

import pytest

from orca.serve import organization
from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_b_conversations import _chat
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


@pytest.fixture
def fake(client, monkeypatch):
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    with FakeOllama(reply="The answer is 42.", chunks=("The answer ", "is 42.")) as backend:
        point_orneur_at(backend, monkeypatch)
        yield backend


def test_pin_and_folder_are_visible_only_to_the_owner(client, fake):
    owner, _owner_id = _signup(client)
    other, _other_id = _signup(client)
    headers = _hdr(owner)
    first = _chat(client, headers, "pin this conversation")["session_id"]
    second = _chat(client, headers, "and this one")["session_id"]
    assert client.post(f"/api/session/{first}/pin", headers=_hdr(other)).status_code == 404
    assert client.post(f"/api/session/{first}/pin", headers=headers).status_code == 200
    assert client.post(f"/api/session/{second}/pin", headers=headers).status_code == 200
    listed = client.get("/api/sessions", headers=headers).json()["sessions"]
    flags = {item["id"]: item["pinned"] for item in listed}
    assert flags[first] is True and flags[second] is True
    assert client.delete(f"/api/session/{first}/pin", headers=headers).status_code == 200
    flags = {item["id"]: item["pinned"] for item in client.get("/api/sessions", headers=headers).json()["sessions"]}
    assert flags[first] is False and flags[second] is True
    folder = client.post("/api/folders", json={"name": "Work"}, headers=headers)
    assert folder.status_code == 200, folder.text
    added = client.post(
        f"/api/folders/{folder.json()['folder_id']}/sessions",
        json={"session_id": second},
        headers=headers,
    )
    assert added.status_code == 200
    assert second in added.json()["session_ids"]
    assert client.get("/api/folders", headers=_hdr(other)).json()["folders"] == []


def test_share_grant_expires_and_revokes_without_opening_the_session_route(client, fake, monkeypatch):
    owner, _owner_id = _signup(client)
    grantee, grantee_id = _signup(client)
    stranger, _stranger_id = _signup(client)
    headers = _hdr(owner)
    sid = _chat(client, headers, "shared words stay behind the grant")["session_id"]
    created = client.post(
        f"/api/session/{sid}/shares",
        json={"grantee_id": grantee_id, "ttl_seconds": 3600},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    share_id = created.json()["share_id"]
    assert client.get(f"/api/session/{sid}/messages", headers=_hdr(grantee)).status_code == 404
    granted = client.get(f"/api/shares/{share_id}/messages", headers=_hdr(grantee))
    assert granted.status_code == 200, granted.text
    assert "shared words stay behind the grant" in granted.text
    incoming = client.get("/api/shares/incoming", headers=_hdr(grantee)).json()["shares"]
    assert share_id in {item["share_id"] for item in incoming}
    assert client.get(f"/api/shares/{share_id}/messages", headers=_hdr(stranger)).status_code == 404
    monkeypatch.setattr(organization.time, "time", lambda: created.json()["expires_at"] + 1)
    assert client.get(f"/api/shares/{share_id}/messages", headers=_hdr(grantee)).status_code == 409
    second = client.post(
        f"/api/session/{sid}/shares",
        json={"grantee_id": grantee_id, "ttl_seconds": 3600},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert client.post(f"/api/shares/{second.json()['share_id']}/revoke", headers=_hdr(grantee)).status_code == 404
    revoked = client.post(f"/api/shares/{second.json()['share_id']}/revoke", headers=headers)
    assert revoked.status_code == 200 and revoked.json()["state"] == "revoked"
    assert client.get(f"/api/shares/{second.json()['share_id']}/messages", headers=_hdr(grantee)).status_code == 409
    assert client.get(f"/api/session/{sid}/messages", headers=_hdr(grantee)).status_code == 404
    assert "session_id" not in created.json()
    assert "session_id" not in granted.json()


def test_temporary_chats_and_deleted_conversations_are_not_shared(client, fake):
    owner, _owner_id = _signup(client)
    grantee, grantee_id = _signup(client)
    headers = _hdr(owner)
    opened = client.post("/api/sessions/temporary", json={"ttl_seconds": 3600}, headers=headers)
    assert opened.status_code == 200, opened.text
    temporary_id = opened.json()["session_id"]
    _chat(client, headers, "temporary words stay here", sid=temporary_id)
    refused = client.post(
        f"/api/session/{temporary_id}/shares",
        json={"grantee_id": grantee_id, "ttl_seconds": 3600},
        headers=headers,
    )
    assert refused.status_code == 400 and refused.json()["code"] == "temporary_not_shareable"
    self_share = client.post(
        f"/api/session/{temporary_id}/shares",
        json={"grantee_id": _owner_id, "ttl_seconds": 3600},
        headers=headers,
    )
    assert self_share.status_code == 400 and self_share.json()["code"] == "share_rejected"
    normal = _chat(client, headers, "delete this shared conversation")["session_id"]
    created = client.post(
        f"/api/session/{normal}/shares",
        json={"grantee_id": grantee_id, "ttl_seconds": 60},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    short = client.post(
        f"/api/session/{normal}/shares",
        json={"grantee_id": grantee_id, "ttl_seconds": 10},
        headers=headers,
    )
    assert short.status_code == 400 and short.json()["code"] == "share_rejected"
    assert client.delete(f"/api/session/{normal}", headers=headers).status_code == 200
    assert client.get(f"/api/shares/{created.json()['share_id']}/messages", headers=_hdr(grantee)).status_code == 409
    listed = client.get("/api/sessions", headers=headers).json()["sessions"]
    assert normal not in [item["id"] for item in listed]
