"""L02-06 / L02-B6: encrypted, verifiable backup of the ORNEUR data directory, and a restore that cannot resurrect deleted data or leave a half-restored directory.

Format ``orneur-backup/2``: ONE file, encrypted and authenticated end to end (AES-256-GCM, see ``backup_crypto``). Inside the encrypted stream: every file (SQLite databases
via SQLite's online-backup API, so each is a consistent snapshot even while the server writes), then a manifest (hashes, sizes, creation time, consistency flags). Because the
manifest is inside the authenticated stream, an attacker who can write the archive can neither alter a file nor "fix up" the manifest.

Key custody is the operator's: the key is provisioned from a file (never generated implicitly, never stored with the backup, refused if it sits inside the data directory
or next to the archive).

Restore, in order: decrypt into a private staging directory next to the target -> verify every file against the manifest, SQLite integrity, required components ->
consult the authoritative deletion history (``deletion_ledger``: the live one in the target and/or an authenticated export) and apply every later deletion to the staged
copy, REFUSING if no deletion history is available -> health-check the staged copy -> swap it into place with a crash-safe journal (rolled back automatically if anything
fails or the process dies mid-swap). Nothing is written to the target before every check has passed.

What this does NOT do: it does not erase older backups or snapshots (a deletion applies to live data; a historical copy has its own lifecycle and stays recoverable until
its holder destroys it), it does not guarantee cross-store consistency of a backup taken while writers are active (only per-database consistency, plus a flag for files that
changed while being copied), and it does not make the vector store consistent with the databases unless the server was stopped.

Incompatible change: the earlier plaintext directory format (``MANIFEST.json`` + files) can no longer be created or restored. Take a new encrypted backup.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
from pathlib import Path

from orca.serve import deletion_ledger as ledger
from orca.serve.backup_crypto import (BackupAuthError, BackupError, BackupKeyError, DecryptedReader, EncryptedWriter, load_key,  # noqa: F401  (re-exported)
                                      write_new_key)

FORMAT = "orneur-backup/2"
_DBS_SUFFIX = (".db", ".sqlite", ".sqlite3")
_SKIP_DIRS = {"backups", "cache", "models", "training", "workspace", "vault"}
_SKIP_NAMES = {ledger.LEDGER_NAME, ".restore-journal.json"}
_CORE = ("auth.db", "memory/conversations/turns.db")
JOURNAL = ".restore-journal.json"


class BackupIncompleteError(BackupError):
    """The archive authenticated but is not a complete, consistent backup."""


class DeletionHistoryUnavailable(BackupError):
    """No authoritative record of later deletions is available, so restoring could silently bring deleted customer data back."""


class RestoreFailed(BackupError):
    """Restore stopped; the target directory is unchanged (or was rolled back)."""


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _excluded(home: Path, p: Path) -> bool:
    parts = p.relative_to(home).parts
    return (any(part in _SKIP_DIRS or part == ".quarantine" or part.startswith(".pre-restore-") or part.startswith(".restore-") for part in parts)
            or p.name in _SKIP_NAMES or p.name.endswith(("-wal", "-shm", ".lock", ".tmp", ".restoring")))


# ── create ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _put(w: EncryptedWriter, rel: str, src: Path, kind: str, files: dict, snapshot_at: float) -> None:
    size = src.stat().st_size
    meta = json.dumps({"path": rel, "size": size, "kind": kind}).encode()
    w.write(b"F" + len(meta).to_bytes(4, "big") + meta)
    h, left = hashlib.sha256(), size
    with open(src, "rb") as f:
        while left:
            block = f.read(min(left, 1 << 20))
            if not block:
                raise OSError("file shrank while being backed up")
            h.update(block)
            w.write(block)
            left -= len(block)
    files[rel] = {"sha256": h.hexdigest(), "size": size, "kind": kind, "snapshot_at": snapshot_at}


def create(home: Path, out_file: Path, *, key: bytes) -> dict:
    """Encrypt a snapshot of ``home`` into the new file ``out_file``. The archive appears under its final name only when complete and flushed."""
    home, out_file = Path(home), Path(out_file)
    if out_file.exists():
        raise FileExistsError("backup destination already exists")
    if len(key) != 32:
        raise BackupKeyError("backup key must be exactly 32 bytes")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    ledger_head = ledger.ensure(home)
    ledger_count = len(ledger.read(home))
    partial = out_file.with_name(out_file.name + ".partial")
    files: dict = {}
    unstable: list[str] = []
    started = time.time()
    scratch = Path(tempfile.mkdtemp(prefix=".orbk-", dir=str(out_file.parent)))      # transient, private; holds one database snapshot at a time
    os.chmod(scratch, 0o700)
    fd = os.open(str(partial), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as raw:
            w = EncryptedWriter(raw, key)
            dbs = sorted(p for p in home.rglob("*") if p.is_file() and p.suffix in _DBS_SUFFIX and not _excluded(home, p))
            for src in dbs:
                rel = str(src.relative_to(home))
                snap = scratch / "snap.db"
                s, d = sqlite3.connect(str(src), timeout=30), sqlite3.connect(str(snap))
                try:
                    s.backup(d)                                           # consistent snapshot, safe while the server writes
                finally:
                    d.close()
                    s.close()
                _put(w, rel, snap, "sqlite_online_backup", files, time.time())
                snap.unlink()
            dbset = set(dbs)
            for src in sorted(p for p in home.rglob("*") if p.is_file() and p not in dbset and not _excluded(home, p)):
                rel = str(src.relative_to(home))
                for _attempt in range(3):                                 # a file that changes while it is read is retried, then flagged
                    before = src.stat()
                    tmp = scratch / "copy.bin"
                    shutil.copyfile(src, tmp)
                    after = src.stat()
                    if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns):
                        break
                else:
                    unstable.append(rel)
                _put(w, rel, tmp, "file_copy", files, time.time())
                tmp.unlink()
            if not any(c in files for c in _CORE):
                raise BackupIncompleteError("nothing to back up: the data directory has neither an accounts nor a transcript database")
            manifest = {"format": FORMAT, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "created_epoch": started, "files": files,
                        "core": [c for c in _CORE if c in files], "unstable_files": unstable, "consistent": not unstable,
                        "ledger_entries_at_backup": ledger_count, "excluded_dirs": sorted(_SKIP_DIRS)}
            body = json.dumps(manifest, sort_keys=True).encode()
            w.write(b"M" + len(body).to_bytes(4, "big") + body)
            w.close()
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(partial, out_file)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {"files": len(files), "path": str(out_file), "bytes": out_file.stat().st_size, "consistent": not unstable, "unstable_files": unstable}


# ── read / verify ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _safe_rel(rel: str) -> Path:
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] == JOURNAL or p.parts[0].startswith(".pre-restore-") or p.name == ledger.LEDGER_NAME:
        raise BackupIncompleteError("archive contains an unsafe path")
    return p


def _extract(archive: Path, key: bytes, dest: Path) -> dict:
    """Decrypt ``archive`` into ``dest`` (created, private) and return the manifest. Raises BackupAuthError / BackupIncompleteError; ``dest`` is the caller's to clean up."""
    dest.mkdir(parents=True, exist_ok=False)
    os.chmod(dest, 0o700)
    try:
        raw = open(archive, "rb")
    except OSError:
        raise BackupIncompleteError("backup archive is missing or unreadable") from None
    with raw:
        r = DecryptedReader(raw, key)
        seen: dict = {}
        manifest = None
        while not r.at_end():
            tag = r.read(1)
            n = int.from_bytes(r.read(4), "big")
            blob = r.read(n)
            if len(blob) != n:
                raise BackupIncompleteError("archive is truncated")
            if tag == b"M":
                if manifest is not None or not r.at_end():
                    raise BackupIncompleteError("archive has data after its manifest")
                manifest = json.loads(blob.decode())
            elif tag == b"F":
                if manifest is not None:
                    raise BackupIncompleteError("archive has a file after its manifest")
                meta = json.loads(blob.decode())
                rel = _safe_rel(meta["path"])
                target = dest / rel
                if rel.as_posix() in seen:
                    raise BackupIncompleteError("archive lists a file twice")
                target.parent.mkdir(parents=True, exist_ok=True)
                h, left = hashlib.sha256(), int(meta["size"])
                with open(target, "wb") as out:
                    while left:
                        block = r.read(min(left, 1 << 20))
                        if not block:
                            raise BackupIncompleteError("archive is truncated")
                        h.update(block)
                        out.write(block)
                        left -= len(block)
                seen[rel.as_posix()] = {"sha256": h.hexdigest(), "size": int(meta["size"]), "kind": meta.get("kind")}
            else:
                raise BackupIncompleteError("archive is corrupt")
    if manifest is None or manifest.get("format") != FORMAT:
        raise BackupIncompleteError("archive has no valid manifest")
    listed = manifest.get("files", {})
    problems = []
    for rel in sorted(set(listed) | set(seen)):
        if rel not in seen:
            problems.append(f"listed but missing: {rel}")
        elif rel not in listed:
            problems.append(f"present but not listed: {rel}")
        elif listed[rel]["sha256"] != seen[rel]["sha256"] or int(listed[rel]["size"]) != seen[rel]["size"]:
            problems.append(f"hash mismatch: {rel}")
        elif listed[rel].get("kind") == "sqlite_online_backup":
            c = sqlite3.connect(str(dest / rel))
            try:
                if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    problems.append(f"integrity_check failed: {rel}")
            except sqlite3.Error:
                problems.append(f"not a readable database: {rel}")
            finally:
                c.close()
    for core in manifest.get("core", []):
        if core not in seen:
            problems.append(f"core component missing: {core}")
    if not manifest.get("core"):
        problems.append("backup contains no core database (accounts or transcripts)")
    if problems:
        raise BackupIncompleteError("; ".join(problems[:5]))
    return manifest


