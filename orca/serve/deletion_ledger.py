"""L02-B6: an append-only record of what customers have deleted, kept OUTSIDE the backed-up data, so a restore of an older backup can re-apply later deletions.

WHAT THIS IS AND IS NOT (read before relying on it)
* It is an ordinary file in the data directory. Anyone who can write that directory can edit it. It is NOT tamper-proof and NOT independently authoritative.
* It is hash-chained (each line commits to the previous one, behind a random per-ledger genesis id). That detects accidental damage and naive edits - a removed, reordered or
  edited middle line, an unchained forged line, a file truncated to nothing - and lets a restore compare it with copies recorded elsewhere (the backup manifest records the
  ledger id, length and head hash at backup time; an authenticated export records the same). A consistent rewrite of the whole chain by someone with write access, or entries
  removed after the last copy made elsewhere, are NOT detectable locally. Completeness therefore can never be verified from the file alone; closing that needs an off-host
  append-only anchor (founder-controlled custody decision - see docs/orneur/landmarks/landmark-02/b6-backup-privacy, status BLOCKED).
* It holds identifiers only (kind, id, owner, time), never content or email addresses.

Written by the live deletion paths (conversation tombstone, document removal, account deletion) BEFORE the destructive work. Excluded from backups; preserved by a restore.
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from pathlib import Path

from orca.serve.backup_crypto import BackupAuthError, BackupError, derive

_logger = logging.getLogger("orneur.deletion_ledger")

LEDGER_NAME = "deletion_ledger.jsonl"
KINDS = ("session", "doc", "user")
ZERO = "0" * 64


class LedgerIntegrityError(BackupError):
    """The ledger file does not form a valid chain (removed/edited/reordered/forged/empty): it cannot be trusted as deletion history."""


def _default_home() -> Path:
    from orca import config

    return Path(config.ORCA_HOME)


def path(home: Path | None = None) -> Path:
    return Path(home or _default_home()) / LEDGER_NAME


def _canon(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()


def _link(prev: str, body: dict) -> dict:
    line = {**body, "prev": prev}
    line["h"] = hashlib.sha256(prev.encode() + _canon({k: v for k, v in body.items()})).hexdigest()
    return line


def parse(text: str) -> list[dict]:
    """Parse and verify a ledger. Returns every line (genesis first). A torn final line (no newline: a crash mid-append that never returned success) is ignored; anything else
    that does not chain raises ``LedgerIntegrityError``."""
    raw = text.split("\n")
    torn_ok = not text.endswith("\n")
    lines: list[dict] = []
    prev = ZERO
    for i, s in enumerate(raw):
        if not s.strip():
            continue
        try:
            d = json.loads(s)
            if not isinstance(d, dict):
                raise ValueError
        except ValueError:
            if torn_ok and i == len(raw) - 1:
                continue
            raise LedgerIntegrityError("deletion ledger is corrupt (unparseable line)") from None
        body = {k: v for k, v in d.items() if k not in ("prev", "h")}
        if d.get("prev") != prev or d.get("h") != _link(prev, body)["h"]:
            raise LedgerIntegrityError("deletion ledger chain is broken (a line was edited, removed, reordered or forged)")
        if not lines:
            if body.get("kind") != "genesis" or not body.get("ledger_id"):
                raise LedgerIntegrityError("deletion ledger has no genesis record")
        elif body.get("kind") not in KINDS or not body.get("id"):
            raise LedgerIntegrityError("deletion ledger contains an invalid entry")
        lines.append(d)
        prev = d["h"]
    if not lines:
        raise LedgerIntegrityError("deletion ledger is empty (no genesis record): it was truncated or never initialised")
    return lines


def read_lines(home: Path | None = None) -> list[dict]:
    p = path(home)
    if not p.exists():
        return []
    return parse(p.read_text())


def read(home: Path | None = None) -> list[dict]:
    """Deletion entries (genesis excluded). Missing file -> []. Invalid file -> ``LedgerIntegrityError``."""
    return [d for d in read_lines(home) if d.get("kind") in KINDS]


def chain_info(home: Path | None = None) -> dict | None:
    """{ledger_id, count (lines incl. genesis), head} or None when there is no ledger. Raises LedgerIntegrityError for an invalid one."""
    lines = read_lines(home)
    if not lines:
        return None
    return {"ledger_id": lines[0]["ledger_id"], "count": len(lines), "head": lines[-1]["h"]}


def _append_locked(fd: int, p: Path, body: dict) -> None:
    size = os.fstat(fd).st_size
    if size == 0:
        g = _link(ZERO, {"kind": "genesis", "ledger_id": uuid.uuid4().hex, "at": time.time()})
        os.write(fd, (json.dumps(g, sort_keys=True, separators=(",", ":")) + "\n").encode())
    text = p.read_text()
    if text and not text.endswith("\n"):                             # drop a torn tail from a crashed append
        keep = text[: text.rfind("\n") + 1]
        os.ftruncate(fd, len(keep.encode()))
        os.lseek(fd, 0, os.SEEK_END)
    try:
        lines = parse(p.read_text())
    except LedgerIntegrityError:
        # The ledger is damaged. Deletions must stay possible (a customer cannot be refused), so set the damaged file aside for the operator and start a NEW lineage. A restore will
        # then refuse to treat the new file as a continuation of anything an older backup recorded.
        aside = p.with_name(p.name + f".damaged-{int(time.time())}")
        os.replace(p, aside)
        _logger.error("deletion ledger failed its integrity check; moved to %s and a new ledger started", aside.name)
        os.close(fd)
        raise _Restart()
    prev = lines[-1]["h"]
    line = _link(prev, body)
    os.write(fd, (json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n").encode())
    os.fsync(fd)


class _Restart(Exception):
    pass


def ensure(home: Path | None = None) -> Path:
    """Create the ledger (with its genesis record) if it does not exist. An existing file is left alone, valid or not."""
    p = path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(p), os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if os.fstat(fd).st_size == 0:
            g = _link(ZERO, {"kind": "genesis", "ledger_id": uuid.uuid4().hex, "at": time.time()})
            os.write(fd, (json.dumps(g, sort_keys=True, separators=(",", ":")) + "\n").encode())
            os.fsync(fd)
    finally:
        os.close(fd)
    return p


def record(kind: str, subject_id: str, user_id: str = "", session_id: str = "", home: Path | None = None) -> None:
    """Durably append one deletion. Raises OSError if it cannot be made durable (the caller must then refuse the deletion)."""
    if kind not in KINDS or not subject_id:
        raise ValueError("invalid ledger entry")
    p = path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = {"at": time.time(), "kind": kind, "id": subject_id, "user_id": user_id, "session_id": session_id}
    for _ in range(2):
        fd = os.open(str(p), os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            _append_locked(fd, p, body)
            return
        except _Restart:
            continue
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
    raise OSError("deletion ledger could not be written")


def session_tombstones(home: Path) -> list[dict]:
    """Conversation deletions recorded in a data directory's transcript database (covers deletions made before the ledger existed or missing from it)."""
    import sqlite3

    db = Path(home) / "memory" / "conversations" / "turns.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    try:
        return [{"at": float(r[2]), "kind": "session", "id": r[0], "user_id": r[1], "session_id": r[0]}
                for r in conn.execute("SELECT session_id, user_id, created_at FROM session_deletions")]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _dedupe(entries: list[dict]) -> list[dict]:
    seen, out = set(), []
    for e in entries:
        k = (e["kind"], e["id"], e.get("session_id", "") if e["kind"] == "doc" else "")
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


