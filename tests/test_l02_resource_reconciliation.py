"""L02-05 -- safe, idempotent reconciliation of leftover resources, on SYNTHETIC deployments and chunks in an isolated home (no real resource is ever touched).

Time is injected (``now=``) so grace and quarantine periods are exercised without waiting.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

import pytest

from orca.gateway import reconcile
from orca.gateway import deployment as _deployment_mod
from orca.gateway.deployment import ModelDeployment, list_deployments, scan_deployment_dir

T0 = 1_000_000.0


def _dd():
    """The deployment directory AT CALL TIME: the suite's autouse fixture redirects the module attribute to a per-test temp dir; a name bound at import would point at the real home."""
    d = _deployment_mod.DEPLOYMENT_DIR
    assert ".orca" not in str(d) or "pytest" in str(d) or "tmp" in str(d), f"deployment dir is not isolated: {d}"
    return d


@pytest.fixture(autouse=True)
def _times(monkeypatch):
    monkeypatch.setattr(reconcile, "OBSERVE_GRACE_S", 100.0)
    monkeypatch.setattr(reconcile, "QUARANTINE_S", 1000.0)


def _dep(did, *, runtime="ollama", lifecycle="EXPERIMENTAL", health="READY"):
    d = ModelDeployment(deployment_id=did, model_id="orneur-novus", model_version="m", artifact_id="m", runtime=runtime, runtime_endpoint="http://localhost:11434",
                        hardware_profile="local", lifecycle=lifecycle, health=health, warmup_completed=True)
    d.save()
    return d


def _ids():
    return {d.deployment_id for d in list_deployments()}


def _states():
    return {(r["kind"], r["state"]): r["n"] for r in reconcile.diagnostics()["ledger"]}


# ── atomicity and tolerance (defects found on the baseline) ─────────────────────────────────────────────────────────────────

def test_one_damaged_record_no_longer_breaks_the_listing_for_everyone_else(isolated_home):
    _dep("ollama-good-aaaaaaaaaaaaaaaa")
    (_dd() / "ollama-bad-bbbbbbbbbbbbbbbb.json").write_text('{"deployment_id": "ollama-bad", "model_id": ')       # a half-written file
    (_dd() / "ollama-shape-cccccccccccccccc.json").write_text(json.dumps({"unexpected": True}))                   # a record of an unknown shape
    assert _ids() == {"ollama-good-aaaaaaaaaaaaaaaa"}, "baseline: list_deployments raised on the first damaged file"
    valid, bad = scan_deployment_dir()
    assert len(valid) == 1 and {p.name for p in bad} == {"ollama-bad-bbbbbbbbbbbbbbbb.json", "ollama-shape-cccccccccccccccc.json"}


def test_save_is_atomic_a_crash_mid_write_leaves_the_previous_record_intact(isolated_home, monkeypatch):
    d = _dep("ollama-atomic-dddddddddddddddd")
    before = (_dd() / "ollama-atomic-dddddddddddddddd.json").read_text()
    d.health = "OFFLINE"
    with monkeypatch.context() as m:                                  # (monkeypatch.undo() would also undo the suite's storage isolation)
        m.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("simulated crash before rename")))
        with pytest.raises(OSError):
            d.save()
    assert (_dd() / "ollama-atomic-dddddddddddddddd.json").read_text() == before
    assert ModelDeployment.load("ollama-atomic-dddddddddddddddd").health == "READY"


# ── lifecycle: observe -> quarantine -> remove, never earlier ───────────────────────────────────────────────────────────────────

