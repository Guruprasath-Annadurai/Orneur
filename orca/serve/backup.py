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

import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
from pathlib import Path

from orca.serve import deletion_ledger as ledger
from orca.serve import datadir_lock
from orca.serve.backup_crypto import DecryptedReader, EncryptedWriter, load_key, write_new_key  # noqa: F401  (re-exported)
from orca.serve.backup_errors import (BackupAuthError, BackupDependencyMissing, BackupError, BackupIncompleteError, BackupKeyError,  # noqa: F401  (re-exported)
                                      DeletionHistoryUnavailable, RestoreFailed)
from orca.serve.datadir_lock import JOURNAL, exclusive_data_dir, recover_interrupted, restore_pending, serving_lock, write_journal as _write_journal  # noqa: F401  (re-exported)

FORMAT = "orneur-backup/2"
_DBS_SUFFIX = (".db", ".sqlite", ".sqlite3")
_SKIP_DIRS = {"backups", "cache", "models", "training", "workspace", "vault"}
_SKIP_NAMES = {ledger.LEDGER_NAME, ".restore-journal.json", ".server.lock"}
_CORE = ("auth.db", "memory/conversations/turns.db")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _excluded(home: Path, p: Path) -> bool:
    parts = p.relative_to(home).parts
    return (any(part in _SKIP_DIRS or part == ".quarantine" or part.startswith(".pre-restore-") or part.startswith(".restore-") for part in parts)
            or p.name in _SKIP_NAMES or p.name.startswith(ledger.LEDGER_NAME + ".damaged-") or p.name.endswith(("-wal", "-shm", ".lock", ".tmp", ".restoring")))


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


def _vector_root(home: Path) -> Path:
    return Path(home) / "memory" / "vectors"


def _vector_present(home: Path) -> bool:
    root = _vector_root(home)
    return root.is_dir() and any(p.is_file() for p in root.rglob("*"))


