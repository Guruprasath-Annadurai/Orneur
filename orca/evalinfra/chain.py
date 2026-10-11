"""Append-only, content-addressed, tamper-evident hash-chain log (JSON Lines). Shared by the result manifest, the replay guard and the budget ledger.

Entry = {seq, prev_hash, kind, content_id, payload, entry_hash}; content_id = sha256(canonical payload) (content addressing);
entry_hash = sha256(canonical entry without entry_hash), chained through prev_hash. Every stored line must be EXACTLY the canonical serialization
(no extra whitespace, no reordered keys, trailing newline present), so an editor that re-saves the file breaks verification.

What this detects: edits, reordering, deletion of a non-final entry, insertion, a truncated final line, duplicate sequence numbers.
What it cannot detect on its own: truncation of the newest whole entries (rollback). Publish `head()` somewhere independent and pass it as
`expected_head` to `entries()` to detect that.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

from orca.evalinfra.canon import GENESIS_HASH, canonical, is_hex64, obj_hash
from orca.evalinfra.errors import ChainCorrupt

ENTRY_KEYS = frozenset({"seq", "prev_hash", "kind", "content_id", "payload", "entry_hash"})


def _body(e: dict) -> dict:
    return {k: v for k, v in e.items() if k != "entry_hash"}


class ChainLog:
    def __init__(self, path, *, allowed_kinds: tuple | None = None):
        self.path = Path(path)
        self._kinds = allowed_kinds

    # -- reading -------------------------------------------------------------------------------------------------------------------
    def entries(self, expected_head: dict | None = None) -> list:
        if not self.path.exists():
            if expected_head is not None and expected_head.get("seq", -1) != -1:
                raise ChainCorrupt("HEAD_MISMATCH", "log is missing but a non-empty head was anchored")
            return []
        raw = self.path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            raise ChainCorrupt("TRUNCATED_LINE", "final line is not newline-terminated")
        out, prev = [], GENESIS_HASH
        for i, line in enumerate(raw.decode("utf-8").split("\n")[:-1] if raw else []):
            try:
                e = json.loads(line)
            except ValueError:
                raise ChainCorrupt("UNPARSEABLE_LINE", f"line {i}") from None
            if not isinstance(e, dict) or set(e) != ENTRY_KEYS:
                raise ChainCorrupt("ENTRY_SCHEMA", f"line {i}")
            if canonical(e) != line:
                raise ChainCorrupt("NON_CANONICAL_LINE", f"line {i}")
            if e["seq"] != i:
                raise ChainCorrupt("SEQUENCE_GAP", f"expected {i}, got {e['seq']}")
            if e["prev_hash"] != prev:
                raise ChainCorrupt("BROKEN_CHAIN", f"line {i}")
            if not is_hex64(e["entry_hash"]) or obj_hash(_body(e)) != e["entry_hash"]:
                raise ChainCorrupt("ENTRY_HASH_MISMATCH", f"line {i}")
            if obj_hash(e["payload"]) != e["content_id"]:
                raise ChainCorrupt("CONTENT_ID_MISMATCH", f"line {i}")
            if self._kinds is not None and e["kind"] not in self._kinds:
                raise ChainCorrupt("UNKNOWN_KIND", f"line {i}: {e['kind']!r}")
            prev = e["entry_hash"]
            out.append(e)
        if expected_head is not None:
            got = {"seq": len(out) - 1, "entry_hash": prev}
            if got != {"seq": expected_head.get("seq"), "entry_hash": expected_head.get("entry_hash")}:
                raise ChainCorrupt("HEAD_MISMATCH", "log head differs from the externally anchored head (rollback or fork)")
        return out

    def head(self) -> dict:
        es = self.entries()
        return {"seq": len(es) - 1, "entry_hash": es[-1]["entry_hash"] if es else GENESIS_HASH}

    # -- appending -----------------------------------------------------------------------------------------------------------------
    def append(self, kind: str, payload) -> dict:
        if self._kinds is not None and kind not in self._kinds:
            raise ChainCorrupt("UNKNOWN_KIND", kind)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            es = self.entries()                           # re-verify the WHOLE chain under the lock before extending it
            prev = es[-1]["entry_hash"] if es else GENESIS_HASH
            e = {"seq": len(es), "prev_hash": prev, "kind": kind, "content_id": obj_hash(payload), "payload": payload}
            e["entry_hash"] = obj_hash(e)
            os.write(fd, (canonical(e) + "\n").encode("utf-8"))
            os.fsync(fd)
            return e
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
