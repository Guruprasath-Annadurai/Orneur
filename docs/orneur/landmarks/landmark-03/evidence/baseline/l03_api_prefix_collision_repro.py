"""L03 baseline -- API-level reproduction of the vector-collection naming defect (session id truncated to 8 characters). Real chromadb, real FastAPI app, two synthetic accounts.
Asserts the SECURE property; expected to FAIL on the baseline. Copy into tests/ to run:  pytest tests/l03_api_prefix_collision_repro.py -p no:cacheprovider -v"""
from __future__ import annotations

import pytest

pytest.importorskip("chromadb", reason="this reproduction needs the real chromadb; it must not pass on the keyword fallback")
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401

SECRET = "L03-VICTIM-PRIVATE-QUARTERLY-FORECAST-48151"


def test_another_customers_remembered_text_is_not_recallable_through_a_session_id_with_the_same_first_8_characters(client):
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    victim_sid, attacker_sid = "deadbeef-1111-victim", "deadbeef-2222-attacker"          # both pass ^[A-Za-z0-9_-]{1,64}$
    assert client.post("/api/remember", json={"session_id": victim_sid, "fact": SECRET}, headers=_hdr(ta)).status_code == 200
    r = client.post("/api/memory/recall", json={"session_id": attacker_sid, "query": "quarterly forecast"}, headers=_hdr(tb))
    assert r.status_code == 200
    assert SECRET not in r.text, "customer B read customer A's private memory"


def test_a_customer_deleting_their_own_session_does_not_destroy_another_customers_memory(client):
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    victim_sid, attacker_sid = "cafebabe-1111-victim", "cafebabe-2222-attacker"
    client.post("/api/remember", json={"session_id": victim_sid, "fact": SECRET}, headers=_hdr(ta))
    client.post("/api/remember", json={"session_id": attacker_sid, "fact": "mine"}, headers=_hdr(tb))
    assert client.delete(f"/api/session/{attacker_sid}", headers=_hdr(tb)).status_code in (200, 202)
    r = client.post("/api/memory/recall", json={"session_id": victim_sid, "query": "quarterly forecast"}, headers=_hdr(ta))
    assert SECRET in r.text, "customer B's deletion destroyed customer A's long-term memory"