def _vector_owner_pid(home: Path) -> int | None:
    """Best-effort live owner pid without importing chromadb. Matches ServiceTransport.owner_pid semantics."""
    try:
        from orca.vectorstore import paths as vpaths
    except Exception:
        return None
    home = Path(home).resolve()
    try:
        pid = int(vpaths.pid_path(home).read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return None
    return pid if b"orca.vectorstore.server" in cmd and str(home).encode() in cmd else None


def _quiesce_vector_owner(home: Path, wait_s: float = 10.0) -> bool:
    """Option A: stop a live vector owner so HNSW segments and SQLite are not written during the snapshot. Returns True when no owner is alive afterwards."""
    home = Path(home).resolve()
    pid = _vector_owner_pid(home)
    if pid is None:
        return True
    try:
        os.kill(pid, 15)  # SIGTERM
    except OSError:
        return _vector_owner_pid(home) is None
    end = time.time() + wait_s
    while time.time() < end:
        if _vector_owner_pid(home) is None:
            return True
        time.sleep(0.05)
    try:
        os.kill(pid, 9)
    except OSError:
        pass
    end = time.time() + 2.0
    while time.time() < end:
        if _vector_owner_pid(home) is None:
            return True
        time.sleep(0.05)
    return _vector_owner_pid(home) is None


@contextlib.contextmanager
def _vector_owner_barrier(home: Path, *, retries: int = 1, retry_s: float = 0.05):
    """Option B: verifiable exclusive hold on the vector owner.lock proving no owner is serving this data directory."""
    try:
        from orca.vectorstore import paths as vpaths
    except Exception:
        yield None
        return
    home = Path(home).resolve()
    lock_path = vpaths.owner_lock_path(home)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    held = False
    try:
        for attempt in range(max(1, retries)):
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
                break
            except OSError:
                if attempt + 1 >= retries:
                    yield None
                    return
                time.sleep(retry_s)
        yield "owner_lock_exclusive"
    finally:
        if held:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass


def create(home: Path, out_file: Path, *, key: bytes, quiesce_vector: bool = False) -> dict:
    """Encrypt a snapshot of ``home`` into the new file ``out_file``. The archive appears under its final name only when complete and flushed.

    Vector consistency (MASTER-04): ``consistent: true`` is never claimed from one readable sample of HNSW/segment files alone. When a vector store is present, either the
    owner must be quiesced (``quiesce_vector=True``, Option A) or a verifiable exclusive owner-lock barrier must be held for the copy (Option B). Otherwise the archive is
    flagged inconsistent even if individual file mtimes appeared stable.
    """
    home, out_file = Path(home), Path(out_file)
    if out_file.exists():
        raise FileExistsError("backup destination already exists")
    if len(key) != 32:
        raise BackupKeyError("backup key must be exactly 32 bytes")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    ledger.ensure(home)
    try:
        ledger_info = ledger.chain_info(home)                       # recorded INSIDE the authenticated archive: a later restore compares the live ledger against it
    except ledger.LedgerIntegrityError:
        ledger_info = {"status": "unreadable"}
    partial = out_file.with_name(out_file.name + ".partial")
    files: dict = {}
    unstable: list[str] = []
    started = time.time()
    scratch = Path(tempfile.mkdtemp(prefix=".orbk-", dir=str(out_file.parent)))      # transient, private; holds one database snapshot at a time
    os.chmod(scratch, 0o700)
    vector_meta = {"present": _vector_present(home), "quiesced": False, "barrier": None, "owner_was_running": _vector_owner_pid(home) is not None,
                   "owner_active_during_copy": False}
    if vector_meta["present"] and quiesce_vector:
        vector_meta["quiesced"] = _quiesce_vector_owner(home)
        if not vector_meta["quiesced"]:
            raise BackupIncompleteError("vector owner could not be quiesced for a coherent vector backup")
        # Give the kernel a moment to release the dead owner's flock before the barrier attempt.
        for _ in range(20):
            if _vector_owner_pid(home) is None:
                break
            time.sleep(0.05)
        time.sleep(0.05)
    consistent = False
    try:
        with _vector_owner_barrier(home, retries=(40 if vector_meta["quiesced"] else 1)) as barrier:
            vector_meta["barrier"] = barrier
            if vector_meta["present"] and barrier is None and not vector_meta["quiesced"]:
                # Owner still holds its exclusive owner.lock (or barrier unavailable): never claim vector consistency from a readable sample.
                vector_meta["owner_active_during_copy"] = True
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
                    if vector_meta["present"] and vector_meta["owner_active_during_copy"]:
                        marker = "memory/vectors/(owner_active_no_quiesce_no_barrier)"
                        if marker not in unstable:
                            unstable.append(marker)
                    if not any(c in files for c in _CORE):
                        raise BackupIncompleteError("nothing to back up: the data directory has neither an accounts nor a transcript database")
                    vector_ok = (not vector_meta["present"]) or bool(vector_meta["quiesced"] or vector_meta["barrier"])
                    consistent = (not unstable) and vector_ok
                    vector_meta["consistent_claim_allowed"] = vector_ok
                    manifest = {"format": FORMAT, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "created_epoch": started, "files": files,
                                "core": [c for c in _CORE if c in files], "unstable_files": unstable, "consistent": consistent,
                                "vector": vector_meta, "ledger": ledger_info, "excluded_dirs": sorted(_SKIP_DIRS)}
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
    return {"files": len(files), "path": str(out_file), "bytes": out_file.stat().st_size, "consistent": consistent, "unstable_files": unstable, "vector": vector_meta}




# ── read / verify ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _safe_rel(rel: str) -> Path:
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] in (JOURNAL, ".server.lock") or p.parts[0].startswith(".pre-restore-") or p.name == ledger.LEDGER_NAME:
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


# ── deletion history for a restore ───────────────────────────────────────────────────────────────────────────────────────────

_HISTORY_STATEMENT = ("Deletion history is NOT verified complete. The live ledger is an editable file (hash-chained, so naive edits and truncation relative to copies made elsewhere are "
                      "detected, but it is not tamper-proof and not authenticated); an export is authenticated but only as new as the moment it was taken; there is no off-host anchor. "
                      "Deletions made after the newest copy kept elsewhere cannot be known.")


def _same_prefix(a: list[dict], b: list[dict]) -> bool:
    n = min(len(a), len(b))
    return n > 0 and a[n - 1]["h"] == b[n - 1]["h"]


def _continues(lines: list[dict], info: dict | None) -> bool:
    """Does this chain extend the (id, count, head) the backup recorded when it was taken?"""
    if not info or "ledger_id" not in info:
        return True                                               # nothing recorded to compare with (older archive, legacy import)
    return lines[0]["ledger_id"] == info["ledger_id"] and len(lines) >= int(info["count"]) and lines[int(info["count"]) - 1]["h"] == info["head"]


