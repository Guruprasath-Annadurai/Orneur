"""Workstream G #4: checkpoint integrity -- save/verify, corruption / truncation / bit-flip detection, atomic write, and refusal to load
anything unverified. Built on orca.registry.checkpoint (hash_artifact_directory, CheckpointRecord.verify_integrity, CorruptCheckpointError)."""
from __future__ import annotations

import os

import pytest

from orca.registry.checkpoint import CheckpointRecord, CorruptCheckpointError
from orca.train.dryrun import canon
from orca.train.dryrun.canon import atomic_write_bytes, canonical_bytes, hash_obj
from orca.train.dryrun.ckpt import (CheckpointUnverified, SimulatedCrash, VerifiedCheckpoint, latest_verified, list_checkpoint_names, load_state,
                                    save_checkpoint, verify_checkpoint)
from orca.train.dryrun.harness import RunRefused
from orca.train.dryrun.toy import Plan, ToyEngine, initial_state
from tests.trainprep_support import big_budget, run

PLAN = Plan()


@pytest.fixture
def saved(tmp_path):
    eng = ToyEngine(PLAN)
    st = initial_state(PLAN)
    for _ in range(3):
        st = eng.compute_step(st)
    root = tmp_path / "ck"
    h = save_checkpoint(root, st, PLAN, "run-x")
    return root, st, h


def _verify(root, name="ckpt-000003", **kw):
    return verify_checkpoint(root, name, expected_plan_sha256=PLAN.sha256, **kw)


def test_save_verify_load_roundtrip_is_exact(saved):
    root, st, h = saved
    vc = _verify(root)
    assert isinstance(vc, VerifiedCheckpoint) and vc.digest == h.digest and vc.step == 3
    assert load_state(vc, PLAN).sha256 == st.sha256


def test_verification_goes_through_the_registry_integrity_check(saved, monkeypatch):
    root, _, _ = saved
    calls = []
    orig = CheckpointRecord.verify_integrity
    monkeypatch.setattr(CheckpointRecord, "verify_integrity", lambda self, p=None: calls.append(p) or orig(self, p))
    _verify(root)
    assert len(calls) == 1


def test_checkpoints_are_immutable(saved):
    root, st, _ = saved
    with pytest.raises(FileExistsError):
        save_checkpoint(root, st, PLAN, "run-x")


# ── corruption of every kind is detected ─────────────────────────────────────────────────────────────────────────────────────────

