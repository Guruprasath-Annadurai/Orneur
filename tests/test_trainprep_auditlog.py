"""Workstream G #14: the secure audit-log writer -- append-only, hash-chained, size/time rotated, and able to detect the tail truncation that the
gate's own verify_event_chain() cannot (documented strict xfail in tests/test_training_authorization_assurance.py). Keys here are ephemeral
random bytes generated in-test; none is stored. Remote/WORM anchoring is DESIGN only (see AUDIT_LOG_RETENTION_ARCHITECTURE.md)."""
from __future__ import annotations

import json
import os
import threading

import pytest

import orca.train.authorization as A
from orca.train.dryrun.auditlog import RotatingAuditLog, anchor_gate_events, verify_gate_events_against_anchor
from orca.train.dryrun.canon import canonical_bytes
from orca.train.dryrun.chainlog import ChainError, write_anchor
from tests.test_training_authorization_assurance import world  # noqa: F401  (fixture re-export)


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def _log(tmp_path, **kw):
    kw.setdefault("max_bytes", 600)
    return RotatingAuditLog(tmp_path / "audit", **kw)


def _fill(log, n):
    return [log.append({"event": "E", "i": i}) for i in range(n)]


def test_append_chain_and_verify(tmp_path):
    log = _log(tmp_path, max_bytes=1 << 20)
    recs = _fill(log, 5)
    res = log.verify()
    assert res.ok and res.count == 5 and res.last_seq == 5 and recs[1]["prev"] == recs[0]["hash"] and recs[0]["body"]["event"] == "E"


def test_size_rotation_continues_one_global_chain_across_segments(tmp_path):
    log = _log(tmp_path)
    _fill(log, 12)
    segs = log.segments()
    assert len(segs) >= 3 and all(p.stat().st_size <= 600 + 200 for p in segs)
    res = log.verify()
    assert res.ok and res.count == 12 and [r["seq"] for r in res.records] == list(range(1, 13))
    first_of_second = json.loads(segs[1].read_bytes().splitlines()[0])
    last_of_first = json.loads(segs[0].read_bytes().splitlines()[-1])
    assert first_of_second["prev"] == last_of_first["hash"]                          # the chain crosses the rotation boundary


def test_time_rotation(tmp_path):
    clk = Clock()
    log = _log(tmp_path, max_bytes=1 << 20, max_age_s=3600, clock=clk)
    log.append({"e": 1})
    clk.t += 1800
    log.append({"e": 2})
    assert len(log.segments()) == 1
    clk.t += 1900                                                                     # now > 3600s since the segment's first record
    log.append({"e": 3})
    assert len(log.segments()) == 2 and log.verify().ok


def test_reopen_continues_the_chain(tmp_path):
    _fill(_log(tmp_path), 7)
    again = _log(tmp_path)
    again.append({"event": "after-restart"})
    assert again.verify().ok and again.verify().count == 8


@pytest.mark.parametrize("tamper", ["edit", "delete_record", "delete_middle_segment", "delete_first_segment", "renumber_segment", "garbage", "partial"])
def test_in_chain_tamper_is_detected_and_blocks_appends(tmp_path, tamper):
    log = _log(tmp_path)
    _fill(log, 12)
    segs = log.segments()
    if tamper == "edit":
        segs[0].write_bytes(segs[0].read_bytes().replace(b'"i":1', b'"i":9', 1))
    elif tamper == "delete_record":
        ls = segs[1].read_bytes().splitlines(True)
        segs[1].write_bytes(b"".join(ls[1:]))
    elif tamper == "delete_middle_segment":
        segs[1].unlink()
    elif tamper == "delete_first_segment":
        segs[0].unlink()
    elif tamper == "renumber_segment":
        segs[1].rename(segs[1].with_name("audit-000009.jsonl"))
    elif tamper == "garbage":
        with open(segs[-1], "ab") as f:
            f.write(b"not json\n")
    elif tamper == "partial":
        with open(segs[-1], "ab") as f:
            f.write(b'{"seq":')
    res = log.verify()
    assert not res.ok and res.problems
    with pytest.raises(ChainError):
        log.append({"event": "should-not-append"})                                   # a tampered log is never extended


def test_tail_truncation_is_detected_by_the_anchor(tmp_path):
    """The case a bare hash chain cannot see."""
    log = _log(tmp_path, max_bytes=1 << 20)
    _fill(log, 6)
    seg = log.segments()[0]
    lines = seg.read_bytes().splitlines(True)
    seg.write_bytes(b"".join(lines[:3]))                                              # cut the last 3 records at a record boundary
    from orca.train.dryrun.chainlog import verify_lines
    assert verify_lines(seg.read_bytes()).ok                                         # the chain alone is perfectly happy ...
    res = log.verify()
    assert not res.ok and any("TRUNCATION_DETECTED" in p for p in res.problems)      # ... the anchor is not
    with pytest.raises(ChainError):
        log.append({"event": "append-after-truncation"})


def test_whole_last_segment_deletion_is_detected_by_the_anchor(tmp_path):
    log = _log(tmp_path)
    _fill(log, 12)
    log.segments()[-1].unlink()
    assert any("TRUNCATION_DETECTED" in p for p in log.verify().problems)


