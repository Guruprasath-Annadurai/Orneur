"""Workstream G #7: training-artifact provenance -- append-only hash-chained run ledger + immutable sealed run manifests that stay valid
orca.registry.training_run.TrainingRunManifest objects. Tamper-detection matrix."""
from __future__ import annotations

import json
import os
import stat

import pytest

import orca.registry.training_run as TR
from orca.train.dryrun.canon import ZERO_HASH, canonical_bytes
from orca.train.dryrun.chainlog import ChainError, HashChainFile, encode_record, make_record, verify_lines, write_anchor
from orca.train.dryrun.ledger import RunLedger, build_run_manifest, seal_run_manifest, verify_sealed_manifest
from orca.train.dryrun.toy import Plan
from tests.trainprep_support import BIND, ENVSHA, big_budget, run


@pytest.fixture
def finished(tmp_path):
    out = run(Plan(), tmp_path / "r", run_id="runA")
    return tmp_path / "r", out


def _lines(p):
    return p.read_bytes().split(b"\n")[:-1]


def _write(p, lines):
    p.write_bytes(b"\n".join(lines) + b"\n")


# ── the chain primitive ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_clean_ledger_verifies(finished):
    root, _ = finished
    res = RunLedger(root / "ledger.jsonl").verify()
    assert res.ok and res.count >= 10 and res.records[0]["body"]["type"] == "run_started"
    assert res.records[0]["body"]["synthetic"] is True and res.records[0]["body"]["binding"]["git_sha"] == BIND.git_sha


@pytest.mark.parametrize("mutate", [
    "edit_body", "delete_middle", "reorder", "insert_duplicate", "garbage_line", "blank_line", "reformat_whitespace", "partial_tail", "swap_hash",
])
def test_every_in_chain_tamper_is_detected(finished, mutate):
    root, _ = finished
    p = root / "ledger.jsonl"
    ls = _lines(p)
    if mutate == "edit_body":
        ls[3] = ls[3].replace(b"step_committed", b"step_commitxed")
    elif mutate == "delete_middle":
        del ls[4]
    elif mutate == "reorder":
        ls[3], ls[4] = ls[4], ls[3]
    elif mutate == "insert_duplicate":
        ls.insert(5, ls[4])
    elif mutate == "garbage_line":
        ls[2] = b"not json"
    elif mutate == "blank_line":
        ls.insert(2, b"")
    elif mutate == "reformat_whitespace":
        ls[2] = json.dumps(json.loads(ls[2]), indent=1).replace("\n", " ").encode()
    elif mutate == "swap_hash":
        rec = json.loads(ls[3])
        rec["hash"] = "f" * 64
        ls[3] = canonical_bytes(rec)
    if mutate == "partial_tail":
        p.write_bytes(b"\n".join(ls) + b"\n" + ls[0][:20])
    else:
        _write(p, ls)
    res = RunLedger(p).verify()
    assert not res.ok and res.problems
    with pytest.raises(ChainError):
        RunLedger(p).append("step_aborted", step=99, reason="x")           # a writer never extends a tampered chain


def test_tail_truncation_is_caught_by_the_head_anchor(finished):
    root, _ = finished
    p = root / "ledger.jsonl"
    _write(p, _lines(p)[:-2])
    res = RunLedger(p).verify()
    assert not res.ok and "TRUNCATION_DETECTED" in res.problems


def test_truncation_plus_anchor_deletion_is_still_reported_as_missing_anchor(finished):
    root, _ = finished
    p = root / "ledger.jsonl"
    _write(p, _lines(p)[:-2])
    (root / "ledger.jsonl.head").unlink()
    assert "ANCHOR_MISSING" in RunLedger(p).verify().problems


def test_a_consistent_rewrite_of_the_whole_chain_is_caught_by_the_anchor(finished):
    """The attacker edits one record and recomputes every later hash -- the chain is internally perfect -- but the head moved."""
    root, _ = finished
    p = root / "ledger.jsonl"
    prev, out = ZERO_HASH, []
    for i, ln in enumerate(_lines(p), 1):
        body = json.loads(ln)["body"]
        if i == 3:
            body = {**body, "state_sha256": "e" * 64}
        rec = make_record(i, prev, body)
        out.append(encode_record(rec).rstrip(b"\n"))
        prev = rec["hash"]
    _write(p, out)
    assert verify_lines(p.read_bytes()).ok                               # the bare chain cannot tell ...
    assert "HEAD_MISMATCH" in RunLedger(p).verify().problems             # ... the anchor can


def test_signed_anchor_stops_a_forged_anchor_without_the_key(tmp_path):
    key = os.urandom(32)                                                  # ephemeral, in-test only
    log = HashChainFile(tmp_path / "l.jsonl", anchor_key=key)
    for i in range(4):
        log.append({"i": i})
    p = tmp_path / "l.jsonl"
    ls = _lines(p)[:2]
    _write(p, ls)
    last = json.loads(ls[-1])
    write_anchor(tmp_path / "l.jsonl.head", last["seq"], last["hash"], key=None)       # attacker rewrites the anchor, cannot sign it
    assert "ANCHOR_SIGNATURE_INVALID" in log.verify().problems
    write_anchor(tmp_path / "l.jsonl.head", last["seq"], last["hash"], key=key)        # whoever holds the key can (documented residual)
    assert log.verify().ok