def test_single_bit_flip_is_detected(saved):
    root, _, _ = saved
    p = root / "ckpt-000003" / "state.json"
    b = bytearray(p.read_bytes())
    b[len(b) // 2] ^= 0x01
    p.write_bytes(bytes(b))
    with pytest.raises(CorruptCheckpointError):
        _verify(root)


@pytest.mark.parametrize("keep", [0, 1, 17, "half", "minus1"])
def test_truncation_is_detected(saved, keep):
    root, _, _ = saved
    p = root / "ckpt-000003" / "state.json"
    data = p.read_bytes()
    n = {"half": len(data) // 2, "minus1": len(data) - 1}.get(keep, keep)
    p.write_bytes(data[:n])
    with pytest.raises(CorruptCheckpointError):
        _verify(root)


def test_appended_bytes_are_detected(saved):
    root, _, _ = saved
    with open(root / "ckpt-000003" / "state.json", "ab") as f:
        f.write(b" ")
    with pytest.raises(CorruptCheckpointError):
        _verify(root)


def test_extra_file_is_detected(saved):
    root, _, _ = saved
    (root / "ckpt-000003" / "weights.bin").write_bytes(b"x")
    with pytest.raises(CorruptCheckpointError):
        _verify(root)


def test_deleted_file_is_detected(saved):
    root, _, _ = saved
    (root / "ckpt-000003" / "meta.json").unlink()
    with pytest.raises(CorruptCheckpointError):
        _verify(root)


def test_symlinked_file_is_refused(saved, tmp_path):
    root, _, _ = saved
    target = tmp_path / "elsewhere.json"
    target.write_bytes((root / "ckpt-000003" / "state.json").read_bytes())
    (root / "ckpt-000003" / "state.json").unlink()
    (root / "ckpt-000003" / "state.json").symlink_to(target)
    with pytest.raises(CorruptCheckpointError):
        _verify(root)


def test_missing_sidecar_means_uncommitted_and_is_refused(saved):
    root, _, _ = saved
    (root / "ckpt-000003.manifest.json").unlink()
    with pytest.raises(CheckpointUnverified):
        _verify(root)


def test_edited_sidecar_is_refused(saved):
    root, _, h = saved
    m = root / "ckpt-000003.manifest.json"
    m.write_text(m.read_text().replace(h.digest, "0" * 64))
    with pytest.raises(CheckpointUnverified):
        _verify(root)


def test_forged_consistent_sidecar_is_caught_by_the_independent_ledger_digest(saved):
    """Attacker corrupts state.json AND rewrites the sidecar with a fully consistent new digest + self-hash. The ledger's digest still differs."""
    import json
    root, _, h = saved
    d = root / "ckpt-000003"
    (d / "state.json").write_bytes((d / "state.json").read_bytes().replace(b'"step":3', b'"step":3 ', 1))
    from orca.registry.checkpoint import hash_artifact_directory
    ident = hash_artifact_directory(d)
    man = json.loads((root / "ckpt-000003.manifest.json").read_text())
    body = {k: v for k, v in man.items() if k != "manifest_sha256"}
    body["artifact_checksum"], body["files"] = ident["manifest_digest"], ident["files"]
    (root / "ckpt-000003.manifest.json").write_bytes(canonical_bytes({**body, "manifest_sha256": hash_obj(body)}))
    assert _verify(root).digest == ident["manifest_digest"]          # locally consistent: the sidecar alone cannot catch it ...
    with pytest.raises(CheckpointUnverified):
        _verify(root, expected_digest=h.digest)                       # ... but the independently recorded digest does


def test_wrong_plan_is_refused(saved):
    root, _, _ = saved
    with pytest.raises(CheckpointUnverified):
        verify_checkpoint(root, "ckpt-000003", expected_plan_sha256=Plan(seed=5).sha256)


@pytest.mark.parametrize("bad", ["../x", "ckpt-3", "ckpt-000003/../..", "", "ckpt-00000a"])
def test_hostile_checkpoint_names_are_refused(saved, bad):
    root, _, _ = saved
    with pytest.raises(CheckpointUnverified):
        _verify(root, name=bad)


# ── refuse to load unverified ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_there_is_no_way_to_load_state_without_verification(saved):
    root, _, _ = saved
    for bad in (None, "ckpt-000003", root / "ckpt-000003", object()):
        with pytest.raises(CheckpointUnverified):
            load_state(bad, PLAN)
    with pytest.raises(CheckpointUnverified):
        VerifiedCheckpoint(name="ckpt-000003", directory=root / "ckpt-000003", digest="0" * 64, step=3, plan_sha256=PLAN.sha256)


def test_state_swapped_after_verification_is_refused_at_load(saved):
    root, _, _ = saved
    vc = _verify(root)
    p = root / "ckpt-000003" / "state.json"
    p.write_bytes(p.read_bytes().replace(b'"step":3', b'"step":3 ', 1))
    with pytest.raises(CheckpointUnverified):
        load_state(vc, PLAN)


# ── atomicity ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_crash_before_rename_leaves_nothing_loadable_and_no_litter(tmp_path):
    st = initial_state(PLAN)
    with pytest.raises(SimulatedCrash):
        save_checkpoint(tmp_path / "c", st, PLAN, "r", crash_at="files")
    assert list_checkpoint_names(tmp_path / "c") == [] and not [p for p in (tmp_path / "c").iterdir()]


def test_crash_after_rename_but_before_commit_is_never_loadable(tmp_path):
    st = initial_state(PLAN)
    with pytest.raises(SimulatedCrash):
        save_checkpoint(tmp_path / "c", st, PLAN, "r", crash_at="renamed")
    assert (tmp_path / "c" / "ckpt-000000").is_dir() and list_checkpoint_names(tmp_path / "c") == []
    with pytest.raises(CheckpointUnverified):
        verify_checkpoint(tmp_path / "c", "ckpt-000000", expected_plan_sha256=PLAN.sha256)
    assert latest_verified(tmp_path / "c", PLAN)[0] is None


def test_atomic_write_is_tmp_fsync_rename_and_a_failed_rename_leaves_the_target_intact(tmp_path, monkeypatch):
    target = tmp_path / "t.json"
    target.write_bytes(b"old")
    order = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(canon.os, "fsync", lambda fd: order.append("fsync") or real_fsync(fd))
    monkeypatch.setattr(canon.os, "replace", lambda a, b: order.append("replace") or real_replace(a, b))
    atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"new" and order.index("fsync") < order.index("replace")
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".tmp-")]

    def boom(a, b):
        raise OSError("disk full")
    monkeypatch.setattr(canon.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"newer")
    assert target.read_bytes() == b"new" and not [p for p in tmp_path.iterdir() if p.name.startswith(".tmp-")]