def _gather_history(home: Path, manifest: dict, deletion_ledger: Path | None, key: bytes) -> tuple[list[dict], list[dict], list[str], dict]:
    """Returns (entries to apply, chain lines to carry into the restored directory, sources, details). Raises DeletionHistoryUnavailable / BackupAuthError."""
    recorded = manifest.get("ledger")
    recorded = recorded if isinstance(recorded, dict) and "ledger_id" in recorded else None
    sources: list[str] = []
    chains: list[tuple[str, list[dict]]] = []
    entries: list[dict] = []
    details: dict = {"export_generated_at": 0.0}
    if (home / ledger.LEDGER_NAME).exists():
        try:
            live = ledger.read_lines(home)
        except ledger.LedgerIntegrityError as exc:
            raise DeletionHistoryUnavailable(f"the live deletion ledger failed its integrity check ({exc}); repair or move it aside and supply an authenticated export") from None
        if not _continues(live, recorded):
            raise DeletionHistoryUnavailable("the live deletion ledger is not a continuation of the ledger this backup recorded (removed, replaced or truncated since): it cannot be trusted as deletion history")
        chains.append(("live_ledger", live))
        entries += ledger.merged(home)
        sources.append("live_ledger")
    if deletion_ledger is not None:
        exp = ledger.load_export(Path(deletion_ledger), key)
        if exp["generated_at"] < float(manifest.get("created_epoch", 0)):
            raise DeletionHistoryUnavailable("the deletion-history export is older than the backup, so it cannot cover later deletions")
        if recorded is not None and exp["ledger_id"] != recorded["ledger_id"]:
            raise DeletionHistoryUnavailable("the deletion-history export belongs to a different ledger lineage than this backup")
        if not _continues(exp["lines"], recorded):
            raise DeletionHistoryUnavailable("the deletion-history export does not continue the ledger this backup recorded")
        chains.append(("export", exp["lines"]))
        entries += exp["entries"]
        sources.append("export")
        details["export_generated_at"] = exp["generated_at"]
    if len(chains) == 2:
        live, exp = chains[0][1], chains[1][1]
        if not _same_prefix(live, exp) or live[0]["ledger_id"] != exp[0]["ledger_id"]:
            raise DeletionHistoryUnavailable("the live ledger and the export have forked (they disagree about earlier entries)")
        if len(live) < len(exp):
            raise DeletionHistoryUnavailable("the live ledger is behind the export (truncated?): it is missing entries the export has")
    longest = max((c for _, c in chains), key=len, default=[])
    details["ledger_id"] = longest[0]["ledger_id"] if longest else None
    return ledger._dedupe(entries), longest, sources, details


def _tighten(root: Path) -> None:
    for dp, dns, fns in os.walk(root):
        os.chmod(dp, 0o700)
        for f in fns:
            fp = os.path.join(dp, f)
            if not os.path.islink(fp):
                os.chmod(fp, 0o600)