def merged(home: Path) -> list[dict]:
    """The ledger's entries plus the live conversation tombstones, de-duplicated."""
    return _dedupe(read(home) + session_tombstones(home))


def _mac(key: bytes, body: dict) -> str:
    return hmac.new(derive(key, b"", b"orneur-ledger-v2"), _canon(body), hashlib.sha256).hexdigest()


def export(home: Path, out_file: Path, key: bytes) -> dict:
    """Write an HMAC-authenticated copy of the ledger chain (identifiers only) to ``out_file``. Keep it OUTSIDE the backups it protects and, ideally, off this host: it is the
    only record that can reveal a truncated or rewritten live ledger."""
    lines = read_lines(home)
    if not lines:
        ensure(home)
        lines = read_lines(home)
    body = {"v": 2, "generated_at": time.time(), "ledger_id": lines[0]["ledger_id"], "lines": lines, "tombstones": session_tombstones(Path(home))}
    fd = os.open(str(out_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({**body, "mac": _mac(key, body)}, f)
        f.flush()
        os.fsync(f.fileno())
    return {"entries": len(lines) - 1 + len(body["tombstones"]), "generated_at": body["generated_at"], "ledger_id": body["ledger_id"], "count": len(lines), "head": lines[-1]["h"]}


def load_export(file: Path, key: bytes) -> dict:
    """Parse and authenticate an export. Raises ``BackupAuthError`` for a wrong key / modified / malformed file."""
    try:
        doc = json.loads(Path(file).read_text())
        mac = doc.pop("mac")
        body = {"v": doc["v"], "generated_at": float(doc["generated_at"]), "ledger_id": doc["ledger_id"], "lines": list(doc["lines"]), "tombstones": list(doc["tombstones"])}
    except Exception:
        raise BackupAuthError("deletion-history export is unreadable") from None
    if body["v"] != 2 or not hmac.compare_digest(_mac(key, body), str(mac)):
        raise BackupAuthError("deletion-history export failed authentication (wrong key or modified)")
    text = "".join(json.dumps(l, sort_keys=True, separators=(",", ":")) + "\n" for l in body["lines"])
    lines = parse(text)
    if lines[0]["ledger_id"] != body["ledger_id"]:
        raise BackupAuthError("deletion-history export is inconsistent")
    tomb = [e for e in body["tombstones"] if isinstance(e, dict) and e.get("kind") == "session" and e.get("id")]
    body["lines"] = lines
    body["entries"] = _dedupe([d for d in lines if d.get("kind") in KINDS] + tomb)
    body["count"], body["head"] = len(lines), lines[-1]["h"]
    return body
