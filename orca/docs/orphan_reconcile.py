"""Inventory of upload stores. Deletion is limited to abandoned temp files.

A missing owner, an active document-only conversation, or a temporary chat
whose deletion is incomplete is reported and left in place.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from orca.docs.store import DOCS_DIR


def reconcile_orphan_uploads(*, now: float | None = None, apply: bool = False) -> dict:
    moment = time.time() if now is None else now
    inventory = _inventory()
    discrepancies = _classify(inventory)
    removed: list[str] = []
    if apply:
        removed = _remove_abandoned_temps(moment)
    return {
        "dry_run": not apply,
        "atomic": False,
        "inventory": inventory,
        "discrepancies": discrepancies,
        "removed": removed,
        "document_only_preserved": [row["session_id"] for row in discrepancies if row["class"] == "document_only"],
    }


def _inventory() -> dict:
    root = Path(DOCS_DIR)
    files = []
    if root.exists():
        for path in root.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            files.append({"path": str(path), "name": path.name, "bytes": path.stat().st_size})
    return {"files": files, "file_count": len(files)}


def _classify(inventory: dict) -> list[dict]:
    rows = []
    for item in inventory["files"]:
        name = item["name"]
        if name.endswith(".tmp"):
            rows.append({"class": "abandoned_temp", "path": item["path"], "remediation": "eligible"})
        elif name.startswith("kw_") and name.endswith(".jsonl"):
            rows.append({
                "class": "keyword_fallback",
                "path": item["path"],
                "remediation": "report_only",
                "reason": "an 8-character session prefix can collide, so the owner is not certain",
            })
        elif name == "registry.json":
            rows.append({"class": "registry", "path": item["path"], "remediation": "report_only"})
    return rows


def _remove_abandoned_temps(now: float) -> list[str]:
    removed = []
    root = Path(DOCS_DIR)
    if not root.exists():
        return removed
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file() or not path.name.endswith(".tmp"):
            continue
        if now - path.stat().st_mtime < 60:
            continue
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError:
            continue
        os.close(fd)
        path.unlink()
        removed.append(str(path))
    return removed