def test_an_orphan_is_observed_then_quarantined_then_removed_and_never_earlier(isolated_home):
    _dep("ollama-orphan-eeeeeeeeeeeeeeee")
    reconcile.sweep(now=T0)
    assert _ids() == {"ollama-orphan-eeeeeeeeeeeeeeee"} and _states() == {("deployment_record", "observed"): 1}
    reconcile.sweep(now=T0 + 10)                                    # a second pass moments later is not an independent confirmation
    assert _ids() == {"ollama-orphan-eeeeeeeeeeeeeeee"}
    reconcile.sweep(now=T0 + 60)                                    # confirmed, but the grace period (100 s) has not elapsed
    assert _ids() == {"ollama-orphan-eeeeeeeeeeeeeeee"}
    reconcile.sweep(now=T0 + 120)
    assert _ids() == set(), "quarantined records are out of routing"
    assert (_dd() / ".quarantine" / "ollama-orphan-eeeeeeeeeeeeeeee.json").exists(), "quarantine keeps the record"
    assert _states() == {("deployment_record", "quarantined"): 1}
    reconcile.sweep(now=T0 + 500)                                   # idempotent while quarantined
    assert (_dd() / ".quarantine" / "ollama-orphan-eeeeeeeeeeeeeeee.json").exists()
    reconcile.sweep(now=T0 + 120 + 1001)
    assert not (_dd() / ".quarantine" / "ollama-orphan-eeeeeeeeeeeeeeee.json").exists() and _states() == {("deployment_record", "removed"): 1}
    actions = [(a["action"], a["outcome"]) for a in reversed(reconcile.diagnostics()["recent_actions"])]
    assert actions == [("quarantine", "ok"), ("remove", "ok")]


def test_protected_and_non_reclaimable_resources_are_never_touched(isolated_home):
    _dep("ollama-prod-ffffffffffffffff", lifecycle="PRODUCTION")
    _dep("ollama-legacy-1111111111111111", lifecycle="LEGACY_PRODUCTION_SERVING")
    _dep("ollama-cand-2222222222222222", lifecycle="CANDIDATE")
    _dep("anthropic-x-3333333333333333", runtime="anthropic")
    for t in (0, 60, 120, 5000, 20000):
        reconcile.sweep(now=T0 + t)
    assert _ids() == {"ollama-prod-ffffffffffffffff", "ollama-legacy-1111111111111111", "ollama-cand-2222222222222222", "anthropic-x-3333333333333333"}
    assert _states() == {} and not (_dd() / ".quarantine").exists()


def test_a_record_a_live_worker_announces_is_never_an_orphan_and_a_quarantined_one_is_restored(isolated_home):
    _dep("ollama-live-4444444444444444")
    _dep("ollama-gone-5555555555555555")
    reconcile.announce_live(["ollama-live-4444444444444444"])
    import time as _t

    # live announcements are compared against the injected clock: refresh the file's timestamp to T0 so it is "recent" at T0..T0+500
    f = next(reconcile._live_dir().glob("*.json"))
    f.write_text(json.dumps({"at": T0, "ids": ["ollama-live-4444444444444444"]}))
    for t in (0, 60, 120):
        reconcile.sweep(now=T0 + t)
    assert _ids() == {"ollama-live-4444444444444444"}, "only the unannounced record was quarantined"
    f.write_text(json.dumps({"at": T0 + 200, "ids": ["ollama-live-4444444444444444", "ollama-gone-5555555555555555"]}))      # a worker starts serving it again
    reconcile.sweep(now=T0 + 210)
    assert _ids() == {"ollama-live-4444444444444444", "ollama-gone-5555555555555555"}, "a quarantined record that is announced live again is restored"
    assert [a["action"] for a in reconcile.diagnostics()["recent_actions"]][0] == "restore"


def test_wiring_announces_what_this_worker_serves(isolated_home, monkeypatch):
    from orca.gateway import wiring
    from types import SimpleNamespace

    wiring.reset_for_tests()
    # a synthetic resolution: the test must not depend on a backend (Ollama) being reachable on the machine that runs it
    res = SimpleNamespace(tier="core", backend="ollama", model="llama3.2:1b", data_left_infrastructure=False)
    wiring.brain_for_tier_resolution(res)
    assert wiring.stable_deployment_id("ollama", res.model, "orneur-novus") in reconcile.live_ids() or any(i.startswith("ollama-") for i in reconcile.live_ids())


# ── bounded, failure-tolerant, concurrent ────────────────────────────────────────────────────────────────────────────────────────