def verify(archive: Path, *, key: bytes) -> dict:
    """Authenticate and fully check an archive (decrypt, hash, integrity, completeness) in a private scratch directory that is removed afterwards. Never raises for a bad
    archive: returns ``ok: False`` with the reason. A missing or malformed KEY still raises ``BackupKeyError`` (a configuration error, not a verdict on the archive)."""
    archive = Path(archive)
    scratch = Path(tempfile.mkdtemp(prefix=".orbk-verify-", dir=str(archive.parent if archive.parent.exists() else None)))
    shutil.rmtree(scratch)
    try:
        m = _extract(archive, key, scratch)
        return {"ok": True, "problems": [], "files": len(m["files"]), "created_at": m["created_at"], "consistent": bool(m.get("consistent", False)),
                "unstable_files": m.get("unstable_files", [])}
    except BackupError as exc:
        return {"ok": False, "problems": [str(exc)], "files": 0}
    except (ValueError, KeyError, OSError, UnicodeDecodeError):
        return {"ok": False, "problems": ["archive is corrupt"], "files": 0}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ── restore ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _apply_deletions(stage: Path, entries: list[dict]) -> dict:
    """Make the staged copy honour every recorded deletion. Conversations get a tombstone (so the running application revokes access and its sweep finishes any remaining
    cascade) and their transcript rows are removed now; documents leave the registry and the keyword fallback; accounts are removed with the product's own row-deletion routine."""
    applied = {"session": 0, "doc": 0, "user": 0}
    turns = stage / "memory" / "conversations" / "turns.db"
    sessions = [e for e in entries if e["kind"] == "session"]
    if sessions and turns.exists():
        from orca.serve import conversations

        c = sqlite3.connect(str(turns))
        try:
            c.execute("PRAGMA secure_delete=ON")                          # freed pages are overwritten, not left holding the deleted text
            conversations._init_schema(c)
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            with c:
                for e in sessions:
                    c.execute("INSERT INTO session_deletions (session_id, deletion_id, user_id, state, created_at, updated_at) VALUES (?,?,?,?,?,?) "
                              "ON CONFLICT(session_id) DO NOTHING", (e["id"], str(uuid.uuid4()), e.get("user_id", ""), "revoked", time.time(), time.time()))
                    for t in tables:
                        if t == "session_deletions" or not t.replace("_", "").isalnum():
                            continue
                        if any(col[1] == "session_id" for col in c.execute(f"PRAGMA table_info({t})")):
                            c.execute(f"DELETE FROM {t} WHERE session_id=?", (e["id"],))
                    applied["session"] += 1
            c.execute("VACUUM")                                           # and the file is rewritten without free pages
        finally:
            c.close()
    reg = stage / "docs" / "registry.json"
    docs = [e for e in entries if e["kind"] == "doc"]
    if docs and reg.exists():
        data = json.loads(reg.read_text())
        for e in docs:
            sid = e.get("session_id", "")
            before = len(data.get(sid, []))
            data[sid] = [d for d in data.get(sid, []) if d.get("doc_id") != e["id"]]
            applied["doc"] += before - len(data[sid])
        reg.write_text(json.dumps(data))
        for kw in (stage / "docs").glob("kw_*.jsonl"):
            ids = {e["id"] for e in docs}
            kept = []
            for line in kw.read_text().splitlines():
                try:
                    if json.loads(line).get("doc_id") in ids:
                        continue
                except ValueError:
                    pass
                kept.append(line)
            kw.write_text("".join(x + "\n" for x in kept))
    users = [e for e in entries if e["kind"] == "user"]
    auth = stage / "auth.db"
    if users and auth.exists():
        from orca.auth.store import delete_account_rows

        c = sqlite3.connect(str(auth))
        try:
            c.execute("PRAGMA secure_delete=ON")
            c.execute("CREATE TABLE IF NOT EXISTS api_keys (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE, name TEXT NOT NULL DEFAULT '', "
                      "created_at REAL NOT NULL, last_used REAL, revoked INTEGER NOT NULL DEFAULT 0)")
            with c:
                for e in users:
                    try:
                        delete_account_rows(c, e["id"])
                    except sqlite3.OperationalError:
                        # an older backup may lack a table added later: delete from whichever of the account tables exist
                        for tbl, col in (("api_keys", "user_id"), ("usage_daily", "user_id"), ("user_settings", "user_id"), ("user_sessions", "user_id"), ("users", "id")):
                            try:
                                c.execute(f"DELETE FROM {tbl} WHERE {col}=?", (e["id"],))
                            except sqlite3.OperationalError:
                                pass
                    applied["user"] += 1
            c.execute("VACUUM")
        finally:
            c.close()
    return applied


