#!/usr/bin/env python3
"""Reproduce Antigravity Audit #007 findings against whatever `orca` tree is
on PYTHONPATH (run once per commit/worktree). Needs root (creates uid 65534
objects) and a sticky /tmp. Creates and removes its own temp tree; touches no
real ORNEUR data (HOME is redirected). Prints one VERDICT line per scenario;
VULNERABLE means the attacker reached or redirected storage.

    git worktree add /tmp/wt <sha>; PYTHONPATH=/tmp/wt python scripts/security/audit007_repro.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

NOBODY = 65534


def main() -> int:
    if os.geteuid() != 0 or not (os.stat("/tmp").st_mode & 0o1000):
        print("SKIPPED: needs root and a sticky /tmp")
        return 0
    base = Path(tempfile.mkdtemp(dir="/tmp"))
    os.chmod(base, 0o755)
    os.environ["HOME"] = str(base / "home")
    os.environ.pop("ORNEUR_HOME", None)
    os.environ.pop("ORCA_HOME", None)
    try:
        import orca.config as cfg
        import orca.lens.queue as queue

        print(f"orca from: {Path(cfg.__file__).resolve().parent}")

        def mk_evil(name: str, mode: int = 0o777) -> Path:
            p = base / name
            p.mkdir(mode=mode)
            os.chown(p, NOBODY, NOBODY)
            os.chmod(p, mode)
            return p

        # S1: Audit #007 / reviewer TOCTOU: attacker-owned symlink in sticky /tmp
        stick = base / "stick"
        stick.mkdir()
        os.chmod(stick, 0o1777)
        safe = base / "safe"
        safe.mkdir(mode=0o700)
        evil = mk_evil("evil")
        link = stick / "x"
        os.symlink(safe, link)
        os.lchown(link, NOBODY, NOBODY)
        try:
            ret = cfg._mkdir_owner_only(link / "cache")
        except Exception as exc:  # noqa: BLE001
            print(f"S1 parent-symlink TOCTOU: BLOCKED ({type(exc).__name__})")
        else:
            link.unlink()  # attacker repoints the entry they own
            os.symlink(evil, link)
            os.lchown(link, NOBODY, NOBODY)
            landed = os.path.realpath(ret)
            bad = landed.startswith(str(evil))
            print(f"S1 parent-symlink TOCTOU: {'VULNERABLE' if bad else 'SAFE'} "
                  f"(accepted; returned {ret}; resolves after repoint to {landed})")

        def queue_case(label: str, cache_dir: Path, evil_dir: Path) -> None:
            try:
                jq = queue.LensJobQueue(cache_dir=cache_dir)
            except Exception as exc:  # noqa: BLE001
                print(f"{label}: BLOCKED ({type(exc).__name__})")
                return
            jq.submit("probe")
            jq._cache.close()
            reached = any(evil_dir.rglob("cache.db"))
            print(f"{label}: {'VULNERABLE' if reached else 'SAFE'} (queue opened; store in attacker dir: {reached})")

        # S2: explicit cache_dir owned by another uid
        e2 = mk_evil("evil2", 0o755)
        queue_case("S2 LensJobQueue foreign-owned cache_dir", e2, e2)
        # S3: explicit cache_dir is a symlink into attacker storage
        e3 = mk_evil("evil3")
        (base / "q3").symlink_to(e3)
        queue_case("S3 LensJobQueue symlink cache_dir", base / "q3", e3)
        # S4: explicit cache_dir below an attacker-owned parent
        e4 = mk_evil("evil4", 0o755)
        queue_case("S4 LensJobQueue attacker-owned parent", e4 / "q", e4)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