def test_each_sweep_acts_on_a_bounded_number_of_resources(isolated_home, monkeypatch):
    monkeypatch.setattr(reconcile, "MAX_ACTIONS_PER_SWEEP", 3)
    for i in range(10):
        _dep(f"ollama-many-{i:016d}")
    for t in (0, 60):
        reconcile.sweep(now=T0 + t)
    reconcile.sweep(now=T0 + 120)
    assert len(_ids()) == 7, "exactly 3 quarantined in one pass"
    reconcile.sweep(now=T0 + 130)
    assert len(_ids()) == 4


def test_a_failing_action_is_retried_a_bounded_number_of_times_then_blocked_and_reported_without_stopping_the_rest(isolated_home, monkeypatch):
    _dep("ollama-stuck-6666666666666666")
    _dep("ollama-fine-7777777777777777")
    real = os.replace

    def flaky(src, dst, *a, **k):
        if "stuck" in str(src):
            raise PermissionError("simulated: file is locked")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", flaky)
    for t in (0, 60, 120, 200, 300, 400, 500, 600, 700):
        reconcile.sweep(now=T0 + t)
    diag = reconcile.diagnostics()
    assert [b["resource_id"] for b in diag["blocked"]] == ["ollama-stuck-6666666666666666"] and diag["blocked"][0]["attempts"] >= reconcile.MAX_ATTEMPTS
    assert "ollama-fine-7777777777777777" not in _ids() and "ollama-stuck-6666666666666666" in _ids(), "the healthy orphan was handled; the stuck one is untouched and visible"


def test_a_sweep_that_cannot_get_the_lease_does_nothing(isolated_home):
    _dep("ollama-lease-8888888888888888")
    conn = reconcile._db()
    with conn:
        conn.execute("INSERT INTO reconcile_lease (kind, holder, until) VALUES ('deployment_record', 'another-worker', ?)", (T0 + 99999,))
    conn.close()
    for t in (0, 60, 120):
        rep = reconcile.sweep(now=T0 + t, holder="me")
    assert rep["deployment_record"] == {"skipped": "another worker holds the lease"} and _ids() == {"ollama-lease-8888888888888888"}