def test_deleting_the_primary_anchor_is_reported(tmp_path):
    log = _log(tmp_path)
    _fill(log, 4)
    (tmp_path / "audit" / "audit.head").unlink()
    assert any("ANCHOR_MISSING" in p for p in log.verify().problems)
    assert log.verify(require_anchor=False).ok                                       # opt-out is explicit, never the default


def test_truncation_with_a_forged_primary_anchor_is_caught_by_a_second_anchor_elsewhere(tmp_path):
    """Defense in depth: one anchor lives somewhere the log's operator cannot rewrite (here a second path stands in for it)."""
    ext = tmp_path / "other-host" / "audit.head"
    ext.parent.mkdir()
    log = _log(tmp_path, max_bytes=1 << 20, extra_anchor_paths=[ext])
    _fill(log, 6)
    seg = log.segments()[0]
    lines = seg.read_bytes().splitlines(True)
    seg.write_bytes(b"".join(lines[:2]))
    last = json.loads(lines[1])
    write_anchor(tmp_path / "audit" / "audit.head", last["seq"], last["hash"])        # attacker makes the local anchor match the truncated log
    res = log.verify()
    assert not res.ok and any(p.startswith("audit.head:") or "TRUNCATION_DETECTED" in p for p in res.problems)
    assert any("TRUNCATION_DETECTED" in p for p in res.problems)


def test_signed_anchor_needs_the_key_to_forge(tmp_path):
    key = os.urandom(32)                                                              # ephemeral, test-only
    log = _log(tmp_path, max_bytes=1 << 20, anchor_key=key)
    _fill(log, 5)
    seg = log.segments()[0]
    lines = seg.read_bytes().splitlines(True)
    seg.write_bytes(b"".join(lines[:2]))
    last = json.loads(lines[1])
    write_anchor(tmp_path / "audit" / "audit.head", last["seq"], last["hash"], key=None)       # forged without the key
    assert any("ANCHOR_SIGNATURE_INVALID" in p for p in log.verify().problems)
    verifier_without_key = RotatingAuditLog(tmp_path / "audit", max_bytes=600, anchor_key=os.urandom(32))
    assert not verifier_without_key.verify().ok


def test_concurrent_writers_keep_one_intact_chain(tmp_path):
    log = _log(tmp_path)
    ts = [threading.Thread(target=lambda n=n: [log.append({"w": n, "i": i}) for i in range(8)]) for n in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    res = log.verify()
    assert res.ok and res.count == 32


def test_rotation_limits_are_validated(tmp_path):
    with pytest.raises(ValueError):
        RotatingAuditLog(tmp_path, max_bytes=10)
    with pytest.raises(ValueError):
        RotatingAuditLog(tmp_path, max_age_s=0)


def test_event_must_be_a_dict_and_must_be_canonical_json(tmp_path):
    log = _log(tmp_path)
    with pytest.raises(TypeError):
        log.append("not a dict")
    with pytest.raises(ValueError):
        log.append({"x": float("nan")})                                              # NaN has no canonical form
    assert canonical_bytes({"a": 1}) == b'{"a":1}'


# ── closing the documented gap in the gate's own events.jsonl, without touching authorization.py ───────────────────────────────

def test_gate_tail_truncation_is_detected_via_an_external_anchor(world):  # noqa: F811
    world.authorize()                                                                 # TRAINING_AUTHORIZED
    A._append_event(world.state, {"event": "LATER"})
    anchor = world.tmp / "gate.head"
    pinned = anchor_gate_events(world.state, anchor)
    assert pinned["seq"] == 2 and verify_gate_events_against_anchor(world.state, anchor) == []
    p = world.state / "events.jsonl"
    p.write_text("\n".join(p.read_text().splitlines()[:1]) + "\n")                    # the exact attack in the strict xfail test
    assert A.verify_event_chain(world.state) is True                                  # the gate alone still cannot see it (that xfail stands) ...
    assert verify_gate_events_against_anchor(world.state, anchor) == ["TRUNCATION_DETECTED"]      # ... the anchor can


def test_gate_anchor_accepts_legitimate_growth_and_flags_a_rewritten_prefix(world):  # noqa: F811
    world.authorize()
    anchor = world.tmp / "gate.head"
    anchor_gate_events(world.state, anchor)
    A._append_event(world.state, {"event": "MORE"})
    assert verify_gate_events_against_anchor(world.state, anchor) == []              # chain grew past the anchor: fine
    p = world.state / "events.jsonl"
    p.write_text(p.read_text().replace('"TRAINING_AUTHORIZED"', '"TRAINING_AUTHORIZEX"', 1))
    assert verify_gate_events_against_anchor(world.state, anchor) == ["GATE_CHAIN_BROKEN"]


def test_gate_anchor_refuses_to_pin_a_broken_chain(world):  # noqa: F811
    world.authorize()
    p = world.state / "events.jsonl"
    p.write_text(p.read_text().replace('"TRAINING_AUTHORIZED"', '"TRAINING_AUTHORIZEX"', 1))
    with pytest.raises(ChainError):
        anchor_gate_events(world.state, world.tmp / "gate.head")