# ── a corrupt checkpoint on resume: roll back to the last good one, quarantine the bad, still end byte-identical ──────────────────

def test_resume_rolls_back_past_a_corrupt_checkpoint_and_quarantines_it(tmp_path):
    plan = Plan(checkpoint_every=2)
    full = run(plan, tmp_path / "full", run_id="full")
    run(plan, tmp_path / "x", run_id="x", budget=big_budget(max_steps=6))
    p = tmp_path / "x" / "checkpoints" / "ckpt-000006" / "state.json"
    b = bytearray(p.read_bytes())
    b[10] ^= 0x04
    p.write_bytes(bytes(b))
    out = run(plan, tmp_path / "x", run_id="x", resume=True)
    assert out.state.sha256 == full.state.sha256
    assert (tmp_path / "x" / "checkpoints" / "quarantine").is_dir() and list((tmp_path / "x" / "checkpoints" / "quarantine").glob("ckpt-000006.*"))
    resumed_ev = [r for r in __import__("orca.train.dryrun.ledger", fromlist=["RunLedger"]).RunLedger(tmp_path / "x" / "ledger.jsonl").records()
                  if r["body"]["type"] == "run_resumed"][-1]["body"]
    assert resumed_ev["from_step"] == 4 and resumed_ev["rejected_checkpoints"] == ["ckpt-000006"]


def test_resume_refuses_when_no_checkpoint_verifies(tmp_path):
    plan = Plan(checkpoint_every=2)
    run(plan, tmp_path / "x", run_id="x", budget=big_budget(max_steps=4))
    for p in (tmp_path / "x" / "checkpoints").glob("ckpt-*/state.json"):
        p.write_bytes(p.read_bytes()[:-3])
    with pytest.raises(RunRefused) as e:
        run(plan, tmp_path / "x", run_id="x", resume=True)
    assert "NO_VERIFIED_CHECKPOINT" in e.value.reasons


def test_resume_ignores_a_valid_looking_checkpoint_the_ledger_never_recorded(tmp_path):
    plan = Plan(checkpoint_every=2)
    run(plan, tmp_path / "x", run_id="x", budget=big_budget(max_steps=4))
    st, eng = initial_state(plan), ToyEngine(plan)
    for _ in range(5):                                                      # a plausible, internally consistent step-5 state nobody recorded
        st = eng.compute_step(st)
    save_checkpoint(tmp_path / "x" / "checkpoints", st, plan, "x")
    out = run(plan, tmp_path / "x", run_id="x", resume=True)
    assert list((tmp_path / "x" / "checkpoints" / "quarantine").glob("ckpt-000005.*"))
    assert out.state.sha256 == run(plan, tmp_path / "full", run_id="full").state.sha256
