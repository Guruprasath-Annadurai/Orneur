"""
Generic on-disk backing store for mutable memory record types (semantic,
entity, procedural, failure) -- distinct from episodic.py's append-only
ledger, since these DO need in-place updates (supersession, epistemic-
state transitions, execution counters). One JSON file per record, under
ORCA_HOME/memory/{memory_type}/{scope_hash}/{memory_id}.json -- makes
per-scope cascade deletion (spec §38) a single directory removal, and
per-record updates a single file rewrite, without introducing a new
database dependency (spec §49: adapt to what exists, don't rewrite
storage for architectural purity alone).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, fields
from pathlib import Path
from typing import TypeVar

from orca.config import ORCA_HOME
from orca.memory.contracts import (
    EntityMemoryRecord,
    EpistemicState,
    FailureMemoryRecord,
    FailureVerificationState,
    MemoryEvidence,
    MemoryLifecycleState,
    MemoryScope,
    MemoryType,
    ProceduralMemoryRecord,
    PrivacyClass,
    SemanticMemoryRecord,
)

MEMORY_ROOT = ORCA_HOME / "memory"

T = TypeVar("T")

_RECORD_TYPES: dict[MemoryType, type] = {
    MemoryType.SEMANTIC: SemanticMemoryRecord,
    MemoryType.ENTITY: EntityMemoryRecord,
    MemoryType.PROCEDURAL: ProceduralMemoryRecord,
    MemoryType.FAILURE: FailureMemoryRecord,
}


def _scope_dir(memory_type: MemoryType, scope: MemoryScope, scope_id: str) -> Path:
    safe = hashlib.sha256(f"{scope.value}:{scope_id}".encode()).hexdigest()[:24]
    d = MEMORY_ROOT / memory_type.value.lower() / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def _hydrate(memory_type: MemoryType, data: dict):
    cls = _RECORD_TYPES[memory_type]
    data = dict(data)
    data.pop("memory_type", None)
    data["scope"] = MemoryScope(data["scope"])
    data["epistemic_state"] = EpistemicState(data["epistemic_state"])
    data["lifecycle_state"] = MemoryLifecycleState(data["lifecycle_state"])
    data["privacy"] = PrivacyClass(data["privacy"])
    data["evidence_refs"] = [MemoryEvidence(**e) for e in data.get("evidence_refs", [])]
    if memory_type == MemoryType.FAILURE and "verification_state" in data:
        data["verification_state"] = FailureVerificationState(data["verification_state"])
    valid_fields = {f.name for f in fields(cls)}
    data = {k: v for k, v in data.items() if k in valid_fields}
    return cls(**data)


def save(record) -> None:
    memory_type = record.memory_type
    d = _scope_dir(memory_type, record.scope, record.scope_id)
    path = d / f"{record.memory_id}.json"
    path.write_text(json.dumps(asdict(record), indent=2))


def load(memory_type: MemoryType, scope: MemoryScope, scope_id: str, memory_id: str):
    path = _scope_dir(memory_type, scope, scope_id) / f"{memory_id}.json"
    if not path.exists():
        return None
    return _hydrate(memory_type, json.loads(path.read_text()))


def list_records(memory_type: MemoryType, scope: MemoryScope, scope_id: str) -> list:
    d = _scope_dir(memory_type, scope, scope_id)
    records = []
    for p in sorted(d.glob("*.json")):
        try:
            records.append(_hydrate(memory_type, json.loads(p.read_text())))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue  # a corrupt single record shouldn't take down the whole scope's listing
    return records


def delete_record(memory_type: MemoryType, scope: MemoryScope, scope_id: str, memory_id: str) -> bool:
    path = _scope_dir(memory_type, scope, scope_id) / f"{memory_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def delete_scope(scope: MemoryScope, scope_id: str) -> dict[str, int]:
    """Full cascade removal of every typed memory record for a scope --
    used by account deletion (spec §38). Returns counts per memory type."""
    counts: dict[str, int] = {}
    for memory_type in _RECORD_TYPES:
        d = _scope_dir(memory_type, scope, scope_id)
        n = len(list(d.glob("*.json")))
        if d.exists():
            shutil.rmtree(d)
        counts[memory_type.value] = n
    return counts