def restore(archive: Path, home: Path, *, key: bytes, deletion_ledger: Path | None = None, overwrite: bool = False,
            unsafe_without_deletion_history: bool = False, allow_inconsistent: bool = False) -> dict:
    archive, home = Path(archive), Path(home)
    home.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_data_dir(home):
        if restore_pending(home):
            raise RestoreFailed("an earlier restore did not finish: run recover first")
        populated = home.exists() and any(p.name not in (JOURNAL, ".server.lock") for p in home.iterdir())
        if populated and not overwrite:
            raise FileExistsError("target data directory is not empty (stop the server and pass overwrite=True)")
        stage = home.parent / f".{home.name}.restore-{uuid.uuid4().hex[:10]}"
        try:
            manifest = _extract(archive, key, stage)
            if not manifest.get("consistent", False) and not allow_inconsistent:
                raise BackupIncompleteError("the backup was taken while files were changing (flagged inconsistent: " + ", ".join(manifest.get("unstable_files", [])[:3]) + ")")
            uniq, chain, sources, details = _gather_history(home, manifest, deletion_ledger, key)
            if not sources and not unsafe_without_deletion_history:
                raise DeletionHistoryUnavailable("no authoritative deletion history (a live ledger in the target or an authenticated export): restoring could bring back data customers deleted")
            applied = _apply_deletions(stage, uniq)
            if sources:                                    # only a restore that HAD history writes a ledger: an empty one would later pass for authoritative
                with open(stage / ledger.LEDGER_NAME, "w") as f:
                    for line in chain:
                        f.write(json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n")
                for e in uniq:                             # deletions known only from tombstones are appended as properly chained records
                    if not any(l.get("kind") == e["kind"] and l.get("id") == e["id"] for l in chain):
                        ledger.record(e["kind"], e["id"], e.get("user_id", ""), e.get("session_id", ""), home=stage)
            for stale in list(stage.rglob("*-wal")) + list(stage.rglob("*-shm")):
                stale.unlink(missing_ok=True)
            _tighten(stage)                                # customer data is private on disk: directories 0700, files 0600
            problems = _health_check(stage, uniq)
            if problems:
                raise RestoreFailed("restored copy failed its health check: " + "; ".join(problems[:3]))
            moved_aside = _swap(stage, home, uniq)
            history = {"sources": sources, "ledger_id": details["ledger_id"], "entries_applied": len(uniq), "completeness_verified": False, "live_ledger_authenticated": False,
                       "off_host_anchor": False, "export_generated_at": details["export_generated_at"], "statement": _HISTORY_STATEMENT if sources else
                       "NO deletion history was available: data customers deleted since this backup may be present again."}
            return {"restored_files": len(manifest["files"]), "verified": True, "deletion_history_sources": sources, "deletions_applied": applied, "deletion_history": history,
                    "deleted_data_may_be_present": not sources, "previous_state_kept_at": moved_aside,
                    "note": "conversation tombstones are active now; the application's deletion sweep removes any remaining conversation data on start. Older backups are NOT changed."}
        finally:
            shutil.rmtree(stage, ignore_errors=True)


def _swap(stage: Path, home: Path, entries: list[dict]) -> str | None:
    top = sorted(p.name for p in stage.iterdir())
    if not home.exists() or not any(p.name not in (".server.lock",) for p in home.iterdir()):
        if home.exists():
            for p in home.iterdir():
                p.unlink()
            home.rmdir()
        os.replace(stage, home)
        return None
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
        post = _health_check(home, entries)
        if post:
            raise RestoreFailed("restored directory failed its post-swap health check: " + "; ".join(post[:3]))
    except BaseException:
        try:
            recover_interrupted(home)
        except RestoreFailed:
            raise
        if not (home / JOURNAL).exists():
            shutil.rmtree(aside, ignore_errors=True)              # nothing was moved (or it was all put back): the empty holding directory goes too
        raise
    (home / JOURNAL).unlink(missing_ok=True)
    return str(aside)


# ── offline migration of pre-existing plaintext backups ─────────────────────────────────────────────────────────────────────────

def _inside(child: Path, parent: Path) -> bool:
    try:
        Path(child).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def import_legacy(legacy_db: Path, out_file: Path, *, key: bytes, live_home: Path | None) -> dict:
    """OFFLINE migration of one pre-existing plaintext accounts-database backup (``auth_backup_*.db`` written by the retired ``orca backup``) into an encrypted archive.

    It reads the legacy file and writes a new archive; it never reads or writes the live data directory, refuses if either path is inside it, and refuses while a server is
    running on it. The archive is marked ``legacy_plaintext_import``, its creation time is the IMPORT time (so an older deletion-history export cannot be used with it), and it
    carries no ledger lineage (nothing proves how it relates to today's ledger). It restores only through the normal ``restore`` (deletion history required, deletions re-applied).
    The plaintext original is NOT deleted: destroying it is the operator's deliberate step."""
    legacy_db, out_file = Path(legacy_db), Path(out_file)
    if live_home is not None:
        live_home = Path(live_home)
        if _inside(legacy_db, live_home) or _inside(out_file, live_home) or _inside(out_file.parent, live_home):
            raise BackupError("both the legacy file and the new archive must be outside the live data directory (this migration is offline-only)")
        if live_home.exists():
            with datadir_lock.flock(live_home / ".server.lock", fcntl.LOCK_EX, "a server is running on the live data directory: stop it first (this migration is offline-only)", create=False):
                pass
    if len(key) != 32:
        raise BackupKeyError("backup key must be exactly 32 bytes")
    if out_file.exists():
        raise FileExistsError("backup destination already exists")
    if not legacy_db.is_file():
        raise BackupIncompleteError("legacy backup file is missing")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=".orbk-import-", dir=str(out_file.parent)))
    os.chmod(scratch, 0o700)
    partial = out_file.with_name(out_file.name + ".partial")
    try:
        snap = scratch / "auth.db"
        s = None
        try:
            s = sqlite3.connect(f"file:{legacy_db}?mode=ro", uri=True, timeout=10)
            if s.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupIncompleteError("legacy backup failed its integrity check")
            if not s.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone():
                raise BackupIncompleteError("legacy backup does not look like an accounts database (no users table)")
            d = sqlite3.connect(str(snap))
            try:
                s.backup(d)
            finally:
                d.close()
        except sqlite3.Error:
            raise BackupIncompleteError("legacy backup is not a readable SQLite database") from None
        finally:
            if s is not None:
                s.close()
        files: dict = {}
        fd = os.open(str(partial), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as raw:
            w = EncryptedWriter(raw, key)
            _put(w, "auth.db", snap, "sqlite_online_backup", files, time.time())
            manifest = {"format": FORMAT, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "created_epoch": time.time(), "files": files, "core": ["auth.db"],
                        "unstable_files": [], "consistent": True, "origin": "legacy_plaintext_import", "ledger": None, "excluded_dirs": sorted(_SKIP_DIRS)}
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
    return {"origin": "legacy_plaintext_import", "path": str(out_file), "files": 1, "bytes": out_file.stat().st_size}
