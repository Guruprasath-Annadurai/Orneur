"""L02-B6: an append-only record of what customers have deleted, kept OUTSIDE the backed-up data.

Why it exists: an older backup contains data that a customer deleted later. A deletion record stored only inside that same backup cannot say so, and the tombstones in the
live databases are overwritten by a restore. The ledger is the authority a restore consults. It holds identifiers only (kind, id, owner, time) - never content.

* Written by the live deletion paths (conversation tombstone, document removal, account deletion) BEFORE the destructive work, and it fails closed: if the entry cannot be
  made durable the deletion is refused and can be retried.
* Excluded from backups (``backup`` skips it) and preserved by a restore.
* Exported, authenticated with the operator's backup key, so a disaster-recovery restore onto a new machine can bring the history with it.

It records that data WAS deleted. It does not erase copies the application does not control (older backups, snapshots); see docs/orneur/landmarks/landmark-02/b6-backup-privacy.
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from orca.serve.backup_crypto import BackupAuthError, derive

LEDGER_NAME = "deletion_ledger.jsonl"
KINDS = ("session", "doc", "user")


def _default_home() -> Path:
    from orca import config

    return Path(config.ORCA_HOME)


def path(home: Path | None = None) -> Path:
    return Path(home or _default_home()) / LEDGER_NAME


def ensure(home: Path | None = None) -> Path:
    """Create the (empty) ledger if absent. An existing ledger file is what marks a data directory as having authoritative deletion history."""
    p = path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT, 0o600)
    os.close(fd)
    return p


def record(kind: str, subject_id: str, user_id: str = "", session_id: str = "", home: Path | None = None) -> None:
    """Durably append one deletion. Raises OSError if it cannot be made durable (the caller must then refuse the deletion)."""
    if kind not in KINDS or not subject_id:
        raise ValueError("invalid ledger entry")
    p = ensure(home)
    line = json.dumps({"at": time.time(), "kind": kind, "id": subject_id, "user_id": user_id, "session_id": session_id}, separators=(",", ":"), sort_keys=True) + "\n"
    fd = os.open(str(p), os.O_WRONLY | os.O_APPEND)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, line.encode())
        os.fsync(fd)
    finally:
        os.close(fd)


def read(home: Path | None = None) -> list[dict]:
    """All entries. A torn final line (crash mid-append) is ignored; any other unparseable line makes the ledger untrustworthy and raises."""
    p = path(home)
    if not p.exists():
        return []
    raw = p.read_text().split("\n")
    out = []
    for i, line in enumerate(raw):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except ValueError:
            if i >= len(raw) - 2 and not p.read_text().endswith("\n"):
                continue
            raise ValueError("deletion ledger is corrupt")
        if e.get("kind") in KINDS and e.get("id"):
            out.append(e)
    return out


def session_tombstones(home: Path) -> list[dict]:
    """Conversation deletions recorded in a data directory's transcript database (covers deletions made before the ledger existed)."""
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


def merged(home: Path) -> list[dict]:
    """The ledger plus the live conversation tombstones, de-duplicated by (kind, id)."""
    seen, out = set(), []
    for e in read(home) + session_tombstones(home):
        k = (e["kind"], e["id"], e.get("session_id", "") if e["kind"] == "doc" else "")
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


def _canonical(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def export(home: Path, out_file: Path, key: bytes) -> dict:
    """Write an authenticated export of the deletion history to ``out_file`` (identifiers only). Keep it OUTSIDE the backup it protects."""
    entries = merged(Path(home))
    body = {"v": 1, "generated_at": time.time(), "entries": entries}
    mac = hmac.new(derive(key, b"", b"orneur-ledger-v1"), _canonical(body), hashlib.sha256).hexdigest()
    fd = os.open(str(out_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({**body, "mac": mac}, f)
        f.flush()
        os.fsync(f.fileno())
    return {"entries": len(entries), "generated_at": body["generated_at"]}


def load_export(file: Path, key: bytes) -> dict:
    """Parse and authenticate a deletion-history export. Raises ``BackupAuthError`` for a wrong key, a modified file or anything malformed."""
    try:
        doc = json.loads(Path(file).read_text())
        mac = doc.pop("mac")
        body = {"v": doc["v"], "generated_at": float(doc["generated_at"]), "entries": list(doc["entries"])}
    except Exception:
        raise BackupAuthError("deletion-history export is unreadable") from None
    expect = hmac.new(derive(key, b"", b"orneur-ledger-v1"), _canonical(body), hashlib.sha256).hexdigest()
    if body["v"] != 1 or not hmac.compare_digest(expect, str(mac)):
        raise BackupAuthError("deletion-history export failed authentication (wrong key or modified)")
    body["entries"] = [e for e in body["entries"] if isinstance(e, dict) and e.get("kind") in KINDS and e.get("id")]
    return body
