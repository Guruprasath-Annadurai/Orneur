"""Append-only, hash-chained JSONL with a head anchor: the primitive under the run ledger and the rotating audit log.

Record: {"seq": n, "prev": <hash of record n-1 | 64 zeros>, "body": {...}, "hash": sha256(canonical record without hash)}.
Each line must be the EXACT canonical encoding of its record, so re-spaced / re-ordered / extra-field edits are tampering too.

Detection matrix (tests/test_trainprep_ledger.py, tests/test_trainprep_auditlog.py):
  edited record, deleted middle record, reordered records, inserted record, malformed line, blank line, partial (cut mid-record) final line
        -> detected by the chain alone.
  truncation of the TAIL at a record boundary -> a hash chain CANNOT see this by itself; it is detected by the head anchor
        (`<log>.head` = {seq, hash, mac?}) written after every append, and (stronger) by an anchor held somewhere the log writer's
        operator cannot rewrite (design doc: AUDIT_LOG_RETENTION_ARCHITECTURE.md). A missing anchor on a non-empty log is itself reported
        when require_anchor=True.
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from orca.train.dryrun.canon import ZERO_HASH, atomic_write_bytes, canonical_bytes, hash_obj

_RECORD_KEYS = {"seq", "prev", "body", "hash"}
ANCHOR_SCHEMA = "orneur-dryrun-log-anchor/1"


class ChainError(RuntimeError):
    """The chain on disk is not intact; appending would extend a tampered log, so the writer refuses."""


def make_record(seq: int, prev: str, body: dict) -> dict:
    rec = {"seq": seq, "prev": prev, "body": body}
    rec["hash"] = hash_obj(rec)
    return rec


def encode_record(rec: dict) -> bytes:
    return canonical_bytes(rec) + b"\n"


@dataclass
class VerifyResult:
    ok: bool
    count: int = 0
    last_seq: int = 0
    last_hash: str = ZERO_HASH
    problems: list = field(default_factory=list)
    records: list = field(default_factory=list)


def verify_lines(data: bytes, *, start_seq: int = 1, start_prev: str = ZERO_HASH) -> VerifyResult:
    res = VerifyResult(ok=True, last_seq=start_seq - 1, last_hash=start_prev)
    if not data:
        return res
    if not data.endswith(b"\n"):
        res.problems.append("PARTIAL_FINAL_RECORD")
        res.ok = False
        data = data[: data.rfind(b"\n") + 1]
    expect_seq, prev = start_seq, start_prev
    for n, line in enumerate(data.split(b"\n")[:-1], 1):
        try:
            rec = json.loads(line)
        except ValueError:
            res.problems.append(f"MALFORMED_LINE_{n}")
            res.ok = False
            return res
        if not isinstance(rec, dict) or set(rec) != _RECORD_KEYS or not isinstance(rec["body"], dict):
            res.problems.append(f"SCHEMA_LINE_{n}")
            res.ok = False
            return res
        try:
            exact = encode_record(rec) == line + b"\n"
            recomputed = hash_obj({k: rec[k] for k in ("seq", "prev", "body")})
        except (TypeError, ValueError):
            res.problems.append(f"SCHEMA_LINE_{n}")
            res.ok = False
            return res
        if not exact:
            res.problems.append(f"NON_CANONICAL_LINE_{n}")
            res.ok = False
            return res
        if rec["seq"] != expect_seq:
            res.problems.append(f"SEQ_GAP_AT_{n}")
            res.ok = False
            return res
        if rec["prev"] != prev:
            res.problems.append(f"BROKEN_LINK_AT_{n}")
            res.ok = False
            return res
        if rec["hash"] != recomputed:
            res.problems.append(f"BAD_HASH_AT_{n}")
            res.ok = False
            return res
        prev, expect_seq = rec["hash"], expect_seq + 1
        res.records.append(rec)
        res.count += 1
    res.last_seq, res.last_hash = expect_seq - 1, prev
    return res


def anchor_mac(key: bytes, seq: int, head: str) -> str:
    return hmac.new(key, canonical_bytes({"schema": ANCHOR_SCHEMA, "seq": seq, "hash": head}), hashlib.sha256).hexdigest()


def write_anchor(path: Path, seq: int, head: str, key: bytes | None = None) -> None:
    doc = {"schema": ANCHOR_SCHEMA, "seq": seq, "hash": head}
    if key is not None:
        doc["mac"] = anchor_mac(key, seq, head)
    atomic_write_bytes(path, canonical_bytes(doc) + b"\n")


def read_anchor(path: Path):
    try:
        doc = json.loads(Path(path).read_bytes())
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("schema") != ANCHOR_SCHEMA or not isinstance(doc.get("seq"), int) or not isinstance(doc.get("hash"), str):
        return None
    return doc


def check_anchor(res: VerifyResult, anchor_path: Path, *, key: bytes | None = None, require: bool = False) -> list:
    """Problems found comparing a verified chain against its anchor (empty list == consistent)."""
    anchor = read_anchor(anchor_path)
    if anchor is None:
        if Path(anchor_path).exists():
            return ["ANCHOR_UNREADABLE"]
        return ["ANCHOR_MISSING"] if (require and res.count) else []
    if key is not None:
        mac = anchor.get("mac")
        if not isinstance(mac, str) or not hmac.compare_digest(mac, anchor_mac(key, anchor["seq"], anchor["hash"])):
            return ["ANCHOR_SIGNATURE_INVALID"]
    if anchor["seq"] > res.last_seq:
        return ["TRUNCATION_DETECTED"]
    if anchor["seq"] == res.last_seq and anchor["hash"] != res.last_hash:
        return ["HEAD_MISMATCH"]
    if anchor["seq"] < res.last_seq:
        # The anchor is behind the log: either a crash between append and anchor update, or a forged old anchor. If the anchor's record is
        # in the chain with that exact hash, the log extends it legitimately.
        known = {r["seq"]: r["hash"] for r in res.records}
        if known.get(anchor["seq"]) != anchor["hash"] and anchor["seq"] != 0:
            return ["ANCHOR_NOT_ON_CHAIN"]
    return []


class HashChainFile:
    """One append-only chained file. Appends are serialized with flock, fsynced, and refuse to extend a log whose tail is not intact."""

    def __init__(self, path, *, anchor: bool = True, anchor_key: bytes | None = None):
        self.path = Path(path)
        self.anchor_path = self.path.with_name(self.path.name + ".head") if anchor else None
        self.anchor_key = anchor_key

    def _read(self) -> bytes:
        try:
            return self.path.read_bytes()
        except FileNotFoundError:
            return b""

    def append(self, body: dict) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            res = verify_lines(self._read())
            if not res.ok:
                raise ChainError("refusing to append: existing chain is not intact: " + ",".join(res.problems))
            if self.anchor_path is not None:
                problems = check_anchor(res, self.anchor_path, key=self.anchor_key, require=True)
                if problems:
                    raise ChainError("refusing to append: " + ",".join(problems))
            rec = make_record(res.last_seq + 1, res.last_hash, body)
            os.write(fd, encode_record(rec))
            os.fsync(fd)
            if self.anchor_path is not None:
                write_anchor(self.anchor_path, rec["seq"], rec["hash"], self.anchor_key)
            return rec
        finally:
            os.close(fd)

    def verify(self, *, require_anchor: bool = False) -> VerifyResult:
        res = verify_lines(self._read())
        if res.ok and self.anchor_path is not None:
            problems = check_anchor(res, self.anchor_path, key=self.anchor_key, require=require_anchor)
            if problems:
                res.ok = False
                res.problems.extend(problems)
        return res

    def head(self) -> tuple:
        res = verify_lines(self._read())
        return res.last_seq, res.last_hash