def test_concurrent_appends_keep_one_intact_chain(tmp_path):
    import threading
    log = HashChainFile(tmp_path / "c.jsonl")
    ts = [threading.Thread(target=lambda n=n: [log.append({"n": n, "i": i}) for i in range(10)]) for n in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    res = log.verify()
    assert res.ok and res.count == 40


# ── event state machine ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_ledger_state_machine_refuses_out_of_order_events(finished):
    root, _ = finished
    led = RunLedger(root / "ledger.jsonl")
    with pytest.raises(ChainError):
        led.append("step_aborted", step=1, reason="late")                 # after seal/finish nothing may be added
    with pytest.raises(ValueError):
        led.append("totally_new_event")
    with pytest.raises(ValueError):
        led.append("run_finished", step=1)                                # missing fields


def test_second_fresh_run_into_an_existing_ledger_is_refused(finished):
    root, _ = finished
    from orca.train.dryrun.harness import RunRefused
    with pytest.raises(RunRefused):
        run(Plan(), root, run_id="runA")


# ── sealed manifest <-> registry <-> ledger ─────────────────────────────────────────────────────────────────────────────────────

def test_sealed_manifest_is_a_valid_registry_manifest_and_matches_the_ledger(finished, tmp_path, monkeypatch):
    root, out = finished
    path = out.manifest_path
    assert verify_sealed_manifest(path, RunLedger(root / "ledger.jsonl")) == []
    doc = json.loads(path.read_text())
    m = TR.TrainingRunManifest(**doc)                                     # the registry's own dataclass accepts it unchanged
    assert m.git_sha == BIND.git_sha and m.compute_provider == "synthetic-dryrun" and m.checkpoint_outputs[-1] == "ckpt-000012"
    assert m.training_config["synthetic"] is True and m.failure_state is None
    monkeypatch.setattr(TR, "TRAINING_RUN_DIR", tmp_path / "registry_runs")
    (tmp_path / "registry_runs").mkdir()
    m.save()
    assert TR.TrainingRunManifest.load("runA") == m                       # and round-trips through the existing registry API
    assert stat.S_IMODE(path.stat().st_mode) == 0o444


def test_manifest_edit_is_detected(finished):
    root, out = finished
    os.chmod(out.manifest_path, 0o644)
    doc = json.loads(out.manifest_path.read_text())
    doc["failure_state"] = "totally fine"
    out.manifest_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    assert verify_sealed_manifest(out.manifest_path, RunLedger(root / "ledger.jsonl")) == ["MANIFEST_HASH_MISMATCH"]


def test_ledger_edit_breaks_the_manifest_cross_check(finished):
    root, out = finished
    p = root / "ledger.jsonl"
    ls = _lines(p)
    ls[2] = ls[2].replace(b"step_committed", b"step_commitxed")
    _write(p, ls)
    probs = verify_sealed_manifest(out.manifest_path, RunLedger(p))
    assert probs and probs[0].startswith("LEDGER_NOT_INTACT")


def test_a_sealed_manifest_cannot_be_overwritten_and_must_bind_the_current_head(finished):
    root, out = finished
    led = RunLedger(root / "ledger.jsonl")
    m = TR.TrainingRunManifest(**json.loads(out.manifest_path.read_text()))
    with pytest.raises(ChainError):
        seal_run_manifest(led, m, root / "manifests")                      # embedded head is stale (the seal event itself moved it)
    stale = build_run_manifest(run_id="runA", plan=Plan(), binding=BIND.as_dict(), ledger=led, checkpoint_names=[], failure_state=None,
                               final_state_sha256=None, env_manifest_sha256=ENVSHA, start_time="t0", end_time="t1")
    with pytest.raises((FileExistsError, ChainError)):
        seal_run_manifest(led, stale, root / "manifests", filename=out.manifest_path.name)


def test_stopped_runs_are_sealed_too_with_a_failure_state(tmp_path):
    out = run(Plan(), tmp_path / "s", run_id="runS", budget=big_budget(max_steps=3))
    doc = json.loads(out.manifest_path.read_text())
    assert doc["failure_state"] == "STOPPED:STEP_CAP" and verify_sealed_manifest(out.manifest_path, RunLedger(tmp_path / "s" / "ledger.jsonl")) == []


def test_existing_registry_manifest_behaviour_is_untouched():
    import dataclasses
    names = [f.name for f in dataclasses.fields(TR.TrainingRunManifest)]
    assert names[:3] == ["run_id", "model_id", "base_model"] and "dataset_bundle_id" in names and len(names) == 23
