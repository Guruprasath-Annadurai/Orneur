"""Workstream B (round 2): conversation listing/pagination/rename and document workflows -- against the FakeOllama TEST DOUBLE
(no real model is involved; these prove product plumbing and isolation, not answer quality)."""
from __future__ import annotations

import threading
import uuid

import pytest

from tests.test_b_conversations import _chat, _msgs, fake  # noqa: F401  (fixture re-export)
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401
from tests.test_product_flows_fake_ollama import _upload


def _ids(client, h, **params):
    r = client.get("/api/sessions", params=params, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# ── listing and pagination ─────────────────────────────────────────────────────────────────────────────────────────

def test_a_new_conversation_appears_in_the_list_without_any_explicit_save(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _chat(client, h, "plan the launch")["session_id"]
    assert sid in [s["id"] for s in _ids(client, h)["sessions"]]


def test_list_is_paginated_newest_first_with_a_total_and_a_next_offset(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sids = [_chat(client, h, f"topic {i}")["session_id"] for i in range(7)]
    page1 = _ids(client, h, limit=3, offset=0)
    assert page1["total"] == 7 and len(page1["sessions"]) == 3 and page1["next_offset"] == 3
    assert [s["id"] for s in page1["sessions"]] == list(reversed(sids))[:3]            # newest first
    page3 = _ids(client, h, limit=3, offset=6)
    assert len(page3["sessions"]) == 1 and page3["next_offset"] is None
    seen = [s["id"] for o in (0, 3, 6) for s in _ids(client, h, limit=3, offset=o)["sessions"]]
    assert sorted(seen) == sorted(sids) and len(set(seen)) == 7                      # no gaps, no repeats


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 1000}, {"limit": -1}, {"offset": -1}, {"limit": "x"}])
def test_pagination_parameters_are_validated(client, fake, params):
    t, _ = _signup(client)
    assert client.get("/api/sessions", params=params, headers=_hdr(t)).status_code == 422


def test_the_default_page_is_bounded_and_says_so(client, fake):
    t, _ = _signup(client)
    body = _ids(client, _hdr(t))
    assert "total" in body and "next_offset" in body


# ── rename ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_rename_is_durable_visible_in_list_and_search_and_validated(client, fake):
    import orca.serve.api as api
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _chat(client, h, "quarterly budget")["session_id"]
    assert client.patch(f"/api/session/{sid}/title", json={"title": "  Budget Q4  "}, headers=h).json()["title"] == "Budget Q4"
    api._sessions.clear()                                                              # restart
    assert {s["id"]: s["title"] for s in _ids(client, h)["sessions"]}[sid] == "Budget Q4"
    hits = client.get("/api/sessions/search", params={"q": "budget q4"}, headers=h).json()
    assert sid in str(hits)
    assert client.patch(f"/api/session/{sid}/title", json={"title": "   "}, headers=h).status_code == 422   # blank title refused
    assert client.patch(f"/api/session/{sid}/title", json={"title": "x" * 500}, headers=h).json()["title"] == "x" * 80


def test_only_the_owner_can_rename(client, fake):
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    sid = _chat(client, _hdr(ta), "private")["session_id"]
    assert client.patch(f"/api/session/{sid}/title", json={"title": "pwned"}, headers=_hdr(tb)).status_code == 404
    assert "pwned" not in str(_ids(client, _hdr(ta)))


# ── documents: association, scoping, recovery ───────────────────────────────────────────────────────────────────────

def test_a_document_belongs_to_exactly_one_conversation(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sid_a = _upload(client, h)
    sid_b = _chat(client, h, "unrelated chat")["session_id"]
    a = client.get("/api/docs/list", params={"session_id": sid_a}, headers=h).json()
    b = client.get("/api/docs/list", params={"session_id": sid_b}, headers=h).json()
    assert len(a["docs"]) == 1 and a["docs"][0]["filename"] and b["docs"] == [] and b["total_chunks"] == 0


def test_documents_survive_a_server_restart(client, fake):
    import orca.serve.api as api
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _upload(client, h)
    before = client.get("/api/docs/list", params={"session_id": sid}, headers=h).json()
    api._sessions.clear()
    after = client.get("/api/docs/list", params={"session_id": sid}, headers=h).json()
    assert after["docs"] == before["docs"] and after["total_chunks"] == before["total_chunks"] >= 1


def test_another_user_can_neither_list_nor_delete_my_documents(client, fake):
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    ha, hb = _hdr(ta), _hdr(tb)
    sid = _upload(client, ha)
    doc_id = client.get("/api/docs/list", params={"session_id": sid}, headers=ha).json()["docs"][0]["doc_id"]
    assert client.get("/api/docs/list", params={"session_id": sid}, headers=hb).status_code == 404
    assert client.delete(f"/api/docs/{doc_id}", params={"session_id": sid}, headers=hb).status_code == 404
    assert len(client.get("/api/docs/list", params={"session_id": sid}, headers=ha).json()["docs"]) == 1


def test_deleting_a_document_that_is_not_in_the_conversation_is_reported_honestly(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _upload(client, h)
    r = client.delete(f"/api/docs/{uuid.uuid4()}", params={"session_id": sid}, headers=h)
    assert r.status_code == 404                                                        # not {"deleted": false} with a 200
    assert len(client.get("/api/docs/list", params={"session_id": sid}, headers=h).json()["docs"]) == 1


def test_failed_uploads_leave_no_trace_and_say_why(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _chat(client, h, "hello")["session_id"]
    bad = [("evil.exe", b"MZ\x00", 400), ("empty.txt", b"   \n", 422)]
    for name, data, code in bad:
        r = client.post("/api/docs/upload", params={"session_id": sid}, files={"file": (name, data)}, headers=h)
        assert r.status_code == code, (name, r.text)
        assert "error" in r.json()
    assert client.get("/api/docs/list", params={"session_id": sid}, headers=h).json()["docs"] == []


def test_concurrent_uploads_to_one_conversation_are_all_registered(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _chat(client, h, "hello")["session_id"]
    errors = []

    def up(i):
        try:
            r = client.post("/api/docs/upload", params={"session_id": sid}, files={"file": (f"n{i}.txt", f"unique note number {i} about topic {i}".encode())}, headers=h)
            if r.status_code != 200:
                errors.append(r.text)
        except Exception as e:                                                         # pragma: no cover
            errors.append(repr(e))

    from orca.serve import ratelimit
    ratelimit._local_counters.clear()
    threads = [threading.Thread(target=up, args=(i,)) for i in range(6)]
    [x.start() for x in threads]
    [x.join() for x in threads]
    docs = client.get("/api/docs/list", params={"session_id": sid}, headers=h).json()["docs"]
    assert not errors, errors
    assert len(docs) == 6 and len({d["doc_id"] for d in docs}) == 6                      # none lost to a read-modify-write race