def test_two_workers_sweeping_concurrently_perform_each_action_once(isolated_home):
    for i in range(6):
        _dep(f"ollama-race-{i:016d}")
    reconcile.sweep(now=T0)
    reconcile.sweep(now=T0 + 60)
    out = []
    ts = [threading.Thread(target=lambda h=h: out.append(reconcile.sweep(now=T0 + 120, holder=h))) for h in ("w1", "w2", "w3", "w4")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert _ids() == set()
    quarantine_actions = [a for a in reconcile.diagnostics()["recent_actions"] if a["action"] == "quarantine"]
    assert len(quarantine_actions) == 6, "each record was quarantined exactly once however many workers raced"


def test_a_crash_between_ledger_and_file_move_is_resumed_not_repeated(isolated_home):
    _dep("ollama-crash-9999999999999999")
    reconcile.sweep(now=T0)
    reconcile.sweep(now=T0 + 60)
    conn = reconcile._db()
    with conn:                                                                    # the process died after the ledger CAS but before the rename
        conn.execute("UPDATE resource_ledger SET state='quarantined', quarantined_at=? WHERE resource_id='ollama-crash-9999999999999999'", (T0 + 100,))
    conn.close()
    assert _ids() == {"ollama-crash-9999999999999999"}
    reconcile.sweep(now=T0 + 100 + 1001)                                          # removal is idempotent whether or not the file is where we left it
    assert _states() == {("deployment_record", "removed"): 1}


def test_a_damaged_record_is_isolated_not_deleted(isolated_home):
    (_dd() / "ollama-bad-aaaaaaaaaaaaaaaa.json").write_text("{not json")
    reconcile.sweep(now=T0)
    assert not (_dd() / "ollama-bad-aaaaaaaaaaaaaaaa.json").exists()
    assert (_dd() / ".quarantine" / "ollama-bad-aaaaaaaaaaaaaaaa.json.corrupt").read_text() == "{not json"


# ── document chunks and temp files ──────────────────────────────────────────────────────────────────────────────────────────────

class _C:
    def __init__(self, text, doc_id):
        self.text, self.chunk_idx, self.doc_id, self.filename, self.char_start, self.char_end = text, 0, doc_id, "f.txt", 0, len(text)

    def to_metadata(self):
        return {"doc_id": self.doc_id, "filename": "f.txt", "chunk_idx": 0, "char_start": 0, "char_end": self.char_end}


def test_orphan_chunks_are_removed_after_two_confirmations_and_registered_or_in_flight_documents_are_not(isolated_home):
    from orca.docs.store import DocStore, register_doc

    sid = str(uuid.uuid4())
    st = DocStore(sid)
    st.add_chunks([_C("registered document text alpha", "keep")], "keep", "f.txt")
    register_doc(sid, "keep", "f.txt", 1, 10)
    st.add_chunks([_C("orphaned document text beta", "orph")], "orph", "f.txt")           # no registry entry: a failed delete / crashed upload
    st.add_chunks([_C("in flight document text gamma", "late")], "late", "f.txt")          # being uploaded right now
    st._fallback_file.write_text(json.dumps({"doc_id": "orph-kw", "filename": "f.txt", "chunk_idx": 0, "text": "orphan keyword line"}) + "\n"
                                 + json.dumps({"doc_id": "keep", "filename": "f.txt", "chunk_idx": 0, "text": "registered keyword line"}) + "\n")
    reconcile.sweep(now=T0)
    reconcile.sweep(now=T0 + 60)
    register_doc(sid, "late", "f.txt", 1, 10)                                              # the upload finished between sweeps
    reconcile.sweep(now=T0 + 130)
    raw = DocStore(sid, enforce_registry=False)
    texts = " | ".join(h["text"] for h in raw._retrieve_raw("document text keyword line alpha beta gamma orphan registered", 20))
    assert "registered document text alpha" in texts and "in flight document text gamma" in texts
    assert "orphaned document text beta" not in texts and "orphan keyword line" not in texts
    assert "registered keyword line" in st._fallback_file.read_text()


def test_leftover_temp_files_are_removed_after_confirmation(isolated_home):
    f = _dd() / ".ollama-x-0000000000000000.json.4242.tmp"
    f.write_text("{")
    for t in (0, 60, 130):
        reconcile.sweep(now=T0 + t)
    assert not f.exists()


def test_reconciliation_never_touches_conversations_documents_or_accounts(isolated_home):
    """Tenant safety: the reconciler has no code path to sessions, transcripts, users or registered documents. A full cycle leaves all of them byte-identical."""
    from orca.docs.store import DocStore, list_docs, register_doc
    from orca.serve import conversations

    sid, uid = str(uuid.uuid4()), "tenant-1"
    fence = uuid.uuid4().hex
    a = conversations.acquire_authority(sid, uid, fence)
    conversations.commit_turn(sid, "private question", "private answer", user_id=uid, turn_id=uuid.uuid4().hex, fence_token=fence, epoch=a.epoch)
    st = DocStore(sid)
    st.add_chunks([_C("tenant document", "d1")], "d1", "f.txt")
    register_doc(sid, "d1", "f.txt", 1, 10)
    _dep("ollama-o-aaaaaaaaaaaaaaaa")
    before = (conversations.turns_for_session(sid), list_docs(sid))
    for t in (0, 60, 130, 5000, 20000):
        reconcile.sweep(now=T0 + t)
    assert (conversations.turns_for_session(sid), list_docs(sid)) == before
    assert DocStore(sid, enforce_registry=True).retrieve("tenant document")


def test_admin_diagnostics_endpoint_is_permissioned(isolated_home):
    from fastapi.testclient import TestClient
    from orca.serve import ratelimit
    from orca.serve.api import app

    c = TestClient(app)
    ratelimit._local_counters.clear()
    assert c.get("/api/admin/reconcile").status_code in (401, 403)
    r = c.post("/api/auth/signup", json={"email": f"u-{uuid.uuid4().hex[:8]}@example.com", "password": "correcthorsebatterystaple", "name": "T"})
    tok = r.json()["token"]
    assert c.get("/api/admin/reconcile", headers={"Authorization": f"Bearer {tok}"}).status_code in (401, 403), "an ordinary user must not see operator diagnostics"