def _health_check(root: Path, entries: list[dict]) -> list[str]:
    problems = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in _DBS_SUFFIX and not any(x in _SKIP_DIRS or x.startswith(".pre-restore-") for x in p.relative_to(root).parts):
            c = sqlite3.connect(str(p))
            try:
                if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    problems.append(f"integrity_check failed: {p.relative_to(root)}")
            except sqlite3.Error:
                problems.append(f"unreadable database: {p.relative_to(root)}")
            finally:
                c.close()
    turns = root / "memory" / "conversations" / "turns.db"
    sessions = [e["id"] for e in entries if e["kind"] == "session"]
    if turns.exists() and sessions:
        c = sqlite3.connect(str(turns))
        try:
            for sid in sessions:
                if c.execute("SELECT 1 FROM conversation_turns WHERE session_id=?", (sid,)).fetchone():
                    problems.append("a deleted conversation still has transcript rows")
                    break
                if not c.execute("SELECT 1 FROM session_deletions WHERE session_id=?", (sid,)).fetchone():
                    problems.append("a deleted conversation has no tombstone")
                    break
        except sqlite3.Error:
            problems.append("transcript database unreadable")
        finally:
            c.close()
    auth = root / "auth.db"
    users = [e["id"] for e in entries if e["kind"] == "user"]
    if auth.exists() and users:
        c = sqlite3.connect(str(auth))
        try:
            for uid in users:
                if c.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
                    problems.append("a deleted account is still present")
                    break
        except sqlite3.Error:
            pass
        finally:
            c.close()
    return problems


