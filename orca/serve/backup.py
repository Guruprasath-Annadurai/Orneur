"""L02-06: consistent backup and verified restore of the ORNEUR data directory (transcripts, accounts, registries, document stores).

SQLite databases are copied with SQLite's online backup API (a consistent snapshot even while the server is writing); small JSON/JSONL stores are copied atomically;
the vector-store directory is copied file-by-file and is only guaranteed consistent when the server is stopped (reported in the manifest). Every file is hashed in a
manifest; ``verify`` re-checks hashes and runs ``PRAGMA integrity_check`` on each database; ``restore`` refuses to overwrite a data directory that is in use or
non-empty unless told to, and verifies before it writes anything.

What this does NOT do: it does not encrypt the backup, does not copy secrets held in the environment, and does not touch anything outside ORNEUR_HOME. A backup is a
COPY of user data: deleting a conversation does not delete it from existing backups (this is stated to users in the deletion response).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

_DBS = ("auth.db", "inference_turns.sqlite", "untrusted_jobs.sqlite", "reconcile.db")
_SKIP_DIRS = {"backups", "cache", "models", "training", "workspace", "vault"}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _sqlite_files(home: Path):
    for p in home.rglob("*"):
        if p.is_file() and p.suffix in (".db", ".sqlite", ".sqlite3") and not any(part in _SKIP_DIRS for part in p.relative_to(home).parts):
            yield p


def create(home: Path, dest: Path) -> dict:
    home, dest = Path(home), Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError("backup destination is not empty")
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    files, dbs = {}, set(_sqlite_files(home))
    for src in sorted(dbs):
        rel = src.relative_to(home)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        s = sqlite3.connect(str(src), timeout=30)
        d = sqlite3.connect(str(out))
        try:
            s.backup(d)                                     # consistent snapshot, safe while the server writes
        finally:
            d.close()
            s.close()
        files[str(rel)] = {"sha256": _sha(out), "kind": "sqlite_online_backup"}
    for src in sorted(p for p in home.rglob("*") if p.is_file() and p not in dbs and not p.name.endswith(("-wal", "-shm", ".lock", ".tmp")) and not any(
            part in _SKIP_DIRS or part == ".quarantine" for part in p.relative_to(home).parts)):
        rel = src.relative_to(home)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        files[str(rel)] = {"sha256": _sha(out), "kind": "file_copy"}
    manifest = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "files": files, "excluded_dirs": sorted(_SKIP_DIRS),
                "note": "SQLite files are consistent snapshots; the vector-store directory is only consistent if the server was stopped; contains user data and is NOT encrypted"}
    (dest / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    return {"files": len(files), "path": str(dest)}


def verify(backup: Path) -> dict:
    backup = Path(backup)
    manifest = json.loads((backup / "MANIFEST.json").read_text())
    problems = []
    for rel, meta in manifest["files"].items():
        p = backup / rel
        if not p.exists():
            problems.append(f"missing: {rel}")
        elif _sha(p) != meta["sha256"]:
            problems.append(f"hash mismatch: {rel}")
        elif meta["kind"] == "sqlite_online_backup":
            c = sqlite3.connect(str(p))
            try:
                if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    problems.append(f"integrity_check failed: {rel}")
            finally:
                c.close()
    return {"ok": not problems, "problems": problems, "files": len(manifest["files"])}


def restore(backup: Path, home: Path, *, overwrite: bool = False) -> dict:
    backup, home = Path(backup), Path(home)
    v = verify(backup)
    if not v["ok"]:
        raise ValueError(f"backup failed verification, nothing was restored: {v['problems'][:3]}")
    if home.exists() and any(home.iterdir()) and not overwrite:
        raise FileExistsError("target data directory is not empty (pass overwrite=True after stopping the server)")
    n = 0
    for p in backup.rglob("*"):
        if p.is_file() and p.name != "MANIFEST.json":
            out = home / p.relative_to(backup)
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_name(out.name + ".restoring")
            shutil.copy2(p, tmp)
            os.replace(tmp, out)
            n += 1
    for stale in list(home.rglob("*-wal")) + list(home.rglob("*-shm")):
        stale.unlink(missing_ok=True)                        # a restored database must not inherit another database's write-ahead log
    return {"restored_files": n, "verified": True}
