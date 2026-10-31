"""A tiny durable ledger of vector cleanup that is known to be incomplete (here: raw bytes not yet reclaimed). One JSON file per vector directory, written atomically.
It holds session/store identifiers and counters only - never content."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


def _path(root: Path) -> Path:
    return Path(root) / "pending_reclamation.json"


def load(root: Path) -> list[dict]:
    p = _path(root)
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(root: Path, entries: list[dict]) -> None:
    p = _path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries))
    os.replace(tmp, p)


def record(root: Path, key: str, reason: str) -> None:
    entries, now = load(root), time.time()
    for e in entries:
        if e.get("key") == key:
            e["attempts"] = e.get("attempts", 0) + 1
            e["last_attempt_at"], e["last_error"] = now, reason
            break
    else:
        entries.append({"key": key, "logically_deleted_at": now, "attempts": 1, "last_attempt_at": now, "last_error": reason})
    _save(root, entries)


def clear_all(root: Path) -> None:
    _save(root, [])


def clear_key(root: Path, key: str) -> None:
    _save(root, [e for e in load(root) if e.get("key") != key])