def _write_journal(home: Path, state: dict) -> None:
    tmp = home / (JOURNAL + ".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, home / JOURNAL)


def restore_pending(home: Path) -> bool:
    """True when an earlier restore did not finish. The data directory must not be served until ``recover_interrupted`` has run."""
    return (Path(home) / JOURNAL).exists()


def recover_interrupted(home: Path) -> dict:
    """Roll back a restore that was interrupted mid-swap: put every moved-aside original back and remove anything the restore had placed. Idempotent."""
    home = Path(home)
    jp = home / JOURNAL
    (home / (JOURNAL + ".tmp")).unlink(missing_ok=True)           # a crash while writing the journal itself leaves only this temporary file
    if not jp.exists():
        return {"recovered": False}
    j = json.loads(jp.read_text())
    aside = home / j["aside"]
    for name in j.get("placed", []):
        tgt = home / name
        if tgt.is_dir() and not tgt.is_symlink():
            shutil.rmtree(tgt, ignore_errors=True)
        else:
            tgt.unlink(missing_ok=True)
    for name in j.get("moved", []):
        src = aside / name
        if src.exists():
            os.replace(src, home / name)
    shutil.rmtree(aside, ignore_errors=True)
    jp.unlink(missing_ok=True)
    return {"recovered": True, "rolled_back": len(j.get("moved", []))}


def restore(archive: Path, home: Path, *, key: bytes, deletion_ledger: Path | None = None, overwrite: bool = False,
            unsafe_without_deletion_history: bool = False, allow_inconsistent: bool = False) -> dict:
    archive, home = Path(archive), Path(home)
    if restore_pending(home):
        raise RestoreFailed("an earlier restore did not finish: run recover first")
    populated = home.exists() and any(p.name not in (JOURNAL,) for p in home.iterdir())
    if populated and not overwrite:
        raise FileExistsError("target data directory is not empty (stop the server and pass overwrite=True)")
    home.parent.mkdir(parents=True, exist_ok=True)
    stage = home.parent / f".{home.name}.restore-{uuid.uuid4().hex[:10]}"
    try:
        manifest = _extract(archive, key, stage)
        if not manifest.get("consistent", False) and not allow_inconsistent:
            raise BackupIncompleteError("the backup was taken while files were changing (flagged inconsistent: " + ", ".join(manifest.get("unstable_files", [])[:3]) + ")")
        # authoritative deletion history: the live ledger in the target and/or an authenticated export; never anything stored only in this archive
        entries: list[dict] = []
        sources = []
        if (home / ledger.LEDGER_NAME).exists():
            entries += ledger.merged(home)
            sources.append("live_ledger")
        if deletion_ledger is not None:
            exp = ledger.load_export(Path(deletion_ledger), key)
            if exp["generated_at"] < float(manifest.get("created_epoch", 0)):
                raise DeletionHistoryUnavailable("the deletion-history export is older than the backup, so it cannot cover later deletions")
            entries += exp["entries"]
            sources.append("export")
        if not sources and not unsafe_without_deletion_history:
            raise DeletionHistoryUnavailable("no authoritative deletion history (a live ledger in the target or an authenticated export): restoring could bring back data customers deleted")
        uniq, seen = [], set()
        for e in entries:
            k = (e["kind"], e["id"], e.get("session_id", "") if e["kind"] == "doc" else "")
            if k not in seen:
                seen.add(k)
                uniq.append(e)
        applied = _apply_deletions(stage, uniq)
        if sources:                                    # only a restore that HAD history writes a ledger: an empty one would later pass for authoritative
            with open(stage / ledger.LEDGER_NAME, "w") as f:
                for e in uniq:
                    f.write(json.dumps(e, separators=(",", ":"), sort_keys=True) + "\n")
            os.chmod(stage / ledger.LEDGER_NAME, 0o600)
        for stale in list(stage.rglob("*-wal")) + list(stage.rglob("*-shm")):
            stale.unlink(missing_ok=True)
        problems = _health_check(stage, uniq)
        if problems:
            raise RestoreFailed("restored copy failed its health check: " + "; ".join(problems[:3]))
        # swap
        top = sorted(p.name for p in stage.iterdir())
        if not home.exists() or not any(home.iterdir()):
            if home.exists():
                home.rmdir()
            os.replace(stage, home)
            moved_aside = None
        else:
            aside_name = f".pre-restore-{uuid.uuid4().hex[:10]}"
            aside = home / aside_name
            aside.mkdir(mode=0o700)
            names = top + [n + sfx for n in top if n.endswith(_DBS_SUFFIX) for sfx in ("-wal", "-shm")]
            journal = {"aside": aside_name, "moved": [], "placed": [], "state": "swapping"}
            try:
                _write_journal(home, journal)
                for name in names:                                       # write-ahead: the intent is durable BEFORE the file moves, so recovery always knows what to undo
                    if (home / name).exists():
                        journal["moved"].append(name)
                        _write_journal(home, journal)
                        os.replace(home / name, aside / name)
                for name in top:
                    journal["placed"].append(name)
                    _write_journal(home, journal)
                    os.replace(stage / name, home / name)
                post = _health_check(home, uniq)
                if post:
                    raise RestoreFailed("restored directory failed its post-swap health check: " + "; ".join(post[:3]))
            except BaseException:
                recover_interrupted(home)
                if not (home / JOURNAL).exists():
                    shutil.rmtree(aside, ignore_errors=True)          # nothing was moved (or it was all put back): the empty holding directory goes too
                raise
            (home / JOURNAL).unlink(missing_ok=True)
            moved_aside = str(aside)
        return {"restored_files": len(manifest["files"]), "verified": True, "deletion_history_sources": sources, "deletions_applied": applied,
                "deleted_data_may_be_present": not sources, "previous_state_kept_at": moved_aside,
                "note": "conversation tombstones are active now; the application's deletion sweep removes any remaining conversation data on start. Older backups are NOT changed."}
    finally:
        shutil.rmtree(stage, ignore_errors=True)
