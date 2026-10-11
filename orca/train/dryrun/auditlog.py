"""Append-only, hash-chained, size- and time-rotated LOCAL audit log with tail-truncation detection.

Closes (locally, as far as local files can) the gap recorded in docs/orneur/authorization/TRAINING_AUTHORIZATION_ASSURANCE.md section 4.2:
a hash chain alone cannot see its tail being cut off. Here every append also updates one or more ANCHORS (seq + head hash, optionally
HMAC-signed with a key supplied by the caller at run time). verify() fails if the chain is shorter than an anchor says it should be.

What this does NOT do (stated, not hidden; see docs/orneur/status/trainprep/AUDIT_LOG_RETENTION_ARCHITECTURE.md):
  * An operator who can rewrite the log AND every anchor AND holds the HMAC key can forge a consistent history. The defence is to put one
    anchor where that operator has no write access (remote append-only/WORM store, a notary, an owner-held offline countersignature).
    `extra_anchor_paths` is the hook for that; no remote sink is implemented or exercised here.
  * No key is created, stored or read by this module: `anchor_key` is a caller-supplied value (tests use ephemeral random bytes).
  * Pruning old segments is not implemented: deleting the oldest segment is reported as tampering. Archival is by sealing + moving the
    whole directory (design).
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
from pathlib import Path
from typing import Callable

from orca.train.dryrun.canon import ZERO_HASH
from orca.train.dryrun.chainlog import ChainError, VerifyResult, check_anchor, encode_record, make_record, verify_lines, write_anchor

_SEG = re.compile(r"^audit-(\d{6})\.jsonl$")


class RotatingAuditLog:
    def __init__(self, directory, *, max_bytes: int = 1 << 20, max_age_s: float = 86400.0, clock: Callable[[], float] = time.time,
                 anchor_key: bytes | None = None, extra_anchor_paths=()):
        if max_bytes < 256 or max_age_s <= 0:
            raise ValueError("rotation limits too small")
        self.dir = Path(directory)
        self.max_bytes, self.max_age_s, self.clock, self.key = max_bytes, max_age_s, clock, anchor_key
        self.anchor_paths = [self.dir / "audit.head", *[Path(p) for p in extra_anchor_paths]]

    # ── layout ──
    def segments(self) -> list:
        if not self.dir.is_dir():
            return []
        return sorted(p for p in self.dir.iterdir() if _SEG.match(p.name))

    @staticmethod
    def _index(p: Path) -> int:
        return int(_SEG.match(p.name).group(1))

    # ── append ──
    def append(self, event: dict) -> dict:
        if not isinstance(event, dict):
            raise TypeError("event must be a dict")
        self.dir.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(str(self.dir / "audit.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            now = self.clock()
            # Full verification on EVERY append (O(total log size); the log is small by design): a tampered or truncated log, in ANY segment or
            # against ANY anchor, is never extended.
            res = self.verify(require_anchor=True)
            if not res.ok:
                raise ChainError("refusing to append: " + ",".join(res.problems))
            segs = self.segments()
            seq, prev, active, first_ts = res.last_seq + 1, res.last_hash, None, None
            if segs:
                active = segs[-1]
                first_ts = json.loads(active.read_bytes().splitlines()[0])["body"].get("ts", now)
            body = {**event, "ts": int(now)}
            rec = make_record(seq, prev, body)
            line = encode_record(rec)
            rotate = active is None or (active.stat().st_size + len(line) > self.max_bytes) or (now - first_ts >= self.max_age_s)
            if rotate:
                nxt = (self._index(active) + 1) if active is not None else 1
                active = self.dir / f"audit-{nxt:06d}.jsonl"
            fd = os.open(str(active), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, line)
                os.fsync(fd)
            finally:
                os.close(fd)
            for ap in self.anchor_paths:
                write_anchor(ap, rec["seq"], rec["hash"], self.key)
            return rec
        finally:
            os.close(lock_fd)

    # ── verify ──
    def verify(self, *, require_anchor: bool = True) -> VerifyResult:
        total = VerifyResult(ok=True)
        segs = self.segments()
        if segs:
            idx = [self._index(p) for p in segs]
            if idx != list(range(1, len(segs) + 1)):
                total.ok = False
                total.problems.append("SEGMENT_MISSING_OR_RENUMBERED")
                return total
        seq, prev = 1, ZERO_HASH
        for p in segs:
            res = verify_lines(p.read_bytes(), start_seq=seq, start_prev=prev)
            total.records.extend(res.records)
            total.count += res.count
            if not res.ok:
                total.ok = False
                total.problems.extend(f"{p.name}:{x}" for x in res.problems)
                return total
            if res.count == 0:
                total.ok = False
                total.problems.append(f"{p.name}:EMPTY_SEGMENT")
                return total
            seq, prev = res.last_seq + 1, res.last_hash
        total.last_seq, total.last_hash = seq - 1, prev
        for ap in self.anchor_paths:
            problems = check_anchor(total, ap, key=self.key, require=require_anchor)
            if problems:
                total.ok = False
                total.problems.extend(f"{ap.name}:{x}" for x in problems)
        return total


# ─── anchoring the gate's own events.jsonl (orca.train.authorization) WITHOUT modifying it ──────────────────────────────────────

def _gate_lines(state_dir) -> list:
    p = Path(state_dir) / "events.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def anchor_gate_events(state_dir, anchor_path, key: bytes | None = None) -> dict:
    """Record the current head of the gate's audit chain (count + last hash) in an anchor. Refuses to anchor a chain that does not verify.
    Intended to be run by a party/place other than the training operator (cron on another host, the owner's machine)."""
    from orca.train.authorization import verify_event_chain
    if not verify_event_chain(Path(state_dir)):
        raise ChainError("gate audit chain does not verify; refusing to anchor it")
    events = _gate_lines(state_dir)
    seq, head = len(events), (events[-1]["hash"] if events else ZERO_HASH)
    write_anchor(Path(anchor_path), seq, head, key)
    return {"seq": seq, "hash": head}


def verify_gate_events_against_anchor(state_dir, anchor_path, key: bytes | None = None) -> list:
    """Problem codes (empty == consistent). Detects the tail truncation that verify_event_chain() cannot (strict xfail in
    tests/test_training_authorization_assurance.py)."""
    from orca.train.authorization import verify_event_chain
    if not verify_event_chain(Path(state_dir)):
        return ["GATE_CHAIN_BROKEN"]
    events = _gate_lines(state_dir)
    res = VerifyResult(ok=True, count=len(events), last_seq=len(events), last_hash=(events[-1]["hash"] if events else ZERO_HASH),
                       records=[{"seq": i + 1, "hash": e["hash"]} for i, e in enumerate(events)])
    return check_anchor(res, Path(anchor_path), key=key, require=True)

