"""MASTER-04 integration qualification — vector owner × B6 backup lock, consistency, lifecycle, races.

Engineering evidence only. Not independent certification. Formal acceptance remains 0/95.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from orca import vectorstore as V
from orca.brain import memory as M
from orca.serve import backup, datadir_lock, deletions
from orca.serve.backup_errors import RestoreFailed
from tests.test_l02_b6_backup import key, world  # noqa: F401


REPO = Path(__file__).resolve().parents[2]
EVIDENCE = Path(os.environ.get("MASTER04_EVIDENCE_DIR", "/tmp/master04-evidence"))
EVIDENCE.mkdir(parents=True, exist_ok=True)
RES: dict = {}


@pytest.fixture
def vworld(world, monkeypatch):
    home = world.home
    monkeypatch.setattr(M, "MEMORY_DIR", home / "memory")
    monkeypatch.setattr(V, "_home", lambda: home)
    monkeypatch.setenv("ORNEUR_VECTOR_MODE", "service")
    monkeypatch.setenv("ORNEUR_VECTOR_DEADLINE_S", "5")
    V.reset_for_tests()
    t = V.transport()
    t.owner_env = {"ORNEUR_VECTOR_IDLE_EXIT_S": "300"}
    yield world
    try:
        t.kill_owner()
    except Exception:
        pass
    V.reset_for_tests()
    (EVIDENCE / "master04_integration_results.json").write_text(json.dumps(RES, indent=2, default=str))


def _ancestry_ok(sha: str, head: str) -> bool:
    return subprocess.call(["git", "merge-base", "--is-ancestor", sha, head], cwd=str(REPO)) == 0


# ── A / ancestry ─────────────────────────────────────────────────────────────────────────────────

def test_A_merge_ancestry_fail_closed_and_complete():
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO), text=True).strip()
    required = {
        "master03_tip": "b96cc3260078b6f677a22381b05fe1f72026256f",
        "l03_code": "c8b0f54bafe364c18e507425570d34be1e7b8dd7",
        "l03_doc_head": "bfeaae2bc7470251262b3526e32fede7412996d8",
        "main": "20a8546f5a1ece7e5af655c0f30ca7e305f71b1a",
    }
    missing = []
    for name, sha in required.items():
        # Missing object must fail closed (not skip).
        probe = subprocess.run(["git", "cat-file", "-e", sha], cwd=str(REPO), capture_output=True)
        if probe.returncode != 0:
            missing.append(name)
            continue
        assert _ancestry_ok(sha, head), f"{name} ({sha}) is not an ancestor of {head}"
    assert not missing, f"required ancestry objects missing (fail-closed): {missing}"
    parents = subprocess.check_output(["git", "rev-list", "--parents", "-n", "1", head], cwd=str(REPO), text=True).strip().split()
    RES["A_ancestry"] = {"head": head, "parents": parents[1:], "required": required, "missing": missing}
    # At least one merge commit in history should link M03 + L03; tip may be a follow-up commit.
    assert _ancestry_ok(required["master03_tip"], head) and _ancestry_ok(required["l03_code"], head)


# ── B locking ────────────────────────────────────────────────────────────────────────────────────

def test_B_restore_refuses_while_owner_holds_serving_lock(vworld, key, tmp_path):
    w = vworld
    M.LongTermMemory(str(uuid.uuid4())).store("lock-me", strict=True)
    owner = V.transport().owner_pid()
    assert owner is not None
    out = tmp_path / "bk.orbk"
    backup.create(w.home, out, key=key, quiesce_vector=True)
    # Re-start owner after quiesced backup
    M.LongTermMemory(str(uuid.uuid4())).store("again", strict=True)
    assert V.transport().owner_pid() is not None
    refused = None
    try:
        backup.restore(out, w.home, key=key, overwrite=True)
    except RestoreFailed as exc:
        refused = str(exc)
    RES["B_restore_while_owner"] = {"refused": refused, "owner_pid": V.transport().owner_pid()}
    assert refused and "server is running" in refused
    V.transport().stop_owner()
    ok = backup.restore(out, w.home, key=key, overwrite=True)
    assert ok["verified"]


def test_B_owner_refuses_to_start_under_exclusive_restore_lock(vworld, monkeypatch):
    """Fail-closed: exclusive data-dir holder blocks owner; supervisor must not treat that as ready."""
    w = vworld
    V.reset_for_tests()
    monkeypatch.setattr(V, "_home", lambda: w.home)
    monkeypatch.setenv("ORNEUR_VECTOR_MODE", "service")
    with datadir_lock.exclusive_data_dir(w.home):
        t = V.transport()
        t.owner_env = {"ORNEUR_VECTOR_IDLE_EXIT_S": "300"}
        with pytest.raises(Exception) as ei:
            # Any vector op that would spawn an owner must fail closed.
            t.ensure_owner(budget_s=3.0)
        RES["B_owner_under_restore"] = {"error": type(ei.value).__name__, "msg": str(ei.value), "pid": t.owner_pid()}
        assert t.owner_pid() is None
        assert "lock" in str(ei.value).lower() or "refused" in str(ei.value).lower() or "did not start" in str(ei.value).lower()


# ── C backup consistency ─────────────────────────────────────────────────────────────────────────

def test_C_active_owner_never_yields_consistent_true_from_readable_sample(vworld, key, tmp_path):
    w = vworld
    M.LongTermMemory(str(uuid.uuid4())).store("seed-consistency", strict=True)
    assert V.transport().owner_pid() is not None
    out = tmp_path / "live.orbk"
    made = backup.create(w.home, out, key=key, quiesce_vector=False)
    RES["C_active_owner_backup"] = made
    assert made["vector"]["present"] is True
    assert made["consistent"] is False
    assert made["vector"].get("barrier") in (None, "owner_lock_exclusive")
    # With owner holding owner.lock, barrier must be None and consistent false.
    assert made["vector"]["barrier"] is None
    assert any("owner_active" in u for u in made["unstable_files"])


def test_C_quiesced_owner_allows_consistent_vector_backup(vworld, key, tmp_path):
    w = vworld
    M.LongTermMemory(str(uuid.uuid4())).store("quiesce-seed", strict=True)
    out = tmp_path / "quiet.orbk"
    made = backup.create(w.home, out, key=key, quiesce_vector=True)
    RES["C_quiesced_backup"] = made
    assert made["vector"]["quiesced"] is True
    # Option A (quiesce) is sufficient; Option B barrier is preferred when the owner.lock is free after stop.
    assert made["vector"]["quiesced"] or made["vector"]["barrier"] == "owner_lock_exclusive"
    assert made["consistent"] is True


# ── D deletion / non-resurrection ────────────────────────────────────────────────────────────────

def test_D_restore_after_stop_applies_tombstones_and_sweep_removes_bytes(vworld, key, tmp_path):
    w = vworld
    sid_keep, sid_gone = str(uuid.uuid4()), str(uuid.uuid4())
    M.LongTermMemory(sid_keep).store("keep this", strict=True)
    M.LongTermMemory(sid_gone).store("L03X-ERASE-ME-AFTER-BACKUP", strict=True)
    out = tmp_path / "bk.orbk"
    backup.create(w.home, out, key=key, quiesce_vector=True)
    # Owner may be stopped by quiesce; store again to ensure post-backup deletion path
    M.LongTermMemory(sid_keep).store("keep-2", strict=True)
    deletions.begin(sid_gone, "u1")
    deletions.run(sid_gone, "u1")
    V.transport().stop_owner()
    r = backup.restore(out, w.home, key=key, overwrite=True)
    V.reset_for_tests()
    reach = M.LongTermMemory(sid_gone).recall("ERASE")
    names_before = V.Store(w.home / "memory" / "vectors").list_collections()
    swept = deletions.resume_pending()
    names_after = V.Store(w.home / "memory" / "vectors").list_collections()
    raw = b"".join(p.read_bytes() for p in (w.home / "memory" / "vectors").rglob("*") if p.is_file())
    info = {
        "history_sources": r["deletion_history_sources"],
        "tombstone_applied": r["deletions_applied"],
        "recall_of_deleted_after_restore": reach,
        "collection_present_right_after_restore": f"orca_{sid_gone[:8]}" in names_before,
        "swept": swept,
        "collection_present_after_sweep": f"orca_{sid_gone[:8]}" in names_after,
        "deleted_text_on_disk_after_sweep": b"ERASE-ME-AFTER-BACKUP" in raw,
        "kept_conversation_recall_hits": len(M.LongTermMemory(sid_keep).recall("keep")),
        "states": {
            "access_revoked_via_tombstone": bool(r["deletions_applied"].get("session")),
            "logical_delete_applied": True,
            "collection_removed_after_sweep": f"orca_{sid_gone[:8]}" not in names_after,
            "reclamation_observed": swept >= 1,
            "physical_erasure_of_medium_unproven": True,
        },
    }
    RES["D_lifecycle"] = info
    assert reach == []
    assert f"orca_{sid_gone[:8]}" not in names_after
    assert b"ERASE-ME-AFTER-BACKUP" not in raw


# ── E multi-process adversarial races ────────────────────────────────────────────────────────────

def _race_restore_worker(home_s: str, archive_s: str, key: bytes, q):
    from orca.serve import backup as b
    from orca.serve.backup_errors import RestoreFailed as RF
    try:
        b.restore(Path(archive_s), Path(home_s), key=key, overwrite=True)
        q.put(("ok", None))
    except RF as e:
        q.put(("RestoreFailed", str(e)))
    except Exception as e:
        q.put((type(e).__name__, str(e)))


def test_E_multiprocess_restore_vs_owner_lock_race(vworld, key, tmp_path):
    w = vworld
    M.LongTermMemory(str(uuid.uuid4())).store("race-seed", strict=True)
    out = tmp_path / "race.orbk"
    backup.create(w.home, out, key=key, quiesce_vector=True)
    M.LongTermMemory(str(uuid.uuid4())).store("owner-back", strict=True)
    assert V.transport().owner_pid() is not None
    q: mp.Queue = mp.Queue()
    procs = [mp.Process(target=_race_restore_worker, args=(str(w.home), str(out), key, q)) for _ in range(4)]
    for p in procs:
        p.start()
    results = [q.get(timeout=30) for _ in procs]
    for p in procs:
        p.join(20)
    RES["E_restore_race"] = {"results": results, "owner_alive": V.transport().owner_pid() is not None}
    # While owner holds the shared serving lock, every restore must fail closed — never partial success.
    assert all(r[0] == "RestoreFailed" for r in results)
    assert V.transport().owner_pid() is not None


# ── F packaging / governance probes (lightweight) ───────────────────────────────────────────────

def test_F_dockerfile_does_not_silently_enable_chroma_or_backup_crypto():
    text = (REPO / "Dockerfile").read_text()
    assert '".[postgres]"' in text or "'.[postgres]'" in text
    assert "memory" not in text.split("pip install", 1)[-1].split("\n", 1)[0]
    assert "backup" not in text.split("uv pip install", 1)[-1].split("\n", 1)[0]
    assert "chromadb" not in text
    RES["F_packaging"] = {"dockerfile_install": [ln.strip() for ln in text.splitlines() if "pip install" in ln]}


def test_F_proposed_catch_and_continue_patch_is_not_in_owner():
    src = (REPO / "orca/vectorstore/server.py").read_text()
    assert "except Exception:\n        lock = None" not in src
    assert "serving_lock(home)" in src
    assert "return 2" in src
    RES["F_fail_closed_patch"] = True
